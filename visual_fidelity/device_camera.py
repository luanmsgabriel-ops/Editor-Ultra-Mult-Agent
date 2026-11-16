"""Fit an authored product-camera projection to four measured body corners.

This is planar pose calibration under supplied intrinsics, not recovery of an
original lens, a physical scale, hidden geometry, or a unique original camera.
The output follows device_scene's +X right, +Y top, +Z front convention.
"""
from __future__ import annotations

import math
import cv2
import numpy as np


def fit_device_pose(corners, *, width=0.78, height=1.634, depth=0.0875,
                    side="front", resolution=(720, 1280), lens_mm=50.0,
                    sensor_width_mm=36.0, camera_distance=3.6,
                    max_error_px=30.0):
    """Return a Blender device pose for TL, TR, BR, BL body corners in pixels.

    Corners refer to the extrapolated rectangular body (before rounding), not
    inset screen corners. Rear views reverse the local X order. Fixed camera
    intrinsics deliberately leave the pose estimate auditable and repeatable.
    """
    xy = np.asarray(corners, dtype=np.float64)
    if xy.shape != (4, 2) or not np.isfinite(xy).all():
        raise ValueError("Four finite pixel corners are required")
    if side not in {"front", "back"}:
        raise ValueError("side must be front or back")
    values = [width, height, depth, lens_mm, sensor_width_mm, camera_distance, *resolution]
    if not all(math.isfinite(float(x)) and x > 0 for x in values):
        raise ValueError("Dimensions and intrinsics must be positive and finite")
    if not cv2.isContourConvex(xy.astype(np.float32)) or abs(cv2.contourArea(xy.astype(np.float32))) < 25:
        raise ValueError("Measured corners must form a nondegenerate convex quad")
    s = 1 if side == "front" else -1
    xyz = np.array([[-s*width/2, height/2, s*depth/2],
                    [s*width/2, height/2, s*depth/2],
                    [s*width/2, -height/2, s*depth/2],
                    [-s*width/2, -height/2, s*depth/2]], dtype=np.float64)
    fx = resolution[0]*lens_mm/sensor_width_mm
    k = np.array([[fx, 0, resolution[0]/2], [0, fx, resolution[1]/2], [0, 0, 1]], np.float64)
    ok, rv, tv = cv2.solvePnP(xyz, xy, k, None, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise ValueError("Pose fit failed")
    r_cv = cv2.Rodrigues(rv)[0]
    camera_points = xyz @ r_cv.T + tv.reshape(3)
    if np.any(camera_points[:, 2] <= 0):
        raise ValueError("Pose lies behind the camera")
    projected = cv2.projectPoints(xyz, rv, tv, k, None)[0].reshape(4, 2)
    errors = np.linalg.norm(projected-xy, axis=1)
    if float(errors.max()) > max_error_px:
        raise ValueError(f"Projection residual {errors.max():.2f}px exceeds {max_error_px}px")
    flip = np.diag([1., -1., -1.])
    return {
        "device": {"location": (np.array([0.,0.,camera_distance])+flip@tv.reshape(3)).tolist(),
                   "rotation_matrix": (flip@r_cv).tolist()},
        "camera": {"location": [0,0,camera_distance], "target": [0,0,0],
                   "lens_mm": lens_mm, "sensor_width_mm": sensor_width_mm},
        "evidence": {"kind": "manually_measured_planar_pose_under_fixed_intrinsics",
                     "side": side, "measured_corners_px": xy.tolist(),
                     "projected_corners_px": projected.tolist(),
                     "corner_errors_px": errors.tolist(),
                     "rms_error_px": float(np.sqrt(np.mean(errors**2))),
                     "original_camera_recovered": False,
                     "physical_scale_recovered": False},
    }
