"""Video-model tasks export instructions; local processing and imports remain usable."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine.production import (
    AdapterRegistry, _execution, execute_request, import_result, production_request,
)
from editorial_engine.workflows import ExecutionUnknown, PreflightBlocked, WorkflowLedger
from editorial_engine import workflows


def video_request(operation="external_video", **kwargs):
    return production_request("new-performance", operation,
                              prompt="Create the authored continuous performance; return the actual clip.",
                              output_kind="video", **kwargs)


def make_video(path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real media verification requires FFmpeg and FFprobe")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=s=32x24:r=4:d=1", "-c:v", "libx264", "-threads", "1",
                    "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
    return path


@pytest.mark.parametrize("registered", [False, True])
def test_external_video_exports_even_when_callback_and_json_override_are_supplied(tmp_path, registered):
    calls = []
    callback = lambda context: calls.append(context)
    registry = AdapterRegistry()
    if registered:
        registry.register("video-adapter", callback, operations=["external_video"],
                          output_kinds=["video"], execution_kind="local_processing")
    request = video_request(adapter_id="video-adapter" if registered else None,
                            parameters={"automatic_video_generation": True, "execution_kind": "local_processing"},
                            context={"execution_kind": "local_processing"})
    ledger = WorkflowLedger(tmp_path / "jobs.sqlite", budget_limit=3)
    output = tmp_path / "export"
    first = execute_request(request, output, registry=registry,
                            executor=None if registered else callback, ledger=ledger, estimated_cost=2)
    second = execute_request(request, output, executor=callback, ledger=ledger, retry_failed=True)
    assert first["status"] == second["status"] == "awaiting_external_generation"
    assert first["execution_policy"]["mode"] == "prompt_export_only"
    assert first["execution_policy"]["automatic_video_generation"] is False
    assert first["issues"][0]["code"] == "video_generation_prompt_only"
    assert request["prompt"] in (output / "REQUEST.md").read_text()
    assert (output / "VIDEO-GENERATION-POLICY.json").exists()
    assert not calls and not list(output.glob("attempt-*"))
    assert ledger.budget()["spent"] == ledger.budget()["reserved"] == 0


def test_returned_external_video_can_still_be_imported_and_reused(tmp_path):
    request = video_request(constraints={"frame_count": 4, "fps": "4", "duration_s": 1})
    output = tmp_path / "export"
    execute_request(request, output)
    returned = make_video(tmp_path / "returned.mp4")
    receipt = import_result(request, returned, output_dir=output,
                            provenance={"actor": "test author", "method": "Imported actual local FFmpeg fixture; no video model called", "simulated": False})
    assert receipt["technical"]["frame_count"] == 4
    assert receipt["status"] == "produced_unreviewed"
    calls = []
    resumed = execute_request(request, output, executor=lambda context: calls.append(context))
    assert resumed["status"] == "succeeded" and resumed["reused"]
    assert not calls


@pytest.mark.parametrize("operation", ["procedural", "private_raster_renderer"])
def test_authored_local_video_processing_still_executes(tmp_path, operation):
    calls = []

    def render(context):
        calls.append(context["request"]["operation"])
        result = make_video(Path(context["output_dir"]) / "render.mp4")
        return {"artifact_path": str(result), "artifact_sha256": file_sha256(result), "actual_cost": 0,
                "provenance": {"actor": "local test", "method": "Original procedural FFmpeg render", "simulated": True}}

    registry = AdapterRegistry()
    registry.register("local-render", render, operations=[operation], output_kinds=["video"],
                      simulated=True, execution_kind="local_processing")
    request = video_request(operation, adapter_id="local-render")
    result = execute_request(request, tmp_path / "render", registry=registry)
    assert result["status"] == "succeeded"
    assert result["result"]["technical"]["frame_count"] == 4
    assert calls == [operation]


def test_unknown_video_callback_cannot_claim_local_processing_through_json(tmp_path):
    calls = []
    request = video_request("renamed_operation", context={"execution_kind": "local_processing"})
    with pytest.raises(ValidationError, match="video_generation_prompt_only"):
        execute_request(request, tmp_path / "export", executor=lambda context: calls.append(context))
    assert not calls
    assert (tmp_path / "export" / "REQUEST.md").exists()


def workflow_args(tmp_path, ledger, callback, *, operation="external_video"):
    source = tmp_path / "authored-direction.txt"
    source.write_text("Original authored direction")
    return {"plan": {"operation": operation}, "source_paths": {"direction": source},
            "recipe": {"id": "fixture", "version": "1", "spatial_mode": "none",
                       "workflow": {"1": {"class_type": "ExplicitFixture", "inputs": {}}}},
            "params": {}, "availability": {"nodes": {"ExplicitFixture": True}},
            "executor": callback, "estimated_cost": 1}


@pytest.mark.parametrize("declaration", ["plan", "recipe", "request"])
def test_generic_ledger_cannot_execute_declared_video_generation(tmp_path, declaration):
    calls = []
    ledger = WorkflowLedger(tmp_path / "jobs.sqlite", budget_limit=3)
    args = workflow_args(tmp_path, ledger, lambda graph, key: calls.append(key), operation="local_processing")
    if declaration == "plan":
        args["plan"].update(operation="external_video", execution_kind="local_processing")
    elif declaration == "recipe":
        args["recipe"]["execution_kind"] = "video_generation"
    else:
        args["plan"]["request"] = video_request()
    with pytest.raises(PreflightBlocked, match="video_generation_prompt_only"):
        ledger.run(**args)
    assert not calls
    assert ledger.budget()["spent"] == ledger.budget()["reserved"] == 0


def test_historical_unknown_job_remains_unresolved_when_video_policy_changes(tmp_path):
    ledger = WorkflowLedger(tmp_path / "jobs.sqlite", budget_limit=3)
    keys = []

    def interrupted(graph, key):
        keys.append(key)
        raise RuntimeError("Historical fixture job was interrupted")

    # Simulate a pre-policy receipt without making a video/model call.
    historical = workflow_args(tmp_path, ledger, interrupted, operation="historical_fixture")
    historical["source_paths"] = {"production_request": historical["source_paths"]["direction"]}
    with pytest.raises(ExecutionUnknown):
        ledger.run(**historical)
    job = ledger.get_job(keys[0])
    request = video_request()
    output = tmp_path / "historical-export"
    output.mkdir()
    previous = _execution(request, output, "unknown", adapter={"id": "historical-video-adapter"},
                          ledger={"key": job["key"], "status": "unknown"},
                          issues=["Interrupted before this policy existed"])
    (output / "execution.json").write_text(json.dumps(previous))
    calls = []
    result = execute_request(request, output, ledger=ledger,
                             executor=lambda context: calls.append(context), retry_failed=True)
    assert result["status"] == "unknown" and result["reused"]
    assert result["ledger"]["key"] == job["key"]
    assert not calls
    assert ledger.budget()["reserved"] == 1


def test_new_export_directory_retains_historical_unknown_video_job(tmp_path, monkeypatch):
    ledger = WorkflowLedger(tmp_path / "jobs.sqlite", budget_limit=3)
    request = video_request()
    old_root = tmp_path / "old-export"
    old_root.mkdir()
    request_path = old_root / "request.json"
    request_path.write_text(json.dumps(request))
    keys = []

    def interrupted(graph, key):
        keys.append(key)
        raise RuntimeError("Simulated interruption under the historical execution policy")

    args = workflow_args(tmp_path, ledger, interrupted)
    args["plan"] = {"request": request, "adapter": {"id": "historical-video-adapter"}}
    args["source_paths"] = {"production_request": request_path}
    # Only fixture setup simulates the earlier policy. No provider is called.
    with monkeypatch.context() as old_policy:
        old_policy.setattr(workflows, "_declares_video_generation", lambda plan, recipe: False)
        with pytest.raises(ExecutionUnknown):
            ledger.run(**args)
    calls = []
    new_root = tmp_path / "new-export"
    result = execute_request(request, new_root, ledger=ledger,
                             executor=lambda context: calls.append(context), retry_failed=True)
    assert result["status"] == "unknown" and result["ledger"]["key"] == keys[0]
    assert result["adapter"]["id"] == "historical-video-adapter"
    assert json.loads((new_root / "execution.json").read_text())["ledger"]["key"] == keys[0]
    assert not calls and ledger.budget()["reserved"] == 1
    with pytest.raises(ValidationError, match="ledger"):
        execute_request(request, new_root)
