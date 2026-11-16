"""Real PCM/FFmpeg integration; injected encoders test only the vector boundary.

No model quality claim is made by these tests. They do not install libraries,
download checkpoints, or call inference APIs.
"""

import contextlib
import copy
from fractions import Fraction
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave

import numpy as np

from audiovisual.semantic_audio import (
    CatalogIntegrityError,
    ClapEncoder,
    SemanticAudioUnavailable,
    index_audio_assets,
    main,
    make_editor_cue,
    probe_backend,
    search,
    spot_sfx,
)
from extensions.editor_policy import validate_plan


class InjectedEncoder:
    """Deliberate encoder fixture, not a CLAP substitute or semantic evaluator."""

    model_id = "test-only/injected-encoder"
    checkpoint = "fixture-v1"
    sample_rate = 48000
    backend = "test_injected_boundary"

    def __init__(self, vectors, query=(1, 0, 0)):
        self.vectors = iter(vectors)
        self.query = query
        self.audio_requests = []
        self.text_requests = []

    def encode_audio(self, audio, sample_rate):
        self.audio_requests.append((audio.shape, sample_rate))
        return next(self.vectors)

    def encode_text(self, text):
        self.text_requests.append(text)
        return self.query


def write_wav(path, rate=48000, count=48000, attack=12000, *, stereo=False, silent=False):
    pcm = np.zeros((count, 2 if stereo else 1), dtype="<i2")
    if not silent:
        pcm[attack, 0] = 28000
        if stereo:
            pcm[attack, 1] = -28000  # Energy spotting must not cancel opposite-phase channels.
    with wave.open(str(path), "wb") as output:
        output.setnchannels(pcm.shape[1])
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm.tobytes())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Real audio integration requires FFmpeg and FFprobe")
class SemanticAudioIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="semantic-audio-tests-")
        cls.root = Path(cls.directory.name)
        cls.wav = cls.root / "pulse.wav"
        cls.other_rate = cls.root / "pulse-44100.wav"
        cls.stereo = cls.root / "antiphase.wav"
        cls.silence = cls.root / "silence.wav"
        write_wav(cls.wav)
        write_wav(cls.other_rate, rate=44100, count=44100, attack=11025)
        write_wav(cls.stereo, stereo=True)
        write_wav(cls.silence, silent=True)
        cls.metadata = index_audio_assets([{"id": "pulse", "path": str(cls.wav), "kind": "impact"}])
        cls.cross_rate = index_audio_assets([{
            "id": "pulse-44100", "path": str(cls.other_rate), "kind": "impact",
            "anchor": {"sample": 11025, "kind": "impact", "status": "reviewed", "review_note": "Known synthetic pulse."},
        }])
        fixture_encoder = InjectedEncoder([(0, 1, 0), (10, 0, 0), (1, 0, 0)])
        cls.semantic = index_audio_assets([
            {"id": "Z", "path": str(cls.wav), "kind": "whoosh"},
            {"id": "B", "path": str(cls.other_rate), "kind": "impact"},
            {"id": "A", "path": str(cls.stereo), "kind": "impact"},
        ], encoder=fixture_encoder)
        cls.encoder_requests = fixture_encoder.audio_requests

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def query(self, index=None, vector=(1, 0, 0), **kwargs):
        return search(index or self.semantic, query_embedding=vector,
                      model_id=InjectedEncoder.model_id, checkpoint=InjectedEncoder.checkpoint, **kwargs)

    def test_real_metadata_uses_decoded_samples_and_records_inferred_anchor(self):
        asset = self.metadata["assets"][0]
        self.assertEqual(asset["metadata"]["sample_count"], 48000)
        self.assertEqual(asset["metadata"]["sample_rate"], 48000)
        self.assertEqual(Fraction(asset["metadata"]["duration_seconds"]), 1)
        self.assertEqual(asset["anchor"]["sample"], 12000)
        self.assertEqual(asset["anchor"]["status"], "inferred")
        self.assertFalse(asset["anchor"]["perceptual_apex_verified"])
        self.assertEqual(self.metadata["semantic_search"], "unavailable")
        self.assertFalse(self.metadata["clap_inference_executed"])

    def test_antiphase_stereo_does_not_erase_energy_anchor(self):
        asset = self.semantic["assets"][2]
        self.assertEqual(asset["anchor"]["sample"], 12000)
        self.assertEqual(asset["anchor"]["method"], "maximum_absolute_channel_amplitude")

    def test_silence_has_no_invented_impact(self):
        asset = index_audio_assets([self.silence])["assets"][0]
        self.assertIsNone(asset["anchor"]["sample"])
        with self.assertRaises(SemanticAudioUnavailable):
            spot_sfx(asset, target_sample=48000, timeline_sample_rate=48000)

    def test_metadata_only_index_never_becomes_keyword_search(self):
        with self.assertRaises(SemanticAudioUnavailable):
            search(self.metadata, query="pulse impact")

    def test_injected_embeddings_are_marked_as_injected_and_resampled_explicitly(self):
        self.assertTrue(self.semantic["injected_encoder"])
        self.assertFalse(self.semantic["clap_inference_executed"])
        self.assertEqual(self.semantic["embedding_backend"], "test_injected_boundary")
        self.assertEqual([rate for _, rate in self.encoder_requests], [48000, 48000, 48000])
        self.assertEqual([shape for shape, _ in self.encoder_requests], [(48000,), (48000,), (48000,)])

    def test_cosine_ranking_is_scale_invariant_and_ties_are_stable(self):
        result = self.query(vector=(1e300, 0, 0))
        self.assertEqual([row["id"] for row in result["matches"]], ["A", "B", "Z"])
        self.assertEqual([row["score"] for row in result["matches"]], [1.0, 1.0, 0.0])
        self.assertFalse(result["semantic_fallback"])
        self.assertEqual(result["editorial_decision"], "not_performed")

    def test_text_query_uses_explicit_encoder_boundary(self):
        encoder = InjectedEncoder([], query=(0, 1, 0))
        result = search(self.semantic, query="gentle paper whoosh", encoder=encoder)
        self.assertEqual(encoder.text_requests, ["gentle paper whoosh"])
        self.assertEqual(result["matches"][0]["id"], "Z")

    def test_precomputed_query_object_carries_identity(self):
        result = search(self.semantic, query_embedding={
            "values": [0, 1, 0], "model_id": InjectedEncoder.model_id,
            "checkpoint": InjectedEncoder.checkpoint,
        })
        self.assertEqual(result["matches"][0]["id"], "Z")

    def test_query_model_and_checkpoint_must_match(self):
        for model, checkpoint in [("other", InjectedEncoder.checkpoint), (InjectedEncoder.model_id, "other"), (None, None)]:
            with self.subTest(model=model, checkpoint=checkpoint), self.assertRaises(ValueError):
                search(self.semantic, query_embedding=[1, 0, 0], model_id=model, checkpoint=checkpoint)

    def test_invalid_embedding_shape_nan_inf_zero_or_dimension_is_rejected(self):
        for vector in ([[1, 0, 0]], [float("nan"), 0, 0], [float("inf"), 1, 0], [0, 0, 0], [1, 0], []):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                self.query(vector=vector)

    def test_asset_embedding_model_mismatch_is_rejected(self):
        altered = copy.deepcopy(self.semantic)
        altered["assets"][0]["embedding"]["checkpoint"] = "other"
        with self.assertRaises(ValueError):
            self.query(altered)

    def test_malformed_catalog_objects_fail_clearly(self):
        for field, value in [("assets", ["not-an-asset"]), ("embedding_model", "not-a-model")]:
            altered = copy.deepcopy(self.semantic)
            altered[field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, SemanticAudioUnavailable)):
                self.query(altered)

    def test_incomplete_index_reports_unavailable_instead_of_partial_false_success(self):
        altered = copy.deepcopy(self.semantic)
        altered["assets"][0]["embedding"] = None
        with self.assertRaises(SemanticAudioUnavailable):
            self.query(altered)

    def test_rejected_assets_and_kind_filters_are_explicit(self):
        altered = copy.deepcopy(self.semantic)
        altered["assets"][2]["review_status"] = "rejected"
        result = self.query(altered, kinds=["impact"])
        self.assertEqual([row["id"] for row in result["matches"]], ["B"])
        self.assertEqual({row["id"]: row["reason"] for row in result["excluded"]},
                         {"Z": "kind_filter", "A": "review_rejected"})
        with self.assertRaises(ValueError):
            spot_sfx(altered["assets"][2], target_sample=48000, timeline_sample_rate=48000)

    def test_changed_audio_bytes_invalidate_retrieval_and_spotting(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "changed.wav"
            shutil.copy2(self.wav, path)
            altered = copy.deepcopy(self.semantic)
            asset = altered["assets"][0]
            asset["path"] = str(path)
            with path.open("ab") as handle:
                handle.write(b"changed")
            with self.assertRaises(CatalogIntegrityError):
                self.query(altered)
            with self.assertRaises(CatalogIntegrityError):
                spot_sfx(asset, target_sample=48000, timeline_sample_rate=48000)

    def test_input_manifest_hash_is_verified(self):
        with self.assertRaises(CatalogIntegrityError):
            index_audio_assets([{"id": "bad", "path": str(self.wav), "sha256": "0" * 64}])

    def test_spot_uses_source_trim_in_normalized_clock(self):
        spot = spot_sfx(self.cross_rate["assets"][0], target_sample=96000,
                        timeline_sample_rate=48000, trim_in=2205, trim_out=22050)
        self.assertEqual(spot["source_clock"]["source_attack_sample"], 11025)
        self.assertEqual(spot["sfx"]["source_attack_sample"], 12000)
        self.assertEqual(spot["sfx"]["trim_in"], 2400)
        self.assertEqual(spot["sfx"]["timeline_start_sample"], 86400)
        self.assertEqual(spot["actual_attack_sample"], 96000)
        self.assertEqual(spot["anchor_status"], "reviewed")
        self.assertFalse(spot["perceptual_review_performed"])

    def _render_pcm(self, path, spot):
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", str(path),
                   "-af", spot["audio_filter"], "-ac", "1", "-ar", str(spot["sample_rate"]),
                   "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]
        result = subprocess.run(command, check=True, capture_output=True, timeout=30)
        return np.frombuffer(result.stdout, dtype="<f4")

    def test_actual_ffmpeg_resample_trim_delay_places_pulse_at_exact_target(self):
        spot = spot_sfx(self.cross_rate["assets"][0], target_sample=96000,
                        timeline_sample_rate=48000, trim_in=2205, trim_out=22050)
        pcm = self._render_pcm(self.other_rate, spot)
        self.assertEqual(int(np.argmax(np.abs(pcm))), 96000)
        self.assertEqual(len(pcm), 86400 + 24000 - 2400)

    def test_negative_start_requires_explicit_policy_and_trim_start_preserves_attack(self):
        asset = self.metadata["assets"][0]
        with self.assertRaises(ValueError):
            spot_sfx(asset, target_sample=1000, timeline_sample_rate=48000)
        spot = spot_sfx(asset, target_sample=1000, timeline_sample_rate=48000, negative_start_policy="trim_start")
        self.assertEqual(spot["discarded_preroll_samples"], 11000)
        self.assertEqual(spot["sfx"]["timeline_start_sample"], 0)
        pcm = self._render_pcm(self.wav, spot)
        self.assertEqual(int(np.argmax(np.abs(pcm))), 1000)

    def test_anchor_must_survive_half_open_trim(self):
        asset = self.metadata["assets"][0]
        for changes in ({"trim_in": 12001}, {"trim_out": 12000}, {"source_attack_sample": 48000},
                        {"trim_in": 20000, "trim_out": 10000}, {"trim_out": 48001}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                spot_sfx(asset, target_sample=96000, timeline_sample_rate=48000, **changes)

    def test_noninteger_resample_positions_report_exact_quantization(self):
        spot = spot_sfx(self.cross_rate["assets"][0], target_sample=48000,
                        timeline_sample_rate=48000, trim_in=1, source_attack_sample=100)
        self.assertEqual(Fraction(spot["quantization"]["trim_in"]["exact_samples"]), Fraction(160, 147))
        for value in spot["quantization"].values():
            self.assertLessEqual(abs(Fraction(value["error_samples"])), Fraction(1, 2))
        self.assertEqual(spot["actual_attack_sample"], 48000)

    def test_reviewed_anchor_gate_does_not_upgrade_inferred_values(self):
        with self.assertRaises(ValueError):
            spot_sfx(self.metadata["assets"][0], target_sample=48000,
                     timeline_sample_rate=48000, require_reviewed_anchor=True)
        spot = spot_sfx(self.cross_rate["assets"][0], target_sample=48000,
                        timeline_sample_rate=48000, require_reviewed_anchor=True)
        self.assertEqual(spot["anchor_status"], "reviewed")
        with self.assertRaises(ValueError):
            spot_sfx(self.cross_rate["assets"][0], target_sample=48000, timeline_sample_rate=48000,
                     source_attack_sample=11025, require_reviewed_anchor=True)

    def test_editor_policy_integration_uses_one_sample_clock(self):
        spot = spot_sfx(self.cross_rate["assets"][0], target_sample=96000,
                        timeline_sample_rate=48000, trim_in=2205)
        cue = make_editor_cue(spot, label="reveal", frame=60, fps=30)
        plan = {"fps": "30", "duration_frames": 150, "segments": [{
            "sequence": [0, 150], "source": [0, 150], "source_fps": "30", "source_frames": 150,
        }], "cues": [cue]}
        result = validate_plan(plan)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["cue_checks"][0]["sfx_offset_samples"], 0)
        invalid = copy.deepcopy(spot)
        invalid["sfx"]["trim_out"] = invalid["sfx"]["source_attack_sample"]
        with self.assertRaises(ValueError):
            make_editor_cue(invalid, label="bad-trim", frame=60, fps=30)

    def test_fractional_fps_cue_avoids_float_time_drift(self):
        spot = spot_sfx(self.metadata["assets"][0], target_sample=480480, timeline_sample_rate=48000)
        cue = make_editor_cue(spot, label="ntsc", frame=300, fps="30000/1001", tolerance_frames=0)
        self.assertEqual(cue["audio_sample"], 480480)
        with self.assertRaises(ValueError):
            make_editor_cue(spot, label="wrong-frame", frame=301, fps="30000/1001", tolerance_frames=0)

    def test_cli_reports_metadata_and_unavailable_semantics_as_json(self):
        with tempfile.TemporaryDirectory() as folder:
            index_path = Path(folder) / "index.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["index", str(self.wav), "--output", str(index_path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "metadata_only")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["search", str(index_path), "--query", "impact"])
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(output.getvalue())["status"], "unavailable")
            self.assertFalse(json.loads(output.getvalue())["semantic_fallback"])

    def test_cli_protects_original_media(self):
        original = self.wav.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            result = main(["index", str(self.wav), "--output", str(self.wav)])
        self.assertEqual(result, 2)
        self.assertEqual(self.wav.read_bytes(), original)


class LazyDependencyTests(unittest.TestCase):
    def test_probe_does_not_claim_model_or_perceptual_validation(self):
        result = probe_backend()
        self.assertFalse(result["clap"]["weights_verified"])
        self.assertFalse(result["clap"]["inference_executed"])
        self.assertFalse(result["clap"]["automatic_download"])
        self.assertEqual(result["api_calls"], 0)

    def test_adapter_construction_does_not_load_model(self):
        encoder = ClapEncoder()
        self.assertIsNone(encoder._model)
        self.assertIsNone(encoder._processor)

    @unittest.skipIf(probe_backend()["clap"]["dependencies_present"], "Missing-dependency test applies only when dependencies are absent")
    def test_actual_absent_dependencies_raise_unavailable(self):
        with self.assertRaises(SemanticAudioUnavailable):
            ClapEncoder().encode_text("short paper whoosh")


if __name__ == "__main__":
    unittest.main()
