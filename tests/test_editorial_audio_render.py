"""Small real AV renders: clocks, stream copy, PCM placement and ducking.

Synthetic signals provide known technical landmarks; these tests do not assess
the intelligibility or aesthetics of a user's video.
"""

import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave

import numpy as np

from audiovisual.semantic_audio import index_audio_assets
from editorial_engine.audio_render import AudioRenderError, mix_sfx


def command(arguments):
    result = subprocess.run(arguments, capture_output=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout


def pcm_wav(path, rate, samples):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(np.asarray(samples, dtype="<i2").tobytes())


def video(path, *, audio=None, seconds=2, fps=10, color="blue"):
    args = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:s=64x64:r={fps}:d={seconds}"]
    if audio:
        args += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "pcm_s16le"]
    else:
        args += ["-an"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-bf", "0", "-pix_fmt", "yuv420p",
             "-video_track_timescale", "10240", str(path)]
    command(args)


def decode(path, rate=48000):
    raw = command(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", str(path),
                   "-map", "0:a:0", "-ac", "2", "-ar", str(rate), "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"])
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires real FFmpeg/FFprobe AV execution")
class EditorialAudioRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="editorial-audio-tests-")
        cls.root = Path(cls.temporary.name)
        cls.original_wav = cls.root / "original.wav"
        original = np.zeros(88200, dtype=np.int16)
        original[11025] = 8000
        pcm_wav(cls.original_wav, 44100, original)
        cls.tone_wav = cls.root / "tone.wav"
        time = np.arange(88200) / 44100
        pcm_wav(cls.tone_wav, 44100, np.sin(2 * np.pi * 440 * time) * 12000)
        cls.sfx_wav = cls.root / "sfx.wav"
        sfx = np.zeros(22050, dtype=np.int16)
        sfx[4410] = 28000
        pcm_wav(cls.sfx_wav, 44100, sfx)
        cls.source = cls.root / "source.mov"
        cls.source_tone = cls.root / "source-tone.mov"
        cls.rendered = cls.root / "rendered.mp4"
        cls.short = cls.root / "short.mp4"
        cls.fast = cls.root / "fast.mp4"
        video(cls.source, audio=cls.original_wav, color="red")
        video(cls.source_tone, audio=cls.tone_wav, color="red")
        video(cls.rendered)
        video(cls.short, seconds=1)
        video(cls.fast, fps=20)
        cls.asset = index_audio_assets([{
            "id": "known-impact", "path": str(cls.sfx_wav), "kind": "impact",
            "anchor": {"sample": 4410, "kind": "impact", "status": "reviewed",
                       "review_note": "Known synthetic impulse; technical fixture only."},
        }])["assets"][0]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def cue(self, **changes):
        result = {"id": "impact-at-one-second", "asset": copy.deepcopy(self.asset),
                  "target_sample": 48000, "gain_db": -3.0}
        result.update(changes)
        return result

    def output(self, name):
        return self.root / name

    def test_real_44100_to_48000_mix_preserves_original_and_exact_sfx_pcm_clock(self):
        output = self.output("clock.mov")
        result = mix_sfx(self.source, self.rendered, output, [self.cue()])
        pcm = decode(output)
        self.assertEqual(len(pcm), 96000)
        self.assertEqual(int(np.argmax(np.abs(pcm[:, 0]))), 48000)
        self.assertGreater(float(abs(pcm[12000, 0])), 0.01)  # Original audio was included.
        self.assertEqual(result["original_audio"]["sample_rate"], 44100)
        self.assertEqual(result["cues"][0]["spot"]["sfx"]["source_attack_sample"], 4800)
        self.assertTrue(result["technical_checks"]["video_packets_identical"])
        self.assertTrue(result["technical_checks"]["output_timeline_match"])
        self.assertTrue(result["technical_checks"]["output_decodes"])
        self.assertEqual(result["delivery_audio"]["codec"], "pcm_s24le")
        self.assertFalse(result["perceptual_review_performed"])
        self.assertEqual(result["speech_intelligibility"], "not_assessed")

    def test_source_without_audio_gets_sfx_and_no_invented_voice_controller(self):
        output = self.output("no-original.mov")
        result = mix_sfx(self.rendered, self.rendered, output, [self.cue()])
        pcm = decode(output)
        self.assertEqual(int(np.argmax(np.abs(pcm[:, 0]))), 48000)
        self.assertFalse(result["original_audio"]["included"])
        self.assertFalse(result["ducking"]["enabled"])
        self.assertEqual(len(pcm), 96000)

    def test_aac_delivery_distinguishes_pcm_alignment_from_codec_padding(self):
        output = self.output("delivery.mp4")
        result = mix_sfx(self.source, self.rendered, output, [self.cue()])
        self.assertEqual(result["pcm_mix"]["sample_count"], 96000)
        self.assertEqual(result["delivery_audio"]["codec"], "aac")
        self.assertEqual(result["delivery_audio"]["sample_exact_claim"], "preencode_pcm_clock_only")
        self.assertEqual(result["delivery_audio"]["padding_samples_after_decode"],
                         result["delivery_audio"]["sample_count"] - 96000)
        self.assertTrue(result["technical_checks"]["video_packets_identical"])

    def test_overlapping_effects_are_limited_without_shifting_their_sample_anchor(self):
        cues = [self.cue(id=f"layer-{number}", gain_db=0) for number in range(6)]
        output = self.output("limited-overlap.mov")
        result = mix_sfx(self.rendered, self.rendered, output, cues)
        pcm = decode(output)
        self.assertLessEqual(float(np.max(np.abs(pcm))), result["limiter"]["limit"] + 1e-5)
        self.assertEqual(int(np.argmax(np.abs(pcm[:, 0]))), 48000)
        self.assertTrue(result["technical_checks"]["encoded_sample_peaks_below_full_scale"])

    def test_ducking_reduces_sfx_when_original_mix_is_active(self):
        with_effect = self.output("ducked.mov")
        source_only = self.output("tone-only.mov")
        no_original = self.output("effect-only.mov")
        report = mix_sfx(self.source_tone, self.rendered, with_effect, [self.cue(gain_db=0)])
        mix_sfx(self.source_tone, self.rendered, source_only, [])
        mix_sfx(self.rendered, self.rendered, no_original, [self.cue(gain_db=0)])
        difference = decode(with_effect) - decode(source_only)
        dry_effect = decode(no_original)
        window = slice(47900, 48100)
        self.assertLess(float(np.max(np.abs(difference[window]))), float(np.max(np.abs(dry_effect[window]))) * 0.5)
        self.assertTrue(report["ducking"]["enabled"])
        self.assertEqual(report["ducking"]["source"], "original_audio_mix")
        self.assertFalse(report["original_audio"]["voice_isolated"])
        self.assertEqual(report["limiter"]["latency_compensated"], True)

    def test_output_cannot_overwrite_video_or_sfx_inputs(self):
        original_bytes = self.source.read_bytes()
        with self.assertRaises(AudioRenderError):
            mix_sfx(self.source, self.rendered, self.source, [self.cue()])
        self.assertEqual(self.source.read_bytes(), original_bytes)
        with self.assertRaises(AudioRenderError):
            mix_sfx(self.source, self.rendered, self.rendered, [self.cue()])
        # A hard link with a permitted output extension must not bypass protection.
        linked = self.output("linked.mov")
        try:
            linked.hardlink_to(self.source)
            with self.assertRaises(AudioRenderError):
                mix_sfx(self.source, self.rendered, linked, [self.cue()])
        finally:
            linked.unlink(missing_ok=True)

    def test_asset_hash_mismatch_fails_before_output_creation(self):
        cue = self.cue()
        cue["asset"]["sha256"] = "0" * 64
        output = self.output("bad-hash.mov")
        with self.assertRaises(ValueError):
            mix_sfx(self.source, self.rendered, output, [cue])
        self.assertFalse(output.exists())

    def test_frame_clock_and_duration_mismatches_are_rejected(self):
        for name, rendered in [("short", self.short), ("fps", self.fast)]:
            with self.subTest(name=name), self.assertRaises(AudioRenderError):
                mix_sfx(self.source, rendered, self.output(name + "-rejected.mov"), [self.cue()])

    def test_gain_is_finite_and_cannot_boost_above_zero_db(self):
        for gain in (float("nan"), float("inf"), 0.1, True):
            with self.subTest(gain=gain), self.assertRaises(AudioRenderError):
                mix_sfx(self.source, self.rendered, self.output("invalid-gain.mov"), [self.cue(gain_db=gain)])

    def test_render_requires_reviewed_anchor_unless_explicitly_allowed(self):
        cue = self.cue()
        cue["asset"]["anchor"]["status"] = "inferred"
        with self.assertRaises(ValueError):
            mix_sfx(self.source, self.rendered, self.output("unreviewed.mov"), [cue])
        cue["require_reviewed_anchor"] = False
        result = mix_sfx(self.source, self.rendered, self.output("explicit-inferred.mov"), [cue])
        self.assertEqual(result["cues"][0]["spot"]["anchor_status"], "inferred")
        self.assertFalse(result["perceptual_review_performed"])

    def test_repeating_reviewed_marker_keeps_its_review_status(self):
        result = mix_sfx(self.source, self.rendered, self.output("same-marker.mov"),
                         [self.cue(source_attack_sample=4410)])
        self.assertEqual(result["cues"][0]["spot"]["anchor_status"], "reviewed")

    def test_tail_overrun_requires_explicit_source_trim(self):
        with self.assertRaises(AudioRenderError):
            mix_sfx(self.source, self.rendered, self.output("tail-overrun.mov"),
                    [self.cue(target_sample=90000)])
        result = mix_sfx(self.source, self.rendered, self.output("tail-trimmed.mov"),
                         [self.cue(target_sample=90000, trim_out=8820)])
        self.assertEqual(result["cues"][0]["spot"]["actual_attack_sample"], 90000)


if __name__ == "__main__":
    unittest.main()
