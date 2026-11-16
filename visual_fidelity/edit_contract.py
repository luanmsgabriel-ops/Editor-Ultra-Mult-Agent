"""Pre-render contracts for musical clocks and planned visual insert coverage.

These checks enforce authored evidence and bindings; they do not infer semantics
or certify perceptual quality. A reviewer must populate the asset plan first.
"""
from pathlib import Path
from fractions import Fraction
import hashlib
import math

VERSION = '1.0.0'

def validate_edit(data, root):
    root = Path(root)
    rate = float(Fraction(str(data['fps'])))
    frames = data['frame_bindings']
    audio = data.get('audio')
    report = {'version': VERSION, 'music': 'not_present', 'asset_slots': []}
    if audio:
        sync = data.get('music_sync')
        if not sync:
            raise ValueError('Audio requires music_sync or an explicit editorial override')
        if sync.get('mode') == 'editorial_override':
            if not sync.get('reason', '').strip():
                raise ValueError('Editorial override requires a reason')
            report['music'] = 'unsynchronized_override'
        else:
            digest = hashlib.sha256((root / audio['path']).read_bytes()).hexdigest()
            if sync.get('audio_sha256') != digest:
                raise ValueError('Music map belongs to another audio file')
            clock = sync.get('clock', {})
            if clock.get('start') != audio.get('start', 0) or clock.get('speed') != audio.get('speed', 1):
                raise ValueError('Music map clock differs from rendered audio clock')
            events = sync.get('events', [])
            if not events:
                raise ValueError('Music map has no authored events')
            ids = set()
            errors = []
            for e in events:
                eid = e['event_id']; f = e['frame']; t = e['cue_time']
                if eid in ids or not isinstance(f, int) or not 0 <= f < len(frames):
                    raise ValueError('Duplicate or invalid musical event')
                ids.add(eid)
                if not math.isfinite(t) or abs(f / rate - t) > 0.5 / rate + 1e-8:
                    raise ValueError('Event not at nearest frame to musical cue')
                if eid not in frames[f].get('music_events', []):
                    raise ValueError('Musical event has no frame binding')
                errors.append(abs(f / rate - t) * 1000)
            report.update(music='bound', events=len(events), maximum_quantization_ms=max(errors))
    plan = data.get('asset_plan')
    if not plan or not plan.get('slots'):
        raise ValueError('Visual asset plan with reference evidence is required')
    for binding in frames:
        if 'layers' not in binding:
            continue
        if not binding['layers'] or not binding.get('foreground', {}).get('matte'):
            raise ValueError('Layered compositions require masks and a subject matte')
        if not (root / binding['foreground']['matte']).is_file():
            raise ValueError('Missing subject matte for layered composition')
        layer_ids = set()
        for layer in binding['layers']:
            if layer['depth'] not in {'behind_subject', 'in_front_of_subject'} or layer['id'] in layer_ids:
                raise ValueError('Layers require resolved depth and unique names')
            layer_ids.add(layer['id'])
            asset = data['assets'][layer['insert']['source']]
            if not (root / asset['path']).is_file():
                raise ValueError('Missing independent layer asset')
            if asset.get('origin') == 'generated' and not (root / asset.get('provenance', '__missing__')).is_file():
                raise ValueError('Generated layer asset needs provenance')
    for slot in plan['slots']:
        if not slot.get('evidence') or not slot.get('role'):
            raise ValueError('Asset slot lacks reference evidence or visual role')
        if slot.get('status') != 'ready':
            raise ValueError('Unresolved asset slot: ' + slot['id'])
        keys = slot.get('asset_ids', [])
        if not keys:
            raise ValueError('Empty asset slot')
        for key in keys:
            asset = data['assets'][key]
            if not (root / asset['path']).is_file():
                raise ValueError('Missing visual asset: ' + key)
            if asset.get('origin') == 'generated' and not (root / asset.get('provenance', '__missing__')).is_file():
                raise ValueError('Generated asset needs provenance: ' + key)
        uses = []
        a, b = slot['interval']
        if not 0 <= a < b <= len(frames):
            raise ValueError('Invalid asset slot interval')
        for binding in frames[a:b]:
            sources = [binding.get(layer, {}).get('source') for layer in ('base', 'insert', 'foreground')]
            sources.extend(layer['insert']['source'] for layer in binding.get('layers', []))
            if any(source in keys for source in sources):
                uses.append(binding['frame'])
        if len(uses) < slot.get('min_visible_frames', 1):
            raise ValueError('Planned asset is not consumed in its scene: ' + slot['id'])
        report['asset_slots'].append({'id':slot['id'], 'bound_frames':len(uses),
                                     'semantic_review':slot.get('semantic_review', 'pending')})
    return report
