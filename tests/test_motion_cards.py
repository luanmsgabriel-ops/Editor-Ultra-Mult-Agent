"""Regression checks for the editable cascade and its matte/DCC hand-off."""

import json
import tempfile
import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

if cv2 is not None:
    from pilots.motion_cards import __main__ as motion
    from pilots.motion_cards import providers, sam2_mask


@unittest.skipIf(cv2 is None, "Dependências do piloto de motion ausentes")
class MotionCardsTests(unittest.TestCase):
    def setUp(self):
        self.rig = motion.read_template(motion.HERE / "motion.json")

    def test_cascade_preserves_entry_depth_and_overshoot(self):
        cards = {layer["id"]: layer for layer in self.rig["layers"]}
        self.assertEqual([layer["id"] for layer in self.rig["layers"]], ["card_c", "card_b", "card_a"])
        self.assertEqual([cards[id]["keys"][0][0] for id in ("card_a", "card_b", "card_c")], [93, 100, 104])
        self.assertIsNone(motion.pose(cards["card_c"], 103))
        self.assertAlmostEqual(motion.pose(cards["card_c"], 111)[2], 1.2221)
        self.assertGreater(motion.pose(cards["card_c"], 107)[3], 0)
        self.assertLess(motion.pose(cards["card_c"], 108)[3], 0)

    def test_media_swap_preserves_actual_alpha_support(self):
        backdrop = np.zeros((1280, 720, 3), dtype=np.uint8)
        for frame in (93, 106, 128, 146):
            renders = []
            for value in (81, 191):
                images = {}
                for layer in self.rig["layers"]:
                    width, height = layer["size"]
                    pixels = np.full((height, width, 3), value, dtype=np.uint8)
                    images[layer["id"]] = motion.paint_card(pixels, layer, from_reference=False)
                renders.append(motion.draw(self.rig, images, frame, backdrop))
            np.testing.assert_equal(np.any(renders[0] > 0, axis=2), np.any(renders[1] > 0, axis=2))

    def test_card_contract_exports_seekable_hyperframes_scene(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            assets = {
                layer["id"]: np.ones((layer["size"][1], layer["size"][0], 4), dtype=np.float32)
                for layer in self.rig["layers"]
            }
            motion.export_hyperframes(directory, self.rig, assets)
            html = (directory / "index.html").read_text()
            self.assertIn("hf-seek", html)
            self.assertIn('"frameCount": 55', html)
            self.assertEqual(len(list(directory.glob("*.png"))), 3)

    def test_sam2_logits_become_usable_rgba(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "000001.png"
            rgb = np.full((16, 16, 3), 140, dtype=np.uint8)
            mask = np.full((1, 16, 16), -4, dtype=np.float32)
            mask[:, 4:12, 4:12] = 4
            sam2_mask.write_foreground(rgb, mask, path)
            rgba = providers.foreground_frame(path.parent, 1, (16, 16))
            self.assertEqual(rgba[0, 0, 3], 0)
            self.assertEqual(rgba[8, 8, 3], 255)
            np.testing.assert_equal(rgba[:, :, :3], rgb)

    def test_rejects_duplicate_frames(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "motion.json"
            keys = self.rig["layers"][0]["keys"]
            keys.insert(1, keys[0])
            path.write_text(json.dumps(self.rig))
            with self.assertRaisesRegex(ValueError, "Chaves inválidas"):
                motion.read_template(path)


if __name__ == "__main__":
    unittest.main()
