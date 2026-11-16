"""Testes do importador SFX ElevenLabs, sem uso de rede ou credits."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from audiovisual import elevenlabs_sfx


class ElevenLabsSFXTests(unittest.TestCase):
    def make_catalog(self, root):
        catalog = {
            "flow_id": "flow-123",
            "assets": [
                {"id": "SFX-001", "category": "whoosh", "name": "AIRY_FAST",
                 "filename": "SFX-001_whoosh_AIRY_FAST.mp3", "duration_ms": 2000,
                 "tags": ["whoosh"], "generation_id": "g-123"}
            ],
        }
        path = root / "catalog.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return path

    def test_reject_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.make_catalog(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["assets"].append(dict(data["assets"][0]))
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                elevenlabs_sfx.read_catalog(path)

    def test_missing_export_does_not_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = elevenlabs_sfx.read_catalog(self.make_catalog(root))
            exports = root / "exports"
            exports.mkdir()
            dest = root / "assets"
            with self.assertRaisesRegex(ValueError, "Faltam exports"):
                elevenlabs_sfx.stage(catalog, exports, dest, root / "manifest.json")
            self.assertFalse(dest.exists())

    @mock.patch.object(elevenlabs_sfx, "duration_ms", return_value=2000)
    def test_stage_preserves_audio_and_disables_eligibility(self, _probe):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = elevenlabs_sfx.read_catalog(self.make_catalog(root))
            exports = root / "exports"
            exports.mkdir()
            (exports / "SFX-001_whoosh_AIRY_FAST.mp3").write_bytes(b"mp3 test fixture")
            output = root / "out" / "manifest.json"
            result = elevenlabs_sfx.stage(catalog, exports, root / "assets", output)
            self.assertTrue(output.exists())
            self.assertEqual((root / "assets" / "SFX-001.mp3").read_bytes(),
                             b"mp3 test fixture")
            asset = result["assets"][0]
            self.assertFalse(asset["editor_eligibility"])
            self.assertEqual(asset["license_status"], "unknown")
            self.assertEqual(asset["duration_ms"], 2000)
            self.assertEqual(asset["source"], "elevenlabs")

    @mock.patch.object(elevenlabs_sfx, "duration_ms", return_value=2000)
    def test_stage_refuses_overwrite_changed_file(self, _probe):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = elevenlabs_sfx.read_catalog(self.make_catalog(root))
            exports, dest = root / "exports", root / "dest"
            exports.mkdir()
            dest.mkdir()
            (exports / "SFX-001_whoosh_AIRY_FAST.mp3").write_bytes(b"new")
            (dest / "SFX-001.mp3").write_bytes(b"old")
            with self.assertRaisesRegex(ValueError, "Conflito"):
                elevenlabs_sfx.stage(catalog, exports, dest, root / "manifest.json")


if __name__ == "__main__":
    unittest.main()
