import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from visual_fidelity.music_sync import analyze_audio, schedule_events, retime_binding_schedule, edited_audio_filter


class MusicSyncTests(unittest.TestCase):
    def wav(self, path, events, duration=5, opposite=False):
        sr = 48000
        audio = np.zeros((round(duration * sr), 2), np.float32)
        # 8 ms broadband click, constant seed, short exponential decay.
        rng = np.random.default_rng(73)
        click = rng.normal(size=384) * np.exp(-np.arange(384) / 85) * .4
        for time in events:
            i = round(time * sr)
            length = min(len(click), len(audio) - i)
            audio[i:i+length, 0] += click[:length]
            audio[i:i+length, 1] += click[:length] * (-1 if opposite else 1)
        wavfile.write(path, sr, audio)

    def test_clicks_center_timing_and_periodic_hypothesis(self):
        events = np.arange(.25, 4.8, .5)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'clicks.wav'; self.wav(p, events)
            result = analyze_audio(p, 5)
        measured = [c['time'] for c in result['cues']]
        self.assertEqual(len(measured), len(events))
        self.assertLess(max(abs(np.array(measured)-events)), .015)
        self.assertEqual(result['pulse']['status'], 'periodic_candidate')
        # Half-time is an admissible musical ambiguity, explicitly reported.
        self.assertTrue(any(abs(v-120)<2 for v in result['pulse']['alternatives_bpm']))

    def test_silence_does_not_invent_beats(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'silence.wav'; self.wav(p, [])
            result = analyze_audio(p, 5)
        self.assertEqual(result['status'], 'silence')
        self.assertEqual(result['cues'], [])
        self.assertIsNone(result['pulse']['bpm'])
        self.assertEqual(result['pulse']['beat_times'], [])

    def test_sustained_energy_return_is_a_candidate_not_a_downbeat(self):
        sr = 48000
        rng = np.random.default_rng(19)
        audio = rng.normal(0, .001, (2 * sr, 2)).astype(np.float32)
        audio[sr:sr+sr//4] += rng.normal(0, .1, (sr//4, 2))
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'return.wav'; wavfile.write(p, sr, audio)
            result = analyze_audio(p, 2)
        cue = min(result['cues'], key=lambda c:abs(c['time']-1))
        self.assertLess(abs(cue['time']-1), .025)
        self.assertGreater(cue['energy_change_db'], 30)
        self.assertEqual(cue['suggested_priority'], 'energy_return')
        self.assertEqual(cue['kind'], 'transient')
        self.assertNotIn('downbeat', cue)
        self.assertTrue(cue['energy_context_complete'])

    def test_narrow_click_has_no_sustained_energy_return_and_zero_is_finite(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'click.wav'; self.wav(p, [.5], duration=1)
            result = analyze_audio(p, 1)
        cue = result['cues'][0]
        self.assertEqual(cue['suggested_priority'], 'texture_attack')
        self.assertEqual(cue['pre_rms_dbfs'], -120)
        self.assertEqual(cue['post_rms_dbfs'], -120)
        self.assertEqual(cue['energy_change_db'], 0)

    def test_opposite_phase_stereo_has_same_transients(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'same.wav'; q = Path(td) / 'opposite.wav'
            self.wav(p, [.5, 1, 1.5, 2]); self.wav(q, [.5, 1, 1.5, 2], opposite=True)
            a = analyze_audio(p, 3); b = analyze_audio(q, 3)
        self.assertEqual(a['cues'], b['cues'])

    def test_trim_clock_maps_to_output_and_preserves_source_offset(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'offset.wav'; self.wav(p, [1.25, 1.75, 2.25, 2.75])
            result = analyze_audio(p, 2, start=1)
        self.assertLess(abs(result['cues'][0]['time']-.25), .015)
        self.assertLess(abs(result['cues'][0]['source_time_nominal']-1.25), .015)
        self.assertEqual(result['clock']['decoded_duration'], 2)
        self.assertTrue(result['clock']['complete'])

    def test_shared_audio_clock_skips_unit_tempo_and_flags_short_audio(self):
        self.assertNotIn('atempo', edited_audio_filter(0, 1, 5))
        self.assertIn('atempo=1.5', edited_audio_filter(0, 1.5, 5))
        with self.assertRaises(ValueError): edited_audio_filter(-1, 1, 5)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'short.wav'; self.wav(p, [], duration=1)
            result = analyze_audio(p, 2)
        self.assertFalse(result['clock']['complete'])

    def test_schedule_global_assignment_avoids_greedy_collision(self):
        cues = [{'id':'a','time':1.0,'strength':.2}, {'id':'b','time':1.1,'strength':1}]
        events = [{'id':'first','target_time':1.1,'max_shift':.2},
                  {'id':'second','target_time':1.1,'max_shift':.01}]
        result = schedule_events(events, cues, 24, 100)
        self.assertEqual([x['cue_id'] for x in result], ['a','b'])

    def test_conflicting_locked_cues_raise_not_drift(self):
        events = [{'id':'a','target_time':1,'max_shift':.1,'cue_id':'same'},
                  {'id':'b','target_time':1,'max_shift':.1,'cue_id':'same'}]
        with self.assertRaisesRegex(ValueError, 'collision-free'):
            schedule_events(events, [{'id':'same','time':1}], 24, 100)

    def test_fractional_fps_quantization_and_manual_evidence(self):
        fps=24000/1001
        result = schedule_events([{'id':'apex','role':'apex','target_time':1.234,'max_shift':.1}],
                                 [{'id':'marked','time':1.234,'kind':'manual','evidence':'editor mark'}], '24000/1001', 240)
        self.assertEqual(result[0]['frame'], 30)
        self.assertLessEqual(abs(result[0]['quantization_error_ms']), 500/fps)
        self.assertEqual(result[0]['cue_evidence'], 'editor mark')
        self.assertEqual(result[0]['role'], 'apex')

    def test_invalid_clock_event_or_cue_is_rejected(self):
        for cue in [{'id':'bad','time':-1},{'id':'bad','time':float('nan')}]:
            with self.assertRaises(ValueError):
                schedule_events([{'id':'event','target_time':1,'max_shift':1}], [cue], 24, 240)
        with self.assertRaises(ValueError):
            schedule_events([{'id':'event','target_time':10,'max_shift':1}], [], 24, 240)
        with self.assertRaises(ValueError):
            schedule_events([{'id':'event','target_time':9.99,'max_shift':.1}],
                            [{'id':'outside','time':9.99}], 24, 240)

    def test_retime_keeps_source_and_matte_together_with_exclusive_endpoint(self):
        original=[{'frame':i,'base':{'frame':i},'mask_file':f'{i}.png',
                   'foreground':{'frame':i,'matte':f'{i}.png'}} for i in range(10)]
        result=retime_binding_schedule(original,[{'output_frame':0,'source_frame':0},
                {'output_frame':4,'source_frame':7},{'output_frame':10,'source_frame':10}],10)
        self.assertEqual(result[4]['base']['frame'],7)
        for b in result:
            source=b['base']['frame']
            self.assertEqual(b['foreground']['frame'],source)
            self.assertEqual(b['mask_file'],f'{source}.png')
            self.assertEqual(b['foreground']['matte'],f'{source}.png')
        result[0]['base']['frame']=99
        self.assertEqual(original[0]['base']['frame'],0)

    def test_retime_rejects_reversed_anchors(self):
        with self.assertRaises(ValueError):
            retime_binding_schedule([{'frame':i} for i in range(10)],
                [{'output_frame':0,'source_frame':0},{'output_frame':5,'source_frame':8},
                 {'output_frame':9,'source_frame':7}],10)

    def test_noninteger_stretch_does_not_reveal_next_shot_before_anchor(self):
        original=[{'frame':i,'shot':'A' if i<4 else 'B'} for i in range(10)]
        output=retime_binding_schedule(original,
                [{'output_frame':0,'source_frame':0},{'output_frame':10,'source_frame':4},
                 {'output_frame':20,'source_frame':10}],20)
        self.assertEqual(output[9]['retime_template_frame'],3)
        self.assertTrue(all(b['shot']=='A' for b in output[:10]))
        self.assertEqual(output[10]['shot'],'B')


if __name__ == '__main__':
    unittest.main()
