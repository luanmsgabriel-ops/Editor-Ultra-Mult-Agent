"""Execution-contract tests; binary fixtures do not assert video quality."""

import hashlib
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from editorial_engine.workflows import (
    ArtifactError, BudgetError, ExecutionUnknown, PreflightBlocked, RecipeError, WorkflowLedger,
    artifact_evidence, bind_workflow, preflight_recipe, resolve_recipe, validate_recipe,
)


def recipe():
    return {
        "id": "hand_trail", "version": "1", "spatial_mode": "3d",
        "workflow": {
            "1": {"class_type": "Render", "inputs": {
                "text": "{{text}}", "strength": 0.5, "clip": "{{clip}}"}},
            "2": {"class_type": "Save", "inputs": {"frames": ["1", 0]}},
        },
        "inputs": {
            "text": {"type": "string", "required": True},
            "clip": {"type": "video", "required": True},
            "strength": {"type": "number", "default": 0.5, "min": 0, "max": 1},
        },
        "bindings": {
            "text": [{"node": "1", "field": "text"}],
            "clip": [{"node": "1", "field": "clip"}],
            "strength": [{"node": "1", "field": "strength"}],
        },
        "requirements": {"models": ["tracker"], "capabilities": ["depth"]},
    }


def ready():
    return {"models": {"tracker": True}, "capabilities": {"depth": True},
            "nodes": {"Render": True, "Save": True}}


