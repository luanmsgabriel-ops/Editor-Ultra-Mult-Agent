"""Track a planar insertion quad with optical flow or imported TAPIR tracks."""
from collections.abc import Mapping
from pathlib import Path

import cv2
import numpy as np


_FLOW = dict(
    winSize=(23, 23),
    maxLevel=3,
    criteria=(cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 35, 0.01),
)


def _gray(frame):
    if frame.dtype != np.uint8:
        raise ValueError('O rastreador espera quadros uint8.')
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _quad_valid(quad):
    if not np.isfinite(quad).all():
        return False
    edges = np.roll(quad, -1, axis=0) - quad
    corners = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
    return bool(np.all(corners > 0) and cv2.contourArea(quad.astype('float32')) > 12)


def _looks_like_cut(last, current):
    last = cv2.resize(last, (48, 36), interpolation=cv2.INTER_AREA)
    current = cv2.resize(current, (48, 36), interpolation=cv2.INTER_AREA)
    changed = cv2.absdiff(last, current).mean()
    if changed < 46:
        return False
    histograms = [cv2.calcHist([image], [0], None, [24], [0, 256]) for image in (last, current)]
    return changed > 89 or cv2.compareHist(*histograms, cv2.HISTCMP_BHATTACHARYYA) > .38


def _homography(reference_points, points, quad, scale, minimum):
    if len(reference_points) < minimum:
        return None
    tolerance = max(1.5, float(scale.max()) * .002)
    matrix, accepted = cv2.findHomography(reference_points, points, cv2.RANSAC, tolerance)
    if matrix is None or accepted is None or not np.isfinite(matrix).all():
        return None
    inliers = accepted.ravel().astype(bool)
    if np.count_nonzero(inliers) < minimum or inliers.mean() < .58:
        return None
    hull = cv2.convexHull(reference_points[inliers].astype('float32'))
    area = cv2.contourArea(quad)
    if cv2.contourArea(hull) < area * .085:
        return None
    projected = cv2.perspectiveTransform(quad[None], matrix)[0]
    if not _quad_valid(projected):
        return None
    relative_area = cv2.contourArea(projected) / area
    if not .08 <= relative_area <= 9:
        return None
    normalized = projected / scale
    if np.any(normalized < -1) or np.any(normalized > 2):
        return None
    return normalized


def _step_plausible(previous, proposed, frame_gap):
    return np.linalg.norm(proposed - previous, axis=1).max() <= min(.7, .21 * frame_gap)


def _lk(frames, quad, start, scale, output):
    first = _gray(frames[start])
    mask = np.zeros(first.shape, dtype='uint8')
    cv2.fillConvexPoly(mask, np.rint(quad).astype('int32'), 255)
    features = cv2.goodFeaturesToTrack(
        first, maxCorners=160, qualityLevel=.012, minDistance=max(3, float(scale.max()) / 220),
        mask=mask,
    )
    minimum = 7
    if features is None or len(features) < minimum:
        return
    previous_points = original = features
    previous = first
    for index in range(start + 1, len(frames)):
        current = _gray(frames[index])
        if _looks_like_cut(previous, current):
            break
        following, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, previous_points, None, **_FLOW)
        if following is None or status is None:
            break
        forward = status.ravel().astype(bool) & np.isfinite(following[:, 0]).all(axis=1)
        if np.count_nonzero(forward) < minimum:
            break
        previous_points, following, original = previous_points[forward], following[forward], original[forward]
        backwards, status, _ = cv2.calcOpticalFlowPyrLK(current, previous, following, None, **_FLOW)
        if backwards is None or status is None:
            break
        error = np.linalg.norm((backwards - previous_points).reshape(-1, 2), axis=1)
        points = following[:, 0]
        inside = np.all((points >= 0) & (points < scale), axis=1)
        usable = status.ravel().astype(bool) & np.isfinite(error) & (error < 1.4) & inside
        original, following = original[usable], following[usable]
        proposed = _homography(original[:, 0], following[:, 0], quad, scale, minimum)
        if proposed is None or not _step_plausible(output[index - 1], proposed, 1):
            break
        output[index] = proposed
        previous, previous_points = current, following


