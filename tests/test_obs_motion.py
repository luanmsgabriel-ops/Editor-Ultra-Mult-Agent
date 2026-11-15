import types
import unittest

from visual_fidelity.motion_qa import audit
from visual_fidelity.obs_capture import inspect, start, stop


class FakeOBS:
    active = False

    def __init__(self):
        self.requests = []

    def get_current_program_scene(self):
        return types.SimpleNamespace(current_program_scene_name='Interface')

    def get_scene_item_list(self, scene):
        return types.SimpleNamespace(scene_items=[{'sourceName': 'App', 'sceneItemEnabled': True},
                                                  {'sourceName': 'Outro', 'sceneItemEnabled': False}])

    def get_record_status(self):
        return types.SimpleNamespace(output_active=self.active, output_paused=False, output_duration=0)

    def start_record(self):
        self.requests.append('start')
        self.active = True

    def stop_record(self):
        self.requests.append('stop')
        self.active = False
        return types.SimpleNamespace(output_path='/capturas/interface.mkv')


class TestOBSCapture(unittest.TestCase):
    def test_inspect_then_record(self):
        fake = FakeOBS()
        self.assertEqual(inspect(fake)['sources'][0]['name'], 'App')
        self.assertFalse(fake.requests)
        self.assertTrue(start(fake, 'Interface', ['App'])['recording'])
        self.assertEqual(stop(fake)['output_path'], '/capturas/interface.mkv')
        self.assertEqual(fake.requests, ['start', 'stop'])

    def test_wrong_scene_or_hidden_source_has_no_side_effects(self):
        fake = FakeOBS()
        with self.assertRaises(ValueError):
            start(fake, 'Outra')
        with self.assertRaises(ValueError):
            start(fake, 'Interface', ['Outro'])
        self.assertFalse(fake.requests)


class TestMotionAudit(unittest.TestCase):
    def test_curve_and_linear_classification(self):
        frame = [{'frame': 0, 'x': 0, 'y': 0, 'ease': 'ease-in-out'}, {'frame': 30, 'x': 1, 'y': 0}]
        payload = {'fps': 30, 'resolution': [100, 100], 'tracks': [
            {'id': 'suave', 'normalized': True, 'keyframes': frame},
            {'id': 'reta', 'normalized': True, 'keyframes': [
                {**frame[0], 'ease': 'linear'}, frame[1]]}
        ]}
        report, rows = audit(payload)
        eased, straight = [t['segments'][0] for t in report['tracks']]
        self.assertFalse(eased['warnings'])
        self.assertGreater(eased['peak_speed_px_s'], 100)
        self.assertIn('velocidade_constante', straight['warnings'])
        self.assertEqual(straight['peak_speed_px_s'], 100)
        self.assertEqual(rows[30]['x_px'], 100)

    def test_observation_only_and_cut(self):
        report, rows = audit({'fps': 30, 'resolution': [600, 600], 'shot_starts': [12],
                              'effects': [{'layer': 'teste', 'sample_centers': {
                                  '0': [.1, .1], '6': [.2, .1], '18': [.8, .1]}}]})
        spans = report['tracks'][0]['segments']
        self.assertEqual(spans[0]['mean_displacement_speed_px_s'], 300)
        self.assertEqual(spans[0]['status'], 'between_observations')
        self.assertEqual(spans[1]['status'], 'cut')
        self.assertEqual(len(rows), 3)
        self.assertIsNone(rows[-1]['speed_px_s'])


if __name__ == '__main__':
    unittest.main()
