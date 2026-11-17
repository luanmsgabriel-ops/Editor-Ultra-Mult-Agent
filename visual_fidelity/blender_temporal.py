"""Temporal-safe authoring of Blender object motion.

This does not infer trajectories or enable motion blur. It records an explicitly
observed/authored sampled motion path on Blender's actual frame clock, so a
renderer with temporal sampling can evaluate it between shutter samples.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

_CHANNELS = {'location': 3, 'rotation_euler': 3, 'scale': 3}


def validate_samples(samples: list[dict], *, first_frame=1, max_frame=3600):
    if type(first_frame) is not int or first_frame < 0 or type(max_frame) is not int or max_frame < first_frame:
        raise ValueError('Invalid frame bounds')
    if not isinstance(samples, list) or len(samples) < 2 or len(samples) > max_frame - first_frame + 1:
        raise ValueError('At least two, bounded samples are required')
    previous = first_frame - 1
    keys = None
    normalized = []
    for sample in samples:
        if not isinstance(sample, dict) or 'frame' not in sample or set(sample) - ({'frame'} | set(_CHANNELS)):
            raise ValueError('Sample must have frame and supported transform channels')
        if type(sample['frame']) is not int or not previous < sample['frame'] <= max_frame:
            raise ValueError('Frame indices must be increasing, unique, and in range')
        previous = sample['frame']
        rowkeys = set(sample) - {'frame'}
        if not rowkeys or (keys is not None and rowkeys != keys):
            raise ValueError('Every sample must define the same nonempty channels')
        keys = rowkeys
        row = {'frame': sample['frame']}
        for channel in sorted(keys):
            value = sample[channel]
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != _CHANNELS[channel]:
                raise ValueError(f'{channel} must have three values')
            if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
                raise ValueError(f'{channel} must contain finite values')
            row[channel] = tuple(float(x) for x in value)
        normalized.append(row)
    return normalized


def key_object_motion(scene, obj, samples, *, first_frame=1, max_frame=3600):
    """Write keyframes and evaluate scene at the first key; rendering is separate."""
    rows = validate_samples(samples, first_frame=first_frame, max_frame=max_frame)
    for row in rows:
        frame = row['frame']
        for channel in ('location', 'rotation_euler', 'scale'):
            if channel in row:
                setattr(obj, channel, row[channel])
                obj.keyframe_insert(data_path=channel, frame=frame)
    scene.frame_set(rows[0]['frame'])
    return {'schema': 'blender-temporal-keyframes/1', 'frame_range': [rows[0]['frame'], rows[-1]['frame']],
            'sample_count': len(rows), 'channels': sorted(set(rows[0]) - {'frame'}),
            'rendered': False, 'motion_blur_verified': False}
