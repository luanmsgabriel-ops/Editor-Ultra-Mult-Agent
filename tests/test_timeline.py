import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audiovisual.__main__ import inventory, validate


class TimelineTest(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "examples/secador.json"
        self.edit = json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_is_valid(self):
        report = validate(self.edit)
        self.assertTrue(report["ok"])
        self.assertEqual(report["cue_checks"][-1]["distance_frames"], 0.16)

    def test_forbidden_frames_in_cut(self):
        self.edit["segments"][0]["source"] = [1, 21]
        self.assertTrue(any("proibido" in error for error in validate(self.edit)["errors"]))

    def test_handles_cannot_reintroduce_defect(self):
        self.edit["segments"][-1]["read"] = [36, 74]
        self.assertFalse(validate(self.edit)["ok"])

    def test_false_cue_rejected(self):
        self.edit["cues"][0]["cut_frame"] = 21
        self.assertFalse(validate(self.edit)["ok"])

    def test_cue_drift_rejected(self):
        self.edit["cues"][0]["audio_sample"] = 45000
        self.assertFalse(validate(self.edit)["ok"])

    def test_gap_rejected(self):
        self.edit["segments"][0]["sequence"] = [0, 19]
        self.assertTrue(any("Lacuna" in error for error in validate(self.edit)["errors"]))

    def test_mixed_rates_with_exact_duration(self):
        self.edit["assets"][1]["fps"] = "30/1"
        self.edit["segments"][1]["source"] = [3, 28]
        self.assertTrue(validate(self.edit)["ok"])

    def test_inventory_records_partial_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ["ok.mp4", "bad.mov", "skip.txt"]]
            for path in paths:
                path.touch()
            with patch("audiovisual.__main__.probe",
                       side_effect=[ValueError("invalid input"), {"path": "ok.mp4"}]):
                result = inventory([Path(directory)])
        self.assertEqual(len(result["assets"]), 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(result["errors"][0]["path"].endswith("bad.mov"))


if __name__ == "__main__":
    unittest.main()
