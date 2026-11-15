"""Exercise camera calibration and reconstruction geometry inside Blender.

From the repository root run:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/blender_scene_smoke.py

The checks use temporary synthetic data and perform no image rendering.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from visual_fidelity import blender_scene


def fixture(fx=231., fy=203.):
    width, height = 320, 240
    intrinsic = np.array([[fx, 0., 141.2], [0., fy, 113.7], [0., 0., 1.]])
    y, x = np.mgrid[:height, :width]
    depth = np.full((height, width), 2.)
    camera_points = np.stack(((x-intrinsic[0, 2])*depth/fx,
                              (y-intrinsic[1, 2])*depth/fy, depth), axis=-1)
    angle = .22
    rotation = np.array([[np.cos(angle), 0., np.sin(angle)],
                         [0., 1., 0.], [-np.sin(angle), 0., np.cos(angle)]])
    translation = np.array([.12, -.07, .19])
    points = (camera_points-translation) @ rotation
    return {
        'points': points[None].astype(np.float32),
        'images': np.full((1, height, width, 3), 127, np.uint8),
        'intrinsics': intrinsic[None],
        'extrinsics': np.c_[rotation, translation][None],
        'valid': np.ones((1, height, width), bool),
    }


class BlenderSceneRegression(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.scene.render.resolution_x = 320
        self.scene.render.resolution_y = 240
        self.scene.render.resolution_percentage = 100

    def configure_camera(self, data):
        return blender_scene.calibrated_camera(
            self.scene, data['intrinsics'][0], data['extrinsics'][0],
            320, 240, np.array([2.]))

    def test_off_center_intrinsics_and_rotated_camera(self):
        for fx, fy in ((231., 203.), (190., 260.)):
            with self.subTest(fx=fx, fy=fy):
                data = fixture(fx, fy)
                camera = self.configure_camera(data)
                for u, v in ((0, 0), (319, 239), (45, 55), (200, 60), (115, 80)):
                    world = data['points'][0, v, u] * [1, -1, -1]
                    projected = world_to_camera_view(self.scene, camera, Vector(world.tolist()))
                    observed = np.array([projected.x*320-.5, (1-projected.y)*240-.5])
                    self.assertLess(float(np.linalg.norm(observed-[u, v])), .001)
                    self.assertGreater(projected.z, 0)

    def test_invalid_samples_and_depth_boundaries(self):
        data = fixture()
        data['valid'][0, 30:65, 20:70] = False
        data['points'][0, 0, 0] = np.nan
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'geometry.npz'
            np.savez_compressed(path, **data)
            data = blender_scene.read_geometry(path, 0)
        self.assertFalse(data['valid'][0, 0, 0])
        vertices, faces, uv, _ = blender_scene.triangulate(
            data['points'][0], data['valid'][0], data['extrinsics'][0], 4, .08)
        self.assertTrue(np.isfinite(vertices).all())
        pixels = np.c_[uv[:, 0]*320-.5, (1-uv[:, 1])*240-.5]
        in_mask = ((pixels[:, 0] >= 20) & (pixels[:, 0] < 70)
                   & (pixels[:, 1] >= 30) & (pixels[:, 1] < 65))
        self.assertFalse(in_mask.any())
        self.assertGreater(len(faces), 0)

        data = fixture()
        extrinsic = data['extrinsics'][0]
        camera = data['points'][0] @ extrinsic[:, :3].T + extrinsic[:, 3]
        camera[:, 160:] *= 2
        points = (camera-extrinsic[:, 3]) @ extrinsic[:, :3]
        _, faces, uv, stats = blender_scene.triangulate(
            points, data['valid'][0], extrinsic, 4, .08)
        sides = uv[:, 0] >= (160.5/320)
        mixed = sides[faces].any(axis=1) & ~sides[faces].all(axis=1)
        self.assertFalse(mixed.any(), 'Uma face atravessou o salto de profundidade.')
        self.assertGreater(stats['discarded_edge_faces'], 0)

    def test_camera_timeline_and_input_rejections(self):
        data = {key: np.concatenate([value, value], axis=0) for key, value in fixture().items()}
        data['extrinsics'][1, :, 3] += [.1, 0, 0]
        data['intrinsics'][1, :2, :2] *= 1.1
        data['intrinsics'][1, 0, 2] += 11
        camera = self.configure_camera(data)
        fps = 24000/1001
        metadata = {'source_manifest': {'nominal_fps': fps,
                                        'frames': [{'source_frame': 100}, {'source_frame': 112}]}}
        report = blender_scene.animate_cameras(self.scene, camera, data, metadata, 1)
        self.assertEqual([row['blender_frame'] for row in report['mapping']], [1, 13])
        self.assertEqual((self.scene.frame_current, self.scene.frame_start, self.scene.frame_end), (13, 1, 13))
        self.assertAlmostEqual(self.scene.render.fps/self.scene.render.fps_base, fps, places=4)
        expected = blender_scene.camera_matrix(data['extrinsics'][1])
        np.testing.assert_allclose(np.array(camera.matrix_world), np.array(expected), atol=1e-5)
        point_camera = np.array([.15, -.12, 2.])
        extrinsic = data['extrinsics'][1]
        point_world = (point_camera-extrinsic[:, 3]) @ extrinsic[:, :3]
        projected = world_to_camera_view(self.scene, camera, Vector((point_world*[1, -1, -1]).tolist()))
        observed = [projected.x*320-.5, (1-projected.y)*240-.5]
        target = data['intrinsics'][1] @ point_camera
        np.testing.assert_allclose(observed, target[:2]/target[2], atol=.001)
        for owner in (camera, camera.data):
            for curve in owner.animation_data.action.fcurves:
                self.assertTrue(all(key.interpolation == 'LINEAR' for key in curve.keyframe_points))
        with self.assertRaisesRegex(ValueError, 'source_manifest'):
            blender_scene.animate_cameras(self.scene, camera, data, {}, 0)
        data['intrinsics'][1, 1, 1] *= 1.15
        with self.assertRaisesRegex(ValueError, 'fx/fy'):
            blender_scene.animate_cameras(self.scene, camera, data, metadata, 0)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BlenderSceneRegression))
    print(json.dumps({'suite': 'blender_scene_smoke', 'tests': result.testsRun,
                      'failures': len(result.failures), 'errors': len(result.errors),
                      'passed': result.wasSuccessful()}))
    if not result.wasSuccessful():
        raise RuntimeError('Falha nos testes de calibração da cena Blender.')
