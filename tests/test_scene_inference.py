import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image
from visual_fidelity.scene_inference import infer, normalized_to_pixel_intrinsics, pad_content_mask


class InferenceCoordinates(unittest.TestCase):
    def test_moge_normalized_pixel_centers(self):
        normalized = np.array([[.8,0,.5],[0,1.1,.5],[0,0,1]],np.float32)
        matrix = normalized_to_pixel_intrinsics(normalized, 80, 60)
        x,y = 17,32
        uv=np.array([(x+.5)/80,(y+.5)/60,1])
        point=np.linalg.inv(normalized)@uv*2
        projected=matrix@point
        np.testing.assert_allclose(projected[:2]/projected[2],[x,y],atol=1e-5)

    def test_vggt_padding_matches_landscape_and_portrait(self):
        with TemporaryDirectory() as tmp:
            paths=[Path(tmp)/'landscape.png',Path(tmp)/'portrait.png']
            Image.new('RGB',(640,360)).save(paths[0])
            Image.new('RGB',(360,640)).save(paths[1])
            mask,boxes=pad_content_mask(paths)
        self.assertEqual(mask.shape,(2,518,518))
        self.assertEqual(boxes,[[0,112,518,406],[112,0,406,518]])
        self.assertEqual(mask[0].sum(),518*294)
        self.assertFalse(mask[0,0,0])
        self.assertTrue(mask[0,112,0])

    def test_moge_rejects_multiple_world_frames_before_import(self):
        with self.assertRaisesRegex(ValueError,'uma imagem'):
            infer('moge',[Path('a.png'),Path('b.png')])


if __name__=='__main__':
    unittest.main()
