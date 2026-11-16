"""Private data bindings must preserve source bytes and never execute projects."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine.templates import instantiate_template, library_request, validate_library
from visual_fidelity.reference_bundle import inventory


class TemplateLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "packages" / "fixture"
        self.package.mkdir(parents=True)
        (self.package / "project.json").write_text(json.dumps({
            "name": "Original", "format": {"fps": 24},
            "scenes": [{"title": "First"}, {"title": "Second"}], "assets": []}), encoding="utf-8")
        (self.package / "index.html").write_text(
            '<style>body{color:#123456;background:#123}</style>'
            '<h1>Chapter I</h1><h2>Chapter II</h2><p>SYS&gt; READY &amp; WAIT</p>'
            '<span>Alpha</span><span>Beta</span><span data-name="Chapter I">Else</span>'
            '<script>const untouched="Chapter I";throw new Error("must never run")</script>', encoding="utf-8")
        (self.package / "preview.md").write_text("Original authoring preview; not a rendered variant.", encoding="utf-8")
        marker = self.root / "executed.txt"
        (self.package / "untrusted.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
        self.template = {"schema": "motion-template/1", "id": "authored-example", "version": "1.0.0",
            "package_id": "fixture", "title": "Original test option", "description": "An authored title sequence.",
            "functions": ["explain"], "entrypoint": "project.json",
            "runtime": {"name": "unexecuted-test-host", "requirements": ["A compatible host is required."]},
            "parameters": {"title": self.parameter("string", "New title", True),
                           "fps": {**self.parameter("integer", 24), "minimum": 1, "maximum": 60}},
            "bindings": [{"parameter": "title", "file": "project.json", "mode": "json_pointer", "pointer": "/scenes/0/title"},
                         {"parameter": "fps", "file": "project.json", "mode": "json_pointer", "pointer": "/format/fps"}],
            "inputs": {}, "previews": [{"path": "preview.md", "kind": "document", "description": "Provided notes only."}],
            "limitations": ["No renderer is executed by this module."],
            "state": {"catalogue": "catalogued", "adaptation": "required", "runtime": "not_executed",
                      "preview": "provided", "user_approval": "pending"},
            "output_contract": {"kind": "opaque_scene", "alpha": "opaque"}}
        self.library = {"schema": "motion-template-library/1", "id": "fixture-library", "version": "1.0.0",
            "packages": [{"id": "fixture", "root": "packages/fixture", "files": inventory(self.package, excludes=()),
                          "provenance": {"source_folder_ids": [], "source_file_ids": [], "notes": "Original synthetic test assets."}}],
            "templates": [self.template]}

    @staticmethod
    def parameter(kind, default=None, required=False):
        return {"type": kind, "required": required, "description": "Explicit authored parameter.", "default": default}

    def html_template(self, bindings, parameters):
        self.template.update(entrypoint="index.html", parameters=parameters, bindings=bindings)

    def instantiate(self, **kwargs):
        return instantiate_template(self.library, self.template["id"], self.root / "variant", root=self.root, **kwargs)

    def test_json_binding_copies_complete_package_without_running_or_modifying_source(self):
        original = inventory(self.package, excludes=())
        receipt = self.instantiate(params={"title": "User's new words", "fps": 30})
        derived = json.loads((self.root / "variant/project/project.json").read_text())
        self.assertEqual(derived["scenes"], [{"title": "User's new words"}, {"title": "Second"}])
        self.assertEqual(derived["format"]["fps"], 30)
        self.assertEqual(inventory(self.package, excludes=()), original)
        self.assertTrue((self.root / "variant/project/untrusted.py").is_file())
        self.assertFalse((self.root / "executed.txt").exists())
        self.assertFalse(receipt["runtime_executed"])
        self.assertEqual(receipt["state"], "instantiated_not_rendered")
        self.assertEqual(receipt["preview_validation"], "unverified_for_this_variant")
        self.assertEqual(receipt["user_approval"], "pending")
        self.assertEqual(receipt, json.loads(Path(receipt["receipt_path"]).read_text()))

    def test_request_resolves_relative_packages_from_library_file_without_exposing_root(self):
        path = self.root / "library.json"
        path.write_text(json.dumps(self.library), encoding="utf-8")
        request = library_request(path)
        self.assertTrue(request["files_verified"])
        self.assertFalse(request["runtime_executed"])
        self.assertNotIn(str(self.root), json.dumps(request))
        self.assertNotIn("files", request["templates"][0])
        self.assertFalse(request["templates"][0]["native_effect_ready"])
        self.assertFalse(request["templates"][0]["output_contract_verified"])
        self.assertEqual(library_request(path, template_ids=[])["templates"], [])
        with self.assertRaises(ValidationError):
            library_request(path, template_ids=["invented"])

    def test_summary_omits_parameter_defaults_without_changing_identity_or_readiness(self):
        self.template["editorial"] = {"use": "Explain the current topic.", "motion": "Progressive reveal.",
                                      "rules": ["Keep the authored hierarchy."], "conflicts": ["Avoid simultaneous titles."]}
        full = library_request(self.library, root=self.root)
        summary = library_request(self.library, root=self.root, summary=True)
        self.assertEqual(full["library_sha256"], summary["library_sha256"])
        detail, card = full["templates"][0], summary["templates"][0]
        for key in ("id", "version", "template_sha256", "package_sha256", "state", "output_contract", "missing_inputs", "parameters_requiring_values"):
            self.assertEqual(card[key], detail[key])
        self.assertNotIn("parameters", card)
        self.assertNotIn("inputs", card)
        self.assertNotIn("files", card)
        self.assertEqual(card["parameters_count"], 2)
        self.assertEqual(card["editorial_fields_in_full_request"], ["rules"])
        self.assertFalse(card["native_effect_ready"])
        self.assertFalse(summary["runtime_executed"])
        self.assertEqual(summary["detail_level"], "summary")
        self.assertEqual(card["detail_request"], {"template_ids": [self.template["id"]], "summary": False})
        self.assertEqual([summary["shared_notes"][key] for key in card["runtime"]["requirements_refs"]],
                         detail["runtime"]["requirements"])
        self.assertEqual([summary["shared_notes"][key] for key in card["limitations_refs"]], detail["limitations"])
        self.assertEqual(card["previews"], [{key: value for key, value in preview.items() if key != "description"}
                                           for preview in detail["previews"]])
        self.assertNotIn("shared_notes", full)
        second = copy.deepcopy(self.template)
        second["id"] = "second-authored-example"
        self.library["templates"].append(second)
        repeated = library_request(self.library, root=self.root, summary=True)
        self.assertEqual(repeated["shared_notes"], summary["shared_notes"])
        self.assertEqual(repeated["templates"][0]["limitations_refs"], repeated["templates"][1]["limitations_refs"])
        self.assertLess(len(json.dumps(repeated)), len(json.dumps(library_request(self.library, root=self.root))))

    def test_html_binds_whole_decoded_nodes_and_escapes_markup(self):
        self.html_template([
            {"parameter": "chapter", "file": "index.html", "mode": "html_text", "search": "Chapter I", "expected_count": 1},
            {"parameter": "system", "file": "index.html", "mode": "html_text", "search": "SYS> READY & WAIT", "expected_count": 1}],
            {"chapter": self.parameter("string", "<img src=x onerror=alert(1)>"),
             "system": self.parameter("string", "NEW > READY & GO")})
        self.instantiate()
        text = (self.root / "variant/project/index.html").read_text()
        self.assertIn("<h1>&lt;img src=x onerror=alert(1)&gt;</h1>", text)
        self.assertIn("<h2>Chapter II</h2>", text)
        self.assertIn('data-name="Chapter I"', text)
        self.assertIn('const untouched="Chapter I"', text)
        self.assertIn("NEW &gt; READY &amp; GO", text)

    def test_substitutions_are_simultaneous_not_cascading(self):
        self.html_template([
            {"parameter": "first", "file": "index.html", "mode": "html_text", "search": "Alpha", "expected_count": 1},
            {"parameter": "second", "file": "index.html", "mode": "html_text", "search": "Beta", "expected_count": 1}],
            {"first": self.parameter("string", "Beta"), "second": self.parameter("string", "Gamma")})
        self.instantiate()
        self.assertIn("<span>Beta</span><span>Gamma</span>", (self.root / "variant/project/index.html").read_text())

    def test_colour_binding_matches_complete_tokens_and_rejects_css_injection(self):
        self.html_template([{"parameter": "color", "file": "index.html", "mode": "hex_color", "search": "#123", "expected_count": 1}],
                           {"color": self.parameter("string", "#ABCDEF")})
        with self.assertRaises(ValidationError):
            self.instantiate(params={"color": "red;background:url(https://invalid.example)"})
        self.assertFalse((self.root / "variant").exists())
        self.instantiate()
        text = (self.root / "variant/project/index.html").read_text()
        self.assertIn("color:#123456;background:#ABCDEF", text)

    def test_binding_count_and_overlapping_json_targets_are_checked(self):
        self.html_template([{"parameter": "label", "file": "index.html", "mode": "html_text", "search": "Chapter I", "expected_count": 2}],
                           {"label": self.parameter("string", "New")})
        with self.assertRaises(ValidationError) as caught:
            self.instantiate()
        self.assertEqual(caught.exception.issues[0]["code"], "template_binding_count")
        self.template.update(entrypoint="project.json", parameters={"a": self.parameter("json", []), "b": self.parameter("string", "One")},
            bindings=[{"parameter": "a", "file": "project.json", "mode": "json_pointer", "pointer": "/scenes"},
                      {"parameter": "b", "file": "project.json", "mode": "json_pointer", "pointer": "/scenes/0/title"}])
        with self.assertRaises(ValidationError) as caught:
            self.instantiate()
        self.assertEqual(caught.exception.issues[0]["code"], "template_binding_overlap")

    def test_missing_video_slot_is_reported_and_only_filled_with_explicit_hash(self):
        self.template["inputs"] = {"source_video": {"path": "graded.mp4", "kind": "video", "required": True,
                                                   "description": "Supply the intended source; media type is not certified here."}}
        request = library_request(self.library, root=self.root)
        self.assertEqual(request["templates"][0]["missing_inputs"], ["source_video"])
        with self.assertRaises(ValidationError) as caught:
            self.instantiate()
        self.assertEqual(caught.exception.issues[0]["code"], "template_missing_input")
        supplied = self.root / "input.fixture"
        supplied.write_bytes(b"Bytes bound for staging only; not a video-format test.")
        with self.assertRaises(ValidationError):
            self.instantiate(inputs={"source_video": {"path": str(supplied), "sha256": "0" * 64}})
        result = self.instantiate(inputs={"source_video": {"path": str(supplied), "sha256": file_sha256(supplied)}})
        self.assertEqual((self.root / "variant/project/graded.mp4").read_bytes(), supplied.read_bytes())
        self.assertFalse(result["input_media_types_verified"])
        self.assertFalse((self.package / "graded.mp4").exists())

    def test_reference_only_entry_can_be_discovered_but_not_instantiated(self):
        self.template["state"]["adaptation"] = "reference_only"
        self.assertEqual(len(library_request(self.library, root=self.root)["templates"]), 1)
        with self.assertRaises(ValidationError) as caught:
            self.instantiate()
        self.assertEqual(caught.exception.issues[0]["code"], "template_reference_only")

    def test_strict_schema_rejects_keyword_scoring_and_fabricated_ready_states(self):
        for change in (lambda d: d["templates"][0].update(fit={"keywords": ["travel"]}),
                       lambda d: d["templates"][0]["state"].update(runtime="executed"),
                       lambda d: d["templates"][0]["state"].update(user_approval="approved")):
            data = copy.deepcopy(self.library)
            change(data)
            with self.assertRaises(ValidationError):
                validate_library(data)

    def test_editorial_context_is_preserved_without_importing_keyword_fit(self):
        self.template["editorial"] = {"use": "Explain an authored comparison.",
                                     "rules": ["Keep the two alternatives readable."],
                                     "motion": {"entry": "progressive reveal"}, "conflicts": []}
        request = library_request(self.library, root=self.root)
        self.assertEqual(request["templates"][0]["editorial"], self.template["editorial"])
        self.template["editorial"]["fit"] = {"keywords": ["comparison"]}
        with self.assertRaises(ValidationError):
            validate_library(self.library)

    def test_external_asset_array_requires_an_explicit_value_before_instantiation(self):
        self.template["parameters"]["media_assets"] = {"type": "json", "required": True,
            "description": "Provide current media/cache references explicitly."}
        self.template["bindings"].append({"parameter": "media_assets", "file": "project.json",
                                           "mode": "json_pointer", "pointer": "/assets"})
        request = library_request(self.library, root=self.root)
        self.assertEqual(request["templates"][0]["parameters_requiring_values"], ["media_assets"])
        with self.assertRaises(ValidationError) as caught:
            self.instantiate()
        self.assertEqual(caught.exception.issues[0]["code"], "template_missing_parameter")

    def test_changed_missing_and_unlisted_source_files_invalidate_verification(self):
        path = self.package / "preview.md"
        original = path.read_bytes()
        path.write_text("changed")
        with self.assertRaises(ValidationError):
            library_request(self.library, root=self.root)
        path.unlink()
        with self.assertRaises(ValidationError):
            library_request(self.library, root=self.root)
        path.write_bytes(original)
        (self.package / "unlisted.txt").write_text("not inventoried")
        with self.assertRaises(ValidationError):
            library_request(self.library, root=self.root)

    def test_inventory_order_is_independent_of_pathlib_component_sorting(self):
        (self.package / "licenses").mkdir()
        (self.package / "licenses/font.txt").write_text("Original license fixture.")
        (self.package / "licenses.json").write_text('{"font":"licenses/font.txt"}')
        rows = inventory(self.package, excludes=())
        # Path component order differs from string order for licenses/ and
        # licenses.json. Both describe exactly the same immutable package.
        self.assertNotEqual([r["path"] for r in rows], sorted(r["path"] for r in rows))
        self.library["packages"][0]["files"] = rows
        validate_library(self.library, root=self.root, verify_files=True)
        self.instantiate()
        self.assertEqual((self.root / "variant/project/licenses/font.txt").read_text(), "Original license fixture.")

    def test_traversal_symlinks_and_input_entrypoint_overwrite_are_rejected(self):
        data = copy.deepcopy(self.library)
        data["packages"][0]["root"] = "../outside"
        with self.assertRaises(ValueError):
            validate_library(data)
        (self.package / "link").symlink_to(self.package / "project.json")
        with self.assertRaises(ValueError):
            library_request(self.library, root=self.root)
        (self.package / "link").unlink()
        self.template["inputs"] = {"override": {"path": "project.json", "kind": "file", "required": True, "description": "Invalid overlap."}}
        with self.assertRaises(ValidationError):
            validate_library(self.library)

    def test_unbound_unknown_and_wrongly_typed_parameters_cannot_change_project(self):
        for params in ({"undeclared": "x"}, {"fps": True}, {"fps": 240}):
            with self.subTest(params=params), self.assertRaises(ValidationError):
                self.instantiate(params=params)
        self.template["parameters"]["orphan"] = self.parameter("string", "No target")
        with self.assertRaises(ValidationError):
            validate_library(self.library)

    def test_existing_output_and_output_inside_source_are_rejected(self):
        with self.assertRaises(ValidationError):
            instantiate_template(self.library, self.template["id"], self.package / "variant", root=self.root)
        self.instantiate()
        before = (self.root / "variant/instance.json").read_bytes()
        with self.assertRaises(ValidationError):
            self.instantiate()
        self.assertEqual((self.root / "variant/instance.json").read_bytes(), before)

    def test_arbitrary_script_or_html_raw_replacement_is_not_a_binding_mode(self):
        for mode in ("shell", "javascript", "python", "text"):
            self.html_template([{"parameter": "x", "file": "index.html", "mode": mode, "search": "Chapter I", "expected_count": 1}],
                               {"x": self.parameter("string", "Replacement")})
            with self.subTest(mode=mode), self.assertRaises(ValidationError):
                validate_library(self.library)


if __name__ == "__main__":
    unittest.main()
