"""Bind measured element curves to real RGBA transforms on an explicit clock.

The profile contains source-pixel geometry, not viewport/camera parameters.
Binding replaces named channels; it does not silently add motion to authored keys.
"""
from copy import deepcopy
from collections import OrderedDict
from fractions import Fraction
import hashlib
import json
import math

import numpy as np

from .motion_layers import Transform
from .motion_profile import evaluate_element, profile_digest, validate_profile

SCHEMA = 'element-motion-binding/1'
CHANNEL_FIELDS = {'position': {'x', 'y'}, 'scale': {'scale'}, 'angle': {'angle'}}
_VALIDATED_PROFILES = OrderedDict()


def _verified_profile(profile, expected):
    if not isinstance(profile, dict) or profile.get('schema') != 'element-motion-curves/1':
        raise ValueError('Motion binding requires an element-motion-curves/1 profile')
    digest = profile_digest(profile)
    if expected != digest:
        raise ValueError('Motion profile hash differs from the bound profile')
    # Hash is recomputed for mutable inline dictionaries. Full coefficient/PTS
    # validation can be reused only for exactly the same canonical bytes.
    if digest not in _VALIDATED_PROFILES:
        validate_profile(profile)
        _VALIDATED_PROFILES[digest] = True
        while len(_VALIDATED_PROFILES) > 32:
            _VALIDATED_PROFILES.popitem(last=False)
    else:
        _VALIDATED_PROFILES.move_to_end(digest)
    return profile


class MotionProfilePool:
    """Private immutable snapshot of profiles, verified once per render.

    Renderers hold this registry instead of repeatedly hashing long trajectories.
    Manifest edits after construction cannot mutate its copied curve data.
    """
    def __init__(self, profiles):
        if not isinstance(profiles, dict):
            raise ValueError('motion_profiles must map hashes to profiles')
        self.__profiles = {}
        for digest, profile in profiles.items():
            value = deepcopy(profile)
            _verified_profile(value, digest)
            self.__profiles[digest] = value

    def _resolve(self, digest):
        if digest not in self.__profiles:
            raise ValueError('Bound motion profile is missing from motion_profiles')
        return self.__profiles[digest]


def _profile_for(binding, profiles):
    digest = binding.get('profile_sha256')
    if 'profile' in binding:
        return _verified_profile(binding['profile'], digest)
    if isinstance(profiles, MotionProfilePool):
        return profiles._resolve(digest)
    if not isinstance(profiles, dict) or digest not in profiles:
        raise ValueError('Bound motion profile is missing; provide inline profile or motion_profiles')
    return _verified_profile(profiles[digest], digest)


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number')
    return float(value)


