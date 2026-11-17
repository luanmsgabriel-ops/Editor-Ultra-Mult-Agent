"""Measure per-element 2D similarity motion without inventing lost observations.

``measure_video(video, spec)`` tracks features selected by an explicit seed ROI
and optional binary mask, forwards and backwards from that seed. LK matches are
checked in both directions and a RANSAC similarity is fitted against the original
seed coordinates. RGB activity is only a diagnostic, never a velocity estimate.

Intervals are [start, end); cuts name the first frame of the new shot. A cut or
lost track requires a new, explicit seed (normally a new element/measurement).
No interpolation, frame repetition, re-identification or model download occurs.
"""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import subprocess

import cv2
import numpy as np

from .anchor_tracking import _looks_like_cut


SCHEMA = 'element-motion-observations/1'
SPEC_SCHEMA = 'element-motion-measurement/1'
METHOD = 'opencv_lk_forward_backward_ransac_similarity'
_DEFAULTS = {
    'max_corners': 240,
    'min_points': 6,
    'quality_level': .01,
    'min_distance_px': 4.,
    'window_size': 31,
    'pyramid_levels': 4,
    'fb_max_px': 1.5,
    'ransac_max_px': 2.,
    'min_inlier_ratio': .6,
    'min_spatial_coverage': .12,
    'max_step_scale_ratio': 2.5,
    'max_step_angle_deg': 120.,
}


def _sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _int(value, name, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(f'{name} must be an integer' + (f' >= {minimum}' if minimum is not None else ''))
    return value


def _number(value, name, minimum=None, maximum=None, strict_minimum=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if minimum is not None and (value <= minimum if strict_minimum else value < minimum):
        raise ValueError(f'{name} is below the supported range')
    if maximum is not None and value > maximum:
        raise ValueError(f'{name} is above the supported range')
    return float(value)


def _settings(values):
    if not isinstance(values, dict) or set(values) - set(_DEFAULTS):
        raise ValueError('Unknown tracker settings')
    result = {**_DEFAULTS, **values}
    for key, minimum in [('min_points', 3), ('max_corners', 3), ('window_size', 5), ('pyramid_levels', 0)]:
        _int(result[key], key, minimum)
    if result['max_corners'] < result['min_points'] or result['window_size'] % 2 != 1:
        raise ValueError('max_corners must cover min_points and window_size must be odd')
    for key in ('quality_level', 'min_inlier_ratio', 'min_spatial_coverage'):
        _number(result[key], key, 0, 1, strict_minimum=True)
    for key in ('min_distance_px', 'fb_max_px', 'ransac_max_px'):
        _number(result[key], key, 0, strict_minimum=True)
    _number(result['max_step_scale_ratio'], 'max_step_scale_ratio', 1)
    _number(result['max_step_angle_deg'], 'max_step_angle_deg', 0, 180, strict_minimum=True)
    return result


def probe_clock(video_path):
    """Read presentation timestamps; VFR is preserved, not normalized silently."""
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-show_frames',
        '-show_entries',
        'stream=width,height,time_base,avg_frame_rate,sample_aspect_ratio:'
        'stream_tags=rotate:stream_side_data=rotation:frame=pts,best_effort_timestamp',
        '-of', 'json', str(video_path),
    ], check=True, capture_output=True, text=True)
    probe = json.loads(result.stdout)
    if len(probe.get('streams', [])) != 1:
        raise ValueError('Video must have a readable first video stream')
    stream = probe['streams'][0]
    try:
        time_base = Fraction(stream['time_base'])
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Video has no usable time_base') from exc
    if time_base <= 0:
        raise ValueError('Video time_base must be positive')
    stamps, kinds = [], set()
    for frame in probe.get('frames', []):
        key = 'pts' if frame.get('pts') is not None else 'best_effort_timestamp'
        value = frame.get(key)
        if type(value) is not int:
            raise ValueError('Every decoded frame needs an integer presentation timestamp')
        stamps.append(value)
        kinds.add(key)
    if not stamps or any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise ValueError('Presentation timestamps must strictly increase; normalize or inspect the source explicitly')
    rate = None
    try:
        candidate = Fraction(stream.get('avg_frame_rate', '0/1'))
        if candidate > 0:
            rate = str(candidate)
    except (ValueError, ZeroDivisionError):
        pass
    sar = stream.get('sample_aspect_ratio', '1:1')
    if sar not in ('N/A', '0:1', '1:1', None):
        raise ValueError('Non-square pixels require an explicitly normalized raster before tracking')
    rotations = [float(side['rotation']) for side in stream.get('side_data_list', []) if 'rotation' in side]
    if not rotations and 'rotate' in stream.get('tags', {}):
        rotations = [float(stream['tags']['rotate'])]
    rotation = rotations[0] if rotations else 0.
    if not math.isfinite(rotation):
        raise ValueError('Invalid container rotation')
    intervals = [b - a for a, b in zip(stamps, stamps[1:])]
    # A CFR file may alternate timestamp tick counts (e.g. 33/34 ms at 30 fps).
    # Classify it using its nominal rational rate and the clock's quantization.
    uniform = len(set(intervals)) <= 1
    if rate is not None:
        nominal = Fraction(rate)
        uniform = all(abs((pts - stamps[0]) * time_base - i / nominal) <= time_base
                      for i, pts in enumerate(stamps))
    return {
        'width': int(stream['width']), 'height': int(stream['height']),
        'time_base': str(time_base), 'first_pts': stamps[0], 'frame_pts': stamps,
        'frames': len(stamps), 'fps': rate, 'sample_aspect_ratio': sar or '1:1',
        'clock_kind': 'cfr' if uniform else 'vfr',
        'timestamp_source': next(iter(kinds)) if len(kinds) == 1 else 'mixed_pts_and_best_effort',
        'container_rotation': rotation,
    }


