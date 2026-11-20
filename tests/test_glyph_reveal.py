import io
from pathlib import Path
import unittest

import numpy as np
from fontTools.ttLib import TTFont
from PIL import ImageFont

from visual_fidelity.glyph_reveal import BoundTitle, measure_title
from visual_fidelity.traced_spacing import fit_traced_advances


def specimen():
    matte = np.zeros((40, 80), np.float32)
    matte[13:34, 4:18] = .9
    matte[13:34, 23:38] = 1
    matte[4:9, 25:34] = .98
    return matte


class GlyphRevealTest(unittest.TestCase):
    def test_detached_accent_respaced_as_one_glyph(self):
        for minimum in (30, 60):
            sample = measure_title(specimen(), glyph_count=2, min_area=minimum)
            np.testing.assert_array_equal(sample.letters[:, 3], [21, 30])
            self.assertEqual(sample.group[3], 30)

    def test_merged_source_records_group_only(self):
        coverage = specimen()
        coverage[20:24, 17:24] = .8
        sample = measure_title(coverage, glyph_count=2, min_area=30)
        self.assertIsNone(sample.letters)
        self.assertIsNone(measure_title(coverage*0, glyph_count=2, min_area=30))

    def test_accented_text_renders_on_one_baseline(self):
        font = ImageFont.truetype("DejaVuSans.ttf", 52)
        rest = measure_title(specimen(), glyph_count=2, min_area=30)
        out = []
        for word in ("ÂVÃ", "A\u0302VA\u0303"):
            title = BoundTitle(word, font, rest)
            out.append(title.mask((210, 90), (103, 44), 160, rest, rest, .5))
        np.testing.assert_array_equal(*out)
        ys, xs = np.where(out[0] > 127)
        self.assertGreater(np.ptp(xs), 145)
        self.assertGreater(np.ptp(ys), 49)
        self.assertGreater(ys.min(), 1)
        self.assertLess(ys.max(), 89)

    def test_advance_width_and_accent_follow_narrowed_trace(self):
        path = Path(ImageFont.truetype("DejaVuSans.ttf", 28).path)
        with TTFont(path) as donor, TTFont(path) as derived:
            key = derived.getBestCmap()[ord("A")]
            glyph = derived["glyf"][key]
            for i, (x, y) in enumerate(glyph.coordinates):
                glyph.coordinates[i] = (glyph.xMin + round((x-glyph.xMin)*.8), y)
            accented = derived.getBestCmap()[ord("Â")]
            fit_traced_advances(derived, donor, "A")
            dx = derived["glyf"][key].xMax - donor["glyf"][key].xMax
            for name in (key, accented):
                self.assertEqual(derived["hmtx"][name][0], donor["hmtx"][name][0] + dx)
            orig_mark = donor["glyf"][accented].components[-1]
            self.assertEqual(derived["glyf"][accented].components[-1].x, orig_mark.x + round(dx/2))
            self.assertEqual(derived["hmtx"]["V"], donor["hmtx"]["V"])
            # A rerun must not accumulate earlier shifts.
            fit_traced_advances(derived, donor, "A")
            self.assertEqual(derived["glyf"][accented].components[-1].x, orig_mark.x + round(dx/2))
            buffer = io.BytesIO()
            derived.save(buffer)
            buffer.seek(0)
            self.assertGreater(ImageFont.truetype(buffer, 36).getlength("PARAGUAI"), 0)
