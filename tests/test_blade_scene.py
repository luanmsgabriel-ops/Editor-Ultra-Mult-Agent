import unittest

from visual_fidelity.blade_scene import swept_blade_mesh, validate_config


class BladeGeometryTests(unittest.TestCase):
    def test_curved_blade_is_closed_volume_with_dense_rounded_caps(self):
        vertices, faces = swept_blade_mesh(length=3, width=.08, depth=.05, bow=.1)
        edges = {}
        for face in faces:
            for a, b in zip(face, face[1:]+face[:1]):
                key = tuple(sorted((a, b)))
                edges[key] = edges.get(key, 0)+1
        self.assertEqual(set(edges.values()), {2})
        self.assertGreater(max(v[2] for v in vertices)-min(v[2] for v in vertices), .04)
        center = [v for v in vertices if abs(v[1]) < .02]
        self.assertGreater(min(v[0] for v in center), .05)
        top_cap = [v for v in vertices if v[1] > 1.48]
        self.assertGreater(len({round(v[1], 8) for v in top_cap}), 4)

    def test_invalid_geometry_and_missing_blade_ids_fail(self):
        with self.assertRaises(ValueError):
            swept_blade_mesh(depth=0)
        with self.assertRaises(ValueError):
            validate_config({"blades": [{"id": "a"}], "frames": [{"frame": 0, "blades": {"missing": {}}}]})


if __name__ == "__main__":
    unittest.main()
