"""Real spatial renders on a synthetic, source-bound person fixture.

Known landmark coordinates and masks are authored by this test; no detector or
generative model is evaluated. Pixel, clock and occlusion checks are technical
integration evidence, never an aesthetic review or user approval.
"""

import copy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine.native import BUNDLE_SCHEMA, native_catalog, render_bundle
from editorial_engine.perception import prepare_analysis, write_json
from editorial_engine.planner import build_plan
from visual_fidelity.reference_cadence import video_clock


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Real FFmpeg spatial integration")
class ContextualSpatialTests(unittest.TestCase):
    SIZE = (320, 480)
    FPS = 20
    COUNT = 24
    INTERVAL = {"start_s": .15, "end_s": 1.05}
    AUTHOR = {"kind": "human", "actor": "synthetic-spatial-fixture",
              "method": "Known authored person geometry and explicit test direction"}

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="contextual-spatial-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.source = cls.root / "person.mp4"
        cls.original_mattes = cls.root / "half-resolution-mattes"
        cls.original_mattes.mkdir()
        frames, pose_frames, hands = [], {}, {}
        width, height = cls.SIZE

        def landmark(x, y):
            return [float(x), float(y), 0.0, .99]

        for index in range(cls.COUNT):
            hand_x = 250 + round(16 * index / (cls.COUNT - 1))
            hand_y = 290 + round(6 * np.sin(index / (cls.COUNT - 1) * np.pi))
            alpha = np.zeros((height, width), np.uint8)
            torso = np.array([(90, 201), (230, 201), (220, 455), (100, 455)], np.int32)
            cv2.fillConvexPoly(alpha, torso, 255)
            cv2.rectangle(alpha, (144, 138), (176, 210), 255, -1)
            cv2.ellipse(alpha, (160, 108), (30, 38), 0, 0, 360, 255, -1)
            cv2.line(alpha, (96, 218), (65, 325), 255, 25)
            cv2.line(alpha, (224, 218), (hand_x, hand_y), 255, 25)
            cv2.circle(alpha, (65, 325), 13, 255, -1)
            cv2.circle(alpha, (hand_x, hand_y), 13, 255, -1)
            frame = np.full((height, width, 3), (22, 16, 12), np.uint8)
            frame[alpha > 0] = (210, 60, 25)
            cv2.rectangle(frame, (144, 138), (176, 202), (100, 175, 230), -1)
            cv2.ellipse(frame, (160, 108), (30, 38), 0, 0, 360, (100, 175, 230), -1)
            cv2.circle(frame, (65, 325), 13, (100, 175, 230), -1)
            cv2.circle(frame, (hand_x, hand_y), 13, (100, 175, 230), -1)
            # An asymmetric high-contrast shirt marker detects translation of
            # the subject independently of the effect's intended pixel changes.
            cv2.rectangle(frame, (142, 326), (178, 366), (245, 245, 245), -1)
            cv2.rectangle(frame, (146, 330), (156, 358), (25, 25, 25), -1)
            cv2.circle(frame, (168, 338), 5, (25, 25, 25), -1)
            frames.append(frame)
            small = cv2.resize(alpha, (width // 2, height // 2), interpolation=cv2.INTER_AREA)
            if not cv2.imwrite(str(cls.original_mattes / f"{index:06d}.png"), small):
                raise AssertionError("Could not create synthetic mask")
            face = {
                "nose": landmark(.50, .22), "left_eye": landmark(.47, .20),
                "right_eye": landmark(.53, .20), "left_ear": landmark(.42, .22),
                "right_ear": landmark(.58, .22), "mouth_left": landmark(.48, .26),
                "mouth_right": landmark(.52, .26),
                "left_shoulder": landmark(.28, .44), "right_shoulder": landmark(.72, .44),
                "left_wrist": landmark(65 / width, 325 / height),
                "right_wrist": landmark(hand_x / width, hand_y / height),
            }
            pose_frames[str(index)] = [{"id": 1, "landmarks": face}]
            cx, cy = hand_x / width, hand_y / height
            hands[str(index)] = [{"side": "right", "landmarks": {
                "hand_wrist": landmark(cx - .018, cy + .025),
                "index_mcp": landmark(cx - .015, cy - .015),
                "middle_mcp": landmark(cx, cy - .02),
                "ring_mcp": landmark(cx + .012, cy - .015),
                "pinky_mcp": landmark(cx + .022, cy),
            }}]

        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}", "-r", str(cls.FPS), "-i", "pipe:0",
            "-an", "-c:v", "libx264", "-crf", "0", "-threads", "1", "-pix_fmt", "yuv420p", str(cls.source),
        ], input=b"".join(frame.tobytes() for frame in frames), capture_output=True, check=True, timeout=30)
        cls.source_hash = file_sha256(cls.source)
        cls.pose_data = {"source_sha256": cls.source_hash, "clock": "source", "fps": str(cls.FPS),
                         "frames": pose_frames, "hands": hands}
        cls.pose_path = cls.root / "pose.json"
        write_json(cls.pose_path, cls.pose_data)
        write_json(cls.original_mattes / "alpha.json", {
            "source_sha256": cls.source_hash, "clock": "source", "fps": str(cls.FPS),
            "frames": cls.COUNT, "resolution": [width // 2, height // 2],
        })
        cls.original_hashes = {path: file_sha256(path) for path in cls.original_mattes.iterdir()}
        cls.asset = cls.root / "orange-strip.png"
        Image.new("RGBA", (320, 80), (255, 180, 0, 255)).save(cls.asset)
        cls.inventory = {"assets": [{"id": "strip", "kind": "image", "path": str(cls.asset),
                                     "description": "Authored orange strip for an occlusion integration test"}]}
        cls.analysis = prepare_analysis(
            cls.source, cls.root / "prepared", pose=cls.pose_path, mattes=cls.original_mattes,
            assets=cls.inventory, sample_every_s=.25,
        )
        cls.catalog = native_catalog()
        cls.font = next((path for path in (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf"),
            Path("/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf"),
        ) if path.is_file()), None)

    def setUp(self):
        self.output_root = Path(tempfile.mkdtemp(prefix="case-", dir=self.root))

    @staticmethod
    def frame(path, index):
        reader = cv2.VideoCapture(str(path))
        reader.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = reader.read()
        reader.release()
        if not ok:
            raise AssertionError("Rendered source frame is not decodable")
        return frame

    def bundle(self, effect, *, analysis=None, anchor=None, params=None, region=None):
        data = copy.deepcopy(self.analysis if analysis is None else analysis)
        self.assertEqual(len(data["events"]), 1, "Fixture must remain a single shot")
        event = data["events"][0]
        event["intent"] = "Exercise explicitly authored spatial composition on a synthetic person"
        function = "reinforce_action" if effect == "native.hand_accent" else "spatial_relation"
        event["opportunities"] = [{"id": "spatial", "function": function,
                                   "why": "Known source geometry makes this integration case measurable"}]
        visual = next(item for item in data["evidence"] if item["id"] == "frame:10")
        visual.update(observation="A generated person with a moving right hand and a fixed shirt marker.",
                      provenance=copy.deepcopy(self.AUTHOR))
        candidate = {
            "id": "spatial", "event_id": event["id"], "effect_id": effect,
            "source_id": "source", "source_sha256": self.source_hash, "clock": "source",
            "interval": dict(self.INTERVAL), "evidence_ids": ["frame:10"],
            "why": "Explicit synthetic fixture: exercise the requested spatial effect while retaining the source person.",
            "scores": dict.fromkeys(("intent_fit", "visual_fit", "style_fit", "timing_fit"), .9),
            "score_provenance": copy.deepcopy(self.AUTHOR),
            "anchor": anchor or {"space": "screen"}, "bindings": {"matte": "matte"},
            "params": params or {}, "addresses": ["spatial"], "region": region or [0, 0, 1, 1],
        }
        if effect == "native.behind_subject":
            candidate["bindings"]["asset"] = "asset:strip"
        proposals = {"schema_version": "1.0", "candidates": [candidate]}
        plan = build_plan(data, self.catalog, proposals, plan_id="synthetic-spatial", verify_files=True)
        return {"schema": BUNDLE_SCHEMA, "analysis": data, "catalog": self.catalog, "plan": plan}

    def assert_clock_and_person_retained(self, output, artifact):
        self.assertEqual(video_clock(output), (Fraction(self.FPS), self.COUNT))
        self.assertEqual(artifact["frame_count"], self.COUNT)
        self.assertEqual(file_sha256(self.source), self.source_hash)
        self.assertEqual(artifact["perceptual_review"]["motion"], "unverified")
        self.assertEqual(artifact["user_approval"], "pending")
        # Across the active interval, the marker must remain at its original
        # pixel position, not merely resemble the source at some new location.
        for index in (4, 12, 20):
            original, result = self.frame(self.source, index), self.frame(output, index)
            marker = original[320:372, 136:184]
            match = cv2.matchTemplate(result, marker, cv2.TM_CCOEFF_NORMED)
            _, peak, _, location = cv2.minMaxLoc(match)
            self.assertGreater(peak, .99)
            self.assertEqual(location, (136, 320))
            # H.264 delivery quantizes color; exact marker location above is
            # the displacement assertion, independent of this codec tolerance.
            self.assertLess(np.abs(marker.astype(float) - result[320:372, 136:184].astype(float)).mean(), 4)

    def assert_effect_pixels_changed(self, output, rectangle):
        original, result = self.frame(self.source, 12), self.frame(output, 12)
        x0, y0, x1, y1 = rectangle
        difference = np.max(np.abs(result[y0:y1, x0:x1].astype(int) - original[y0:y1, x0:x1].astype(int)), axis=2)
        self.assertGreater(np.count_nonzero(difference > 35), 40)
        inactive = np.abs(self.frame(output, 1).astype(float) - self.frame(self.source, 1).astype(float))
        self.assertLess(inactive.mean(), 3)

    def test_half_grid_masks_are_normalized_without_mutation_and_render_behind(self):
        capability = next(cap for cap in self.analysis["capabilities"] if cap["id"] == "matte")
        receipt = json.loads(Path(capability["verification"]["artifact_path"]).read_text())
        normalized = Path(receipt["directory"])
        self.assertNotEqual(normalized, self.original_mattes)
        self.assertEqual(receipt["normalization"], {
            "from": [160, 240], "to": [320, 480], "method": "cv2.INTER_LINEAR", "clock_unchanged": True,
        })
        self.assertEqual(file_sha256(capability["verification"]["artifact_path"]), capability["verification"]["artifact_sha256"])
        for index in range(self.COUNT):
            path = normalized / f"{index:06d}.png"
            self.assertEqual(cv2.imread(str(path), cv2.IMREAD_GRAYSCALE).shape, (480, 320))
            self.assertEqual(file_sha256(path), receipt["frame_sha256"][str(index)])
        bundle = self.bundle("native.behind_subject", region=[.15, .38, .7, .22])
        self.assertTrue(bundle["plan"]["validation"]["executable"])
        output = self.output_root / "behind.mp4"
        artifact = render_bundle(bundle, output)
        self.assert_clock_and_person_retained(output, artifact)
        self.assert_effect_pixels_changed(output, (50, 210, 85, 250))
        source, result = self.frame(self.source, 12), self.frame(output, 12)
        # The strip crosses this opaque torso patch: its survival is evidence
        # of the actual holdout, in addition to the unrelated marker check.
        self.assertLess(np.abs(source[220:250, 140:180].astype(float) - result[220:250, 140:180].astype(float)).mean(), 3)
        self.assertEqual({path: file_sha256(path) for path in self.original_hashes}, self.original_hashes)

    def test_hand_accent_renders_against_real_tracked_frames(self):
        capability = next(cap for cap in self.analysis["capabilities"] if cap["name"] == "hand_tracking")
        bundle = self.bundle("native.hand_accent",
                             anchor={"space": "hand", "capability_id": capability["id"]}, params={"side": "right"})
        self.assertTrue(bundle["plan"]["validation"]["executable"])
        output = self.output_root / "hand.mp4"
        artifact = render_bundle(bundle, output)
        self.assertEqual(artifact["compilation"][0]["mode"], "hand_track")
        self.assertEqual(artifact["compilation"][0]["coverage"], 18)
        self.assert_clock_and_person_retained(output, artifact)
        self.assert_effect_pixels_changed(output, (220, 260, 310, 330))

    def test_body_orbit_renders_visible_front_and_occluded_rear_passes(self):
        if self.font is None:
            self.skipTest("A local TrueType/OpenType font is required for orbital typography")
        capability = next(cap for cap in self.analysis["capabilities"] if cap["name"] == "body_tracking")
        # Same geometry and thresholds: this shorter title does not expose
        # enough occluded rear text at the initial phase, so it must block.
        insufficient = self.bundle("native.body_orbit",
                                   anchor={"space": "body", "capability_id": capability["id"]}, params={"title": "ORBITA"})
        blocked = self.output_root / "insufficient-orbit.mp4"
        with self.assertRaisesRegex(ValidationError, "orbit_passes"):
            render_bundle(insufficient, blocked, font=self.font)
        self.assertFalse(blocked.exists())
        bundle = self.bundle("native.body_orbit",
                             anchor={"space": "body", "capability_id": capability["id"]}, params={"title": "GESTO EM CENA"})
        self.assertTrue(bundle["plan"]["validation"]["executable"])
        output = self.output_root / "orbit.mp4"
        artifact = render_bundle(bundle, output, font=self.font)
        compilation = artifact["compilation"][0]
        self.assertEqual(compilation["mode"], "body_orbit")
        self.assertEqual(compilation["coverage"], 18)
        self.assertEqual(len(compilation["sampled_orbit_evidence"]), 5)
        for sample in compilation["sampled_orbit_evidence"]:
            self.assertGreater(min(sample[key] for key in ("rear_visible", "rear_occluded", "front_visible")), 0)
        self.assert_clock_and_person_retained(output, artifact)
        self.assert_effect_pixels_changed(output, (50, 100, 275, 270))

    def test_lost_hand_tracking_blocks_the_plan_and_does_not_fallback(self):
        lost = copy.deepcopy(self.pose_data)
        lost["hands"].pop("12")
        path = self.output_root / "lost-hand.json"
        write_json(path, lost)
        analysis = prepare_analysis(self.source, self.output_root / "prepared", pose=path,
                                    mattes=self.original_mattes, sample_every_s=.25)
        capability = next(cap for cap in analysis["capabilities"] if cap["name"] == "hand_tracking")
        bundle = self.bundle("native.hand_accent", analysis=analysis,
                             anchor={"space": "hand", "capability_id": capability["id"]}, params={"side": "right"})
        self.assertFalse(bundle["plan"]["validation"]["executable"])
        self.assertEqual(bundle["plan"]["decisions"], [])
        self.assertEqual(bundle["plan"]["discarded"][0]["effect_id"], "native.hand_accent")
        self.assertIn("anchor_unverified", [issue["code"] for issue in bundle["plan"]["discarded"][0]["issues"]])
        output = self.output_root / "must-not-render.mp4"
        with self.assertRaisesRegex(ValidationError, "plan_not_executable"):
            render_bundle(bundle, output)
        self.assertFalse(output.exists())
        self.assertEqual(file_sha256(self.source), self.source_hash)


if __name__ == "__main__":
    unittest.main()
