"""Measured audio cues, constrained motion scheduling and coherent frame retiming.

Transient peaks are not claimed to be musical beats. Pulse confidence is a
heuristic, not a probability; manual cue sheets remain first-class inputs.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import argparse
import hashlib
import json
import math
import subprocess

import numpy as np
from scipy.signal import find_peaks

VERSION = '1.0.1'
SAMPLE_RATE = 48000
HOP = 240
FFT_SIZE = 1024
BANDS = [('low', 35, 180), ('mid', 180, 2000), ('high', 2000, 12000)]


def _finite(value, name):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return value


def edited_audio_filter(start, speed, duration):
    """Shared analysis/render clock. speed=1 bypasses WSOLA entirely."""
    duration = _finite(duration, 'duration'); start = _finite(start, 'start')
    speed = _finite(speed, 'speed')
    if duration <= 0 or start < 0 or not .5 <= speed <= 2:
        raise ValueError('Require duration>0, start>=0 and speed in [0.5,2]')
    tempo_filter = '' if speed == 1 else f',atempo={speed}'
    return f'atrim=start={start},asetpts=PTS-STARTPTS{tempo_filter},atrim=duration={duration}'


def _flux(audio):
    """Centered windows; channel maximum protects opposite-phase stereo."""
    centers = np.arange(0, len(audio), HOP)
    frequencies = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
    selections = [(frequencies >= lo) & (frequencies < hi) for _, lo, hi in BANDS]
    window = np.hanning(FFT_SIZE)
    previous = np.zeros(len(frequencies))
    blocks = []
    for start in range(0, len(centers), 128):
        ix = centers[start:start + 128, None] + np.arange(-FFT_SIZE // 2, FFT_SIZE // 2)
        valid = (ix >= 0) & (ix < len(audio))
        samples = np.where(valid[..., None], audio[ix.clip(0, len(audio) - 1)], 0)
        spectrum = abs(np.fft.rfft(samples * window[None, :, None], axis=1)).max(axis=2)
        spectrum = np.log1p(1000 * spectrum / (window.sum() / 2))
        rise = np.maximum(0, np.diff(spectrum, axis=0, prepend=previous[None, :]))
        blocks.append(np.column_stack([rise[:, m].mean(axis=1) for m in selections]))
        previous = spectrum[-1]
    return centers / SAMPLE_RATE, np.concatenate(blocks)


def _energy_context(audio, time):
    """Measure sustained energy around a cue, excluding the transient itself.

    A large return is only a candidate accent. It does not identify a downbeat.
    Stereo power avoids phase cancellation; silence is floored at -120 dBFS.
    """
    values = {}
    complete = True
    for name, start, end in [('pre', -.080, -.015), ('post', .015, .080)]:
        left = round((time + start) * SAMPLE_RATE)
        right = round((time + end) * SAMPLE_RATE)
        complete &= left >= 0 and right <= len(audio)
        window = audio[max(0, left):min(len(audio), right)] if right > 0 and left < len(audio) else []
        power = float(np.mean(np.square(window, dtype=np.float64))) if len(window) else 0.0
        values[f'{name}_rms_dbfs'] = round(10 * math.log10(max(power, 1e-12)), 4)
    change = values['post_rms_dbfs'] - values['pre_rms_dbfs']
    return {**values, 'energy_change_db': round(change, 4),
            'energy_context_complete': bool(complete),
            'suggested_priority': 'energy_return' if complete and change >= 6 else 'texture_attack'}


def _pulse(times, envelope, cues):
    empty = {'status': 'insufficient_evidence', 'bpm': None, 'confidence': 0.0,
             'beat_times': [], 'alternatives_bpm': [],
             'note': 'Heuristic periodicity only; no downbeat or meter identification.'}
    if len(cues) < 4 or len(times) < 400 or float(envelope.max()) < 1e-8:
        return empty
    dt = HOP / SAMPLE_RATE
    x = np.maximum(envelope - np.median(envelope), 0)
    candidates = []
    for lag in range(round(60 / 200 / dt), round(60 / 60 / dt) + 1):
        left, right = x[:-lag], x[lag:]
        denom = math.sqrt(float(left @ left) * float(right @ right))
        correlation = float(left @ right) / max(denom, 1e-12)
        candidates.append((correlation, lag))
    candidates.sort(reverse=True)
    correlation, lag = candidates[0]
    period = lag * dt
    cue_times = np.array([c['time'] for c in cues])
    weights = np.array([c['strength'] for c in cues])
    # Find a phase supported by observed attacks, not an assumed zero-time beat.
    def phase_score(phase):
        distance = abs((cue_times - phase + period / 2) % period - period / 2)
        return float(np.sum(weights * np.exp(-.5 * (distance / .045) ** 2)) / weights.sum())
    phase = max(cue_times % period, key=phase_score)
    support = phase_score(phase)
    confidence = float(np.clip(correlation, 0, 1) * support)
    alternatives = []
    for score, candidate_lag in candidates:
        bpm = 60 / (candidate_lag * dt)
        if score >= correlation * .7 and all(abs(bpm - p) > 5 for p in alternatives):
            alternatives.append(round(bpm, 3))
        if len(alternatives) == 3:
            break
    status = 'periodic_candidate' if confidence >= .35 else 'irregular_or_ambiguous'
    beats = np.arange(phase, times[-1] + dt / 2, period) if status == 'periodic_candidate' else []
    return {**empty, 'status': status, 'bpm': round(60 / period, 4),
            'confidence': round(confidence, 4), 'correlation': round(correlation, 4),
            'phase_support': round(support, 4), 'alternatives_bpm': alternatives,
            'beat_times': [round(float(t), 6) for t in beats]}


def decode_pcm(path, duration, start=0, speed=1):
    """Decode the render's soundtrack interval as stereo float32 little-endian PCM."""
    filters = edited_audio_filter(start, speed, duration)
    return subprocess.check_output([
        'ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:a:0',
        '-vn', '-af', filters, '-ar', str(SAMPLE_RATE), '-ac', '2',
        '-f', 'f32le', '-c:a', 'pcm_f32le', '-',
    ])