class RecipeTests(unittest.TestCase):
    def test_unknown_resource_and_node_readiness_are_blocked(self):
        self.assertEqual(preflight_recipe(recipe(), {})["status"], "blocked")
        availability = ready()
        availability["models"]["tracker"] = "ready"
        self.assertIn("models:tracker:unknown_or_unavailable",
                      preflight_recipe(recipe(), availability)["reasons"])
        availability = ready()
        del availability["nodes"]["Save"]
        self.assertEqual(preflight_recipe(recipe(), availability)["status"], "blocked")

    def test_declared_capability_and_model_file_are_verified(self):
        availability = ready()
        availability["capabilities"]["depth"] = False
        self.assertEqual(preflight_recipe(recipe(), availability)["status"], "blocked")
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model.bin"
            model.write_bytes(b"model")
            availability = ready()
            availability["models"]["tracker"] = {
                "status": "ready", "path": str(model),
                "sha256": hashlib.sha256(b"wrong").hexdigest()}
            self.assertEqual(preflight_recipe(recipe(), availability)["status"], "blocked")

    def test_binding_is_typed_and_does_not_mutate_recipe(self):
        original = recipe()
        graph = bind_workflow(original, {"text": "Reveal", "clip": "/source.mp4"})
        self.assertEqual(graph["1"]["inputs"]["text"], "Reveal")
        self.assertEqual(original["workflow"]["1"]["inputs"]["text"], "{{text}}")
        with self.assertRaises(RecipeError):
            bind_workflow(original, {"text": "Reveal", "clip": "/source.mp4", "strength": True})
        with self.assertRaises(RecipeError):
            bind_workflow(original, {"text": "Reveal", "clip": "/source.mp4", "strength": 2})

    def test_dangling_binding_and_workflow_link_are_rejected(self):
        broken = recipe()
        broken["bindings"]["clip"][0]["field"] = "missing"
        with self.assertRaisesRegex(RecipeError, "Dangling binding"):
            validate_recipe(broken)
        broken = recipe()
        broken["workflow"]["2"]["inputs"]["frames"] = ["absent", 0]
        with self.assertRaisesRegex(RecipeError, "Dangling workflow"):
            validate_recipe(broken)

    def test_missing_unknown_or_unfilled_input_cannot_execute(self):
        with self.assertRaisesRegex(RecipeError, "Missing required"):
            bind_workflow(recipe(), {"text": "Reveal"})
        with self.assertRaisesRegex(RecipeError, "Undeclared"):
            bind_workflow(recipe(), {"text": "Reveal", "clip": "/source.mp4", "typo": 1})
        broken = recipe()
        broken["workflow"]["2"]["inputs"]["destination"] = "{{UNRESOLVED}}"
        with self.assertRaisesRegex(RecipeError, "Unresolved placeholder"):
            bind_workflow(broken, {"text": "Reveal", "clip": "/source.mp4"})

    def test_requirement_declarations_are_validated(self):
        broken = recipe()
        broken["requirements"]["models"] = "tracker"
        with self.assertRaisesRegex(RecipeError, "models"):
            validate_recipe(broken)

    def test_fallback_cycle_is_blocked_and_path_preserved(self):
        a, b = recipe(), recipe()
        a["id"], a["fallback"] = "a", "b"
        b["id"], b["fallback"] = "b", "a"
        result = resolve_recipe("a", {"a": a, "b": b}, {})
        self.assertEqual(result["reasons"], ["fallback_cycle"])
        self.assertEqual(result["path"], ["a", "b", "a"])

    def test_fallback_never_silently_flattens_3d(self):
        a, b = recipe(), recipe()
        a["id"], a["fallback"] = "a", "b"
        a["requirements"]["models"] = ["unavailable"]
        b["id"], b["spatial_mode"] = "b", "screen"
        result = resolve_recipe("a", {"a": a, "b": b}, ready())
        self.assertEqual(result["reasons"], ["spatial_fallback_forbidden"])
        b["spatial_mode"] = "3d"
        result = resolve_recipe("a", {"a": a, "b": b}, ready())
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["recipe_id"], "b")
        self.assertEqual(result["path"], ["a", "b"])


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.bin"
        self.source.write_bytes(b"unchanged-source")
        self.ledger = WorkflowLedger(self.root / "execution.sqlite", budget_limit=10)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def arguments(self):
        return {
            "plan": {"shot": "s01", "purpose": "gesture reveal"},
            "source_paths": {"clip": self.source}, "recipe": recipe(),
            "params": {"text": "Reveal", "clip": str(self.source)},
            "availability": ready(), "estimated_cost": 1, "executor": self.render,
        }

    def render(self, graph, key):
        self.calls.append(key)
        self.assertGreaterEqual(self.ledger.budget()["reserved"], 1)
        output = self.root / f"{key}.bin"
        output.write_bytes(json.dumps(graph, sort_keys=True).encode())
        return {"artifact_path": str(output), "artifact_sha256": artifact_evidence(output)["sha256"],
                "actual_cost": 0.4}

    def test_success_requires_real_hash_and_identical_work_is_reused(self):
        first = self.ledger.run(**self.arguments())
        second = self.ledger.run(**self.arguments())
        self.assertEqual(first["status"], "succeeded")
        self.assertTrue(second["reused"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.ledger.budget()["spent"], 0.4)
        self.assertEqual(self.ledger.budget()["reserved"], 0)
        self.assertEqual(second["artifact"]["sha256"],
                         artifact_evidence(second["artifact"]["path"])["sha256"])

    def test_cache_reuse_does_not_require_gpu_available_again(self):
        first = self.ledger.run(**self.arguments())
        args = self.arguments()
        args["availability"] = {}
        result = self.ledger.run(**args)
        self.assertEqual(result["key"], first["key"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(self.calls), 1)

    def test_plan_source_recipe_and_params_all_participate_in_identity(self):
        keys = {self.ledger.run(**self.arguments())["key"]}
        for component in ("plan", "recipe", "params", "source"):
            args = self.arguments()
            if component == "plan":
                args["plan"]["purpose"] = "compare"
            elif component == "recipe":
                args["recipe"]["version"] = "2"
            elif component == "params":
                args["params"]["text"] = "Another"
            else:
                self.source.write_bytes(b"changed-source")
            keys.add(self.ledger.run(**args)["key"])
        self.assertEqual(len(keys), 5)
        self.assertEqual(len(self.calls), 5)

    def test_changed_output_invalidates_success_without_automatic_rerun(self):
        first = self.ledger.run(**self.arguments())
        Path(first["artifact"]["path"]).write_bytes(b"changed-output")
        result = self.ledger.run(**self.arguments())
        self.assertEqual(result["status"], "unknown")
        self.assertIn("SHA-256 mismatch", result["error"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.ledger.budget()["spent"], 0.4)

    def test_exit_zero_without_artifact_is_not_success(self):
        args = self.arguments()
        args["executor"] = lambda graph, key: {"exit_code": 0, "actual_cost": 0}
        result = self.ledger.run(**args)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["artifact"])
        self.assertEqual(self.ledger.budget()["reserved"], 0)

    def test_false_artifact_hash_cannot_pass(self):
        args = self.arguments()
        def incorrect(graph, key):
            outcome = self.render(graph, key)
            outcome["artifact_sha256"] = "0" * 64
            return outcome
        args["executor"] = incorrect
        result = self.ledger.run(**args)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.ledger.budget()["spent"], 0.4)

    def test_output_cannot_alias_or_modify_source(self):
        args = self.arguments()
        args["executor"] = lambda graph, key: {
            "artifact_path": str(self.source),
            "artifact_sha256": artifact_evidence(self.source)["sha256"], "actual_cost": 0}
        result = self.ledger.run(**args)
        self.assertEqual(result["status"], "failed")
        self.assertIn("separate from source", result["error"])
        args["plan"]["shot"] = "s02"
        def corrupt_source(graph, key):
            outcome = self.render(graph, key)
            self.source.write_bytes(b"unexpected-source-change")
            return outcome
        args["executor"] = corrupt_source
        result = self.ledger.run(**args)
        self.assertEqual(result["status"], "failed")
        self.assertIn("SHA-256 mismatch", result["error"])

    def test_unknown_preflight_and_estimate_block_before_callback(self):
        args = self.arguments()
        args["availability"]["capabilities"] = {}
        with self.assertRaises(PreflightBlocked):
            self.ledger.run(**args)
        args = self.arguments()
        args["estimated_cost"] = None
        with self.assertRaisesRegex(BudgetError, "Unknown cost"):
            self.ledger.run(**args)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ledger.budget()["reserved"], 0)

    def test_media_inputs_must_be_in_hashed_source_manifest(self):
        untracked = self.root / "other.bin"
        untracked.write_bytes(b"other-source")
        args = self.arguments()
        args["params"]["clip"] = str(untracked)
        with self.assertRaisesRegex(RecipeError, "Untracked media"):
            self.ledger.run(**args)
        self.assertEqual(self.calls, [])

    def test_exception_keeps_reservation_until_reconciled_then_explicit_retry(self):
        args = self.arguments()
        seen = []
        def interrupted(graph, key):
            seen.append(key)
            raise RuntimeError("worker lost")
        args["executor"] = interrupted
        with self.assertRaises(ExecutionUnknown):
            self.ledger.run(**args)
        self.assertEqual(self.ledger.budget()["reserved"], 1)
        existing = self.ledger.run(**args)
        self.assertEqual(existing["status"], "unknown")
        self.assertEqual(len(seen), 1)
        resolved = self.ledger.reconcile_job(seen[0], actual_cost=0.2)
        self.assertEqual(resolved["status"], "failed")
        self.assertEqual(self.ledger.budget()["reserved"], 0)
        self.assertEqual(self.ledger.budget()["spent"], 0.2)
        args["executor"] = self.render
        self.assertEqual(self.ledger.run(**args)["status"], "failed")
        args["retry_failed"] = True
        done = self.ledger.run(**args)
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["attempt"], 2)
        self.assertEqual(self.ledger.budget()["spent"], 0.6)

    def test_missing_actual_cost_is_unknown_and_reconciliation_is_idempotent(self):
        args = self.arguments()
        evidence = {}
        def missing_cost(graph, key):
            evidence.update(self.render(graph, key))
            evidence["key"] = key
            return {k: v for k, v in evidence.items() if k != "actual_cost"}
        args["executor"] = missing_cost
        with self.assertRaises(ExecutionUnknown):
            self.ledger.run(**args)
        self.assertEqual(self.ledger.budget()["reserved"], 1)
        for _ in range(2):
            done = self.ledger.reconcile_job(
                evidence["key"], actual_cost=0.4, artifact_path=evidence["artifact_path"],
                artifact_sha256=evidence["artifact_sha256"])
            self.assertEqual(done["status"], "succeeded")
        self.assertEqual(self.ledger.budget()["spent"], 0.4)
        self.assertEqual(self.ledger.budget()["reserved"], 0)

    def test_recovery_cannot_treat_original_source_as_render(self):
        args = self.arguments()
        seen = []
        def interrupted(graph, key):
            seen.append(key)
            raise RuntimeError("interrupted")
        args["executor"] = interrupted
        with self.assertRaises(ExecutionUnknown):
            self.ledger.run(**args)
        with self.assertRaisesRegex(ArtifactError, "separate from source"):
            self.ledger.reconcile_job(
                seen[0], actual_cost=0,
                artifact_path=self.source,
                artifact_sha256=artifact_evidence(self.source)["sha256"])
        self.assertEqual(self.ledger.budget()["reserved"], 1)

    def test_nonterminal_callback_cannot_release_reservation(self):
        args = self.arguments()
        args["executor"] = lambda graph, key: {"status": "running", "actual_cost": 0}
        with self.assertRaisesRegex(ExecutionUnknown, "terminal"):
            self.ledger.run(**args)
        self.assertEqual(self.ledger.budget()["reserved"], 1)

    def test_concurrent_identical_job_only_executes_once(self):
        started, release = threading.Event(), threading.Event()
        args = self.arguments()
        def waiting(graph, key):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test worker not released")
            return self.render(graph, key)
        args["executor"] = waiting
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.ledger.run, **args)
            try:
                self.assertTrue(started.wait(3))
                duplicate = self.ledger.run(**args)
                self.assertEqual(duplicate["status"], "running")
                self.assertTrue(duplicate["reused"])
                self.assertEqual(self.ledger.budget()["reserved"], 1)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=3)["status"], "succeeded")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.ledger.budget()["spent"], 0.4)

    def test_executor_overrun_is_recorded_and_not_marked_success(self):
        args = self.arguments()
        def overrun(graph, key):
            result = self.render(graph, key)
            result["actual_cost"] = 1.2
            return result
        args["executor"] = overrun
        result = self.ledger.run(**args)
        self.assertEqual(result["status"], "failed")
        self.assertIn("actual_cost_exceeds_reservation", result["error"])
        self.assertEqual(self.ledger.budget()["spent"], 1.2)


