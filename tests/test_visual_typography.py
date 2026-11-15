from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

try:
    import cv2
    import numpy as np
    from PIL import Image, features

    from visual_fidelity.typography import compare, font_ink, read_ink, trace_svg
except ModuleNotFoundError as error:
    raise unittest.SkipTest(f"Optional visual dependencies are unavailable: {error}") from error


class TypographyTest(unittest.TestCase):
    def test_extracts_colored_ink_with_hole_and_drops_isolated_noise(self):
        image = np.full((60, 80, 3), (190, 100, 90), dtype="uint8")
        ink = (30, 40, 70)
        cv2.ellipse(image, (39, 32), (23, 19), 0, 0, 360, ink, 6)
        image[5, 6] = ink
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.png"
            Image.fromarray(image).save(path)
            mask = read_ink(path, ink_rgb=ink, color_tolerance=0, min_area=5)
        self.assertEqual(mask.shape, (45, 53))
        self.assertEqual(mask[22, 26], 0)
        node = ElementTree.fromstring(trace_svg(mask))
        self.assertEqual(node.attrib["viewBox"], "0 0 53 45")
        self.assertEqual(node[0].attrib["fill-rule"], "evenodd")
        self.assertEqual(node[0].attrib["d"].count("M"), 2)

    def test_ranks_exact_candidate_without_stretching_other_fonts(self):
        root = Path("/usr/share/fonts/truetype/dejavu")
        regular, mono = root / "DejaVuSans.ttf", root / "DejaVuSansMono.ttf"
        if not (features.check_feature("raqm") and regular.exists() and mono.exists()):
            self.skipTest("This integration case requires portable DejaVu test fonts and RAQM.")
        reference, _ = font_ink(regular, "Vai lá!")
        report, masks = compare(reference, "Vai lá!", [mono, regular])
        self.assertEqual(report["candidates"][0]["path"], str(regular))
        self.assertEqual(report["candidates"][0]["outline_iou"], 1)
        self.assertNotEqual(report["candidates"][1]["relative_width_error"], 0)
        self.assertEqual(len(masks), 3)


if __name__ == "__main__":
    unittest.main()
