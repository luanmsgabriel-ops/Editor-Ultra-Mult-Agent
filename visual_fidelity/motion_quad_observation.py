"""Convert reviewed/measured quadrilaterals to explicit similarity observations.

The caller supplies a verified source clock and complete corner observations;
this adapter does not decode a video, detect an object, infer clipped corners or
recover a physical camera. Four corresponding corners are fitted equally. If a
quad cannot be represented by uniform scale, rotation and translation within the
declared RMS tolerance, its pose is missing and the original evidence is retained.

Corner order is reference-corner identity TL, TR, BR, BL, with positive winding
in the x-right/y-down raster. Do not re-sort corners by their current screen
position during rotation: correspondence is part of the caller's evidence.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from .motion_profile import OBSERVATION_SCHEMA, fit_profile


SCHEMA = 'element-motion-quads/1'
METHOD = 'four_corner_equal_weight_similarity_least_squares'


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


def _reference_box(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('reference_box_px must contain x, y, width, height')
    x, y, width, height = [_finite(v, 'reference_box_px') for v in value]
    if width <= 0 or height <= 0:
        raise ValueError('reference_box_px dimensions must be positive')
    if not all(math.isfinite(v) for v in (x + width, y + height)):
        raise ValueError('reference_box_px exceeds finite coordinate range')
    return x, y, width, height


def _quad(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('quad_px must contain four corresponding TL, TR, BR, BL corners')
    points = []
    for pair in value:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('Each quad corner must contain x and y')
        points.append([_finite(v, 'quad_px') for v in pair])
    quad = np.array(points, dtype=np.float64)
    # Scale before cross products: validation must not overflow on finite input.
    with np.errstate(over='ignore', invalid='ignore'):
        edges = np.roll(quad, -1, axis=0) - quad
    if not np.isfinite(edges).all():
        raise ValueError('Quad edges exceed finite coordinate range')
    extent = float(np.max(np.abs(edges)))
    if extent <= 0:
        raise ValueError('Quad corners must be distinct and strictly convex')
    edges = edges / extent
    following = np.roll(edges, -1, axis=0)
    cross = edges[:, 0] * following[:, 1] - edges[:, 1] * following[:, 0]
    if not np.all(cross > 1e-12):
        raise ValueError('Quad must be strictly convex in TL, TR, BR, BL correspondence order')
    return quad


def _fit(reference, observed):
    """Closed-form equal-weight fit, using centered coordinates for stability."""
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        origin = reference.mean(axis=0)
        target = observed.mean(axis=0)
        source_delta = reference - origin
        span = float(np.max(np.abs(source_delta)))
        normalized = source_delta / span
        delta = observed - target
        denominator = float(np.sum(normalized * normalized))
        a = float(np.sum(normalized[:, 0] * delta[:, 0] + normalized[:, 1] * delta[:, 1]) / denominator / span)
        b = float(np.sum(normalized[:, 1] * delta[:, 0] - normalized[:, 0] * delta[:, 1]) / denominator / span)
        linear = np.array([[a, b], [-b, a]], dtype=np.float64)
        projected = source_delta @ linear.T + target
        translation = target - linear @ origin
        residual = np.linalg.norm(observed - projected, axis=1)
        largest = float(residual.max())
        rms = largest * math.sqrt(float(np.mean((residual / largest) ** 2))) if largest else 0.
        matrix = np.column_stack((linear, translation))
    if not all(np.isfinite(v).all() for v in (target, matrix, projected, residual)) or not math.isfinite(rms):
        raise ValueError('Similarity arithmetic exceeds finite coordinate range')
    scale = math.hypot(a, b)
    return {
        'center': target, 'scale': scale, 'raw_angle': math.degrees(math.atan2(b, a)),
        'matrix': matrix, 'projected_quad': projected, 'residual': residual, 'rms': rms,
    }


def observations_from_quads(source, spec):
    """Adapt complete, corresponding quads to ``element-motion-observations/1``.

    Spec fields are ``schema``, ``elements`` and optional ``fit_tolerance_px``
    (default 2 px RMS, measured over the four Euclidean corner errors). Elements
    declare ``id``, ``reference_box_px`` and ``samples``. Samples preserve their
    original frame, PTS, segment, confidence, visibility, status and provenance.

    A missing/clipped observation must use ``status='missing', quad_px=None``.
    This function cannot determine whether corners beyond the image were truly
    measured; the caller must not substitute inferred hidden geometry as observed.
    """
    if not isinstance(spec, dict) or spec.get('schema') != SCHEMA:
        raise ValueError(f'Expected {SCHEMA}')
    if set(spec) - {'schema', 'fit_tolerance_px', 'elements'}:
        raise ValueError('Unknown quad specification fields')
    tolerance = _finite(spec.get('fit_tolerance_px', 2.), 'fit_tolerance_px')
    if tolerance <= 0:
        raise ValueError('fit_tolerance_px must be positive')
    if not isinstance(spec.get('elements'), list) or not spec['elements']:
        raise ValueError('elements must be a nonempty list')
    converted = []
    for element in spec['elements']:
        if not isinstance(element, dict) or set(element) - {'id', 'reference_box_px', 'samples', 'provenance'}:
            raise ValueError('Unknown quad element fields')
        x, y, width, height = _reference_box(element.get('reference_box_px'))
        reference = np.array([[x, y], [x + width, y], [x + width, y + height], [x, y + height]], dtype=float)
        if not isinstance(element.get('samples'), list) or not element['samples']:
            raise ValueError('Each element needs nonempty quad samples')
        samples, previous = [], None
        for sample in element['samples']:
            if not isinstance(sample, dict) or set(sample) - {
                'frame', 'pts', 'segment', 'quad_px', 'confidence', 'visibility', 'status', 'provenance', 'cut_before',
            }:
                raise ValueError('Unknown quad sample fields')
            if 'quad_px' not in sample:
                raise ValueError('Each sample must explicitly provide quad_px or null')
            if type(sample.get('frame')) is not int or sample['frame'] < 0 or type(sample.get('pts')) is not int:
                raise ValueError('Quad samples need a nonnegative integer frame and integer PTS')
            if not isinstance(sample.get('segment'), str) or not sample['segment']:
                raise ValueError('Quad samples need a nonempty segment')
            if sample.get('status') not in ('observed', 'missing'):
                raise ValueError('Quad status must be observed or missing')
            if sample.get('visibility') not in ('visible', 'unknown', 'occluded'):
                raise ValueError('Quad visibility must be visible, unknown or occluded')
            confidence = sample.get('confidence')
            if confidence is not None and not 0 <= _finite(confidence, 'confidence') <= 1:
                raise ValueError('confidence must be null or in [0, 1]')
            if 'cut_before' in sample and type(sample['cut_before']) is not bool:
                raise ValueError('cut_before must be boolean')
            # Validate correspondence even when the caller marked a supplied quad
            # unusable. Incomplete geometry is represented by null, not NaN rows.
            observed = None if sample['quad_px'] is None else _quad(sample['quad_px'])
            if sample.get('status') == 'observed' and observed is None:
                raise ValueError('Observed status requires a complete quad; mark unavailable corners missing')
            result = copy.deepcopy(sample)
            result.update(position_px=None, scale=None, angle_deg_unwrapped=None)
            diagnostics = {'method': METHOD, 'fit_tolerance_rms_px': tolerance,
                'points_used': 0, 'points_rejected': 0}
            result['diagnostics'] = diagnostics
            if sample.get('status') == 'missing' or observed is None or sample.get('visibility') == 'occluded':
                diagnostics['reason'] = 'caller_marked_missing' if sample.get('status') == 'missing' else 'occluded_quad_not_observable'
                result['status'] = 'missing'
                previous = None
            else:
                fit = _fit(reference, observed)
                diagnostics.update(points_used=4, fit_rms_px=fit['rms'], fit_max_corner_error_px=float(fit['residual'].max()),
                    corner_errors_px=fit['residual'].tolist())
                result['similarity_quad_px'] = fit['projected_quad'].tolist()
                result['similarity_matrix_reference_to_frame'] = fit['matrix'].tolist()
                if fit['scale'] <= 0 or fit['rms'] > tolerance:
                    result['status'] = 'missing'
                    diagnostics['reason'] = 'quad_not_representable_by_similarity'
                    previous = None
                else:
                    angle = fit['raw_angle']
                    contiguous = (previous is not None and type(sample.get('frame')) is int and
                                  sample['frame'] == previous['frame'] + 1 and
                                  sample.get('segment') == previous['segment'] and not sample.get('cut_before', False))
                    if contiguous:
                        angle = previous['angle'] + ((angle - previous['angle'] + 180) % 360 - 180)
                    result.update(position_px=fit['center'].tolist(), scale=fit['scale'], angle_deg_unwrapped=angle)
                    diagnostics['angle_unwrap_continued'] = contiguous
                    previous = {'frame': sample.get('frame'), 'segment': sample.get('segment'), 'angle': angle}
            samples.append(result)
        result_element = {'id': element.get('id'), 'model': 'similarity_2d',
            'reference': {'size_px': [width, height], 'anchor': 'center',
                'position_px': [x + width / 2, y + height / 2], 'quad_px': reference.tolist(),
                'geometry_source': 'declared_axis_aligned_reference_box'},
            'method': METHOD, 'samples': samples,
            'angle_unwrap_assumption': 'shortest_contiguous_step_below_180_degrees',
            'coverage': {'provided_samples': len(samples),
                'observed_samples': sum(s.get('status') == 'observed' for s in samples),
                'missing_samples': sum(s.get('status') == 'missing' for s in samples)}}
        if 'provenance' in element:
            result_element['provenance'] = copy.deepcopy(element['provenance'])
        converted.append(result_element)
    output = {'schema': OBSERVATION_SCHEMA, 'source': copy.deepcopy(source), 'elements': converted,
        'measurement': {'method': METHOD, 'input_schema': SCHEMA, 'fit_tolerance_rms_px': tolerance,
            'corner_order': 'reference_identity_TL_TR_BR_BL', 'weighting': 'equal_all_four_corners',
            'outlier_removal': 'none', 'interpolation': 'none', 'model_inference': False,
            'limitations': [
                'Source clock, identity, complete corner coverage and provenance are supplied by the caller.',
                'A declared reference box sets the scale baseline; it is not a recovered physical camera.',
                'Similarity-incompatible, missing and occluded quads remain missing.',
                'Clipped/hidden corners are never reconstructed by this adapter.',
            ]}}
    # The core owns the OBS contract. Linear fitting is only a validation pass;
    # no fitted/extrapolated values replace the measurements returned here.
    fit_profile(output, method='linear')
    return output
