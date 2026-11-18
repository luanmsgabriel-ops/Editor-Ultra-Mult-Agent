"""Real media, routing and per-scene QC: planning != rendering != approval."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from editorial_engine.contracts import file_sha256
from editorial_engine.scene_router import route_scenes
from editor_ultra_app.engine import EngineAdapter
from editorial_engine.motion_assets import load_layer


def make_video(path, color="testsrc2"):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    source = ("testsrc2=size=160x90:rate=10:duration=1" if color == "testsrc2"
              else "color=c=" + color + ":s=160x90:r=10:d=1")
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y",
                    "-f", "lavfi", "-i", source, "-an", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=25)


def manifest(sha):
    return {"schema": "editor-ultra-reference-scenes/1", "source_sha256": sha,
            "fps": "10/1", "frame_count": 10, "scenes": [
                {"id": "opening", "start_frame": 0, "end_frame": 5,
                 "elements": ["panel"],
                 "events": [{"id": "show-panel", "element_id": "panel", "frame": 1,
                             "action": "panel enters", "observed": True}], "unresolved": []},
                {"id": "ending", "start_frame": 5, "end_frame": 10,
                 "elements": ["panel"],
                 "events": [{"id": "end-panel", "element_id": "panel", "frame": 6,
                             "action": "panel exits", "observed": True}], "unresolved": []},
            ]}


def recipe():
    return {"schema_version": "motionlab-scene/1", "id": "scene-opening", "mode": "2d",
            "width": 160, "height": 90, "fps": "10/1", "frame_count": 5,
            "background": None, "nodes": [
                {"id": "tile", "type": "rect", "width": 28, "height": 24,
                 "fill": "#21aacc", "x": 8, "y": 30}],
            "tracks": [{"target": "tile", "property": "x",
                        "keys": [{"t": 0, "value": 8}, {"t": .4, "value": 75}]}]}


def choices(with_recipe=False):
    opening = {"scene_id": "opening", "needs": ["motion_graphic_2d"]}
    if with_recipe:
        opening["recipe"] = recipe()
    return {"schema": "editor-ultra-scene-routing/1", "scenes": [
        opening, {"scene_id": "ending", "needs": ["new_actor_performance"]}]}


def fixture_project(tmp_path):
    adapter = EngineAdapter(tmp_path / "private")
    reference = tmp_path / "reference.mp4"
    candidate = tmp_path / "candidate.mp4"
    make_video(reference)
    make_video(candidate, "blue")
    cur = adapter.save_project(None, {"objective": "Scene router and QA verification"})
    pid = cur["project_id"]
    for role, path in (("ref", reference), ("clone", candidate)):
        cur = adapter.import_local_file(pid, role, path, path.name, "video/mp4",
                                        expected_revision=cur["revision"])
    cur = adapter.register_reference_scenes(pid, manifest(file_sha256(reference)),
                                            expected_revision=cur["revision"])
    return adapter, cur, reference


def test_route_never_relabels_unavailable_generation_as_local_motion():
    value = manifest("a" * 64)
    status = {"motionlab": {"available": True, "evidence": "pixel_probe"},
              "external_generation": {"available": False, "evidence": "requires_user"}}
    plan = route_scenes(value, choices(with_recipe=True), readiness=status)
    assert plan["status"] == "planned_not_executed"
    assert plan["scenes"][0]["operations"][0]["status"] == "ready_local_production"
    assert plan["scenes"][1]["operations"][0]["status"] == "external_generation_requires_user_authorization"
    assert all(op["execution"] == "not_executed"
               for scene in plan["scenes"] for op in scene["operations"])
    with pytest.raises(ValueError, match="All reference scenes"):
        route_scenes(value, {"schema": "editor-ultra-scene-routing/1",
                             "scenes": [choices()["scenes"][0]]}, readiness=status)
    with pytest.raises(ValueError, match="Recipe"):
        bad = choices(with_recipe=True)
        bad["scenes"][0]["needs"] = ["preserve"]
        route_scenes(value, bad, readiness=status)


def test_project_routes_are_source_bound_and_qa_records_temporal_gaps(tmp_path, monkeypatch):
    import editor_ultra_app.scene_bridge as bridge
    adapter, current, reference = fixture_project(tmp_path)
    monkeypatch.setattr(bridge, "probe_capabilities", lambda requirements: {
        "motionlab": {"available": True, "evidence": "test_injected_pixel_probe"},
        "external_generation": {"available": False, "evidence": "user_action"},
    })
    pid = current["project_id"]
    routed = adapter.route_reference_scenes(pid, choices(with_recipe=True),
                                            expected_revision=current["revision"])
    assert routed["scene_route"]["current"] is True
    assert routed["scene_route"]["status"] == "planned_not_executed"
    assert routed["scene_route"]["executions"] == {}
    assert routed["scene_quality_gate"]["status"] == "pending_scene_comparison"
    plan = routed["plan"]
    assert plan["scenes"][0]["motion_recipe_sha256"]
    assert plan["scenes"][1]["operations"][0]["status"] == "external_generation_requires_user_authorization"
    audited = adapter.audit_scene_batch(pid, ["opening", "ending"],
                                        expected_revision=routed["revision"])
    gate = audited["scene_quality_gate"]
    assert gate["status"] == "technical_evidence_complete_visual_review_pending"
    assert gate["current"] and gate["missing"] == []
    assert gate["quality_is_user_approved"] is False
    batch = audited["scene_qa_batch"]
    assert len(batch["scenes"]) == 2
    assert all(row["status"] == "technical_diagnostic_visual_review_pending" for row in batch["scenes"])
    assert all(row["temporal"]["pairs"] > 0 for row in batch["scenes"])
    assert all(row["spatial_metrics"]["mae_rgb_mean"] > 0 for row in batch["scenes"])
    report = adapter.resolve_asset(pid, batch["batch_asset_id"])
    data = json.loads(report.read_text())
    assert data["reference_sha256"] == file_sha256(reference)
    assert not data["user_approved"]
    # Old QA must not certify a newly supplied candidate.
    replacement = tmp_path / "replacement.mp4"
    make_video(replacement, "red")
    changed = adapter.import_local_file(pid, "clone", replacement, replacement.name, "video/mp4",
                                        expected_revision=audited["revision"])
    assert changed["scene_quality_gate"]["status"] == "pending_scene_comparison"
    assert changed["scene_quality_gate"]["missing"] == ["opening", "ending"]
    # Route stays bound to the same reference; QA does not remain valid.
    assert changed["scene_route"]["current"] is True


def test_executable_scene_uses_real_producer_ledger_and_reuses_receipt(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    runtime = root / "editorial_engine/backends/motionlab/node_modules/@napi-rs/canvas/package.json"
    if not shutil.which("node") or not runtime.is_file():
        pytest.skip("Pinned Motion Lab dependencies are required for local render")
    import editor_ultra_app.scene_bridge as bridge
    adapter, current, _ = fixture_project(tmp_path)
    monkeypatch.setattr(bridge, "probe_capabilities", lambda required: {
        "motionlab": {"available": True, "evidence": "pinned_runtime"},
        "external_generation": {"available": False, "evidence": "external"},
    })
    pid = current["project_id"]
    routed = adapter.route_reference_scenes(pid, choices(with_recipe=True),
                                            expected_revision=current["revision"])
    produced = adapter.execute_local_scene_motion(pid, "opening",
                                                  expected_revision=routed["revision"])
    assert produced["status"] == "motion_produced_unreviewed"
    result = produced["scene_execution"]
    assert result["backend"] == "motionlab"
    assert result["integrated_into_clone"] is False
    assert result["user_approved"] is False
    manifest_path = adapter.resolve_asset(pid, result["motion_asset_id"])
    layer = load_layer(manifest_path, verify_files=True)
    assert layer["frame_count"] == 5
    assert produced["approval"]["clone"] is None
    rerun = adapter.execute_local_scene_motion(pid, "opening",
                                               expected_revision=produced["revision"])
    assert rerun["idempotent"] is True
    assert rerun["scene_execution"] == result


def test_invalid_source_or_scene_does_not_mutate_project(tmp_path, monkeypatch):
    import editor_ultra_app.scene_bridge as bridge
    adapter, current, _ = fixture_project(tmp_path)
    monkeypatch.setattr(bridge, "probe_capabilities", lambda required: {
        "motionlab": {"available": False, "evidence": "unavailable"},
        "external_generation": {"available": False, "evidence": "external"},
    })
    pid = current["project_id"]
    routed = adapter.route_reference_scenes(pid, choices(),
                                            expected_revision=current["revision"])
    with pytest.raises(Exception):
        adapter.execute_local_scene_motion(pid, "opening",
                                           expected_revision=routed["revision"])
    with pytest.raises(ValueError):
        adapter.audit_scene_batch(pid, ["ending", "opening"],
                                  expected_revision=routed["revision"])
    assert adapter.get_project(pid)["revision"] == routed["revision"]
