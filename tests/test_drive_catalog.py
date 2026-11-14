from unittest import TestCase
from audiovisual.drive_catalog import FOLDER, SHORTCUT, family, scan


class DriveTest(TestCase):
    def test_scoped_children_pages_and_shortcut(self):
        calls = []

        def list_mock(path, **query):
            calls.append((path, query.get("q"), query.get("pageToken")))
            if path == "/root":
                return {"name": "Acervo", "mimeType": FOLDER}
            parent = "root" if "'root'" in query["q"] else "sub"
            if parent == "root" and not query.get("pageToken"):
                return {"nextPageToken": "p2", "files": [
                    {"id": "sub", "name": "Som", "mimeType": FOLDER, "parents": ["root"]},
                ]}
            if parent == "root":
                return {"files": [{"id": "shortcut", "name": "Outro Drive", "mimeType": SHORTCUT,
                                   "parents": ["root"]}]}
            return {"files": [{"id": "sound", "name": "Fogo", "mimeType": "audio/mpeg",
                               "parents": ["sub"], "capabilities": {"canDownload": True}}]}

        result = scan(["root"], list_mock)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["roots"][0]["count"], 2)
        self.assertEqual(result["assets"][1]["root_ids"], ["root"])
        self.assertEqual(result["assets"][1]["folder_ids"], ["sub"])
        self.assertTrue(result["assets"][0]["is_shortcut"])

    def test_typing_preserves_scope_of_sound(self):
        self.assertEqual(family("Trilha Épica", "audio/mpeg"), "music_candidate")
        self.assertEqual(family("Fogo curto", "audio/mpeg"), "fire")
        self.assertEqual(family("Adobe.cube", "application/octet-stream"), "lut")