def _box(value, name, size=None):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f'{name} must contain x, y, width, height')
    x, y, w, h = [_number(v, name) for v in value]
    if w <= 0 or h <= 0 or not all(math.isfinite(v) for v in (x + w, y + h)):
        raise ValueError(f'{name} must have positive width and height')
    if size is not None and (x < 0 or y < 0 or x + w > size[0] or y + h > size[1]):
        raise ValueError(f'{name} must lie inside the oriented source raster')
    return x, y, w, h


def _validate_spec(spec, frame_count, size):
    if not isinstance(spec, dict) or spec.get('schema') != SPEC_SCHEMA:
        raise ValueError(f'Expected {SPEC_SCHEMA}')
    if set(spec) - {'schema', 'rotation_ccw', 'cuts', 'elements', 'tracker'}:
        raise ValueError('Unknown measurement fields')
    settings = _settings(spec.get('tracker', {}))
    cuts = spec.get('cuts', [])
    if not isinstance(cuts, list) or any(type(cut) is not int or not 0 < cut < frame_count for cut in cuts):
        raise ValueError('Cuts must name integer first-frame indices inside the video')
    if cuts != sorted(set(cuts)):
        raise ValueError('Cuts must be sorted and unique')
    elements = spec.get('elements')
    if not isinstance(elements, list) or not elements:
        raise ValueError('At least one explicitly selected element is required')
    ids = set()
    for element in elements:
        if not isinstance(element, dict) or set(element) - {
            'id', 'range', 'seed_frame', 'roi_px', 'reference_box_px', 'segment', 'mask_path',
        }:
            raise ValueError('Unknown element fields')
        identity = element.get('id')
        if not isinstance(identity, str) or not identity.strip() or identity in ids:
            raise ValueError('Element IDs must be nonempty and unique')
        ids.add(identity)
        bounds = element.get('range')
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise ValueError('Element range must be [start, end)')
        start, end = [_int(v, 'range', 0) for v in bounds]
        seed = _int(element.get('seed_frame'), 'seed_frame', 0)
        if not 0 <= start <= seed < end <= frame_count:
            raise ValueError('Seed and range must lie inside the decoded video')
        _box(element.get('roi_px'), 'roi_px', size)
        _box(element.get('reference_box_px', element['roi_px']), 'reference_box_px')
        if 'segment' in element and (not isinstance(element['segment'], str) or not element['segment'].strip()):
            raise ValueError('segment must be a nonempty string')
        if 'mask_path' in element and not isinstance(element['mask_path'], (str, Path)):
            raise ValueError('mask_path must be a local file path')
    return settings, cuts