def _npz_data(tracks):
    if isinstance(tracks, Mapping):
        return tracks
    with np.load(Path(tracks), allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def _string_value(data, key, default):
    value = np.asarray(data.get(key, default))
    if value.ndim != 0:
        raise ValueError(f'Metadado {key!r} deve ser uma string escalar.')
    item = value.item()
    if isinstance(item, bytes):
        return item.decode('utf-8')
    return str(item)


def _visibility(data, point_shape):
    def values(name):
        result = np.asarray(data[name])
        if result.ndim == 3 and result.shape[0] == 1:
            result = result[0]
        if result.shape != point_shape:
            raise ValueError(f'{name} deve ter o mesmo layout de pontos e quadros que tracks.')
        return result

    if 'visibility' in data:
        return values('visibility') > .5
    if 'occlusion' not in data:
        raise ValueError('Inclua visibility ou os logits TAPIR occlusion no NPZ.')
    occlusion = values('occlusion')
    visible = 1 / (1 + np.exp(np.clip(occlusion, -40, 40)))
    if 'expected_dist' in data:
        distance = values('expected_dist')
        visible *= 1 / (1 + np.exp(np.clip(distance, -40, 40)))
    return visible > .5


def load_tapir_tracks(tracks, frame_size, frame_count):
    """Normalize TAPIR-style tracks to [points, frames, xy] and boolean visibility.

    The default layout is PT, identical to TAPIR model outputs. TP is supported
    with explicit metadata. XY coordinates default to pixels at frame_size.
    Use coordinates='normalized' or image_size=(width,height) to scale
    predictions made on resized model input.
    """
    data = _npz_data(tracks)
    if 'tracks' not in data:
        raise ValueError('O NPZ precisa da matriz tracks.')
    points = np.asarray(data['tracks'], dtype='float32')
    if points.ndim == 4 and points.shape[0] == 1:
        points = points[0]
    if points.ndim != 3 or points.shape[2] != 2:
        raise ValueError('tracks precisa medir P×T×2 ou T×P×2, com lote unitário opcional.')
    visible = _visibility(data, points.shape[:2])
    layout = _string_value(data, 'layout', 'PT').upper()
    if layout == 'TP':
        points, visible = points.swapaxes(0, 1), visible.T
    elif layout != 'PT':
        raise ValueError('layout deve ser PT ou TP.')
    if points.shape[1] != frame_count:
        raise ValueError(f'NPZ tem {points.shape[1]} quadros e o vídeo tem {frame_count}.')
    coords = _string_value(data, 'coordinates', 'pixels')
    if coords == 'normalized':
        normalized = points
    elif coords == 'pixels':
        source_size = np.asarray(data.get('image_size', frame_size), dtype='float32')
        if source_size.shape != (2,) or not np.isfinite(source_size).all() or np.any(source_size <= 0):
            raise ValueError('image_size deve conter (largura, altura) positivas.')
        normalized = points / source_size
    else:
        raise ValueError('coordinates deve ser pixels ou normalized.')
    return normalized, visible & np.isfinite(normalized).all(axis=2)


def _offline(frames, quad, start, scale, output, tracks):
    points, visible = load_tapir_tracks(tracks, scale, len(frames))
    pixels = points * scale
    initial = pixels[:, start]
    planar = np.zeros(len(initial), dtype=bool)
    for index in np.flatnonzero(visible[:, start]):
        planar[index] = cv2.pointPolygonTest(quad, tuple(map(float, initial[index])), False) >= 0
    previous_frame = _gray(frames[start])
    previous_index = start
    for index in range(start + 1, len(frames)):
        current_frame = _gray(frames[index])
        if _looks_like_cut(previous_frame, current_frame):
            break
        previous_frame = current_frame
        use = planar & visible[:, index]
        proposed = _homography(initial[use], pixels[use, index], quad, scale, 4)
        if proposed is not None and _step_plausible(output[previous_index], proposed, index - previous_index):
            output[index] = proposed
            previous_index = index


def track_planar(frames, quad, start=0, tracks=None):
    """Return one normalized quad or None per frame.

    Set the initial quad at start (TL, TR, BR, BL in screen order). The
    confidence gate uses RANSAC, geometry and cadence. With optical flow a lost
    anchor must be seeded again. Imported tracks can resume after a gap when
    points become visible within the same shot.
    """
    if not 0 <= start < len(frames):
        raise ValueError('O quadro inicial precisa existir no vídeo.')
    height, width = frames[start].shape[:2]
    if any(frame.shape[:2] != (height, width) for frame in frames):
        raise ValueError('Todos os quadros do plano precisam da mesma resolução.')
    quad = np.asarray(quad, dtype='float32')
    if quad.shape != (4, 2) or not np.isfinite(quad).all() or np.any((quad < 0) | (quad > 1)):
        raise ValueError('Informe quatro pontos normalizados dentro do quadro.')
    scale = np.array([width, height], dtype='float32')
    pixels = quad * scale
    if not _quad_valid(pixels):
        raise ValueError('A âncora precisa ser um quadrilátero convexo em ordem TL, TR, BR, BL.')
    output = [None] * len(frames)
    output[start] = quad
    if tracks is None:
        _lk(frames, pixels, start, scale, output)
    else:
        _offline(frames, pixels, start, scale, output, tracks)
    return output
