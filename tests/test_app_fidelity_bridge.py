"""Adapter contract tests for project-bound evidence and queued local producers."""
from pathlib import Path
import subprocess
import pytest

from editor_ultra_app.engine import EngineAdapter

def make_video(path, *, color="testsrc2"):
    source = ("testsrc2=size=160x90:rate=10:duration=1" if color == "testsrc2"
              else f"color=c={color}:s=160x90:r=10:d=1")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source,
                    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   check=True, timeout=30)

def project_with_video(tmp_path):
    engine = EngineAdapter(tmp_path / "engine")
    original, alternate = tmp_path / "original.mp4", tmp_path / "alternate.mp4"
    make_video(original)
    make_video(alternate, color="red")
    started = engine.save_project(None, {"schema": "editor-ultra-interface/1",
                                         "sourceType": "video", "objective": "QA real"})
    identifier, rev = started["project_id"], started["revision"]
    ref = engine.import_local_file(identifier, "ref", original, "original.mp4", "video/mp4",
                                   expected_revision=rev)
    clone = engine.import_local_file(identifier, "clone", original, "clone.mp4", "video/mp4",
                                     expected_revision=ref["revision"])
    return engine, identifier, original, alternate, clone["revision"]

def test_project_comparison_and_temporal_evidence_are_independently_unapproved(tmp_path):
    engine, project_id, source, alternate, rev = project_with_video(tmp_path)
    comparison = engine.compare_clone(project_id, expected_revision=rev)
    assert comparison["comparison"]["diagnostics"]["mae_rgb_mean"] == 0
    assert comparison["comparison"]["metrics_are_not_a_fidelity_grade"] is True
    assert comparison["quality_evidence"][-1]["current"] is True
    cadence = engine.compare_temporal(project_id, center_s=.5, expected_revision=comparison["revision"])
    assert cadence["temporal_comparison"]["metrics"]["mean_change_gap"] == 0
    assert cadence["temporal_evidence"][-1]["current"] is True
    assert cadence["approval"]["clone"] is None
    changed = engine.import_local_file(project_id, "clone", alternate, "different.mp4", "video/mp4",
                                       expected_revision=cadence["revision"])
    assert changed["quality_evidence"][-1]["current"] is False
    assert changed["temporal_evidence"][-1]["current"] is False

def test_queue_authored_local_motion_without_claiming_render(tmp_path):
    engine, project_id, source, alternate, rev = project_with_video(tmp_path)
    scene = {"schema_version": "motionlab-scene/1", "id": "motion-proof-test",
             "mode": "2d", "width": 160, "height": 90, "fps": "10/1",
             "frame_count": 10, "background": None,
             "nodes": [{"id": "tile", "type": "rect", "width": 40, "height": 30,
                        "fill": "#00FFFF", "x": 40, "y": 30}],
             "tracks": [{"target": "tile", "property": "x",
                         "keys": [{"t": 0, "value": 10}, {"t": .9, "value": 90}]}]}
    queued = engine.queue_bundled_motion(project_id, scene, expected_revision=rev)
    assert queued["engine"]["motion"]["status"] == "queued_local_motion_unreviewed"
    assert queued["approval"]["clone"] is None
    assert queued["status"] == "queued_local_motion_unreviewed"
    # It is queued only, not rendered or perceptually verified.
    assert "result_asset" not in queued
    oversized = dict(scene, frame_count=200)
    with pytest.raises(Exception):
        engine.queue_bundled_motion(project_id, oversized, expected_revision=queued["revision"])


def test_bundled_motion_pipeline_exports_real_unapproved_alpha_sequence(tmp_path):
    """Requires pinned Motion Lab Node runtime installed by CI, not a mocked adapter."""
    from editorial_engine.motion_assets import load_layer
    engine, project_id, _, _, rev = project_with_video(tmp_path)
    recipe = {"schema_version": "motionlab-scene/1", "id": "proof-live",
              "mode": "2d", "width": 160, "height": 90, "fps": "10/1",
              "frame_count": 10, "background": None,
              "nodes": [{"id": "tile", "type": "rect", "width": 20, "height": 20,
                         "x": 10, "y": 40, "fill": "#AA55DD"}],
              "tracks": [{"target": "tile", "property": "x",
                          "keys": [{"t": 0, "value": 10}, {"t": .9, "value": 80}]}]}
    queued = engine.queue_bundled_motion(project_id, recipe, expected_revision=rev)
    produced = engine.execute_bundled_motion(project_id, expected_revision=queued["revision"])
    assert produced["status"] == "motion_produced_unreviewed"
    asset = produced["result_asset"]
    assert asset is not None and asset["available"] is True
    manifest = load_layer(engine.resolve_asset(project_id, asset["id"]), verify_files=True)
    assert manifest["frame_count"] == 10 and manifest["fps"] == "10/1"
    assert produced["approval"]["clone"] is None
