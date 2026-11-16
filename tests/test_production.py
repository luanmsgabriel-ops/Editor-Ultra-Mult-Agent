"""Production verifies real files and boundaries, never a provider's promises."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import wave

from PIL import Image
import pytest

from editorial_engine.contracts import ValidationError, digest, file_sha256
from editorial_engine.motion_assets import write_layer_manifest
from editorial_engine.production import (AdapterRegistry, execute_request, import_result,
    production_request, queue_status, validate_request, validate_result)
from editorial_engine.workflows import WorkflowLedger
from visual_fidelity.reference_bundle import inventory


ORIGIN = {"actor": "local-test-author", "method": "Original local fixture; no external provider called", "simulated": True}


def png(path, color=(230, 60, 40, 255)):
    image = Image.new("RGBA", (24, 16), (0, 0, 0, 0))
    image.paste(color, (3, 4, 13, 12))
    image.save(path)
    return path


def request(**kwargs):
    return production_request("illustration", "chat_image", prompt="Author an original transparent visual asset.",
                              output_kind="image", **kwargs)


def result_of(context, *, cost=0, origin=None):
    path = png(Path(context["output_dir"]) / "render.png")
    return {"artifact_path": str(path), "artifact_sha256": file_sha256(path), "actual_cost": cost,
            "provenance": copy.deepcopy(origin or ORIGIN)}


def test_manual_export_resumes_without_provider_then_imports_actual_png(tmp_path):
    needed = request(constraints={"width": 24, "height": 16, "require_transparency": True})
    export = tmp_path / "export"
    first = execute_request(needed, export)
    second = execute_request(needed, export)
    assert first["status"] == second["status"] == "awaiting_external"
    assert second["reused"] and second["result"] is None
    assert needed["prompt"] in (export / "REQUEST.md").read_text()
    assert not list(export.glob("attempt-*"))
    image = png(tmp_path / "user-supplied.png")
    origin = {**ORIGIN, "simulated": False, "method": "Imported an actual local author-supplied PNG"}
    received = import_result(needed, image, provenance=origin, output_dir=export, expected_sha256=file_sha256(image))
    assert received["status"] == "produced_unreviewed"
    assert received["artifact"]["path"] == str(image)
    assert received["technical"]["alpha_extrema"] == [0, 255]
    assert received["verification"]["user_approval"] == "pending"
    assert not received["verification"]["audio_listened"]
    assert import_result(needed, image, provenance=origin, output_dir=export) == received
    assert execute_request(needed, export)["status"] == "succeeded"
    assert queue_status([needed], [received])["needs"][0]["status"] == "produced_unreviewed"


def test_corrupt_type_wrong_hash_changed_result_and_revised_request_are_rejected(tmp_path):
    needed = request()
    bad = tmp_path / "fake.png"
    bad.write_bytes(b"a filename and hash are not a decodable image")
    with pytest.raises(ValidationError, match="decoded"):
        import_result(needed, bad, provenance=ORIGIN)
    image = png(tmp_path / "real.png")
    with pytest.raises(ValidationError, match="SHA-256"):
        import_result(needed, image, provenance=ORIGIN, expected_sha256="0" * 64)
    received = import_result(needed, image, provenance=ORIGIN)
    revised = request(revision=2, context={"plan_sha256": "1" * 64})
    with pytest.raises(ValidationError, match="current request"):
        validate_result(received, revised)
    png(image, (1, 2, 3, 255))
    with pytest.raises(ValidationError):
        validate_result(received, needed)


def test_unknown_json_adapter_never_executes_imports_commands_or_spends(tmp_path):
    marker = tmp_path / "would-be-executed"
    needed = request(adapter_id="os.system", parameters={"command": "touch " + str(marker)})
    ledger = WorkflowLedger(tmp_path / "ledger.db", budget_limit=1)
    exported = execute_request(needed, tmp_path / "export", ledger=ledger)
    assert exported["status"] == "awaiting_adapter"
    assert ledger.budget()["spent"] == ledger.budget()["reserved"] == 0
    assert not marker.exists()


def test_unresolved_authoring_is_exported_as_blocked_and_typed_fields_are_not_coerced(tmp_path):
    needed = production_request("diagram", "procedural", prompt="Choose the diagram's factual content first.",
                                output_kind="image", unresolved=["Missing the approved diagram content"])
    calls = []
    executed = execute_request(needed, tmp_path / "export", executor=lambda context: calls.append(context))
    assert executed["status"] == "blocked" and not calls
    assert (tmp_path / "export/request.json").exists()
    with pytest.raises(ValidationError):
        request(parameters=[])
    tampered = copy.deepcopy(needed)
    tampered["prompt"] = "Changed after sealing"
    with pytest.raises(ValidationError, match="sealed"):
        validate_request(tampered)


def test_registered_local_callback_produces_real_png_once_and_labels_simulation(tmp_path):
    calls = []

    def local(context):
        calls.append(context["job_key"])
        return result_of(context)

    registry = AdapterRegistry()
    registry.register("fixture-image", local, operations=["chat_image"], output_kinds=["image"], simulated=True)
    needed = request(adapter_id="fixture-image")
    first = execute_request(needed, tmp_path / "work", registry=registry)
    second = execute_request(needed, tmp_path / "work", registry=registry)
    assert first["status"] == second["status"] == "succeeded"
    assert len(calls) == 1 and second["reused"]
    assert first["result"]["status"] == "simulated_result"
    assert Path(first["result"]["artifact"]["path"]).is_file()
    assert first["result"]["verification"]["semantics"] == "unverified"
    assert registry.describe()[0]["callback_code_sha256"]


def test_simulated_adapter_cannot_hide_simulation_or_return_an_existing_input(tmp_path):
    registry = AdapterRegistry()
    registry.register("fixture-image", lambda context: result_of(context, origin={**ORIGIN, "simulated": False}),
                      operations=["chat_image"], output_kinds=["image"], simulated=True)
    result = execute_request(request(adapter_id="fixture-image"), tmp_path / "work", registry=registry)
    assert result["status"] == "failed" and result["result"] is None
    reference = png(tmp_path / "reference.png")
    needed = request(inputs=[{"id": "reference", "kind": "image", "path": str(reference), "sha256": file_sha256(reference)}])
    with pytest.raises(ValidationError, match="separate"):
        import_result(needed, reference, provenance=ORIGIN)


def test_callback_cannot_mutate_source_then_claim_a_valid_result(tmp_path):
    reference = png(tmp_path / "reference.png")
    needed = request(inputs=[{"id": "reference", "kind": "image", "path": str(reference), "sha256": file_sha256(reference)}])

    def local(context):
        png(reference, (1, 7, 11, 255))
        return result_of(context)

    result = execute_request(needed, tmp_path / "work", executor=local)
    assert result["status"] == "failed" and result["result"] is None


def test_ledger_reserves_reuses_across_output_locations_and_detects_nested_change(tmp_path):
    calls = []

    def local(context):
        calls.append(context["job_key"])
        return result_of(context, cost=1.25)

    needed = request()
    ledger = WorkflowLedger(tmp_path / "ledger.db", budget_limit=3)
    first = execute_request(needed, tmp_path / "work", executor=local, ledger=ledger, estimated_cost=1.5)
    second = execute_request(needed, tmp_path / "resumed", executor=local, ledger=ledger, estimated_cost=1.5)
    assert first["status"] == second["status"] == "succeeded" and len(calls) == 1
    assert first["ledger"]["key"] == second["ledger"]["key"]
    assert second["reused"] and ledger.budget()["spent"] == 1.25
    assert ledger.budget()["reserved"] == 0
    png(Path(first["result"]["artifact"]["path"]), (20, 30, 40, 255))
    with pytest.raises(ValidationError):
        execute_request(needed, tmp_path / "work", executor=local, ledger=ledger, estimated_cost=1.5)
    assert len(calls) == 1


def test_ledger_unknown_keeps_reservation_and_does_not_retry(tmp_path):
    calls = []

    def external(context):
        calls.append(context["job_key"])
        return {"status": "submitted", "provider_job_id": "simulated-job-17", "actual_cost": None}

    needed = request()
    ledger = WorkflowLedger(tmp_path / "ledger.db", budget_limit=2)
    first = execute_request(needed, tmp_path / "work", executor=external, ledger=ledger, estimated_cost=1)
    second = execute_request(needed, tmp_path / "work", executor=external, ledger=ledger,
                             estimated_cost=1, retry_failed=True)
    assert first["status"] == second["status"] == "unknown" and len(calls) == 1
    assert ledger.budget()["reserved"] == 1 and ledger.budget()["spent"] == 0
    report = json.loads(Path(first["executor_report"]["path"]).read_text())
    assert report["provider_job_id"] == "simulated-job-17"
    assert second["executor_report"] == first["executor_report"]
    assert second["result"] is None
    def replacement(context):
        raise AssertionError("Changing the configured callback cannot bypass the unresolved job")
    assert execute_request(needed, tmp_path / "work", executor=replacement, ledger=ledger,
                           estimated_cost=1, retry_failed=True)["status"] == "unknown"
    with pytest.raises(ValidationError, match="ledger"):
        execute_request(needed, tmp_path / "work", executor=external)


def test_independent_reconciliation_recovers_result_without_calling_provider_again(tmp_path):
    needed = request()
    ledger = WorkflowLedger(tmp_path / "ledger.db", budget_limit=2)
    pending = execute_request(needed, tmp_path / "work", ledger=ledger, estimated_cost=1,
        executor=lambda context: {"status": "submitted", "provider_job_id": "simulated-recovery-1"})
    assert pending["status"] == "unknown"
    image = png(tmp_path / "returned-later.png")
    received = import_result(needed, image, provenance=ORIGIN, output_dir=tmp_path / "recovered")
    receipt = tmp_path / "recovered/result.json"
    ledger.reconcile_job(pending["ledger"]["key"], actual_cost=.25,
                         artifact_path=receipt, artifact_sha256=file_sha256(receipt))
    recovered = execute_request(needed, tmp_path / "work", ledger=ledger)
    assert recovered["status"] == "succeeded" and recovered["reused"]
    assert recovered["result"] == received
    assert ledger.budget()["reserved"] == 0 and ledger.budget()["spent"] == .25
    assert len(list((tmp_path / "work").glob("attempt-*"))) == 1


def test_known_cost_of_invalid_artifact_is_settled_and_failed_job_is_not_repeated(tmp_path):
    calls = []

    def bad(context):
        calls.append(1)
        path = Path(context["output_dir"]) / "not-image.png"
        path.write_bytes(b"invalid media")
        return {"artifact_path": str(path), "artifact_sha256": file_sha256(path), "actual_cost": .5, "provenance": ORIGIN}

    needed = request()
    ledger = WorkflowLedger(tmp_path / "ledger.db", budget_limit=2)
    first = execute_request(needed, tmp_path / "work", executor=bad, ledger=ledger, estimated_cost=1)
    second = execute_request(needed, tmp_path / "work", executor=bad, ledger=ledger, estimated_cost=1)
    assert first["status"] == second["status"] == "failed" and len(calls) == 1
    assert ledger.budget()["spent"] == .5 and ledger.budget()["reserved"] == 0


def test_unknown_without_ledger_preserves_export_history_and_is_not_reexecuted(tmp_path):
    needed = request()
    execute_request(needed, tmp_path / "work")
    calls = []

    def external(context):
        calls.append(1)
        raise RuntimeError("Simulated lost connection after submission")

    first = execute_request(needed, tmp_path / "work", executor=external)
    second = execute_request(needed, tmp_path / "work", executor=external, retry_failed=True)
    assert first["status"] == second["status"] == "unknown" and len(calls) == 1
    assert json.loads((tmp_path / "work/execution.json").read_text())["status"] == "awaiting_external"
    assert (tmp_path / "work/latest.json").exists()


def template_library(tmp_path):
    package = tmp_path / "library/package"
    package.mkdir(parents=True)
    (package / "project.json").write_text(json.dumps({"title": "Original", "frames": 2}))
    (package / "preview.md").write_text("Original preview, not proof that a variant was rendered.")
    marker = tmp_path / "package-script-ran"
    (package / "bootstrap.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    template = {"schema": "motion-template/1", "id": "authored", "version": "1",
        "package_id": "local", "title": "Authored original fixture", "description": "Two-frame local authoring test.",
        "functions": ["explain"], "entrypoint": "project.json",
        "runtime": {"name": "explicit-local-test-renderer", "requirements": ["A registered Python callback"]},
        "parameters": {"title": {"type": "string", "required": True, "default": "Original", "description": "Authored text"}},
        "bindings": [{"parameter": "title", "file": "project.json", "mode": "json_pointer", "pointer": "/title"}],
        "inputs": {}, "previews": [{"path": "preview.md", "kind": "document", "description": "Only a supplied preview"}],
        "limitations": ["Does not execute its package scripts."],
        "state": {"catalogue": "catalogued", "adaptation": "required", "runtime": "not_executed",
                  "preview": "provided", "user_approval": "pending"},
        "output_contract": {"kind": "overlay", "alpha": "straight"}}
    library = {"schema": "motion-template-library/1", "id": "fixture-library", "version": "1",
        "packages": [{"id": "local", "root": "package", "files": inventory(package, excludes=()),
                      "provenance": {"source_folder_ids": [], "source_file_ids": [], "notes": "Original test files"}}],
        "templates": [template]}
    path = tmp_path / "library/library.json"
    path.write_text(json.dumps(library))
    needed = production_request("authored-layer", "template", prompt="Render the revised authored title as RGBA frames.",
        output_kind="motion_layer", inputs=[{"id": "library", "kind": "json", "path": str(path), "sha256": file_sha256(path)}],
        parameters={"template_id": "authored", "params": {"title": "New intended title"}},
        constraints={"fps": "4", "frame_count": 2, "width": 24, "height": 16, "alpha": "straight"})
    return needed, marker, package


def template_callback(context):
    instance = context["template_instance"]
    root = Path(instance["receipt_path"]).parent
    project = json.loads((root / instance["entrypoint"]).read_text())
    assert project["title"] == "New intended title"
    work = Path(context["output_dir"])
    frames = []
    for index in range(project["frames"]):
        path = png(work / f"{index:06d}.png", (30 + index * 20, 40, 70, 255))
        frames.append({"index": index, "path": str(path), "sha256": file_sha256(path)})
    manifest = work / "motion-layer.json"
    write_layer_manifest(frames, manifest, fps="4", backend="local-test-renderer",
                         method="Executed two original fixture frames; not an external provider")
    return {"artifact_path": str(manifest), "artifact_sha256": file_sha256(manifest),
            "actual_cost": 0, "provenance": ORIGIN}


def test_template_stage_resumes_to_real_layer_without_running_package_code(tmp_path):
    needed, marker, package = template_library(tmp_path)
    source_inventory = inventory(package, excludes=())
    staged = execute_request(needed, tmp_path / "work")
    assert staged["status"] == "instantiated_not_rendered" and staged["result"] is None
    receipt = json.loads(Path(staged["template_instance"]["path"]).read_text())
    assert receipt["runtime_executed"] is False
    rendered = execute_request(needed, tmp_path / "work", executor=template_callback)
    assert rendered["status"] == "succeeded"
    result = validate_result(rendered["result"], needed)
    assert result["kind"] == "motion_layer" and result["technical"]["frame_count"] == 2
    assert len(result["files"]) == 3
    assert result["template_instance"]["sha256"] == staged["template_instance"]["sha256"]
    assert not marker.exists() and inventory(package, excludes=()) == source_inventory
    png(Path(result["files"][0]["path"]), (2, 5, 8, 255))
    with pytest.raises(ValidationError):
        validate_result(result, needed)


def test_template_instance_change_before_external_import_is_rejected(tmp_path):
    needed, _, _ = template_library(tmp_path)
    staged = execute_request(needed, tmp_path / "work")
    instance = Path(staged["template_instance"]["path"])
    (instance.parent / "project/project.json").write_text('{"title":"Changed after staging"}')
    with pytest.raises(ValidationError, match="changed"):
        execute_request(needed, tmp_path / "work", executor=template_callback)


def test_task_export_cannot_write_inside_original_template_package(tmp_path):
    needed, _, package = template_library(tmp_path)
    before = inventory(package, excludes=())
    with pytest.raises(ValidationError, match="immutable template package"):
        execute_request(needed, package / "new-task")
    assert inventory(package, excludes=()) == before
    assert not (package / "new-task").exists()


def test_template_ledger_does_not_duplicate_callback_for_new_export_directory(tmp_path):
    needed, marker, _ = template_library(tmp_path)
    calls = []

    def local(context):
        calls.append(context["job_key"])
        return template_callback(context)

    ledger = WorkflowLedger(tmp_path / "ledger.db", budget_limit=1)
    first = execute_request(needed, tmp_path / "first", executor=local, ledger=ledger)
    second = execute_request(needed, tmp_path / "second", executor=local, ledger=ledger)
    assert first["status"] == second["status"] == "succeeded"
    assert len(calls) == 1 and second["reused"] and not marker.exists()


def test_provided_video_preview_is_rejected_even_when_copied_to_a_new_output(tmp_path):
    needed, marker, package = template_library(tmp_path)
    media, _ = source_video(tmp_path)
    preview = package / "preview.mp4"
    shutil.copyfile(media[0]["path"], preview)
    library_path = Path(needed["inputs"][0]["path"])
    library = json.loads(library_path.read_text())
    library["packages"][0]["files"] = inventory(package, excludes=())
    library["templates"][0]["previews"].append({"path": "preview.mp4", "kind": "video", "description": "Provided example only"})
    library_path.write_text(json.dumps(library))
    needed = production_request("authored-video", "template", prompt="Render the new variant, not its supplied preview.",
        output_kind="video", inputs=[{"id": "library", "kind": "json", "path": str(library_path), "sha256": file_sha256(library_path)}],
        parameters={"template_id": "authored", "params": {"title": "New intended title"}})

    def copied_preview(context):
        original = Path(context["template_instance"]["receipt_path"]).parent / "project/preview.mp4"
        output = Path(context["output_dir"]) / "claimed-render.mp4"
        shutil.copyfile(original, output)
        return {"artifact_path": str(output), "artifact_sha256": file_sha256(output), "actual_cost": 0, "provenance": ORIGIN}

    rejected = execute_request(needed, tmp_path / "work", executor=copied_preview)
    assert rejected["status"] == "failed" and "provided preview" in rejected["issues"][0]
    assert not marker.exists()


def source_video(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real media verification needs FFmpeg and FFprobe")
    path = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=s=32x24:r=4:d=1",
                    "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
    inputs = [{"id": "source", "kind": "video", "path": str(path), "sha256": file_sha256(path)}]
    binding = {"input_id": "source", "source_sha256": file_sha256(path), "fps": "4", "frame_count": 4}
    return inputs, binding


def test_source_bound_transcript_pose_and_mattes_return_typed_real_outputs(tmp_path):
    inputs, binding = source_video(tmp_path)
    shared = {"source_sha256": binding["source_sha256"], "fps": "4", "clock": "source"}
    transcripts = {**shared, "segments": [{"start": 0, "end": .5, "text": "Frase literal."}]}
    pose = {**shared, "frames": {str(index): [] for index in range(4)}}
    for kind, payload in (("transcript", transcripts), ("pose", pose)):
        needed = production_request(kind, kind, prompt="Return source-clock observations with explicit provenance.",
                                    output_kind=kind, inputs=inputs, source_binding=binding)
        path = tmp_path / f"{kind}.json"
        path.write_text(json.dumps(payload))
        received = import_result(needed, path, provenance=ORIGIN)
        assert received["kind"] == kind and received["source_binding"] == binding
        assert received["verification"]["semantics"] == "unverified"
        payload["source_sha256"] = "0" * 64
        path.write_text(json.dumps(payload))
        with pytest.raises(ValidationError, match="another source"):
            import_result(needed, path, provenance=ORIGIN)
    masks = tmp_path / "masks"
    masks.mkdir()
    alpha = masks / "alpha.json"
    alpha.write_text(json.dumps({**shared, "frames": 4, "resolution": [32, 24]}))
    for index in range(4):
        Image.new("L", (32, 24), index * 20).save(masks / f"{index:06d}.png")
    needed = production_request("mask", "mattes", prompt="Produce masks for the current source.", output_kind="mattes",
                                inputs=inputs, source_binding=binding)
    received = import_result(needed, alpha, provenance=ORIGIN)
    assert received["artifact"]["path"] == str(alpha) and len(received["files"]) == 5
    (masks / "000002.png").unlink()
    with pytest.raises(ValidationError):
        validate_result(received, needed)


def test_preparation_clock_is_measured_and_partial_planar_coverage_stays_explicit(tmp_path):
    inputs, binding = source_video(tmp_path)
    wrong = production_request("pose", "pose", prompt="Current source pose.", output_kind="pose", inputs=inputs,
                               source_binding={**binding, "frame_count": 5})
    with pytest.raises(ValidationError, match="real source clock"):
        validate_request(wrong, verify_files=True)
    request_data = dict(prompt="Measured quads on the current source.", output_kind="planar_tracking", inputs=inputs,
                        source_binding=binding)
    needed = production_request("tracking", "planar_tracking", **request_data)
    projection = tmp_path / "projection.json"
    projection.write_text(json.dumps({"source_sha256": binding["source_sha256"], "clock": "source", "fps": "4", "frame_count": 4,
        "provenance": {"kind": "tool", "actor": "local-test-tracker", "method": "Synthetic fixture; no model inference"},
        "quads": {"0": [[.1, .1], [.5, .1], [.5, .5], [.1, .5]]}}))
    received = import_result(needed, projection, provenance=ORIGIN)
    assert received["technical"]["observed_frames"] == [0]
    assert received["technical"]["full_coverage"] is False
    full = production_request("tracking", "planar_tracking", **request_data, constraints={"full_coverage": True})
    with pytest.raises(ValidationError, match="coverage"):
        import_result(full, projection, provenance=ORIGIN)


def test_real_video_and_audio_are_decoded_and_duration_contract_is_enforced(tmp_path):
    inputs, _ = source_video(tmp_path)
    path = tmp_path / "returned.mp4"
    shutil.copyfile(inputs[0]["path"], path)
    needed = production_request("clip", "external_video", prompt="Supply a one-second local fixture.", output_kind="video",
                                constraints={"fps": "4", "frame_count": 4, "duration_s": 1, "alpha": "opaque"})
    result = import_result(needed, path, provenance=ORIGIN)
    assert result["technical"]["check"] == "stream_and_decode"
    wrong = production_request("clip", "external_video", prompt="Two seconds are required.", output_kind="video",
                               constraints={"duration_s": 2})
    with pytest.raises(ValidationError, match="duration"):
        import_result(wrong, path, provenance=ORIGIN)
    audio = tmp_path / "voice.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\x00\x00" * 800)
    voice = production_request("voice", "voice", prompt="Return the actual authored voice file.", output_kind="audio")
    result = import_result(voice, audio, provenance=ORIGIN)
    assert result["technical"]["sample_rate"] == 8000
    assert result["verification"]["audio_listened"] is False


def test_bundled_motion_runs_existing_renderer_and_imports_its_rgba_output(tmp_path):
    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not font.exists():
        pytest.skip("Tiny typography render needs a real installed font")
    needed = production_request("original-motion", "motion_recipe", prompt="Render the explicitly authored two-frame lettering test.",
        output_kind="motion_layer", inputs=[{"id": "font", "kind": "font", "path": str(font), "sha256": file_sha256(font)}],
        parameters={"backend": "motngrfx", "font_input": "font", "font_license": "Installed system font; no font redistributed",
            "recipe": {"schema": "motngrfx-motion/1", "text": "AÓ", "fps": "4", "frame_count": 2,
                       "width": 96, "height": 64, "font_size": 24, "extrusion_px": 2,
                       "animation": {"module": "rotate", "keyframes": [
                           {"frame": 0, "rotation_deg": [-5, 0, 0]}, {"frame": 1, "rotation_deg": [5, 0, 0]}]}}},
        constraints={"fps": "4", "frame_count": 2, "alpha": "straight"})
    executed = execute_request(needed, tmp_path / "motion")
    assert executed["status"] == "succeeded", executed["issues"]
    result = validate_result(executed["result"], needed)
    assert result["status"] == "produced_unreviewed"
    manifest = json.loads(Path(result["artifact"]["path"]).read_text())
    assert manifest["origin"]["execution_in_this_call"] is True
    assert manifest["origin"]["upstream_commit"]
    assert result["verification"]["continuous_motion"] == "unverified"
    producer = Path(result["provenance"]["producer_receipt"]["path"])
    assert str(producer) in {item["path"] for item in result["files"]}
    producer.write_text(producer.read_text() + "\n")
    with pytest.raises(ValidationError):
        validate_result(result, needed)