def analyze_audio(path, duration, start=0, speed=1):
    """Analyze the same trimmed/tempo-mapped clock used for the output soundtrack.

    Returns cues with output-relative seconds. start is a source offset in
    seconds and speed is FFmpeg atempo (0.5..2). No new music is synthesized.
    """
    duration = float(duration); start = float(start); speed = float(speed); path = Path(path)
    raw = decode_pcm(path, duration, start, speed)
    audio = np.frombuffer(raw, dtype='<f4').reshape(-1, 2)
    if not len(audio):
        raise ValueError('Selected soundtrack contains no decoded samples')
    if not np.isfinite(audio).all():
        raise ValueError('Non-finite audio samples')
    times, bands = _flux(audio)
    # Per-band normalization avoids low-band amplitude hiding short bright accents.
    scales = np.maximum(np.percentile(bands, 95, axis=0), .02)
    normalized = np.minimum(bands / scales, 4)
    envelope = normalized @ np.array([.40, .35, .25])
    median = float(np.median(envelope))
    mad = float(np.median(abs(envelope - median)))
    threshold = max(.18, median + 2.5 * mad, float(envelope.max()) * .10)
    peaks, _ = find_peaks(envelope, height=threshold, prominence=max(.10, mad),
                          distance=round(.09 * SAMPLE_RATE / HOP))
    # Short-window energy rise refines the centered spectral-window estimate.
    block = 48
    trimmed = audio[:len(audio) // block * block]
    energy = np.sqrt(np.mean(trimmed.reshape(-1, block, 2) ** 2, axis=(1, 2)))
    rise = np.maximum(0, np.diff(energy, prepend=0))
    cues = []
    top = max(float(envelope.max()), 1e-12)
    for k in peaks:
        approximate = times[k]
        lo = max(0, round((approximate - .012) * 1000))
        hi = min(len(rise), round((approximate + .018) * 1000) + 1)
        refined = (lo + int(np.argmax(rise[lo:hi]))) / 1000 if hi > lo else approximate
        if refined >= duration or refined < 0:
            continue
        cues.append({'id': f'onset-{len(cues):03}', 'time': round(float(refined), 6),
                     'source_time_nominal': round(start + refined * speed, 6),
                     'strength': round(float(envelope[k] / top), 6), 'kind': 'transient',
                     'spectral_peak_time': round(float(approximate), 6),
                     **_energy_context(audio, refined),
                     'bands': {name: round(float(normalized[k, j]), 5)
                               for j, (name, _, _) in enumerate(BANDS)}})
    silent = float(np.max(abs(audio))) < 1e-5
    if silent:
        cues = []
    return {'schema': 'music-cues/1', 'engine_version': VERSION,
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'pcm_sha256': hashlib.sha256(raw).hexdigest(),
            'clock': {'source_start': start, 'speed': speed, 'duration': duration,
                      'decoded_duration': len(audio) / SAMPLE_RATE, 'sample_rate': SAMPLE_RATE,
                      'complete': len(audio) >= round(duration * SAMPLE_RATE) - 1,
                      'time_origin': 'first sample after trim/atempo, output-relative seconds'},
            'status': 'silence' if silent else 'analyzed', 'cues': cues,
            'pulse': _pulse(times, envelope, cues),
            'method': {'fft_samples': FFT_SIZE, 'hop_samples': HOP,
                       'peak_min_distance_seconds': .09, 'energy_refinement_bin_seconds': .001,
                       'energy_context_windows_seconds': {'pre': [-.080, -.015], 'post': [.015, .080]},
                       'energy_return_threshold_db': 6},
            'limitations': ['Transient candidates are not verified beats or downbeats.',
                            'Tempo ambiguity (half/double time) and mixed sound effects require review.',
                            'No confirmed perceptual listening; waveform timing is not aesthetic approval.']}


def schedule_events(events, cues, fps, total_frames):
    """Globally choose ordered cues in explicit windows; fail instead of drifting.

    events: id,target_time,max_shift,min_gap_frames(optional,default1),role,
    cue_id(optional lock). cues: id,time,strength(optional),kind(optional).
    Manual cues use the same schema with kind='manual'. FPS may be fractional.
    """
    try:
        fps = _finite(Fraction(str(fps)), 'fps')
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('Invalid FPS') from error
    if fps <= 0 or int(total_frames) != total_frames or total_frames <= 0:
        raise ValueError('Invalid output clock')
    if not events:
        return []
    pool = []
    seen = set()
    for cue in cues:
        if cue['id'] in seen:
            raise ValueError('Cue IDs must be unique')
        seen.add(cue['id'])
        time = _finite(cue['time'], 'cue time')
        if time < 0:
            raise ValueError('Negative cue time')
        frame = math.floor(time * fps + .5)
        if frame < total_frames:
            pool.append({**cue, 'time': time, 'frame': frame,
                         'strength': float(np.clip(_finite(cue.get('strength', 1), 'strength'), 0, 1))})
    pool.sort(key=lambda c: (c['frame'], c['id']))
    layers = []
    previous_target = -1
    event_ids = set()
    for event in events:
        target = _finite(event['target_time'], 'target_time')
        window = _finite(event['max_shift'], 'max_shift')
        gap = event.get('min_gap_frames', 1)
        if (not 0 <= target < total_frames / fps or target < previous_target or window < 0
                or int(gap) != gap or gap < 1 or event['id'] in event_ids):
            raise ValueError('Invalid event clock, order, gap, window or duplicate ID')
        previous_target = target; event_ids.add(event['id'])
        options = []
        for cue in pool:
            if event.get('cue_id') is not None and event['cue_id'] != cue['id']:
                continue
            if abs(cue['time'] - target) > window + 1e-9:
                continue
            if abs(cue['frame'] / fps - target) > window + .5 / fps + 1e-9:
                continue
            cost = (abs(cue['time'] - target) / max(window, .5 / fps)) ** 2 - .25 * cue['strength']
            if not layers:
                options.append((cost, cue, None))
            else:
                admissible = [(p[0], j) for j, p in enumerate(layers[-1])
                              if cue['frame'] - p[1]['frame'] >= gap]
                if admissible:
                    best, parent = min(admissible)
                    options.append((cost + best, cue, parent))
        if not options:
            raise ValueError(f"No collision-free cue assignment for event {event['id']}")
        layers.append(options)
    index = min(range(len(layers[-1])), key=lambda j: layers[-1][j][0])
    result = []
    for i in range(len(events) - 1, -1, -1):
        _, cue, parent = layers[i][index]; event = events[i]
        time = cue['frame'] / fps
        result.append({'event_id': event['id'], 'role': event.get('role', 'cut'),
                       'cue_id': cue['id'], 'cue_kind': cue.get('kind', 'transient'),
                       'cue_evidence': deepcopy(cue.get('evidence')),
                       'cue_time': cue['time'], 'frame': cue['frame'], 'time': time,
                       'quantization_error_ms': (time - cue['time']) * 1000,
                       'shift_ms': (time - event['target_time']) * 1000})
        index = parent
    return list(reversed(result))


def retime_binding_schedule(bindings, anchors, total_frames):
    """Piecewise frame mapping; source pixels and their mattes travel together.

    Anchors are integer {output_frame,source_frame} pairs. First output anchor
    must be 0; last can be total_frames-1 (sample) or total_frames (exclusive
    boundary). Source indexes strictly increase. Binding
    internals are copied intact, including geometric mask phase values; callers
    must bake animated expressions first. Frame repetition/drop is explicit.
    """
    if len(anchors) < 2 or total_frames < 2:
        raise ValueError('At least two anchors/frames required')
    xs = [a['output_frame'] for a in anchors]; ys = [a['source_frame'] for a in anchors]
    exclusive = xs[-1] == total_frames
    if (any(int(x) != x for x in xs + ys) or xs[0] != 0 or xs[-1] not in (total_frames - 1, total_frames)
            or any(b <= a for a, b in zip(xs, xs[1:]))
            or any(b <= a for a, b in zip(ys, ys[1:]))
            or ys[0] < 0 or ys[-1] > len(bindings) - (0 if exclusive else 1)):
        raise ValueError('Invalid retiming anchors')
    # Floor instead of round: round may reveal the next shot a frame before its
    # anchor when source83.6 becomes84. The upper segment boundary is exclusive.
    mapped = np.floor(np.interp(np.arange(total_frames), xs, ys) + 1e-9).astype(int).clip(0, len(bindings)-1)
    result = []
    for frame, source in enumerate(mapped):
        binding = deepcopy(bindings[int(source)])
        binding['frame'] = frame
        binding['retime_template_frame'] = int(source)
        result.append(binding)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--duration', required=True, type=float)
    parser.add_argument('--start', default=0, type=float); parser.add_argument('--speed', default=1, type=float)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(analyze_audio(args.audio, args.duration, args.start, args.speed), indent=2))