def _pair(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(name + ' must have two numbers')
    return tuple(_number(v, name) for v in value)


def validate_time_map(time_map):
    if not isinstance(time_map, list) or len(time_map) < 2:
        raise ValueError('Motion time_map requires at least two explicit time pairs')
    times = []
    for row in time_map:
        if not isinstance(row, dict) or set(row) != {'output_time', 'source_time'}:
            raise ValueError('Motion time_map rows require output_time and source_time')
        pair = (_number(row['output_time'], 'output_time'), _number(row['source_time'], 'source_time'))
        if pair[0] < 0 or pair[1] < 0:
            raise ValueError('Motion times are elapsed seconds and must be nonnegative')
        if times and (pair[0] <= times[-1][0] or pair[1] <= times[-1][1]):
            raise ValueError('Motion time_map must increase strictly on both clocks')
        times.append(pair)
    return times


def validate_binding(binding, *, image_size=None, canvas_size=None, profiles=None):
    if not isinstance(binding, dict) or binding.get('schema') != SCHEMA:
        raise ValueError('Expected ' + SCHEMA)
    allowed = {'schema', 'profile', 'profile_sha256', 'element_id', 'channels', 'time_map',
               'pivot_px', 'base_scale', 'spatial_scale', 'spatial_offset_px',
               'base_angle_deg', 'outside', 'stage'}
    if set(binding) - allowed:
        raise ValueError('Unknown motion binding fields: ' + ', '.join(sorted(set(binding) - allowed)))
    profile = _profile_for(binding, profiles)
    matches = [e for e in profile.get('elements', []) if e.get('id') == binding.get('element_id')]
    if len(matches) != 1 or matches[0].get('model') != 'similarity_2d':
        raise ValueError('Motion binding requires one known similarity_2d element')
    channels = binding.get('channels')
    if not isinstance(channels, list) or not channels or len(channels) != len(set(channels)) or set(channels) - CHANNEL_FIELDS.keys():
        raise ValueError('Motion channels must be an explicit unique subset of position, scale, angle')
    validate_time_map(binding.get('time_map'))
    _pair(binding.get('pivot_px'), 'pivot_px')
    _pair(binding.get('spatial_offset_px', [0, 0]), 'spatial_offset_px')
    for key, default in [('base_scale', None), ('spatial_scale', 1)]:
        if _number(binding.get(key, default), key) <= 0:
            raise ValueError(key + ' must be positive')
    _number(binding.get('base_angle_deg', 0), 'base_angle_deg')
    if binding.get('outside', 'error') != 'error':
        raise ValueError('Motion binding only supports explicit rejection outside coverage')
    if binding.get('stage') not in {'local_rgba', 'masked_canvas'}:
        raise ValueError('Motion stage must be local_rgba or masked_canvas')
    for size, name in [(image_size, 'image_size'), (canvas_size, 'canvas_size')]:
        if size is not None and any(v <= 0 for v in _pair(size, name)):
            raise ValueError(name + ' must be positive')
    if canvas_size is not None:
        source = profile['source']
        if tuple(canvas_size) != (source['width'], source['height']) and 'spatial_scale' not in binding:
            raise ValueError('Changed canvas requires explicit uniform spatial_scale and framing')
    return True


def validate_authored_channels(spec):
    """Reject two simultaneous owners of the same transform channel."""
    binding = spec.get('motion')
    if binding is None:
        return
    validate_binding(binding)
    fields = set().union(*(CHANNEL_FIELDS[name] for name in binding['channels']))
    conflicting = fields & set(spec)
    for key in spec.get('keys', []):
        conflicting |= fields & set(key)
    if conflicting:
        raise ValueError('Measured motion conflicts with authored channels: ' + ', '.join(sorted(conflicting)))
    if 'pivot' in spec:
        raise ValueError('Measured motion owns pivot_px; remove the separate authored pivot')
    if spec.get('quad_file'):
        raise ValueError('A perspective quad and similarity motion require a separate explicit composition stage')
    if spec.get('enter', 0):
        raise ValueError('Measured motion and authored enter animation cannot share a layer')


def source_time_at(binding, output_time):
    times = validate_time_map(binding.get('time_map'))
    time = _number(output_time, 'Output time')
    # Only absorb arithmetic roundoff, never a missing frame or source range.
    epsilon = 1e-10
    if time < times[0][0] - epsilon or time > times[-1][0] + epsilon:
        raise ValueError('Output time is outside the bound motion time_map')
    return float(np.interp(time, [r[0] for r in times], [r[1] for r in times]))


def transform_at(binding, output_time, image_size, canvas_size, defaults=None, *, profiles=None):
    """Evaluate the same profile used by QA, returning a renderer Transform.

    ``pivot_px`` refers to the image entering this call (after resize/crop).
    Position is the desired canvas location of that pivot. OpenCV's x/y fields
    are offsets, hence the subtraction, including during scale and rotation.
    """
    validate_binding(binding, image_size=image_size, canvas_size=canvas_size, profiles=profiles)
    profile = _profile_for(binding, profiles)
    pose = evaluate_element(profile, binding['element_id'], source_time_at(binding, output_time))
    fields = {'x': 0, 'y': 0, 'scale': 1, 'angle': 0, 'opacity': 1}
    if defaults:
        if set(defaults) - fields.keys():
            raise ValueError('Unknown default transform fields')
        fields.update(defaults)
    pivot = _pair(binding['pivot_px'], 'pivot_px')
    space = float(binding.get('spatial_scale', 1))
    offset = _pair(binding.get('spatial_offset_px', [0, 0]), 'spatial_offset_px')
    for channel in binding['channels']:
        key = {'position': 'position_px', 'scale': 'scale', 'angle': 'angle_deg_unwrapped'}[channel]
        if pose.get(key) is None:
            raise ValueError(f'Motion coverage missing for {binding["element_id"]}:{channel} at source time {source_time_at(binding, output_time):.9f}')
        if channel == 'position':
            observed = _pair(pose[key], 'Measured position')
            fields['x'] = observed[0] * space + offset[0] - pivot[0]
            fields['y'] = observed[1] * space + offset[1] - pivot[1]
        elif channel == 'scale':
            fields['scale'] = _number(pose[key], 'Measured scale') * binding['base_scale'] * space
        else:
            fields['angle'] = _number(pose[key], 'Measured angle') + binding.get('base_angle_deg', 0)
    return Transform(**fields, pivot=pivot)


def record_motion_use(usage, binding, frame, output_time, target):
    """Record only calls that reached a renderer; validation is not consumption."""
    spec = {k: v for k, v in binding.items() if k != 'profile'}
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    key = (digest, target)
    if key not in usage:
        usage[key] = {'binding_sha256': digest, 'profile_sha256': binding['profile_sha256'],
                      'element_id': binding['element_id'], 'target': target,
                      'channels': binding['channels'], 'stage': binding['stage'],
                      'frames': [], 'source_times': []}
    item = usage[key]
    if frame not in item['frames']:
        item['frames'].append(frame)
        item['source_times'].append(source_time_at(binding, output_time))


def motion_use_report(usage):
    records = []
    for item in usage.values():
        row = {k: v for k, v in item.items() if k != 'source_times'}
        row['frames'] = sorted(row['frames'])
        row['frame_count'] = len(row['frames'])
        row['source_time_range'] = [min(item['source_times']), max(item['source_times'])]
        records.append(row)
    return {'schema': 'element-motion-consumption/1', 'bindings': records,
            'perceptual_review': 'pending', 'user_approved': False}


def _target(row, target):
    if target in {'insert', 'foreground'}:
        if target not in row:
            raise ValueError('Motion target missing in output frame: ' + target)
        if target == 'insert' and 'layers' in row:
            raise ValueError('Top-level insert is inactive when independent layers are present')
        return row[target]
    if isinstance(target, str) and target.startswith('layer:'):
        found = [l['insert'] for l in row.get('layers', []) if l['id'] == target[6:]]
        if len(found) == 1:
            return found[0]
    raise ValueError('Motion target must be insert, foreground, or layer:<id>')


def bind_timeline_motion(timeline, profile, bindings, *, time_map=None):
    """Return a copied geometric timeline with explicit measured-motion bindings.

    Each configuration adds ``target`` and an output-frame ``interval`` [a,b)
    to the binding fields. Source-to-output time comes from its time_map or the
    supplied cadence map. No source RGB or alpha is borrowed from the profile.
    """
    if not isinstance(bindings, list) or not bindings:
        raise ValueError('Select at least one explicit element-motion binding')
    output = deepcopy(timeline)
    profile_sha = profile_digest(profile)
    _verified_profile(profile, profile_sha)
    pool = output.setdefault('motion_profiles', {})
    if profile_sha in pool and profile_digest(pool[profile_sha]) != profile_sha:
        raise ValueError('Existing motion_profiles entry has invalid content')
    pool[profile_sha] = deepcopy(profile)
    registry = MotionProfilePool(pool)
    rate = Fraction(str(output['fps']))
    total = output['frames']
    if rate <= 0 or len(output['frame_bindings']) != total:
        raise ValueError('Motion binding requires a positive complete output clock')
    if [b['frame'] for b in output['frame_bindings']] != list(range(total)):
        raise ValueError('Motion binding frame indices must cover output exactly')
    evidence = []
    for config in bindings:
        interval = config.get('interval')
        if not isinstance(interval, list) or len(interval) != 2 or any(type(v) is not int for v in interval) or not 0 <= interval[0] < interval[1] <= total:
            raise ValueError('Motion interval must be output frames [start,end) inside the timeline')
        binding = {k: deepcopy(v) for k, v in config.items() if k not in {'target', 'interval'}}
        if 'profile' in binding or 'profile_sha256' in binding:
            raise ValueError('Supply profile once; per-target profile overrides are not allowed')
        binding.update(schema=SCHEMA, profile_sha256=profile_sha)
        binding.setdefault('stage', 'masked_canvas')
        if binding['stage'] != 'masked_canvas':
            raise ValueError('Geometric motion requires stage masked_canvas')
        if time_map is not None:
            if 'time_map' in binding:
                raise ValueError('Cadence and binding cannot both own the motion time_map')
            binding['time_map'] = deepcopy(time_map)
        validate_binding(binding, image_size=(output['width'], output['height']), canvas_size=(output['width'], output['height']), profiles=registry)
        target = config.get('target')
        for frame in range(*interval):
            row = output['frame_bindings'][frame]
            item = _target(row, target)
            if 'motion' in item:
                raise ValueError('Overlapping or already-bound motion target: ' + str(target))
            if target == 'foreground' and 'box' in item:
                raise ValueError('Foreground box conflicts with measured placement; remove it explicitly')
            # Reject coverage gaps before starting an encoder or returning a plan.
            transform_at(binding, float(frame / rate), (output['width'], output['height']), (output['width'], output['height']), profiles=registry)
            item['motion'] = binding
        evidence.append({'element_id': binding['element_id'], 'target': target,
                         'interval': interval, 'profile_sha256': binding['profile_sha256'],
                         'time_map': binding['time_map'], 'stage': binding['stage']})
    output['element_motion'] = {'schema': 'element-motion-timeline/1', 'bindings': evidence,
                                'status': 'bound_not_rendered'}
    return output
