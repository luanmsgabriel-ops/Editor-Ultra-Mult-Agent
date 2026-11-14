from pathlib import Path
import unittest

from editor_policy import manifest, rank, read, validate_plan

FIXTURE = Path(__file__).parent / "fixtures"


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.plan = read(FIXTURE / "plan.json")
        self.catalog = read(FIXTURE / "catalog.json")
        self.need = read(FIXTURE / "need.json")
        self.scope = read(FIXTURE / "scope.json")

    def test_drive_scope_and_rights_are_hard_limits(self):
        result = rank(self.catalog, self.need, self.scope)
        self.assertEqual([row["id"] for row in result["eligible"]], ["fx-01"])
        rejected = {row["id"]: row["reasons"] for row in result["rejected"]}
        self.assertIn("direitos sem aprovação explícita", rejected["fx-02"])
        self.assertIn("fora das raízes autorizadas", rejected["fx-03"])

    def test_reject_unverified_compatibility(self):
        self.catalog["assets"][0]["engines"] = []
        self.assertEqual(rank(self.catalog, self.need, self.scope)["eligible"], [])

    def test_repeatable_ranking_ties_use_id(self):
        self.catalog["assets"].insert(0, {**self.catalog["assets"][0], "id": "fx-04"})
        result = rank(self.catalog, self.need, self.scope)
        self.assertEqual([row["id"] for row in result["eligible"]], ["fx-01", "fx-04"])
        self.assertEqual(result["eligible"][0]["score"], 23)

    def test_validate_frame_sound_and_effect(self):
        result = validate_plan(self.plan, self.catalog, self.scope)
        self.assertTrue(result["ok"])
        self.assertEqual(result["cue_checks"][1]["sfx_offset_samples"], 0)

    def test_handles_cannot_reintroduce_bad_frames(self):
        self.plan["segments"][1]["read"] = [33, 60]
        result = validate_plan(self.plan, self.catalog, self.scope)
        self.assertFalse(result["ok"])
        self.assertIn("trecho proibido", result["errors"][0])

    def test_reject_cue_displacement(self):
        self.plan["cues"][1]["sfx"]["timeline_start_sample"] += 1001
        result = validate_plan(self.plan, self.catalog, self.scope)
        self.assertFalse(result["ok"])
        self.assertEqual(result["cue_checks"][1]["sfx_offset_samples"], 1001)

    def test_reject_plan_using_wrong_scope(self):
        self.plan["effects"][0]["asset_id"] = "fx-03"
        self.assertFalse(validate_plan(self.plan, self.catalog, self.scope)["ok"])

    def test_unknown_rights_private_only_if_enabled_and_downloadable(self):
        asset = self.catalog["assets"][0]
        asset.update(license_status="unknown", can_download=True)
        self.need["use"] = "private_preview"
        self.plan["use"] = "private_preview"
        self.assertFalse(rank(self.catalog, self.need, self.scope)["eligible"])
        self.assertFalse(validate_plan(self.plan, self.catalog, self.scope)["ok"])
        self.scope["allow_unverified_private_preview"] = True
        self.assertIn("prévia privada", rank(self.catalog, self.need, self.scope)["eligible"][0]["restrictions"][0])
        report = validate_plan(self.plan, self.catalog, self.scope)
        self.assertTrue(report["ok"])
        self.assertIn("prévia privada", report["warnings"][0])
        asset["can_download"] = False
        self.assertFalse(rank(self.catalog, self.need, self.scope)["eligible"])
        asset["can_download"] = True
        self.need["use"] = "web"
        self.plan["use"] = "web"
        self.assertFalse(rank(self.catalog, self.need, self.scope)["eligible"])
        self.assertFalse(validate_plan(self.plan, self.catalog, self.scope)["ok"])

    def test_direct_file_required(self):
        self.catalog["assets"][0]["is_shortcut"] = True
        report = rank(self.catalog, self.need, self.scope)
        self.assertFalse(report["eligible"])
        self.assertIn("atalho", report["rejected"][0]["reasons"][0])

    def test_manifest_fingerprint_changes_with_plan(self):
        before = manifest(self.plan, {"need": FIXTURE / "need.json"})
        self.plan["duration_frames"] = 60
        after = manifest(self.plan, {"need": FIXTURE / "need.json"})
        self.assertNotEqual(before["timeline_sha256"], after["timeline_sha256"])
        self.assertEqual(before["files"], after["files"])


if __name__ == "__main__":
    unittest.main()
