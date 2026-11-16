"""Measure reference cuts, musical phase and movement, then retime authored layers."""

import argparse
from bisect import bisect_right
from collections import Counter
from fractions import Fraction
from itertools import groupby
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np

from .cadence_models import beat_this, flow_estimator, transnet_v2
from .geometric_replay import evaluate
from .music_sync import analyze_audio, retime_binding_schedule

SCHEMA = 'reference-cadence/1'


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def video_clock(path):
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=avg_frame_rate,time_base:frame=best_effort_timestamp',
        '-of', 'json', str(path),
    ]))
    stream = probe['streams'][0]
    rate = Fraction(stream['avg_frame_rate'])
    tick = Fraction(stream['time_base'])
    stamps = [int(frame['best_effort_timestamp']) for frame in probe['frames']]
    if rate <= 0 or not stamps:
        raise ValueError('Video has no usable frame clock')
    if abs(stamps[0] * tick) > tick:
        raise ValueError('Normalize the reference to start at timestamp zero before analysis')
    if any(b <= a for a, b in zip(stamps, stamps[1:])) or any(
           abs((stamp - stamps[0]) * tick - i / rate) > tick
           for i, stamp in enumerate(stamps)):
        raise ValueError('Normalize variable-frame-rate media to CFR before cadence analysis')
    return rate, len(stamps)


def video_frames(path, rotation):
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f'Cannot open video: {path}')
    # With an explicit override, ignore container rotation for both decode passes.
    if rotation is not None:
        capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
    rotations = {90: cv2.ROTATE_90_COUNTERCLOCKWISE, 180: cv2.ROTATE_180,
                 270: cv2.ROTATE_90_CLOCKWISE}
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            yield cv2.rotate(frame, rotations[rotation]) if rotation in rotations else frame
    finally:
        capture.release()


def cut_candidates(frames, detector, threshold, implementation, checkpoint, device):
    if detector == 'transnet_v2':
        scores = transnet_v2(frames, implementation, checkpoint, device)
        single, multi = scores.T
        active = (np.maximum(single, multi) >= threshold)
        candidates = []
        for detected, interval in groupby(range(len(frames)), key=lambda i: active[i]):
            if not detected:
                continue
            start, *rest = interval
            end = rest[-1] if rest else start
            peak = start + int(np.argmax(single[start:end + 1]))
            # The official scene converter ends the old shot at the transition
            # frame. Keep the complete predicted interval for gradual changes.
            frame = min(end + 1, len(frames) - 1)
            if frame > 0:
                candidates.append({
                    'frame': frame, 'transition_frames': [start, end + 1],
                    'score': round(float(max(single[peak], multi[start:end + 1].max())), 5),
                })
        return candidates

    changes = np.abs(np.diff(frames.astype(np.float32), axis=0)).mean(axis=(1, 2, 3)) / 255
    return [{'frame': i, 'transition_frames': [i, i + 1], 'score': round(float(value), 5)}
            for i, value in enumerate(changes, 1) if value >= threshold]


def musical_position(time, music):
    beats = music['beats']
    index = bisect_right(beats, time) - 1
    position = {'time': time}
    if 0 <= index < len(beats) - 1:
        interval = beats[index + 1] - beats[index]
        fraction = (time - beats[index]) / interval
        nearest = index + int(fraction > .5)
        position.update(beat_index=index, beat_fraction=fraction,
                        offset_from_nearest_beat_ms=(time - beats[nearest]) * 1000)
    if music['cues']:
        cue = min(music['cues'], key=lambda c: abs(c['time'] - time))
        position['offset_from_nearest_transient_ms'] = (time - cue['time']) * 1000
    return position


def measure_motion(path, rotation, rate, count, backend, device, checkpoint,
                   regions, cut_frames, stride):
    estimate = flow_estimator(backend, device, checkpoint)
    previous = None
    excluded = set(cut_frames)
    profile = []
    for frame, image in enumerate(video_frames(path, rotation)):
        if frame % stride:
            continue
        height, width = image.shape[:2]
        scale = 256 / max(height, width)
        width, height = max(128, round(width * scale)), max(128, round(height * scale))
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        if previous is not None and excluded.isdisjoint(range(frame - stride + 1, frame + 1)):
            flow = estimate(previous, image)
            flow = flow * np.array([1 / width, 1 / height]) * float(rate) / stride
            row = {'frames': [frame - stride, frame], 'regions': {}}
            for name, (x, y, w, h) in regions.items():
                region = flow[int(y * height):max(int(y * height) + 1, round((y + h) * height)),
                              int(x * width):max(int(x * width) + 1, round((x + w) * width))]
                magnitude = np.linalg.norm(region, axis=2)
                row['regions'][name] = {
                    'median_xy_per_s': np.median(region, axis=(0, 1)).round(6).tolist(),
                    'p90_speed_per_s': round(float(np.quantile(magnitude, .90)), 6),
                }
            profile.append(row)
        previous = image
    if frame + 1 != count:
        raise ValueError('Motion decoder frame count differs from the reference clock')
    return profile


