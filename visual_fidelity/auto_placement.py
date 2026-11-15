"""Choose a stable onscreen rectangle from the frames of a single shot."""

import os
from pathlib import Path

import cv2
import numpy as np

_WHITE = (248, 250, 252)
_DARK = (14, 18, 22)


def _detector(configured, model, width, height):
    yunet = getattr(cv2, 'FaceDetectorYN_create', None)
    if yunet is not None and model and Path(model).is_file():
        try:
            return 'yunet', yunet(model, '', (width, height), .72, .3, 200)
        except cv2.error:
            pass
    haar = getattr(cv2, 'CascadeClassifier', None)
    if haar is None:
        return None
    standard = getattr(getattr(cv2, 'data', None), 'haarcascades', '')
    search = [
        Path(configured) if configured else None,
        Path(standard) / 'haarcascade_frontalface_default.xml' if standard else None,
        Path('/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml'),
        Path('/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml'),
    ]
    for source in search:
        if source is None or not source.is_file():
            continue
        try:
            detector = haar(str(source))
            if not detector.empty():
                return 'haar', detector
        except cv2.error:
            continue
    return None


def _normalized_box(values):
    box = np.asarray(values, dtype=float)
    if (
        box.shape != (4,) or not np.isfinite(box).all()
        or (box < 0).any() or (box > 1).any()
        or box[0] >= box[2] or box[1] >= box[3]
    ):
        raise ValueError('Protected boxes must be normalized [left, top, right, bottom].')
    return box


def _box_mask(mask, box):
    height, width = mask.shape
    x0, y0, x1, y1 = box * [width, height, width, height]
    mask[int(np.floor(y0)):int(np.ceil(y1)), int(np.floor(x0)):int(np.ceil(x1))] = True


def _manual_mask(protected, count, width, height):
    mask = np.zeros((height, width), dtype=bool)
    if protected is None:
        return mask

    def is_box(value):
        if isinstance(value, np.ndarray):
            return value.shape == (4,) and all(np.isscalar(point) for point in value)
        return isinstance(value, (tuple, list)) and len(value) == 4 and all(
            np.isscalar(point) for point in value
        )

    def is_mask(value):
        return isinstance(value, np.ndarray) and value.ndim == 2

    if isinstance(protected, np.ndarray):
        if protected.ndim == 3:
            protected = list(protected)
        elif (protected.ndim == 2 and protected.shape[1] == 4
              and np.issubdtype(protected.dtype, np.floating)
              and np.all(protected[:, :2] < protected[:, 2:])):
            protected = list(protected)
    if is_mask(protected):
        protected = [protected] * count
    elif is_box(protected):
        _box_mask(mask, _normalized_box(protected))
        return mask
    if all(is_box(entry) for entry in protected):
        for box in protected:
            _box_mask(mask, _normalized_box(box))
        return mask
    if len(protected) != count:
        raise ValueError('Provide one protected mask or box list per frame, or shared boxes.')
    for entry in protected:
        if entry is None:
            continue
        if is_mask(entry):
            resized = cv2.resize((entry > 0).astype('float32'), (width, height), interpolation=cv2.INTER_AREA)
            mask |= resized > 0
        else:
            for box in [entry] if is_box(entry) else entry:
                _box_mask(mask, _normalized_box(box))
    return mask


def _linear(value):
    return np.where(value <= .04045, value / 12.92, ((value + .055) / 1.055) ** 2.4)


def _luminance(rgb):
    return np.einsum('...j,j->...', _linear(rgb.astype('float32') / 255), [0.2126, 0.7152, 0.0722])


