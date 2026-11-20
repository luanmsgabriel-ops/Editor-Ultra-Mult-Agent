"""Compare the screen coverage and timing of a selected effect color in decoded CFR media."""
import argparse
from contextlib import ExitStack, closing
from fractions import Fraction
import json
import math
from pathlib import Path

import cv2
import numpy as np

from .reference_cadence import digest, video_clock, video_frames


def _interval(side, total):
    bounds = side.get('frames')
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2 or any(type(n) is not int for n in bounds)
            or not 0 <= bounds[0] < bounds[1] <= total):
        raise ValueError(f'Expected a non-empty, half-open frame interval within {total} frames')
    return range(*bounds)


def _hsv_bounds(pair):
    limits = (179, 255, 255)
    if (not isinstance(pair, (list, tuple)) or len(pair) != 2
            or any(not isinstance(vector, (list, tuple)) or len(vector) != 3 for vector in pair)
            or any(type(v) is not int or not 0 <= v <= limit
                   for vector in pair for v, limit in zip(vector, limits))
            or any(lo > hi for lo, hi in zip(*pair))):
        raise ValueError('hsv must contain ordered OpenCV HSV lower/upper bounds')
    return tuple(tuple(vector) for vector in pair)


def _roi(side, width, height):
    coords = side.get('roi', [0, 0, 1, 1])
    if (not isinstance(coords, (list, tuple)) or len(coords) != 4
            or not all(type(x) in (int, float) and math.isfinite(x) for x in coords)
            or not (0 <= coords[0] < coords[2] <= 1 and 0 <= coords[1] < coords[3] <= 1)):
        raise ValueError('roi must be normalized [left, top, right, bottom]')
    l, t, r, b = np.array(coords) * [width, height, width, height]
    return math.floor(l), math.floor(t), math.ceil(r), math.ceil(b)


def _observe(frame, clean, side, selector, min_area, change, matte):
    height, width = frame.shape[:2]
    left, top, right, bottom = _roi(side, width, height)
    region = np.s_[top:bottom, left:right]
    pixels = frame[region]
    selected = cv2.inRange(cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV), *selector)
    if matte is not None:
        if matte.shape != (height, width):
            raise ValueError('Mask dimensions must match the displayed video raster')
        selected[matte[region] < 128] = 0
    if clean is not None:
        delta = cv2.absdiff(pixels, clean[region]).max(axis=2)
        selected[delta < change] = 0
    moments = cv2.moments(selected, binaryImage=True)
    count = moments['m00']
    area = count / (width * height)
    center = None
    if count and area >= min_area:
        center = [(left + .5 + moments['m10'] / count) / width,
                  (top + .5 + moments['m01'] / count) / height]
    return {'area_fraction': area, 'center': center}


def _extract(path, lanes, side_name, *, base, clean=None, change=24):
    fps, count = video_clock(path)
    if clean is not None and video_clock(clean) != (fps, count):
        raise ValueError('Clean footage and render must share the same CFR and frame count')
    tracks = []
    for lane in lanes:
        side = lane[side_name]
        tracks.append((_interval(side, count), side, _hsv_bounds(lane.get('hsv')), lane['min_area'], []))
    last = max(track[0].stop for track in tracks)
    masks = {}  # Cache static mattes only; sequences can be arbitrarily long.
    with ExitStack() as stack:
        frames = stack.enter_context(closing(video_frames(path, None)))
        plates = stack.enter_context(closing(video_frames(clean, None))) if clean is not None else None
        for index in range(last):
            frame = next(frames, None)
            plate = next(plates, None) if plates is not None else None
            if frame is None or (plates is not None and (plate is None or frame.shape != plate.shape)):
                raise ValueError(f'Missing or incompatible decoded frame {index}')
            for interval, side, selector, min_area, rows in tracks:
                if index not in interval:
                    continue
                matte = None
                if side.get('mask'):
                    pattern = side['mask']
                    file = base / pattern.format(frame=index)
                    matte = masks.get(file)
                    if matte is None:
                        matte = cv2.imread(str(file), cv2.IMREAD_GRAYSCALE)
                        if matte is None:
                            raise ValueError(f'Cannot read effect mask {file}')
                        if '{' not in pattern:
                            masks[file] = matte
                rows.append(_observe(frame, plate, side, selector, min_area, change, matte))
    return {'sha256': digest(path), 'fps': str(fps), 'frames': count}, [t[-1] for t in tracks]


