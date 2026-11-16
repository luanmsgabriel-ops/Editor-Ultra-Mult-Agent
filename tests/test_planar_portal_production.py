"""A real portal render must traverse production, with every nested input bound."""
import copy
import json
from pathlib import Path
import shutil

from PIL import Image
import pytest

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine.production import execute_request, production_request, validate_result
from visual_fidelity.planar_portal import sequence_sha256


pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg is required")


def portal_request(tmp_path, *, omit_insert=False, sequence=False, adapter=None):
    base = tmp_path / "base.png"
    insert = tmp_path / "insert.png"
    Image.new("RGB", (64, 48), (20, 30, 60)).save(base)
    Image.new("RGB", (32, 24), (240, 90, 30)).save(insert)
    def source(path):
        return {"kind": "image", "path": path.name, "sha256": file_sha256(path),
                "origin": "Independent synthetic asset for a real local render", "static": True}
    quad = [[.1, .25], [.9, .1], [.9, .75], [.1, .9]]
    manifest = {"schema": "planar-portal/1", "width": 64, "height": 48, "frames": 2,
                "fps": "4/1", "base": source(base), "insert": source(insert),
                "mapping": "screen_reveal", "placement": [0, 0, 1, 1],
                "geometry": {"keyframes": [{"frame": frame, "quad": quad, "opacity": 1, "easing": "linear"}
                                             for frame in range(2)]}}
    inputs = [{"id": "base", "kind": "image", "path": str(base), "sha256": file_sha256(base)}]
    if not omit_insert:
        inputs.append({"id": "insert", "kind": "image", "path": str(insert), "sha256": file_sha256(insert)})
    if sequence:
        other = tmp_path / "insert-second.png"
        Image.new("RGB", (32, 24), (30, 90, 240)).save(other)
        files = [{"path": path.name, "sha256": file_sha256(path)} for path in (insert, other)]
        manifest["insert"] = {"kind": "sequence", "files": files, "sha256": sequence_sha256(files),
                              "fps": "4/1", "clock": {"start_frame": 0, "step": 1},
                              "origin": "Two separately authored source frames"}
        # The second frame is deliberately not tracked in the production request.
    path = tmp_path / "portal.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    inputs.append({"id": "portal-manifest", "kind": "json", "path": str(path), "sha256": file_sha256(path)})
    return production_request("portal-test", "planar_portal", prompt="Render the authored reveal from independent sources.",
        output_kind="video", adapter_id=adapter, inputs=inputs, parameters={"manifest_input": "portal-manifest"},
        constraints={"width": 64, "height": 48, "fps": "4/1", "frame_count": 2, "alpha": "opaque"})


@pytest.mark.parametrize("adapter", [None, "bundled.planar_portal"])
def test_native_production_runs_actual_portal_and_resumes_without_duplicate(tmp_path, adapter):
    request = portal_request(tmp_path, adapter=adapter)
    execution = execute_request(request, tmp_path / "run")
    assert execution["status"] == "succeeded", execution["issues"]
    assert execution["adapter"]["id"] == "bundled.planar_portal"
    assert execution["actual_cost"] == 0
    result = validate_result(execution["result"], request)
    assert result["status"] == "produced_unreviewed"
    assert result["provenance"]["simulated"] is False
    assert result["verification"]["continuous_motion"] == "unverified"
    assert result["technical"]["frame_count"] == 2
    receipt_path = Path(result["provenance"]["producer_receipt"]["path"])
    receipt = json.loads(receipt_path.read_text())
    assert receipt["mapping"] == "screen_reveal"
    assert receipt["audio"] == "not_rendered"
    assert receipt["sources"]["base"]["sha256"] != receipt["sources"]["insert"]["sha256"]
    assert receipt["encoded_verification"]["frames"] == 2
    resumed = execute_request(request, tmp_path / "run")
    assert resumed["status"] == "succeeded"
    assert resumed["reused"] is True
    assert len(list((tmp_path / "run").glob("attempt-*"))) == 1
    receipt_path.write_text(receipt_path.read_text() + "\n")
    with pytest.raises(ValidationError):
        validate_result(result, request)


@pytest.mark.parametrize("kwargs", [{"omit_insert": True}, {"sequence": True}])
def test_hidden_nested_media_are_blocked_before_render(tmp_path, kwargs):
    request = portal_request(tmp_path, **kwargs)
    execution = execute_request(request, tmp_path / "run")
    assert execution["status"] == "failed"
    assert execution["actual_cost"] == 0
    assert "hashed request input" in " ".join(execution["issues"])
    assert not list((tmp_path / "run").rglob("*.mp4"))


def test_native_implementation_change_invalidates_successful_resume(tmp_path, monkeypatch):
    request = portal_request(tmp_path)
    execution = execute_request(request, tmp_path / "run")
    assert execution["status"] == "succeeded", execution["issues"]
    from editorial_engine import production
    original = production._file
    def changed(path, expected=None):
        evidence = original(path, expected)
        if Path(path).name == "planar_portal.py":
            evidence = {**copy.deepcopy(evidence), "sha256": "0" * 64}
        return evidence
    monkeypatch.setattr(production, "_file", changed)
    with pytest.raises(ValidationError, match="Portal implementation changed"):
        execute_request(request, tmp_path / "run")
    assert Path(execution["result"]["artifact"]["path"]).is_file()


def test_custom_unregistered_adapter_does_not_run_builtin_implicitly(tmp_path):
    request = portal_request(tmp_path, adapter="unregistered.portal")
    execution = execute_request(request, tmp_path / "run")
    assert execution["status"] == "awaiting_adapter"
    assert not list((tmp_path / "run").rglob("*.mp4"))


@pytest.mark.parametrize("defect", ["fps", "sequence_fps", "geometry", "null_key"])
def test_malformed_portal_has_known_failed_status_and_zero_cost(tmp_path, defect):
    request = portal_request(tmp_path)
    manifest_path = tmp_path / "portal.json"
    manifest = json.loads(manifest_path.read_bytes())
    if defect == "fps":
        manifest["fps"] = "1/0"
    elif defect == "geometry":
        manifest["geometry"] = []
    elif defect == "null_key":
        manifest["geometry"]["keyframes"] = [None]
    else:
        other = tmp_path / "insert-next.png"
        Image.new("RGB", (32, 24), (30, 90, 240)).save(other)
        files = [{"path": path.name, "sha256": file_sha256(path)}
                 for path in (tmp_path / "insert.png", other)]
        manifest["insert"] = {"kind": "sequence", "files": files, "sha256": sequence_sha256(files),
            "fps": "1/0", "clock": {"start_frame": 0, "step": 1}, "origin": "Malformed clock fixture"}
        request["inputs"].append({"id": "next-frame", "kind": "image", "path": str(other), "sha256": file_sha256(other)})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    for item in request["inputs"]:
        if item["id"] == "portal-manifest":
            item["sha256"] = file_sha256(manifest_path)
    request = production_request(request["id"], request["operation"], prompt=request["prompt"],
        output_kind=request["output_kind"], inputs=request["inputs"], parameters=request["parameters"],
        constraints=request["constraints"])
    execution = execute_request(request, tmp_path / "run")
    assert execution["status"] == "failed", execution
    assert execution["actual_cost"] == 0
    assert "local_adapter_failed:" in " ".join(execution["issues"])
    assert not list((tmp_path / "run").rglob("*.mp4"))