def _decode_selected(path, selected, clock, rotation):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError('Cannot decode video')
    if hasattr(cv2, 'CAP_PROP_ORIENTATION_AUTO'):
        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
        if cap.get(cv2.CAP_PROP_ORIENTATION_AUTO):
            cap.release()
            raise ValueError('Decoder did not disable implicit orientation')
    rotations = {90: cv2.ROTATE_90_COUNTERCLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_CLOCKWISE}
    frames, index = {}, 0
    try:
        while True:
            ok, image = cap.read()
            if not ok:
                break
            if image.shape[:2] != (clock['height'], clock['width']):
                raise ValueError('Decoder raster differs from probed raster; implicit resize/orientation is unsupported')
            if index in selected:
                if rotation in rotations:
                    image = cv2.rotate(image, rotations[rotation])
                frames[index] = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            index += 1
    finally:
        cap.release()
    if index != clock['frames'] or set(frames) != selected:
        raise ValueError('Decoded frame count differs from the presentation clock')
    return frames


def _missing(index, pts, segment, reason, diagnostics=None):
    return {
        'frame': index, 'pts': pts, 'segment': segment,
        'position_px': None, 'scale': None, 'angle_deg_unwrapped': None,
        'confidence': None, 'visibility': 'unknown', 'status': 'missing',
        'diagnostics': {'reason': reason, **(diagnostics or {})},
    }


def _hull_area(points):
    return cv2.contourArea(cv2.convexHull(np.asarray(points, dtype=np.float32))) if len(points) >= 3 else 0.


