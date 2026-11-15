from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from PIL import Image

from visual_fidelity.origins import scenes
from visual_fidelity.origins.render import load_wordmark
from visual_fidelity.providers import colmap, trellis


class FidelityTest(unittest.TestCase):
    def test_apply_asset_clips_and_respects_transparency(self):
        target = scenes.flat(80)
        plate = np.array([[[255, 255, 255, 0], [255, 0, 0, 255]],
                          [[22, 22, 22, 255], [22, 22, 22, 255]]], dtype='uint8')
        scenes.apply_asset(target, plate, 358, 639)
        np.testing.assert_array_equal(target[639, 358], [80, 80, 80])
        np.testing.assert_array_equal(target[639, 359], [255, 0, 0])

    def test_wordmark_retains_alpha_when_recolored(self):
        with TemporaryDirectory() as working:
            file = Path(working) / 'mark.png'
            canvas = Image.new('RGBA', (30, 20))
            canvas.paste((0, 0, 0, 255), (2, 4, 8, 12))
            canvas.paste((0, 0, 0, 255), (13, 4, 21, 12))
            canvas.save(file)
            art = load_wordmark(file, '#123456')
            np.testing.assert_array_equal(art[30, 40], [18, 52, 86, 255])
            np.testing.assert_array_equal(art[..., 3], load_wordmark(file, None)[..., 3])

    def test_external_providers_reject_missing_inputs_before_creating_outputs(self):
        with TemporaryDirectory() as working:
            folder = Path(working)
            with self.assertRaisesRegex(ValueError, 'três fotos'):
                colmap(folder, folder / 'work', 'colmap')
            self.assertFalse((folder / 'work').exists())
            with self.assertRaisesRegex(ValueError, 'Imagem não encontrada'):
                trellis(folder / 'missing.png', folder / 'asset.glb', 'python')
            self.assertFalse((folder / 'asset.glb').exists())


if __name__=='__main__':
    unittest.main()
