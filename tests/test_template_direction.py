"""Template discovery must not manufacture native execution capabilities."""

import copy
import json
import unittest

import test_editorial_engine as engine_fixtures
import test_template_library as template_fixtures

from editorial_engine.contracts import ValidationError, digest
from editorial_engine.directions import build_request
from editorial_engine.native import native_catalog
from editorial_engine.planner import build_plan


class TemplateDirectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = engine_fixtures.EngineFixture()
        self.engine.setUp()
        self.addCleanup(self.engine.doCleanups)
        self.templates = template_fixtures.TemplateLibraryTests()
        self.templates.setUp()
        self.addCleanup(self.templates.doCleanups)
        self.library_path = self.templates.root / "library.json"
        self.library_path.write_text(json.dumps(self.templates.library), encoding="utf-8")

    def test_verified_candidates_enter_request_without_becoming_effects_or_capabilities(self):
        analysis = copy.deepcopy(self.engine.analysis)
        catalog = native_catalog()
        baseline = build_request(analysis, catalog, "Explain the observed comparison.", include_images=False)
        request = build_request(analysis, catalog, "Explain the observed comparison.", include_images=False,
                                template_library=self.library_path, template_ids=["authored-example"])
        payload = json.loads(request["body"]["messages"][1]["content"][0]["text"])
        context = payload["template_library"]
        self.assertEqual([t["id"] for t in context["templates"]], ["authored-example"])
        self.assertTrue(context["files_verified"])
        self.assertFalse(context["runtime_executed"])
        self.assertFalse(context["templates"][0]["native_effect_ready"])
        self.assertNotIn("files", context["templates"][0])
        self.assertNotIn(str(self.templates.root), json.dumps(context))
        self.assertEqual(payload["catalog"], native_catalog())
        self.assertEqual(analysis, self.engine.analysis)
        self.assertEqual(payload["analysis"]["capabilities"], self.engine.analysis["capabilities"])
        self.assertEqual(request["analysis_sha256"], baseline["analysis_sha256"])
        self.assertEqual(request["catalog_sha256"], baseline["catalog_sha256"])
        self.assertNotEqual(request["request_sha256"], baseline["request_sha256"])
        self.assertEqual(request["request_sha256"], digest(request["body"]))
        candidate = self.engine.candidate(effect_id="authored-example", params={})
        plan = build_plan(analysis, catalog, {"schema_version": "1.0", "candidates": [candidate]})
        self.assertEqual(plan["decisions"], [])
        self.assertIn("unknown_effect", {issue["code"] for row in plan["discarded"] for issue in row["issues"]})

    def test_altered_private_package_blocks_context_request_before_direction(self):
        (self.templates.package / "project.json").write_text('{"changed":"unbound project"}')
        with self.assertRaises(ValidationError) as caught:
            build_request(self.engine.analysis, native_catalog(), "Inspect the source.", include_images=False,
                          template_library=self.library_path)
        self.assertEqual(caught.exception.issues[0]["code"], "template_package_changed")


if __name__ == "__main__":
    unittest.main()