def _comparison(ref, out):
    """Weight over the union of native frame boundaries, without dropping short events."""
    rn, cn = len(ref), len(out)
    ticks = sorted({Fraction(i, n) for n in (rn, cn) for i in range(n + 1)})
    missing = excess = both = area_error = center_error = 0.
    for start, end in zip(ticks, ticks[1:]):
        r, c = ref[int(start * rn)], out[int(start * cn)]
        dt = float(end - start)
        area_error += dt * abs(r['area_fraction'] - c['area_fraction'])
        a, b = r['center'], c['center']
        if a is not None and b is not None:
            both += dt
            center_error += dt * math.dist(a, b)
        elif a is not None:
            missing += dt
        elif b is not None:
            excess += dt
    ref_on = next((i / rn for i, row in enumerate(ref) if row['center'] is not None), None)
    out_on = next((i / cn for i, row in enumerate(out) if row['center'] is not None), None)
    return {
        'mean_absolute_area_difference': area_error,
        'missing_phase_fraction': missing, 'extra_phase_fraction': excess,
        'joint_visible_phase_fraction': both,
        'presence_iou': both / (both + missing + excess) if both + missing + excess else None,
        'mean_center_distance_normalized_xy': center_error / both if both else None,
        'onset_shift_phase': out_on - ref_on if ref_on is not None and out_on is not None else None,
    }


def compare(reference, render, spec, base, clean=None, min_change=24):
    lanes = spec.get('effects') if isinstance(spec, dict) else None
    if not isinstance(lanes, list) or not lanes:
        raise ValueError('At least one effect interval must be selected')
    if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'].strip()
           for row in lanes):
        raise ValueError('Each effect needs a non-empty id')
    if len({row['id'] for row in lanes}) != len(lanes):
        raise ValueError('Effect ids must be unique')
    for row in lanes:
        if not all(isinstance(row.get(side), dict) for side in ('reference', 'render')):
            raise ValueError('Each effect requires reference and render intervals')
        if type(row.get('min_area')) not in (int, float) or not 0 < row['min_area'] <= 1:
            raise ValueError('min_area must be a positive fraction of the full screen')
    if type(min_change) is not int or not 1 <= min_change <= 255:
        raise ValueError('min_change must be an integer between 1 and 255')
    rclock, references = _extract(reference, lanes, 'reference', base=base)
    cclock, candidates = _extract(render, lanes, 'render', base=base, clean=clean, change=min_change)
    effects = []
    for lane, ref, out in zip(lanes, references, candidates):
        entry = {'spec': lane, 'metrics': _comparison(ref, out)}
        for name, rows in [('reference', ref), ('render', out)]:
            first, end = lane[name]['frames']
            visible = [first + i for i, row in enumerate(rows) if row['center'] is not None]
            entry[name] = {
                'start_frame': first, 'end_frame_exclusive': end,
                'first_visible_frame': visible[0] if visible else None,
                'last_visible_frame': visible[-1] if visible else None,
                'detected_at_interval_start': bool(visible and visible[0] == first),
                'mean_screen_area': sum(r['area_fraction'] for r in rows) / len(rows),
                'peak_screen_area': max(r['area_fraction'] for r in rows),
                'observations': rows,
            }
        effects.append(entry)
    return {
        'schema': 'effect-pixel-audit/1', 'reference': rclock, 'render': cclock,
        'clean_render_source_sha256': digest(clean) if clean is not None else None,
        'min_changed_channel_levels': min_change if clean is not None else None,
        'alignment': 'Linear phase between declared half-open intervals. Each decoded frame holds until the next.',
        'coordinates': 'Area as fraction of full raster. Center as fraction of screen width and height.',
        'limitations': 'Matching color and location do not establish object identity, typography or depth. '
                       'An unchanged render source can be excluded only with a registered clean plate. '
                       'No aggregate fidelity score or approval is inferred.',
        'effects': effects,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('reference', type=Path)
    cli.add_argument('render', type=Path)
    cli.add_argument('spec', type=Path, help='JSON effect pairs with frames, HSV, optional normalized roi and PNG mask')
    cli.add_argument('output', type=Path)
    cli.add_argument('--clean-render-source', type=Path,
                     help='Registered original footage, with the same raster, frame indices and camera geometry as the render')
    cli.add_argument('--min-change', default=24, type=int, help='Required channel change from the clean render source')
    args = cli.parse_args()
    if (args.output.suffix.lower() != '.json' or
            args.output.resolve() in {args.spec.resolve(), args.reference.resolve(), args.render.resolve()}):
        cli.error('The report must be a separate .json file.')
    cv2.setNumThreads(2)
    result = compare(args.reference, args.render, json.loads(args.spec.read_text(encoding='utf-8')),
                     args.spec.parent, args.clean_render_source, args.min_change)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