def analyze(path, *, soundtrack=None, audio_start=0, audio_speed=1, rotation=None,
            beat_checkpoint='final0', transnet_code=None, transnet_weights=None,
            raft_weights=None, device='cpu', baseline=False, regions=None, markers=None,
            stride=1, threshold=None):
    rate, count = video_clock(path)
    duration = float(count / rate)
    regions = regions or {'full': [0, 0, 1, 1]}
    if any(not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 - x + 1e-9
                and 0 < h <= 1 - y + 1e-9) for x, y, w, h in regions.values()):
        raise ValueError('Regions must be nonempty normalized [x, y, width, height] boxes')
    if stride < 1:
        raise ValueError('Motion stride must be >= 1')
    if not baseline and (not transnet_code or not transnet_weights):
        raise ValueError('Pass --transnet-code and --transnet-weights, or explicitly select --baseline')
    detector = 'pixel_change' if baseline else 'transnet_v2'
    flow = 'farneback' if baseline else 'raft_small'
    threshold = (.15 if baseline else .50) if threshold is None else threshold
    if not 0 < threshold <= 1:
        raise ValueError('Cut threshold must be in (0, 1]')
    if not soundtrack:
        audio_probe = subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=index', '-of', 'csv=p=0', str(path),
        ])
        soundtrack = path if audio_probe.strip() else None
    music = {'backend': 'none', 'beats': [], 'downbeats': [], 'cues': []}
    if soundtrack:
        cues = analyze_audio(soundtrack, duration, audio_start, audio_speed)
        if cues['status'] == 'silence':
            backend = {'backend': 'silence', 'beats': [], 'downbeats': []}
        elif baseline:
            backend = {'backend': 'spectral_flux', 'beats': [], 'downbeats': [],
                       'estimated_pulse': cues['pulse']}
        else:
            backend = beat_this(soundtrack, duration, audio_start, audio_speed, beat_checkpoint, device)
        music.update(backend, cues=cues['cues'], audio_sha256=cues['source_sha256'],
                     clock=cues['clock'])

    thumbnails = np.array([
        cv2.cvtColor(cv2.resize(image, (48, 27), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        for image in video_frames(path, rotation)
    ])
    if len(thumbnails) != count:
        raise ValueError('Cut decoder frame count differs from the reference clock')
    cuts = cut_candidates(thumbnails, detector, threshold, transnet_code, transnet_weights, device)
    for cut in cuts:
        cut.update(musical_position(float(cut['frame'] / rate), music))
    intervals = [(c['transition_frames'][0], c['frame']) for c in cuts]
    excluded = {f for start, end in intervals for f in range(start, end + 1)}
    boundaries = sorted({0, count, *(c['frame'] for c in cuts)})
    landmarks = {}
    for name, frame in (markers or {}).items():
        if type(frame) is not int or not 0 <= frame < count:
            raise ValueError(f'Invalid reference marker: {name}')
        landmarks[name] = {'frame': frame, **musical_position(float(frame / rate), music)}
    model_files = {
        key: digest(value) for key, value in {
            'transnet_code': transnet_code, 'transnet_weights': transnet_weights,
            'raft_weights': raft_weights, 'beat_checkpoint': beat_checkpoint,
        }.items() if not baseline and value and Path(value).is_file()
    }
    return {
        'schema': SCHEMA, 'source_sha256': digest(path), 'fps': str(rate), 'frames': count,
        'rotation_ccw': rotation, 'cut_detector': detector, 'cut_threshold': threshold,
        'cuts': cuts, 'shots': [{'start': a, 'end': b, 'duration_s': float((b - a) / rate)}
                                for a, b in zip(boundaries, boundaries[1:])],
        'music': music, 'markers': landmarks, 'motion_backend': flow, 'motion_stride': stride,
        'regions': regions, 'motion': measure_motion(
            path, rotation, rate, count, flow, device, raft_weights, regions, excluded, stride,
        ),
        'model_files_sha256': model_files,
        'status': 'baseline' if baseline else 'model_inference',
    }


def project_time(position, target_music, beat_offset):
    if target_music is None:
        return position['time']
    if 'beat_index' not in position:
        raise ValueError('Reference landmark is outside the measured beat grid')
    beats = target_music['beats']
    index = position['beat_index'] + beat_offset
    if not 0 <= index < len(beats) - 1:
        raise ValueError('Target soundtrack has no corresponding beat interval')
    return beats[index] + position['beat_fraction'] * (beats[index + 1] - beats[index])


def apply_cadence(template, reference, anchors, *, target_music=None, beat_offset=0,
                  reference_start_frame=0, mask_track=None):
    """Retarget selected cut/transition landmarks while preserving layer bindings."""
    if reference.get('schema') != SCHEMA:
        raise ValueError('Expected a reference cadence map')
    if not anchors:
        raise ValueError('Select at least one reference cut or marker')
    rate = Fraction(str(template['fps']))
    reference_rate = Fraction(reference['fps'])
    if type(reference_start_frame) is not int or not 0 <= reference_start_frame < reference['frames']:
        raise ValueError('Reference start frame is outside the reference')
    if target_music is not None and (reference_start_frame or mask_track):
        raise ValueError('Reference excerpts and measured mask tracks use the original time clock')
    total = template['frames']
    if len(template['frame_bindings']) != total:
        raise ValueError('The template must bind every output frame')
    cuts = {c['frame']: c for c in reference['cuts']}
    mapping = [{'output_frame': 0, 'source_frame': 0}]
    evidence = []
    for anchor in anchors:
        selector = 'marker' if 'marker' in anchor else 'reference_cut'
        value = anchor[selector]
        position = reference['markers'][value] if selector == 'marker' else cuts[value]
        time = project_time(position, target_music, beat_offset) - float(reference_start_frame / reference_rate)
        frame = round(time * rate)
        original = anchor['template_frame']
        if type(original) is not int or not 0 < original < total or not 0 < frame < total:
            raise ValueError('Cadence anchors must fall inside the template and output')
        mapping.append({'output_frame': frame, 'source_frame': original})
        evidence.append({selector: value, 'reference_frame': position['frame'],
                         'reference_time': position['time'], 'output_frame': frame,
                         'time': time, 'template_frame': original,
                         'beat_index': position.get('beat_index'),
                         'beat_fraction': position.get('beat_fraction')})
    mapping.append({'output_frame': total, 'source_frame': total})
    bindings = retime_binding_schedule(template['frame_bindings'], mapping, total)
    samples = [b['retime_template_frame'] for b in bindings]
    events = []
    mask_frames = {}
    for sample in mask_track or []:
        index = sample['frame']
        if type(index) is not int or not 0 <= index < reference['frames'] or index in mask_frames:
            raise ValueError('Measured mask frames must be unique and inside the reference')
        mask_frames[index] = sample['mask']
    reference_samples = np.floor(np.interp(
        np.arange(total), [0, *(e['output_frame'] for e in evidence), total],
        [reference_start_frame, *(e['reference_frame'] for e in evidence),
         float(reference_start_frame + total * reference_rate / rate)],
    ) + 1e-8).astype(int) if mask_frames else ()
    transferred = 0
    for binding in bindings:
        binding.pop('music_events', None)
        template_frame = binding['retime_template_frame']
        if 'mask' in binding:
            binding['mask'] = evaluate(binding['mask'], template_frame)
        if binding.get('tint'):
            binding['tint']['mask'] = evaluate(binding['tint']['mask'], template_frame)
        if mask_frames and (ref_frame := int(reference_samples[binding['frame']])) in mask_frames:
            if 'insert' not in binding:
                raise ValueError(f'Measured mask at frame {ref_frame} has no bound insert')
            binding.pop('mask_file', None)
            binding['mask'] = evaluate(mask_frames[ref_frame], ref_frame)
            # Authored opacity on the reference track is handled by mask().
            binding.pop('mask_opacity', None)
            binding['reference_mask_frame'] = ref_frame
            transferred += 1
    for i, event in enumerate(evidence):
        frame = event['output_frame']
        event_id = f'reference-landmark-{i + 1}'
        bindings[frame]['music_events'] = [event_id]
        events.append({'event_id': event_id, 'frame': frame, 'cue_time': event['time'],
                       'role': 'cut' if 'reference_cut' in event else 'reference_marker'})

    audio = template.get('audio')
    new_sync = None
    if audio:
        music = target_music if target_music is not None else template.get('music_sync', {})
        audio_hash = music.get('audio_sha256')
        clock = music.get('clock', {})
        start = clock.get('source_start', clock.get('start'))
        speed = clock.get('speed')
        if not audio_hash or start != audio.get('start', 0) or speed != audio.get('speed', 1):
            raise ValueError('Cadence soundtrack hash and clock must match template audio')
        new_sync = {'mode': 'reference_cadence', 'audio_sha256': audio_hash,
                    'clock': {'start': start, 'speed': speed}, 'events': events,
                    'projection': 'beat_phase' if target_music is not None else 'reference_seconds'}

    plan = template.get('asset_plan')
    output = dict(template, frame_bindings=bindings)
    if plan:
        slots = []
        for slot in plan['slots']:
            start, end = slot['interval']
            interval = [int(np.searchsorted(samples, t)) for t in (start, end)]
            slots.append(dict(slot, interval=interval))
        output['asset_plan'] = dict(plan, slots=slots)
    if new_sync:
        output['music_sync'] = new_sync
    shots = []
    for shot, rows in groupby(bindings, key=lambda b: b['shot']):
        frames = [row['frame'] for row in rows]
        shots.append({'id': shot, 'start': frames[0], 'end': frames[-1] + 1})
    output['shots'] = shots
    frame_counts = Counter(samples)
    output['reference_cadence'] = {
        'schema': SCHEMA, 'source_sha256': reference['source_sha256'],
        'status': reference['status'], 'anchors': evidence, 'reference_start_frame': reference_start_frame,
        'measured_mask_frames_applied': transferred,
        'repeated_template_frames': sum(n - 1 for n in frame_counts.values()),
        'skipped_template_frames': total - len(frame_counts),
        'providers': {'cuts': reference['cut_detector'], 'motion': reference['motion_backend'],
                      'music': reference['music']['backend']},
    }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('analyze')
    scan.add_argument('video', type=Path)
    scan.add_argument('output', type=Path)
    scan.add_argument('--soundtrack', type=Path)
    scan.add_argument('--audio-start', type=float, default=0)
    scan.add_argument('--audio-speed', type=float, default=1)
    scan.add_argument('--rotation', choices=[0, 90, 180, 270], type=int)
    scan.add_argument('--beat-checkpoint', default='final0')
    scan.add_argument('--transnet-code', type=Path)
    scan.add_argument('--transnet-weights', type=Path)
    scan.add_argument('--raft-weights', type=Path)
    scan.add_argument('--device', default='cpu')
    scan.add_argument('--stride', type=int, default=1)
    scan.add_argument('--threshold', type=float)
    scan.add_argument('--regions', type=Path)
    scan.add_argument('--markers', type=Path)
    scan.add_argument('--baseline', action='store_true')
    apply = commands.add_parser('apply')
    apply.add_argument('template', type=Path)
    apply.add_argument('reference', type=Path)
    apply.add_argument('anchors', type=Path)
    apply.add_argument('output', type=Path)
    apply.add_argument('--target-map', type=Path)
    apply.add_argument('--beat-offset', type=int, default=0)
    apply.add_argument('--reference-start-frame', type=int, default=0)
    apply.add_argument('--mask-track', type=Path, help='JSON list of {frame, mask} reference samples')
    apply.add_argument('--render', type=Path)
    args = parser.parse_args()

    def load(path):
        return json.loads(path.read_text()) if path else None

    if args.command == 'analyze':
        result = analyze(
            args.video, soundtrack=args.soundtrack, audio_start=args.audio_start,
            audio_speed=args.audio_speed, rotation=args.rotation, beat_checkpoint=args.beat_checkpoint,
            transnet_code=args.transnet_code, transnet_weights=args.transnet_weights,
            raft_weights=args.raft_weights, device=args.device, baseline=args.baseline,
            regions=load(args.regions), markers=load(args.markers), stride=args.stride,
            threshold=args.threshold,
        )
    else:
        from .edit_contract import validate_edit
        if args.output.resolve().parent != args.template.resolve().parent:
            parser.error('Output manifest must share the template directory so asset paths still resolve')
        if args.output.resolve() == args.template.resolve():
            parser.error('Use a new output filename to preserve the original timeline')
        target = load(args.target_map)
        result = apply_cadence(load(args.template), load(args.reference), load(args.anchors),
                               target_music=None if target is None else target['music'],
                               beat_offset=args.beat_offset, reference_start_frame=args.reference_start_frame,
                               mask_track=load(args.mask_track))
        validate_edit(result, args.output.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    if args.command == 'apply' and args.render:
        from .geometric_video import render
        render(args.output, args.render)


if __name__ == '__main__':
    main()
