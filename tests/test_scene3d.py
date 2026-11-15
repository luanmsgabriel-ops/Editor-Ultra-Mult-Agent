import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from visual_fidelity.scene3d import prepare, validate_geometry, destination_folder


def geometry():
    yy, xx = np.mgrid[:3, :4]
    points = np.stack([(xx-1.5)/10, (yy-1)/10, np.ones_like(xx)], axis=-1)[None]
    return {'points': points, 'images': np.zeros((1,3,4,3), np.uint8),
            'intrinsics': np.array([[[10,0,1.5],[0,10,1],[0,0,1]]]),
            'extrinsics': np.eye(4)[None,:3], 'valid': np.ones((1,3,4),bool)}


class SceneGeometryTests(unittest.TestCase):
    def test_camera_rotation_is_validated(self):
        data=geometry()
        data['extrinsics'][0,0,0]=2
        with self.assertRaisesRegex(ValueError,'rígidas'):
            validate_geometry(data)

    def test_invalid_and_behind_camera_points_are_removed(self):
        data=geometry()
        data['points'][0,0,0]=np.nan
        data['points'][0,0,1,2]=-1
        result=validate_geometry(data)
        self.assertEqual(int(result['valid'].sum()),10)
        self.assertTrue(np.isnan(result['points'][0,0,1]).all())

    def test_prepared_image_does_not_change_raster(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            pixels=np.full((17,29,3),(25,80,123),dtype=np.uint8)
            Image.fromarray(pixels).save(root/'source.png')
            manifest=prepare(root/'source.png',root/'views')
            data=json.loads(manifest.read_text())
            self.assertEqual(data['frames'][0]['width'],29)
            np.testing.assert_array_equal(np.asarray(Image.open(root/'views/view-000.png')),pixels)

    def test_failed_stage_does_not_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'run'
            with self.assertRaisesRegex(RuntimeError,'model failed'):
                with destination_folder(output) as stage:
                    (stage/'partial').write_text('data')
                    raise RuntimeError('model failed')
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).iterdir()),[])


if __name__=='__main__':
    unittest.main()