class BudgetConcurrencyTests(unittest.TestCase):
    def test_two_simultaneous_reservations_cannot_exceed_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.sqlite"
            ledger = WorkflowLedger(path, budget_limit=1)
            gate = threading.Barrier(2)
            def reserve(name):
                other = WorkflowLedger(path)
                gate.wait(timeout=3)
                try:
                    other.reserve_budget(name, 0.75)
                    return "reserved"
                except BudgetError:
                    return "blocked"
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(reserve, ("one", "two")))
            self.assertEqual(sorted(results), ["blocked", "reserved"])
            self.assertEqual(ledger.budget()["reserved"], 0.75)

    def test_settlement_releases_hold_and_never_double_charges(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = WorkflowLedger(Path(tmp) / "budget.sqlite", budget_limit=1)
            ledger.reserve_budget("one", 0.8)
            ledger.reserve_budget("one", 0.8)
            ledger.release_reservation("one", 0.3)
            ledger.release_reservation("one", 0.3)
            self.assertEqual(ledger.budget()["spent"], 0.3)
            self.assertEqual(ledger.budget()["reserved"], 0)
            ledger.reserve_budget("two", 0.7)
            with self.assertRaises(BudgetError):
                ledger.reserve_budget("three", 0.000001)
            with self.assertRaisesRegex(BudgetError, "another cost"):
                ledger.release_reservation("one", 0.4)


if __name__ == "__main__":
    unittest.main()