def _samples(frames, width, height, occlusion, subject):
    detector = _detector(os.environ.get('VISUAL_FIDELITY_FACE_CASCADE'),
                         os.environ.get('VISUAL_FIDELITY_FACE_MODEL'), width, height)
    selected = np.unique(np.linspace(0, len(frames) - 1, min(12, len(frames)), dtype=int))
    luminance, edges = [], []
    motion = np.zeros((height, width), dtype='float32')
    previous = None
    face_count = 0
    for number in selected:
        bgr = cv2.resize(frames[number][:, :, :3], (width, height), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        luminance.append(_luminance(bgr[:, :, ::-1]))
        edges.append(cv2.Canny(gray, 42, 115) > 0)
        if previous is not None:
            motion += cv2.absdiff(previous, gray).astype('float32') / 255
        previous = gray
        if detector is None:
            continue
        backend, model = detector
        try:
            if backend == 'yunet':
                _, detected = model.detect(bgr)
                faces = () if detected is None else detected[:, :4]
            else:
                equalized = cv2.equalizeHist(gray)
                minimum = max(17, min(width, height) // 15)
                faces = model.detectMultiScale(equalized, scaleFactor=1.1, minNeighbors=5,
                                               minSize=(minimum, minimum))
        except cv2.error:
            detector = None
            continue
        for x, y, w, h in faces:
            box = np.array([x - .30*w, y - .30*h, x + 1.30*w, y + 1.55*h])
            box = np.clip(box / [width, height, width, height], 0, 1)
            _box_mask(occlusion, box)
            # A soft torso estimate keeps a clear frame around the presenter.
            body = np.array([x-1.7*w, y+.6*h, x+2.7*w, y+7.4*h])
            _box_mask(subject, np.clip(body/[width,height,width,height],0,1))
        face_count += len(faces)
    return (np.asarray(luminance, dtype='float32'), np.asarray(edges),
            motion / max(1, len(selected) - 1), detector[0] if detector else None, face_count)


def choose_anchor(frames, size, *, protected=None, previous=None):
    """Return one stable normalized center and a readable RGB color for the shot.

    Frames are uint8 BGR arrays. Size is a normalized tuple (width, height).
    Protected may be one shared mask, shared normalized boxes, or one list of
    boxes or binary mask per input frame. Previous is a normalized (x, y) center.
    Confidence is a layout heuristic. A flagged result calls for review.
    """
    frames = list(frames)
    if not frames or any(
        not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] < 3
        or not min(frame.shape[:2]) or frame.dtype != np.uint8 for frame in frames
    ):
        raise ValueError('Provide at least one nonempty uint8 BGR frame.')
    size = np.asarray(size, dtype=float)
    if size.shape != (2,) or not np.isfinite(size).all() or (size <= 0).any() or (size > 1).any():
        raise ValueError('Size must be a normalized (width, height).')
    prior = None if previous is None else np.asarray(previous, dtype=float)
    if prior is not None and (
        prior.shape != (2,) or not np.isfinite(prior).all() or (prior < 0).any() or (prior > 1).any()
    ):
        raise ValueError('Previous center must be normalized (x, y).')

    source_h, source_w = frames[0].shape[:2]
    scale = min(1., 320 / max(source_h, source_w))
    width, height = [max(24, round(dimension * scale)) for dimension in (source_w, source_h)]
    occlusion = _manual_mask(protected, len(frames), width, height)
    subject=np.zeros_like(occlusion)
    light, edges, motion, face_backend, faces_detected = _samples(frames, width, height, occlusion, subject)
    ink_light, ink_dark = _luminance(np.array([_WHITE, _DARK]))
    margin = np.minimum([.06, .08], (1 - size) / 2)
    low, high = size / 2 + margin, 1 - size / 2 - margin
    xs, ys = [list(np.linspace(a, max(b, a), 9)) for a, b in zip(low, high)]
    if prior is not None:
        x, y = np.clip(prior, low, np.maximum(high, low))
        xs.append(float(x))
        ys.append(float(y))
    candidates = []
    for y in ys:
        for x in xs:
            x0, y0, x1, y1 = np.concatenate((np.array([x, y]) - size / 2,
                                            np.array([x, y]) + size / 2))
            # Rounding protects any pixel even if only its edge crosses the requested area.
            left, right = max(0, int(np.floor(x0*width))), min(width, int(np.ceil(x1*width)))
            top, bottom = max(0, int(np.floor(y0*height))), min(height, int(np.ceil(y1*height)))
            region = np.s_[top:max(top+1, bottom), left:max(left+1, right)]
            patch = light[:, region[0], region[1]]
            blocked = float(occlusion[region].mean())
            body_overlap=float(subject[region].mean())
            dark, bright = np.quantile(patch, [.20, .80], axis=(1, 2))
            white_contrast = float(np.min((ink_light + .05) / (bright + .05)))
            dark_contrast = float(np.min((dark + .05) / (ink_dark + .05)))
            contrast = max(white_contrast, dark_contrast)
            color = _WHITE if white_contrast >= dark_contrast else _DARK
            edge = float(np.max(edges[:, region[0], region[1]].mean(axis=(1, 2))))
            local_motion = float(motion[region].mean())
            spread = float(np.max(bright-dark))
            bias = .12 * abs(y-.74) + .055 * abs(x-.5)
            continuity = 0. if prior is None else .24*float(np.linalg.norm(np.array([x, y])-prior))
            energy = 1.5*edge + 1.1*local_motion + .23*spread + .45/max(contrast, 1) + bias + continuity + .84*body_overlap
            bounds = np.clip([x0, y0, x1, y1], 0, 1).tolist()
            candidates.append((blocked, energy, [float(x), float(y)], bounds, color, contrast,
                               edge, local_motion, body_overlap))
    blocked, _, center, bounds, color, contrast, edge, local_motion, body_overlap = min(
        candidates, key=lambda row: (row[0] > 0, row[0], row[1])
    )
    confidence = np.clip(
        (1 - blocked) * min(1, contrast / 4.5) * (1 - min(.7, edge + local_motion)), 0, 1
    )
    return {
        'center': center,
        'bounds': bounds,
        'color': list(color),
        'confidence': round(float(confidence), 3),
        'contrast': round(contrast, 3),
        'protected_overlap': round(blocked, 5),
        'subject_overlap_estimate': round(body_overlap, 5),
        'review_required': bool(blocked > 0 or contrast < 3 or confidence < .55),
        'face_detector': face_backend is not None,
        'face_backend': face_backend,
        'faces_detected': faces_detected,
    }
