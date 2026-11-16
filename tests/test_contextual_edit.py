"""Actual tiny-media integration for contextual direction and native rendering.

Directions here are explicit synthetic human fixtures. They do not evaluate a
model, prove semantic understanding, or count as perceptual user approval.
"""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import cv2
import numpy as np
from PIL import Image

from audiovisual.semantic_audio import index_audio_assets
from editorial_engine.contracts import ValidationError, digest, file_sha256
from editorial_engine.directions import apply_direction, build_request, call_provider, plan_direction
from editorial_engine.native import native_catalog, render_bundle
from editorial_engine.perception import prepare_analysis, write_json
from editorial_engine.planner import build_plan
from editorial_engine.review import new_review


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Actual FFmpeg integration")
class ContextualEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="contextual-integration-")
        cls.root = Path(cls.directory.name)
        cls.source = cls.root / "source.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=0x101820:s=320x240:r=30:d=2",
                        "-vf", "drawbox=x=128:y=48:w=80:h=144:color=blue:t=fill", "-c:v", "libx264", "-threads", "1",
                        "-pix_fmt", "yuv420p", str(cls.source)], check=True, capture_output=True)
        cls.source_hash = file_sha256(cls.source)
        cls.transcript = cls.root / "speech.json"
        write_json(cls.transcript, {"source_sha256": cls.source_hash, "clock": "source",
                   "segments": [{"start": 0, "end": 2, "text": "Uma forma aparece ao lado do objeto."}]})
        cls.protection = cls.root / "protection.json"
        write_json(cls.protection, {"source_sha256": cls.source_hash, "fps": "30", "frame_count": 60,
            "provenance": {"kind": "human", "actor": "synthetic-test-fixture", "method": "Known generated rectangle coordinates"},
            "frames": {str(i): [[.4, .2, .65, .8]] for i in range(60)}})
        cls.asset = cls.root / "orange.png"
        Image.new("RGBA", (256, 256), (255, 180, 0, 255)).save(cls.asset)
        cls.wav = cls.root / "pulse.wav"
        pcm = np.zeros(22050, dtype="<i2")
        pcm[4410] = 20000
        with wave.open(str(cls.wav), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(pcm.tobytes())
        indexed = index_audio_assets([{"id": "pulse", "path": str(cls.wav), "anchor": {
            "sample": 4410, "kind": "impact", "status": "reviewed", "review_note": "Known synthetic impulse"}}])
        cls.inventory = {"assets": [{"id": "orange", "kind": "image", "path": str(cls.asset), "description": "Synthetic orange square"},
                                    {"id": "pulse", "kind": "sfx", "asset": indexed["assets"][0]}]}
        cls.mattes = cls.root / "matte"
        cls.mattes.mkdir()
        write_json(cls.mattes / "alpha.json", {"source_sha256": cls.source_hash, "fps": "30", "frames": 60})
        matte = np.zeros((240, 320), np.uint8)
        matte[48:192, 128:208] = 255
        for i in range(60):
            cv2.imwrite(str(cls.mattes / f"{i:06d}.png"), matte)
        cls.analysis = prepare_analysis(cls.source, cls.root / "prepared", transcript=cls.transcript,
                                       protection=cls.protection, mattes=cls.mattes, assets=cls.inventory, sample_every_s=.5)
        cls.catalog = native_catalog()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.output_root = Path(tempfile.mkdtemp(prefix="case-", dir=self.root))

    def direction(self, *, effect="native.overlay", params=None, bindings=None, region=None, audio=False):
        event = self.analysis["events"][0]
        provenance = {"kind": "human", "actor": "synthetic-test-fixture", "method": "Known synthetic source and effect intent"}
        candidate = {"id": "visual", "event_id": event["id"], "effect_id": effect,
                "source_id": "source", "source_sha256": self.source_hash, "clock": "source",
                "interval": {"start_s": .5, "end_s": 1.5}, "evidence_ids": ["speech:0", "frame:30"],
                "why": "The known orange test shape illustrates the named reveal beside the synthetic subject.",
                "scores": dict.fromkeys(("intent_fit", "visual_fit", "style_fit", "timing_fit"), .9),
                "score_provenance": provenance, "anchor": {"space": "screen"},
                "bindings": bindings if bindings is not None else {"asset": "asset:orange"},
                "params": params or {}, "addresses": ["illustration"], "region": region or [.05, .1, .2, .2]}
        if effect == "preserve":
            candidate.update(interval=event["interval"], bindings={}, params={}, addresses=[])
            candidate.pop("anchor")
        proposals = [candidate]
        if audio:
            proposals.append({**copy.deepcopy(candidate), "id": "sound", "effect_id": "native.sfx", "addresses": ["impact"],
                 "interval": {"start_s": .8, "end_s": 1.5}, "anchor": {"space": "none"}, "bindings": {"asset": "asset:pulse"},
                 "params": {"target_sample": 48000, "sample_rate": 48000, "gain_db": -12},
                 "why": "The synthetic impulse accompanies the visible reveal at exactly one second."})
        return {"schema_version": "1.0", "provenance": provenance,
                "evidence_annotations": [{"id": "frame:30", "observation": "Synthetic blue rectangle on a dark background; empty region on its left."}],
                "event_annotations": [{"id": event["id"], "intent": "Demonstrate a visual reveal beside the source object",
                  "opportunities": [{"id": "illustration", "function": "visualize_concept", "why": "Known synthetic illustration opportunity"},
                                    {"id": "impact", "function": "accent", "why": "Known timed reveal"}]}],
                "proposals": {"schema_version": "1.0", "candidates": proposals}, "limitations": ["Synthetic fixture; no model inference or aesthetic review"]}

    def bundle(self, **kwargs):
        return plan_direction(self.analysis, self.catalog, self.direction(**kwargs))

    @staticmethod
    def frame(path, index):
        capture = cv2.VideoCapture(str(path))
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        capture.release()
        if not ok:
            raise AssertionError("Actual frame could not be read")
        return frame

    def test_prepare_keeps_semantic_interpretation_explicit(self):
        self.assertEqual(self.analysis["preparation"]["semantic_status"], "awaiting_direction")
        self.assertEqual(self.analysis["events"][0]["intent"], "requires_direction")
        self.assertEqual(file_sha256(self.source), self.source_hash)
        self.assertTrue(all(e["provenance"]["kind"] == "tool" for e in self.analysis["evidence"]))

    def test_request_contains_actual_frame_pixels_and_labeled_sampling_scope(self):
        request = build_request(self.analysis, self.catalog, "Demonstrate the reveal", max_frames=3)
        content = request["body"]["messages"][1]["content"]
        images = [part for part in content if part["type"] == "image_url"]
        self.assertEqual(len(images), 4)  # Three source samples and one asset preview.
        self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertFalse(request["model_inference_executed"])
        self.assertFalse(request["review_scope"]["continuous_motion_review"])
        self.assertEqual(request["review_scope"]["image_asset_capability_ids"], ["asset:orange"])

    def test_native_render_changes_selected_interval_and_preserves_source(self):
        bundle = self.bundle()
        output = self.output_root / "render.mp4"
        artifact = render_bundle(bundle, output)
        before, after = self.frame(output, 5), self.frame(output, 30)
        self.assertGreater(float(after[35:65, 20:70, 2].mean() - before[35:65, 20:70, 2].mean()), 100)
        original = self.frame(self.source, 30)
        self.assertLess(np.abs(original[70:160, 145:185].astype(float) - after[70:160, 145:185].astype(float)).mean(), 3)
        self.assertEqual(file_sha256(self.source), self.source_hash)
        self.assertEqual(artifact["frame_count"], 60)
        self.assertEqual(artifact["plan_sha256"], bundle["plan"]["plan_sha256"])
        self.assertEqual(artifact["user_approval"], "pending")
        self.assertEqual(artifact["perceptual_review"]["motion"], "unverified")
        self.assertFalse(new_review(bundle["plan"], artifact)["can_finalize"])

    def test_visual_and_sound_selected_together_and_really_muxed(self):
        bundle = self.bundle(audio=True)
        self.assertEqual(len(bundle["plan"]["decisions"]), 2)
        output = self.output_root / "av.mp4"
        artifact = render_bundle(bundle, output)
        self.assertIsNotNone(artifact["audio"])
        audio = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(output), "-vn", "-f", "f32le",
                                "-ar", "48000", "-ac", "1", "-"], capture_output=True, check=True).stdout
        samples = np.frombuffer(audio, dtype="<f4")
        # AAC delivery is lossy; sample-exact alignment is proved in PCM module tests.
        self.assertLess(abs(int(np.argmax(np.abs(samples))) - 48000), 100)
        self.assertGreater(float(np.max(np.abs(samples))), .01)

    def test_behind_subject_uses_actual_mask_without_relocating_subject(self):
        bundle = self.bundle(effect="native.behind_subject", bindings={"asset": "asset:orange", "matte": "matte"},
                             region=[.25, .15, .5, .7])
        output = self.output_root / "behind.mp4"
        render_bundle(bundle, output)
        original, result = self.frame(self.source, 30), self.frame(output, 30)
        self.assertLess(np.abs(original[80:150, 145:190].astype(float) - result[80:150, 145:190].astype(float)).mean(), 3)
        self.assertGreater(result[100:140, 100:120, 2].mean(), original[100:140, 100:120, 2].mean() + 100)

    def test_preserve_is_explicit_and_copies_the_source_bytes(self):
        bundle = self.bundle(effect="preserve")
        artifact = render_bundle(bundle, self.output_root / "preserved.mp4")
        self.assertEqual(artifact["sha256"], self.source_hash)

    def test_empty_proposals_cannot_silently_render_preservation(self):
        direction = self.direction()
        direction["proposals"]["candidates"] = []
        bundle = plan_direction(self.analysis, self.catalog, direction)
        with self.assertRaisesRegex(ValidationError, "plan_not_executable"):
            render_bundle(bundle, self.output_root / "empty.mp4")

    def test_protected_face_region_blocks_actual_render(self):
        bundle = self.bundle(region=[.45, .3, .1, .2])
        with self.assertRaisesRegex(ValidationError, "protected_overlap"):
            render_bundle(bundle, self.output_root / "unsafe.mp4")

    def test_slide_and_pop_remain_inside_reserved_region(self):
        for animation in ("slide", "pop"):
            with self.subTest(animation=animation):
                artifact = render_bundle(self.bundle(params={"animation": animation}), self.output_root / f"{animation}.mp4")
                self.assertEqual(artifact["technical_checks"]["clock"], "pass")

    def test_changed_asset_bytes_are_rejected_before_render(self):
        bundle = self.bundle()
        original = self.asset.read_bytes()
        try:
            self.asset.write_bytes(original + b"changed")
            with self.assertRaisesRegex(ValidationError, "file_hash_mismatch"):
                render_bundle(bundle, self.output_root / "changed.mp4")
        finally:
            self.asset.write_bytes(original)

    def test_missing_spatial_capability_does_not_become_screen_text(self):
        direction = self.direction(effect="native.hand_accent", bindings={"matte": "matte"}, params={"side": "right"})
        candidate = direction["proposals"]["candidates"][0]
        candidate.update(anchor={"space": "hand", "capability_id": "invented-hand"}, addresses=[])
        bundle = plan_direction(self.analysis, self.catalog, direction)
        self.assertFalse(bundle["plan"]["validation"]["executable"])
        self.assertFalse(bundle["plan"]["decisions"])
        self.assertEqual(bundle["plan"]["discarded"][0]["stage"], "eligibility")

    def test_unseen_provider_frame_cannot_receive_visual_annotation(self):
        request = build_request(self.analysis, self.catalog, "Reveal", include_images=False)
        direction = self.direction()
        direction["provider_receipt"] = {"analysis_sha256": digest(self.analysis), "catalog_sha256": digest(self.catalog),
                                         "review_scope": request["review_scope"]}
        with self.assertRaisesRegex(ValidationError, "unseen_frame"):
            apply_direction(self.analysis, self.catalog, direction)

    def test_unannotated_frame_is_not_treated_as_semantic_evidence(self):
        direction = self.direction()
        direction["evidence_annotations"] = []
        with self.assertRaisesRegex(ValidationError, "uninterpreted_frame"):
            apply_direction(self.analysis, self.catalog, direction)

    def test_output_clock_transcript_is_rejected(self):
        transcript = self.output_root / "bad-clock.json"
        raw = json.loads(self.transcript.read_text())
        raw["clock"] = "output"
        write_json(transcript, raw)
        with self.assertRaisesRegex(ValidationError, "transcript_clock"):
            prepare_analysis(self.source, self.output_root / "bad-analysis", transcript=transcript)

    def test_overwriting_original_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "output_exists"):
            render_bundle(self.bundle(), self.source)

    def test_provider_adapter_returns_data_and_receipt_without_claiming_validation(self):
        request = build_request(self.analysis, self.catalog, "Reveal", max_frames=3)
        response = {"choices": [{"message": {"content": json.dumps(self.direction())}}], "usage": {"total_tokens": 23}}
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return json.dumps(response).encode()
        with patch("urllib.request.urlopen", return_value=FakeResponse()) as provider:
            result = call_provider(request, endpoint="http://localhost:9000/v1/chat/completions", model="test-boundary-fixture")
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result["provenance"]["actor"], "test-boundary-fixture")
        self.assertEqual(result["provider_receipt"]["analysis_sha256"], digest(self.analysis))
        self.assertNotIn("plan", result)

    def test_reference_lessons_require_explicit_user_approval(self):
        with self.assertRaisesRegex(ValidationError, "unapproved_lesson"):
            build_request(self.analysis, self.catalog, "Reveal", lessons=[{"status": "model_approved"}])


if __name__ == "__main__":
    unittest.main()
