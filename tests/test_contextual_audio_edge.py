"""Focused real-media regressions for subframe audio and discarded pre-roll.

The explicit directions describe generated fixtures, not model judgment or
user-approved editorial choices. No visual compositor or network is mocked.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave

import numpy as np

from audiovisual.semantic_audio import index_audio_assets
from editorial_engine.directions import plan_direction
from editorial_engine.native import native_catalog, render_bundle
from editorial_engine.perception import prepare_analysis


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires actual AV rendering")
class ContextualAudioEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="contextual-audio-edge-")
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "two-frames.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
            "color=c=blue:s=64x64:r=10:d=0.2", "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-bf", "0", "-pix_fmt", "yuv420p", str(cls.source),
        ], check=True, capture_output=True, timeout=30)
        inventory = {"assets": []}
        for identifier, length, attack in [("short", 384, 192), ("preroll", 1200, 960)]:
            path = cls.root / f"{identifier}.wav"
            pcm = np.zeros(length, dtype="<i2")
            pcm[attack] = 20000
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(48000)
                handle.writeframes(pcm.tobytes())
            asset = index_audio_assets([{
                "id": identifier, "path": str(path), "kind": "impact",
                "anchor": {"sample": attack, "kind": "impact", "status": "reviewed",
                           "review_note": "Known synthetic sample position; technical fixture only."},
            }])["assets"][0]
            inventory["assets"].append({"id": identifier, "kind": "sfx", "asset": asset})
        cls.analysis = prepare_analysis(cls.source, cls.root / "prepared", assets=inventory, sample_every_s=.05)
        cls.catalog = native_catalog()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def bundle(self, asset_id, start, end, target_sample, **params):
        event = self.analysis["events"][0]
        source = self.analysis["sources"][0]
        provenance = {"kind": "human", "actor": "synthetic-test-fixture",
                      "method": "Explicit generated-video and PCM landmarks; no perceptual assessment"}
        direction = {
            "schema_version": "1.0", "provenance": provenance,
            "evidence_annotations": [{"id": "frame:0", "observation": "Known generated blue frame."}],
            "event_annotations": [{"id": event["id"], "intent": "Exercise a known short audio accent",
                                   "opportunities": [{"id": "accent", "function": "accent",
                                                      "why": "Synthetic timing regression with a known PCM impulse."}]}],
            "proposals": {"schema_version": "1.0", "candidates": [{
                "id": "short-sound", "event_id": event["id"], "effect_id": "native.sfx",
                "source_id": source["id"], "source_sha256": source["sha256"], "clock": "source",
                "interval": {"start_s": start, "end_s": end}, "evidence_ids": ["frame:0"],
                "why": "Known technical audio cue occupies less time than one video frame.",
                "scores": dict.fromkeys(("intent_fit", "visual_fit", "style_fit", "timing_fit"), .9),
                "score_provenance": provenance, "anchor": {"space": "none"},
                "bindings": {"asset": "asset:" + asset_id},
                "params": {"sample_rate": 48000, "target_sample": target_sample, "gain_db": -6, **params},
                "addresses": ["accent"],
            }]},
            "limitations": ["Synthetic integration case; no listening or model inference."],
        }
        return plan_direction(self.analysis, self.catalog, direction)

    def test_audio_interval_without_a_video_frame_boundary_renders(self):
        # At 10 fps, [0.02, 0.03) contains no complete video frame. Audio uses
        # sample time: retained SFX [1008, 1392), with attack at sample 1200.
        bundle = self.bundle("short", .02, .03, 1200)
        self.assertTrue(bundle["plan"]["validation"]["executable"])
        output = self.root / "subframe.mp4"
        result = render_bundle(bundle, output)
        spot = result["compilation"][0]["spot"]
        self.assertEqual(spot["sfx"]["timeline_start_sample"], 1008)
        self.assertEqual(spot["actual_attack_sample"], 1200)
        self.assertEqual(result["frame_count"], 2)
        self.assertEqual(result["audio"]["pcm_mix"]["sample_count"], 9600)
        self.assertTrue(result["audio"]["technical_checks"]["video_packets_identical"])
        self.assertTrue(output.is_file())

    def test_trim_start_coverage_uses_retained_samples_not_original_preroll(self):
        # Untrimmed length is 1200 samples and would exceed this interval.
        # Removing negative pre-roll leaves exactly [0, 480), attack at 240.
        bundle = self.bundle("preroll", 0, .011, 240, negative_start_policy="trim_start")
        result = render_bundle(bundle, self.root / "trim-start.mp4")
        spot = result["compilation"][0]["spot"]
        self.assertEqual(spot["discarded_preroll_samples"], 720)
        self.assertEqual(spot["sfx"]["trim_in"], 720)
        self.assertEqual(spot["sfx"]["trim_out"] - spot["sfx"]["trim_in"], 480)
        self.assertEqual(spot["actual_attack_sample"], 240)
        self.assertEqual(result["audio"]["cues"][0]["spot"]["discarded_preroll_samples"], 720)
        self.assertFalse(result["audio"]["perceptual_review_performed"])


if __name__ == "__main__":
    unittest.main()
