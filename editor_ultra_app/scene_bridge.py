"""Project-owned bridge for scene routing, source-clock QA and real motion receipts.

Only trusted project media paths and validated reference-scene inventories reach
the engines. Every operation is scoped to a project revision and source hash.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import uuid

from editorial_engine.contracts import ValidationError, clone, digest, file_sha256, require
from editorial_engine.scene_router import (
    probe_capabilities, route_scenes, validate_choices, validate_local_recipe,
)
from editorial_engine.scene_quality import audit_scenes, validate_selection, MAX_SCENES

_SCENE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")


class SceneBridgeMixin:
    def _scene_inventory(self, record):
        from visual_fidelity.reference_fidelity import _clock
        from visual_fidelity.reference_scene import validate_reference_scenes
        pid = record["project_id"]
        refs = [a for a in self._selected(record, "ref") if a["type"].startswith("video/")]
        require(len(refs) == 1, "scene_reference",
                "A verified single video reference is required")
        ref = refs[0]
        index = record.get("reference_scene_inventory")
        require(index and index.get("source_sha256") == ref["sha256"],
                "scene_inventory_stale", "Register the current full-clock scene inventory first")
        asset_id = index["asset_id"]
        path = self.resolve_asset(pid, asset_id)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        source_path = self.resolve_asset(pid, ref["id"])
        clock = _clock(source_path)
        validate_reference_scenes(manifest, source_sha256=ref["sha256"],
                                  fps=clock["fps"], frame_count=clock["frame_count"])
        return manifest, ref, source_path

    def _scene_route_public(self, record):
        route = record.get("scene_route")
        if not route:
            return {"status": "not_planned", "current": False}
        current = False
        inventory = record.get("reference_scene_inventory")
        try:
            ref = [a for a in self._selected(record, "ref") if a["type"].startswith("video/")]
            current = len(ref) == 1 and ref[0]["sha256"] == route["source_sha256"] and bool(
                inventory and inventory.get("source_sha256") == route["source_sha256"]
                and inventory.get("asset_id") == route["inventory_asset_id"])
        except (KeyError, TypeError):
            current = False
        return {
            "status": route["status"] if current else "stale",
            "current": current, "plan_asset_id": route["plan_asset_id"],
            "scene_ids": route["scene_ids"],
            "executions": clone(route.get("executions", {})),
            "user_approved": False,
        }

    def _scene_quality_gate(self, record):
        """No score/green light: complete technical evidence only unlocks human review."""
        inventory = record.get("reference_scene_inventory")
        if not inventory:
            return {"status": "needs_scene_inventory", "current": False,
                    "covered": [], "missing": []}
        try:
            manifest, ref, _ = self._scene_inventory(record)
        except (ValidationError, ValueError, OSError, KeyError):
            return {"status": "scene_inventory_stale", "current": False,
                    "covered": [], "missing": []}
        copies = [a for a in self._selected(record, "clone") if a["type"].startswith("video/")]
        if len(copies) != 1:
            return {"status": "needs_clone_video", "current": False,
                    "covered": [], "missing": [s["id"] for s in manifest["scenes"]]}
        candidate = copies[0]
        manifest_hash = digest(manifest)
        covered = set()
        for batch in record.get("scene_qa_batches", []):
            if not (batch["reference_sha256"] == ref["sha256"]
                    and batch["candidate_sha256"] == candidate["sha256"]
                    and batch["scene_manifest_sha256"] == manifest_hash):
                continue
            # Evidence must still exist with exactly the recorded bytes, not
            # merely a matching metadata hash in a mutable record.
            ids = [batch["batch_asset_id"], *(
                artifact_id for scene in batch["scenes"]
                for artifact_id in (scene["spatial_asset_id"], scene["contact_asset_id"]))]
            if batch.get("temporal_asset_id"):
                ids.append(batch["temporal_asset_id"])
            try:
                for identifier in ids:
                    self.resolve_asset(record["project_id"], identifier)
            except (ValidationError, ValueError, OSError, KeyError):
                continue
            covered.update(batch["scene_ids"])
        required = [scene["id"] for scene in manifest["scenes"]]
        missing = [identifier for identifier in required if identifier not in covered]
        return {
            "status": "technical_evidence_complete_visual_review_pending" if not missing
                      else "pending_scene_comparison",
            "current": not missing, "covered": sorted(covered),
            "missing": missing, "total_scenes": len(required),
            "quality_is_user_approved": False,
        }

    def route_reference_scenes(self, project_id, choices, *, expected_revision=None):
        require(isinstance(choices, dict) and len(json.dumps(choices, allow_nan=False)) <= 1024 * 1024,
                "scene_choices_size", "Scene routing document is too large")
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            manifest, source, _ = self._scene_inventory(record)
            directives = validate_choices(manifest, choices)
            needs = {need for row in directives.values() for need in row["needs"]}
            availability = probe_capabilities(needs)
            plan = route_scenes(manifest, choices, readiness=availability)
            folder = self._directory(project_id) / "scene-routes" / uuid.uuid4().hex
            folder.mkdir(parents=True, exist_ok=False, mode=0o700)
            try:
                path = folder / "route-plan.json"
                path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                encoding="utf-8")
                item = self._register_internal(record, path, role="evidence")
                record["scene_route"] = {
                    "status": "planned_not_executed", "plan_asset_id": item["id"],
                    "source_sha256": source["sha256"],
                    "inventory_asset_id": record["reference_scene_inventory"]["asset_id"],
                    "scene_ids": [x["scene_id"] for x in plan["scenes"]],
                    "executions": {}, "folder": str(folder)}
                self._write(record, "Roteamento por cena com disponibilidade comprovada; sem execução")
            except BaseException:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            return {**self._snapshot(record), "status": "scene_routes_planned",
                    "plan": plan, "plan_asset": self._public_file(item)}

    def execute_local_scene_motion(self, project_id, scene_id, *, expected_revision=None):
        """Execute a single authored Motion Lab 2D step through existing production ledger."""
        from editorial_engine.production import production_request, execute_request
        from editorial_engine.workflows import WorkflowLedger
        require(isinstance(scene_id, str) and _SCENE_ID.fullmatch(scene_id),
                "scene_id", "Use the declared scene ID")
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            route = record.get("scene_route")
            require(route and self._scene_route_public(record)["current"],
                    "scene_route_stale", "Plan the current reference scenes before execution")
            manifest, source, _ = self._scene_inventory(record)
            plan_path = self.resolve_asset(project_id, route["plan_asset_id"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            require(plan["source_sha256"] == source["sha256"]
                    and plan["scene_manifest_sha256"] == digest(manifest),
                    "scene_route_stale", "Scene plan is not bound to this reference inventory")
            selected = next((x for x in plan["scenes"] if x["scene_id"] == scene_id), None)
            require(selected is not None, "scene_id", "Scene is not in the current plan")
            op = next((o for o in selected["operations"] if o["need"] == "motion_graphic_2d"), None)
            require(op is not None and op["status"] == "ready_local_production"
                    and op["backend"] == "motionlab",
                    "scene_not_executable", "Only a ready authored 2D Motion Lab step can run")
            authored = next(row for row in manifest["scenes"] if row["id"] == scene_id)
            require(digest(selected["motion_recipe"]) == selected["motion_recipe_sha256"],
                    "scene_recipe_changed", "The authored scene recipe changed")
            recipe = validate_local_recipe(selected["motion_recipe"], authored, manifest["fps"])
            previous = route.get("executions", {}).get(scene_id)
            if previous:
                self.resolve_asset(project_id, previous["motion_asset_id"])
                return {**self._snapshot(record), "status": "motion_produced_unreviewed",
                        "scene_execution": clone(previous), "idempotent": True}
            work = Path(route["folder"]) / ("scene-" + scene_id)
            work.mkdir(parents=True, exist_ok=True)
            request = production_request(
                "scene-" + scene_id + "-" + selected["motion_recipe_sha256"][:12],
                "motion_recipe", prompt="Render an explicitly authored transparent 2D scene component",
                output_kind="motion_layer", adapter_id="bundled.motion",
                parameters={"backend": "motionlab", "recipe": recipe,
                            "asset_id": "scene-" + scene_id,
                            "description": "Authored local alpha component, not an approved clone"},
                context={"scene_id": scene_id, "source_sha256": source["sha256"],
                         "scene_manifest_sha256": digest(manifest),
                         "reference_pixels_used": False})
            ledger = WorkflowLedger(work / "local-production.sqlite3",
                                    budget_limit=0, unit="credits")
            receipt = execute_request(request, work / "production",
                                      ledger=ledger, estimated_cost=0)
            if receipt["status"] != "succeeded":
                return {**self._snapshot(record), "status": "scene_execution_" + receipt["status"],
                        "execution": self._portable(record, receipt)}
            result = receipt["result"]
            require(result and result["status"] == "produced_unreviewed"
                    and result["kind"] == "motion_layer"
                    and result["provenance"].get("simulated") is False,
                    "scene_motion_receipt", "Local producer did not deliver a real verified alpha asset")
            path = Path(result["artifact"]["path"])
            require(path.resolve().is_relative_to(work.resolve()), "scene_motion_path",
                    "Producer artifact escaped the scene execution directory")
            item = self._register_internal(record, path, role="evidence")
            execution = {
                "scene_id": scene_id, "backend": "motionlab",
                "status": "motion_produced_unreviewed",
                "motion_asset_id": item["id"],
                "motion_sha256": result["artifact"]["sha256"],
                "request_sha256": request["request_sha256"],
                "execution_sha256": receipt["execution_sha256"],
                "user_approved": False, "integrated_into_clone": False,
            }
            route.setdefault("executions", {})[scene_id] = execution
            route["status"] = "local_components_produced_unreviewed"
            self._write(record, "Motion Lab por cena executado e verificado; não composto no clone")
            return {**self._snapshot(record), "status": "motion_produced_unreviewed",
                    "scene_execution": clone(execution), "motion_asset": self._public_file(item)}

    def _audit_scene_batch_internal(self, record, scene_ids):
        manifest, reference, ref_path = self._scene_inventory(record)
        scenes = validate_selection(manifest, scene_ids)
        candidates = [a for a in self._selected(record, "clone") if a["type"].startswith("video/")]
        require(len(candidates) == 1, "scene_clone_video",
                "A real current clone video is required for scene QA")
        candidate = candidates[0]
        # The just-rendered clone is registered in memory before the atomic
        # project write. Resolve it from this locked record, not from a stale
        # on-disk snapshot, while still enforcing the private root and SHA.
        path = Path(candidate["path"])
        private_root = self._directory(record["project_id"]).resolve()
        require(path.is_file() and not path.is_symlink()
                and path.resolve().is_relative_to(private_root)
                and file_sha256(path) == candidate["sha256"],
                "scene_clone_changed", "Clone pixels differ from its newly registered asset")
        folder = self._directory(record["project_id"]) / "scene-quality" / uuid.uuid4().hex
        report = audit_scenes(ref_path, path, manifest, scene_ids, folder)
        try:
            batch = self._register_internal(record, folder / "batch.json", role="evidence")
            per_scene = []
            for entry in report["scenes"]:
                spatial = self._register_internal(record, Path(entry["comparison_report"]["path"]),
                                                  role="evidence")
                contact = self._register_internal(record, Path(entry["contact_sheet"]["path"]),
                                                  role="evidence")
                per_scene.append({"scene_id": entry["scene_id"], "spatial_asset_id": spatial["id"],
                                  "contact_asset_id": contact["id"], "temporal": entry["temporal"],
                                  "spatial_metrics": entry["spatial_metrics"],
                                  "status": "technical_diagnostic_visual_review_pending"})
            temporal = (self._register_internal(record, Path(report["temporal_report"]["path"]),
                                                role="evidence")
                        if report.get("temporal_report") else None)
            receipt = {
                "id": uuid.uuid4().hex, "reference_sha256": reference["sha256"],
                "candidate_sha256": candidate["sha256"],
                "scene_manifest_sha256": digest(manifest),
                "scene_ids": [entry["scene_id"] for entry in per_scene],
                "batch_asset_id": batch["id"],
                "temporal_asset_id": temporal["id"] if temporal else None,
                "scenes": per_scene, "status": "diagnosed_not_approved",
                "user_approved": False}
            record.setdefault("scene_qa_batches", []).append(receipt)
            return receipt
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def audit_scene_batch(self, project_id, scene_ids, *, expected_revision=None):
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            receipt = self._audit_scene_batch_internal(record, scene_ids)
            self._write(record, "Comparação automática por cena registrada; exige revisão visual")
            return {**self._snapshot(record), "status": "scene_qa_diagnostic_only",
                    "scene_qa_batch": clone(receipt)}
