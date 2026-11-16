"""Synthetic checks for the authored Blender/CV camera convention.

These fixtures supply their own geometry, pose and intrinsics. They validate
coordinate conversion and reprojection, not recovery of any reference lens.
"""

import math
import unittest

import numpy as np

from visual_fidelity.device_camera import fit_device_pose


def rotation_xyz_degrees(x, y, z):
    """Construct a proper local-to-world rotation without OpenCV helpers."""
    x, y, z = map(math.radians, (x, y, z))
    rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)],
                   [0, math.sin(x), math.cos(x)]], dtype=float)
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0],
                   [-math.sin(y), 0, math.cos(y)]], dtype=float)
    rz = np.array([[math.cos(z), -math.sin(z), 0],
                   [math.sin(z), math.cos(z), 0], [0, 0, 1]], dtype=float)
    return rz @ ry @ rx


def project_from_blender_world(local_points, rotation, location, *,
                               resolution, lens_mm, sensor_width_mm,
                               camera_distance):
    """Independent pinhole projection: camera looks down world -Z, +Y is up.

    The pixel origin is top left. Horizontal sensor fit sets focal length in
    pixels from raster width; y therefore has the opposite sign to world y.
    """
    world = np.asarray(local_points) @ rotation.T + np.asarray(location)
    positive_depth = camera_distance - world[:, 2]
    if np.any(positive_depth <= 0):
        raise ValueError("Synthetic fixture must be in front of the camera")
    focal_px = resolution[0] * lens_mm / sensor_width_mm
    return np.column_stack((
        resolution[0] / 2 + focal_px * world[:, 0] / positive_depth,
        resolution[1] / 2 - focal_px * world[:, 1] / positive_depth,
    ))


class DeviceCameraPoseTests(unittest.TestCase):
    def check_known_pose(self, *, local_corners, angles, location, config):
        expected_rotation = rotation_xyz_degrees(*angles)
        intrinsics = {key: config[key] for key in (
            "resolution", "lens_mm", "sensor_width_mm", "camera_distance")}
        measured = project_from_blender_world(
            local_corners, expected_rotation, location, **intrinsics)

        result = fit_device_pose(measured, max_error_px=1e-4, **config)
        fitted_rotation = np.asarray(result["device"]["rotation_matrix"])
        fitted_location = np.asarray(result["device"]["location"])

        # A reflected or incorrectly flipped basis can preserve some planar
        # appearances, so verify orientation as well as the pixel residual.
        self.assertAlmostEqual(float(np.linalg.det(fitted_rotation)), 1.0,
                               delta=1e-9)
        np.testing.assert_allclose(fitted_rotation.T @ fitted_rotation,
                                   np.eye(3), atol=1e-9)
        np.testing.assert_allclose(fitted_rotation, expected_rotation,
                                   rtol=0, atol=1e-6)
        np.testing.assert_allclose(fitted_location, location,
                                   rtol=0, atol=1e-6)

        # Reproject through the independently authored Blender convention,
        # rather than trusting the solver's own reported projected points.
        reprojection = project_from_blender_world(
            local_corners, fitted_rotation, fitted_location, **intrinsics)
        np.testing.assert_allclose(reprojection, measured, rtol=0, atol=1e-4)
        evidence = result["evidence"]
        np.testing.assert_allclose(evidence["projected_corners_px"],
                                   measured, rtol=0, atol=1e-4)
        self.assertLess(evidence["rms_error_px"], 1e-4)
        self.assertFalse(evidence["original_camera_recovered"])
        self.assertFalse(evidence["physical_scale_recovered"])
        self.assertEqual(result["camera"]["location"],
                         [0, 0, config["camera_distance"]])
        self.assertEqual(result["camera"]["target"], [0, 0, 0])

    def test_front_pose_reprojects_in_blender_coordinates(self):
        width, height, depth = 0.78, 1.634, 0.0875
        # TL, TR, BR, BL when looking at the device's +Z face.
        corners = np.array([
            [-width/2, height/2, depth/2],
            [width/2, height/2, depth/2],
            [width/2, -height/2, depth/2],
            [-width/2, -height/2, depth/2],
        ])
        config = dict(width=width, height=height, depth=depth, side="front",
                      resolution=(720, 1280), lens_mm=50.0,
                      sensor_width_mm=36.0, camera_distance=3.6)
        for angles, location in (
            ((0, 0, 0), (0.0, 0.0, 0.0)),
            ((12, -21, -6), (0.08, -0.04, 0.12)),
        ):
            with self.subTest(angles=angles):
                self.check_known_pose(local_corners=corners, angles=angles,
                                      location=location, config=config)

    def test_back_pose_reverses_local_x_without_a_reflection(self):
        width, height, depth = 0.87, 1.76, 0.094
        # Looking at -Z reverses the local X order of the measured corners.
        corners = np.array([
            [width/2, height/2, -depth/2],
            [-width/2, height/2, -depth/2],
            [-width/2, -height/2, -depth/2],
            [width/2, -height/2, -depth/2],
        ])
        config = dict(width=width, height=height, depth=depth, side="back",
                      resolution=(960, 540), lens_mm=42.0,
                      sensor_width_mm=32.0, camera_distance=4.2)
        for angles, location in (
            ((0, 180, 0), (0.0, 0.0, 0.0)),
            ((8, 164, 7), (-0.06, 0.09, -0.15)),
        ):
            with self.subTest(angles=angles):
                self.check_known_pose(local_corners=corners, angles=angles,
                                      location=location, config=config)

    def test_degenerate_or_nonconvex_quads_are_rejected(self):
        invalid_quads = {
            "coincident": [[100, 100]] * 4,
            "collinear": [[0, 0], [100, 100], [200, 200], [300, 300]],
            "crossed": [[100, 100], [200, 200], [200, 100], [100, 200]],
            "concave": [[100, 100], [200, 100], [130, 130], [100, 200]],
            "subpixel_scale": [[100, 100], [104, 100],
                               [104, 104], [100, 104]],
        }
        for name, corners in invalid_quads.items():
            with self.subTest(quad=name):
                with self.assertRaises(ValueError):
                    fit_device_pose(corners)

    def test_nonpositive_or_nonfinite_intrinsics_are_rejected(self):
        corners = [[240, 350], [480, 350], [480, 930], [240, 930]]
        invalid = (
            {"lens_mm": 0}, {"lens_mm": -50},
            {"lens_mm": float("nan")}, {"lens_mm": float("inf")},
            {"sensor_width_mm": 0}, {"sensor_width_mm": -36},
            {"sensor_width_mm": float("nan")},
            {"sensor_width_mm": float("inf")},
            {"resolution": (0, 1280)}, {"resolution": (720, -1)},
            {"resolution": (float("nan"), 1280)},
            {"resolution": (720, float("inf"))},
            {"camera_distance": 0}, {"camera_distance": -3.6},
            {"camera_distance": float("nan")},
            {"camera_distance": float("inf")},
        )
        for kwargs in invalid:
            with self.subTest(intrinsics=kwargs):
                with self.assertRaises(ValueError):
                    fit_device_pose(corners, **kwargs)


if __name__ == "__main__":
    unittest.main()