def _reanchor(seed_image, current, original, matrix, settings, flow, size):
    """Refine against seed texture after compensating the provisional transform.

    Adjacent-frame LK alone accumulates patch-shape bias during rotations/zoom.
    Bringing the new image back into the seed raster lets LK observe only the
    small remaining displacement, without assuming an unchanged patch shape.
    This is still an image measurement, not interpolation from the prior pose.
    """
    aligned = cv2.warpAffine(current, matrix, size,
        flags=cv2.WARP_INVERSE_MAP | cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    corrected, status, _ = cv2.calcOpticalFlowPyrLK(seed_image, aligned, original, None, **flow)
    if corrected is None or status is None:
        return None
    forward = status.ravel().astype(bool) & np.isfinite(corrected[:, 0]).all(axis=1)
    original, corrected = original[forward], corrected[forward]
    if len(corrected) < settings['min_points']:
        return None
    backward, status, _ = cv2.calcOpticalFlowPyrLK(aligned, seed_image, corrected, None, **flow)
    if backward is None or status is None:
        return None
    errors = np.linalg.norm((backward - original)[:, 0], axis=1)
    current_points = (corrected[:, 0] @ matrix[:, :2].T + matrix[:, 2]).astype(np.float32)
    valid = status.ravel().astype(bool) & np.isfinite(errors) & (errors <= settings['fb_max_px'])
    valid &= np.all((current_points >= 0) & (current_points < np.asarray(size)), axis=1)
    original, current_points = original[valid], current_points[valid, None]
    if len(current_points) < settings['min_points']:
        return None
    refined, accepted = cv2.estimateAffinePartial2D(original[:, 0], current_points[:, 0],
        method=cv2.RANSAC, ransacReprojThreshold=settings['ransac_max_px'],
        maxIters=2000, confidence=.99, refineIters=15)
    if refined is None or accepted is None or not np.isfinite(refined).all():
        return None
    inliers = accepted.ravel().astype(bool)
    if inliers.sum() < settings['min_points'] or inliers.mean() < settings['min_inlier_ratio']:
        return None
    projected = original[:, 0] @ refined[:, :2].T + refined[:, 2]
    residual = np.linalg.norm(projected - current_points[:, 0], axis=1)
    return refined, original[inliers], current_points[inliers], {
        'seed_reanchored': True, 'seed_reanchor_inliers': int(inliers.sum()),
        'seed_reanchor_inlier_ratio': float(inliers.mean()),
        'seed_reanchor_reprojection_median_px': float(np.median(residual[inliers])),
        'seed_reanchor_reprojection_p90_px': float(np.percentile(residual[inliers], 90)),
    }


def _observe(index, pts, segment, matrix, center, quad, previous_angle, diagnostics):
    position = matrix[:, :2] @ center + matrix[:, 2]
    raw_angle = math.degrees(math.atan2(float(matrix[0, 1]), float(matrix[0, 0])))
    angle = previous_angle + ((raw_angle - previous_angle + 180) % 360 - 180)
    return {
        'frame': index, 'pts': pts, 'segment': segment,
        'position_px': position.tolist(), 'scale': float(np.hypot(matrix[0, 0], matrix[0, 1])),
        'angle_deg_unwrapped': float(angle), 'confidence': None,
        'visibility': 'visible', 'status': 'observed',
        'quad_px': (quad @ matrix[:, :2].T + matrix[:, 2]).tolist(),
        'similarity_matrix_seed_to_frame': matrix.tolist(),
        'diagnostics': diagnostics,
    }


def _track_element(frames, stamps, element, cuts, settings, size):
    start, end = element['range']
    seed = element['seed_frame']
    segment_base = element.get('segment', element['id'])
    shot = lambda frame: sum(c <= frame for c in cuts)
    segment = lambda frame: f'{segment_base}:shot-{shot(frame)}'
    x, y, w, h = _box(element['roi_px'], 'roi_px', size)
    gx, gy, gw, gh = _box(element.get('reference_box_px', element['roi_px']), 'reference_box_px')
    quad = np.array([[gx, gy], [gx + gw, gy], [gx + gw, gy + gh], [gx, gy + gh]], dtype=np.float64)
    center = np.array([gx + gw / 2, gy + gh / 2], dtype=np.float64)
    mask = np.zeros((size[1], size[0]), np.uint8)
    mask[math.ceil(y):math.ceil(y + h), math.ceil(x):math.ceil(x + w)] = 255
    mask_receipt = None
    if element.get('mask_path'):
        path = Path(element['mask_path'])
        supplied = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if supplied is None or supplied.shape != mask.shape:
            raise ValueError('Seed mask must decode at the oriented source raster')
        mask[supplied == 0] = 0
        mask_receipt = {'path': str(path), 'sha256': _sha256(path), 'positive_pixels': int(np.count_nonzero(mask))}
    features = cv2.goodFeaturesToTrack(frames[seed], maxCorners=settings['max_corners'],
        qualityLevel=settings['quality_level'], minDistance=settings['min_distance_px'], mask=mask)
    points = np.empty((0, 1, 2), np.float32) if features is None else features
    samples = {
        i: _missing(i, stamps[i], segment(i), 'not_reached_from_seed') for i in range(start, end)
    }
    samples[seed] = _observe(seed, stamps[seed], segment(seed), np.array([[1., 0., 0.], [0., 1., 0.]]),
        center, quad, 0., {'method': 'declared_seed_geometry', 'features': len(points),
        'seed_geometry_is_authored': True})
    flow = dict(winSize=(settings['window_size'],) * 2, maxLevel=settings['pyramid_levels'],
        criteria=(cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 50, .005))
    initial_hull = _hull_area(points[:, 0])
    for direction in (-1, 1):
        previous_index = seed
        previous_points = points.copy()
        original = points.copy()
        previous_angle, previous_scale = 0., 1.
        failure = None
        indices = range(seed - 1, start - 1, -1) if direction < 0 else range(seed + 1, end)
        for index in indices:
            if shot(index) != shot(seed):
                samples[index] = _missing(index, stamps[index], segment(index), 'declared_cut_requires_new_seed')
                continue
            if failure is not None:
                samples[index] = _missing(index, stamps[index], segment(index), 'track_lost_requires_new_seed',
                    {'initial_failure_frame': failure})
                continue
            if len(previous_points) < settings['min_points'] or initial_hull < 1.:
                failure = index
                samples[index] = _missing(index, stamps[index], segment(index), 'insufficient_seed_features')
                continue
            previous, current = frames[previous_index], frames[index]
            diagnostics = {'method': METHOD, 'direction_from_seed': direction,
                'input_points': len(previous_points),
                'luminance_activity': float(cv2.absdiff(previous, current).mean()),
                'cut_candidate_only': bool(_looks_like_cut(previous, current))}
            following, forward_status, _ = cv2.calcOpticalFlowPyrLK(previous, current, previous_points, None, **flow)
            reason = 'lk_forward_failed'
            if following is not None and forward_status is not None:
                forward_ok = forward_status.ravel().astype(bool) & np.isfinite(following[:, 0]).all(axis=1)
                original = original[forward_ok]
                previous_points = previous_points[forward_ok]
                following = following[forward_ok]
                reason = 'too_few_forward_matches'
                if len(following) >= settings['min_points']:
                    backward, backward_status, _ = cv2.calcOpticalFlowPyrLK(current, previous, following, None, **flow)
                    reason = 'lk_backward_failed'
                    if backward is not None and backward_status is not None:
                        errors = np.linalg.norm((backward - previous_points)[:, 0], axis=1)
                        in_bounds = np.all((following[:, 0] >= 0) & (following[:, 0] < np.asarray(size)), axis=1)
                        good = backward_status.ravel().astype(bool) & np.isfinite(errors) & (errors <= settings['fb_max_px']) & in_bounds
                        diagnostics['forward_backward_survivors'] = int(good.sum())
                        diagnostics['forward_backward_error_median_px'] = float(np.median(errors[good])) if good.any() else None
                        diagnostics['forward_backward_error_p90_px'] = float(np.percentile(errors[good], 90)) if good.any() else None
                        original, following = original[good], following[good]
                        reason = 'too_few_consistent_matches'
                        if len(following) >= settings['min_points']:
                            matrix, accepted = cv2.estimateAffinePartial2D(original[:, 0], following[:, 0],
                                method=cv2.RANSAC, ransacReprojThreshold=settings['ransac_max_px'],
                                maxIters=2000, confidence=.99, refineIters=15)
                            reason = 'similarity_fit_failed'
                            if matrix is not None and accepted is not None and np.isfinite(matrix).all():
                                inliers = accepted.ravel().astype(bool)
                                fraction = float(inliers.mean())
                                coverage = _hull_area(original[inliers, 0]) / initial_hull
                                diagnostics.update(inlier_count=int(inliers.sum()), inlier_ratio=fraction,
                                    seed_feature_hull_coverage=coverage)
                                if inliers.any():
                                    projected = original[:, 0] @ matrix[:, :2].T + matrix[:, 2]
                                    residual = np.linalg.norm(projected - following[:, 0], axis=1)
                                    diagnostics['reprojection_error_median_px'] = float(np.median(residual[inliers]))
                                    diagnostics['reprojection_error_p90_px'] = float(np.percentile(residual[inliers], 90))
                                reason = 'insufficient_ransac_support'
                                if inliers.sum() >= settings['min_points'] and fraction >= settings['min_inlier_ratio'] and coverage >= settings['min_spatial_coverage']:
                                    refined = _reanchor(frames[seed], current, original[inliers], matrix,
                                        settings, flow, size)
                                    if refined is None:
                                        samples[index] = _missing(index, stamps[index], segment(index),
                                            'seed_reanchor_failed', diagnostics)
                                        failure = index
                                        continue
                                    matrix, original, following, refinement = refined
                                    diagnostics.update(refinement)
                                    diagnostics['seed_feature_hull_coverage'] = _hull_area(original[:, 0]) / initial_hull
                                    if diagnostics['seed_feature_hull_coverage'] < settings['min_spatial_coverage']:
                                        samples[index] = _missing(index, stamps[index], segment(index),
                                            'insufficient_reanchored_spatial_support', diagnostics)
                                        failure = index
                                        continue
                                    sample = _observe(index, stamps[index], segment(index), matrix, center, quad,
                                        previous_angle, diagnostics)
                                    relative_scale = sample['scale'] / previous_scale
                                    angle_step = abs(sample['angle_deg_unwrapped'] - previous_angle)
                                    reason = 'implausible_similarity_step'
                                    if 1 / settings['max_step_scale_ratio'] <= relative_scale <= settings['max_step_scale_ratio'] and angle_step <= settings['max_step_angle_deg']:
                                        samples[index] = sample
                                        previous_points = following
                                        previous_index, previous_angle, previous_scale = index, sample['angle_deg_unwrapped'], sample['scale']
                                        continue
            samples[index] = _missing(index, stamps[index], segment(index), reason, diagnostics)
            failure = index
    ordered = [samples[i] for i in range(start, end)]
    observed = sum(s['status'] == 'observed' for s in ordered)
    return {
        'id': element['id'], 'model': 'similarity_2d',
        'reference': {'size_px': [gw, gh], 'anchor': 'center', 'position_px': center.tolist(),
            'quad_px': quad.tolist(), 'frame': seed, 'pts': stamps[seed], 'scale': 1.,
            'angle_deg': 0., 'geometry_source': 'declared_seed_box'},
        'selection': {'range': [start, end], 'roi_px': list(element['roi_px']), 'mask': mask_receipt},
        'method': METHOD, 'angle_unwrap_assumption': 'shortest_step_from_seed_below_180_degrees',
        'confidence_semantics': 'not_available; diagnostics are uncalibrated tracking measurements',
        'samples': ordered,
        'coverage': {'requested_frames': end - start, 'observed_frames': observed,
            'missing_frames': end - start - observed,
            'observed_fraction': observed / (end - start),
            'seed_geometry_authored_frames': 1},
    }


def measure_video(video_path, spec):
    """Return observations for explicitly selected elements in a real video.

    ``roi_px`` selects seed features in oriented source pixels. Optional
    ``reference_box_px`` describes the complete object when the feature ROI is
    only an interior patch. Its geometry is declared, not recovered from hidden
    content. A binary ``mask_path`` is intersected with the ROI. Masks use the
    full oriented raster. No operation resizes the image or stretches its aspect.

    A nonzero container display rotation requires ``rotation_ccw`` explicitly;
    this avoids silently changing the coordinate system of a supplied mask/ROI.
    """
    video_path = Path(video_path)
    clock = probe_clock(video_path)
    if not isinstance(spec, dict):
        raise ValueError('Measurement specification must be an object')
    if 'rotation_ccw' not in spec and abs(clock['container_rotation'] % 360) > 1e-6:
        raise ValueError('Set rotation_ccw explicitly for a source with container rotation')
    rotation = spec.get('rotation_ccw', 0)
    if type(rotation) is not int or rotation not in (0, 90, 180, 270):
        raise ValueError('rotation_ccw must be 0, 90, 180 or 270')
    size = (clock['width'], clock['height'])
    if rotation in (90, 270):
        size = size[::-1]
    settings, cuts = _validate_spec(spec, clock['frames'], size)
    selected = {frame for element in spec['elements'] for frame in range(*element['range'])}
    frames = _decode_selected(video_path, selected, clock, rotation)
    elements = [_track_element(frames, clock['frame_pts'], element, cuts, settings, size)
                for element in spec['elements']]
    source = {key: value for key, value in clock.items() if key not in ('frame_pts', 'width', 'height')}
    if source.get('fps') is None:
        source.pop('fps', None)
    source.update(sha256=_sha256(video_path), width=size[0], height=size[1],
        encoded_size=[clock['width'], clock['height']], rotation_ccw_applied=rotation,
        coordinate_convention='opencv_pixel_centers', position_units='pixels',
        angle_units='degrees_ccw', frame_index_origin=0)
    return {'schema': SCHEMA, 'source': source, 'elements': elements,
        'measurement': {'method': METHOD, 'tracker_settings': settings,
            'declared_cuts': cuts, 'interpolation': 'none', 'model_inference': False,
            'decoded_all_frames_for_clock_alignment': True,
            'limitations': [
                'Seed geometry and element identity are supplied, not inferred semantically.',
                'Similarity tracks cannot represent perspective, nonrigid motion or physical camera depth.',
                'Tracking stops after loss or declared cuts; missing samples require a new seed.',
                'RANSAC support and LK errors are not calibrated confidence probabilities.',
            ]}}
