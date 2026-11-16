import math
import unittest

from visual_fidelity.device_scene import (DEFAULT_GEOMETRY, frame_state,
    rounded_prism, screen_geometry, screen_uv, validate_config)


class DeviceSceneGeometryTests(unittest.TestCase):
    def test_chassis_is_closed_and_has_expected_positive_volume(self):
        # A nonzero signed volume and two incident faces per edge distinguish
        # actual chassis geometry from a flat display masquerading as a phone.
        w, h, depth, radius = 0.78, 1.634, 0.0875, 0.078
        vertices, faces = rounded_prism(w, h, depth, radius, 32)
        incidence = {}
        volume = 0.0
        for face in faces:
            for a, b in zip(face, face[1:]+face[:1]):
                edge = tuple(sorted((a, b)))
                incidence[edge] = incidence.get(edge, 0)+1
            a = vertices[face[0]]
            for i in range(1, len(face)-1):
                b, c = vertices[face[i]], vertices[face[i+1]]
                cross = (b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0])
                volume += sum(x*y for x, y in zip(a, cross))/6
        self.assertEqual(set(incidence.values()), {2})
        self.assertAlmostEqual(volume, (w*h-(4-math.pi)*radius**2)*depth, delta=2e-6)
        self.assertAlmostEqual(max(v[2] for v in vertices)-min(v[2] for v in vertices), depth)

    def test_screen_has_consistent_local_corner_orientation_and_front_clearance(self):
        screen = screen_geometry()
        w, h = screen["width"], screen["height"]
        self.assertEqual(screen_uv(-w/2, h/2, w, h), (0, 1))
        self.assertEqual(screen_uv(w/2, -h/2, w, h), (1, 0))
        self.assertGreater(screen["z"], DEFAULT_GEOMETRY["depth"]/2)

    def test_camera_changes_do_not_mutate_device_pose_or_previous_frame(self):
        config = validate_config({"devices": [{"id": "phone", "rotation_deg": [10, 20, 30]}],
            "frames": [{"frame": 0, "devices": {"phone": {"location": [1, 0, 0]}}},
                       {"frame": 1, "camera": {"location": [2, 1, 4]}}]})
        first, second = [frame_state(config, row) for row in config["frames"]]
        self.assertEqual(first["devices"][0]["location"], [1, 0, 0])
        self.assertNotIn("location", second["devices"][0])
        self.assertEqual(second["devices"][0]["rotation_deg"], [10, 20, 30])
        self.assertEqual(first["camera"]["location"], [0, 0, 3.6])

    def test_invalid_camera_reflections_and_ambiguous_frame_schedules_fail(self):
        for config in (
            {"camera": {"rotation_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, -1]]}},
            {"camera": {"rotation_quaternion_wxyz": [0, 0, 0, 0]}},
            {"frames": [{"frame": 1}, {"frame": 1}]},
            {"frames": [{"frame": 1, "devices": {"missing": {}}}]},
            {"devices": [{"id": "phone", "geometry": {"depth": 0}}]},
        ):
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_frame_can_explicitly_change_rotation_representation(self):
        config = validate_config({"devices": [{"id": "phone", "rotation_quaternion_wxyz": [1, 0, 0, 0]}],
                                  "frames": [{"frame": 0, "devices": {"phone": {"rotation_deg": [0, 90, 0]}}}]})
        state = frame_state(config, config["frames"][0])
        self.assertNotIn("rotation_quaternion_wxyz", state["devices"][0])
        self.assertEqual(state["devices"][0]["rotation_deg"], [0, 90, 0])


if __name__ == "__main__":
    unittest.main()
