# Production requests and explicit adapters

`editorial_engine.production` connects authored needs to actual resources. It
exports tasks for a person or external tool, calls Python adapters explicitly
configured by the host, imports typed results, and optionally uses the existing
`WorkflowLedger` for reservation, idempotency and recovery. It does not choose
editorial intent, invoke ChatGPT from local Python, install models, import Python
names from JSON, execute package bootstraps or treat a template preview as a new
render.

Video synthesis is always **prompt export only**. An `external_video` request
never invokes a supplied executor or adapter. It exports instructions/settings
and returns `awaiting_external_generation` until the user supplies actual media.
Choosing a provider, account or registered avatar is not required. This rule does
not disable local editing, compositing, procedural rendering or text direction.

The main API is:

```python
production_request(request_id, operation, *, prompt, output_kind,
                   inputs=None, parameters=None, adapter_id=None,
                   source_binding=None, context=None, unresolved=None,
                   constraints=None, revision=1)
validate_request(request, *, verify_files=False)
execute_request(request, output_dir, *, executor=None, registry=None,
                ledger=None, estimated_cost=0, retry_failed=False)
import_result(request, artifact_path, *, kind=None, provenance,
              output_dir=None, expected_sha256=None, template_instance=None)
validate_result(result, request, *, verify_files=True)
queue_status(requests, results=(), *, verify_files=True)
```

All functions return finite JSON data. Invalid contracts raise
`editorial_engine.contracts.ValidationError`; execution receipts also represent
known failures and unknown provider states. These states are not approvals.

## 1. Author a need and export it

```python
from editorial_engine.production import production_request, execute_request

need = production_request(
    "missing-product-view", "chat_image",
    prompt="Create the explicitly described product view using the attached identity reference.",
    output_kind="image",
    inputs=[{
        "id": "identity", "kind": "image", "path": "/project/media/product-reference.png",
        "sha256": "<actual lowercase SHA-256 of that file>", "role": "identity_reference",
    }],
    constraints={"width": 1024, "height": 1024, "require_transparency": True},
    context={"project_id": "example", "plan_revision": 3, "asset_id": "product-side"},
)
pending = execute_request(need, "/project/production/product-side-v1")
# pending["status"] == "awaiting_external"; no provider was called.
```

The task directory contains `request.json`, `REQUEST.md` and its initial
`execution.json`. The Markdown contains the authored instructions, exact input
paths/hashes, parameters, constraints and missing authoring decisions. Repeating
the same export in the same directory reuses it. A changed request cannot
overwrite that directory: create a new revision and location.

Operations such as `chat_image`, `external_video`, `voice`, `music`, `sfx`,
`manual_asset` and `procedural` are useful route labels. There is no keyword
selection or automatic route substitution. Other operation IDs are allowed for
explicit host adapters. An unknown `adapter_id` is an unresolved adapter, not an
importable module or shell command.

For `external_video`, even an explicit adapter ID or callable cannot change the
manual route. The export includes `VIDEO-GENERATION-POLICY.json` and makes no
budget reservation. Local `motion_recipe`, `planar_portal`, `template` and
`procedural` operations remain available. Another video-processing operation
must have `execution_kind="local_processing"` registered by the trusted host
in `AdapterRegistry.register`; JSON parameters cannot confer that classification.
These contracts do not sandbox or inspect arbitrary Python callback semantics.

`unresolved` contains decisions genuinely required before production, such as
missing narration text or an unspecified data value. A request with unresolved
items can be exported but is blocked for execution and import. Lack of a chosen
video/image provider is not itself a reason to invent an unresolved authoring
decision for a useful manual task.

Inputs are a list of `{id, kind, path, sha256}` with optional `role`. Paths are
absolute local files. `parameters` and `context` hold declarative JSON.
`context` should carry the project/plan/need identity relevant to the caller.
Changing it changes `request_sha256` and invalidates old results.

## 2. Import an actual external result

```python
from editorial_engine.production import import_result, validate_result

received = import_result(
    need, "/project/returned/product-side.png",
    expected_sha256="<actual returned-file SHA-256>",
    provenance={
        "actor": "operator or producing tool",
        "method": "Executed the exported task in the selected tool and supplied this PNG",
        "simulated": False,
        "provider_job_id": "optional externally observed job id",
    },
    output_dir="/project/production/product-side-v1",
)
validate_result(received, need, verify_files=True)
```

`provenance.actor`, `provenance.method` and an explicit boolean `simulated` are
required. Provider/job/model/version/license notes may also be retained as
attestations. An import does not independently prove that an external provider
used each attachment, followed a prompt or preserved identity.

The primary file is always `result["artifact"] = {path, sha256, size}` and its
type is `result["kind"]`. The complete `files` inventory also includes dependent
frames and glyph maps where applicable. `technical` records measured format,
clock/raster or source-bound data checks. `request_sha256`, revision, context,
inputs and source binding must match the current request.

`status` is `produced_unreviewed`, or `simulated_result` for a simulated provider
or fixture. A normal project fulfillment must not promote a simulated result to
real production. Technical import keeps semantic suitability and continuous
motion unverified, audio listening false and user approval pending. Do not
replace those fields with an approval: register perceptual review separately.

An identical `result.json` import into the same task directory is idempotent.
Another candidate/result needs another output location or a revised task. The
original files and prior records are not overwritten.

### Result types

| Kind | Primary file | Verification and downstream use |
|---|---|---|
| `image` | Decodable image | Loads pixels; measures raster and explicit transparency. Can become a generation-plan image or contextual image inventory entry. |
| `video` | Real video container | FFprobe plus full FFmpeg video decode; stream, count, duration and FPS checks. Feed the appropriate video import/montage contract next. |
| `audio` | Real audio file | FFprobe plus full FFmpeg audio decode. Measures duration/rate/channels; this is not listening, SFX attack review or voice approval. |
| `motion_layer` | `motion-layer.json` | Reuses `motion_assets.load_layer`; verifies every RGBA PNG and optional glyph map. Use the contextual inventory's `kind: motion`. |
| `transcript` | Source-bound JSON | Ordered nonoverlapping source-time segments with literal text. Timestamp validity does not prove ASR completeness or listening. Pass its path to `prepare --transcript`. |
| `pose` | Source-bound JSON | A frame record for every source frame, including empty detections. This does not prove successful detection on every frame. Pass to `prepare --pose`. |
| `mattes` | `alpha.json` | Source clock, proportional raster and a real grayscale PNG for every frame. Pass its parent directory to `prepare --mattes`. |
| `planar_tracking` | Source-bound JSON | Valid measured/declarative quads and frame indices. Partial coverage stays explicit. Pass to `prepare --projection`; only covered spans can become capabilities. |

Image/media files are checked as their declared types, not only by suffix or
hash. FFmpeg/FFprobe verification is local and limits media protocols to local
files/pipes. Neither verification tool is used to call remote providers. A video
file is not accepted as an RGBA motion layer. No implicit trim, loop, frame hold,
resampling or retiming makes a mismatched result satisfy a request.

`constraints` supports `width`, `height`, rational-string `fps`, `frame_count`,
`duration_s`, explicit `duration_tolerance_s`, `alpha`, `require_transparency`
and `full_coverage`. Only request properties that the result must actually meet.
Video alpha is conservatively classified; a flattened MP4 does not certify
straight alpha. Timestamps, raster and bytes do not certify content semantics.

## 3. Configure a Python adapter

A callable receives one context object and returns explicit execution evidence:

```python
from pathlib import Path
from PIL import Image
from editorial_engine.contracts import file_sha256
from editorial_engine.production import AdapterRegistry

def render_local_asset(context):
    # This is an actual small local image producer, not a simulated remote API.
    work = Path(context["output_dir"])
    target = work / "authored-marker.png"
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.paste((220, 110, 30, 255), (12, 12, 52, 52))
    image.save(target)
    return {
        "artifact_path": str(target), "artifact_sha256": file_sha256(target),
        "actual_cost": 0,
        "provenance": {
            "actor": "project.local-marker-renderer",
            "method": "Executed the explicitly configured local PNG producer",
            "simulated": False,
        },
    }

registry = AdapterRegistry()
registry.register("local-marker", render_local_asset,
                  operations=["procedural"], output_kinds=["image"], version="1")
```

Create the corresponding request with `operation="procedural"`,
`adapter_id="local-marker"` and matching dimensions. Then call
`execute_request(..., registry=registry)`. A direct `executor=callable` is also
explicit Python configuration; it never comes from a JSON import string.

Context keys are `request`, `output_dir`, `job_key`, `template_instance`,
`template_instance_file`, `cost_limit` and `cost_unit`. The template fields are
null for ordinary resources. Output
must be produced in the fresh attempt directory, including nested layer frames.
Callbacks should only use declared inputs, preserve their bytes, use arguments
instead of interpolated commands, enforce provider spending bounds and return
the real artifact/job/cost facts. They are host-owned code, not sandboxed or
inferred from package instructions. Secrets must not appear in callback reports.

Use a registry with an explicit version for production integrations. The receipt
also fingerprints Python callback code where available. Closure variables,
remote configuration and model changes must be represented in version/parameters
by the host; a code fingerprint cannot infer them.

A registered simulated adapter must also return `provenance.simulated=true`.
This is useful for provider integration tests without presenting a stub as a
remote service that was called. The local PNG/layer artifacts in tests are still
actually produced and decoded.

## 4. Existing motion renderer bridge

The bundled `operation="motion_recipe"` calls `motion.render_recipe` with a
declarative recipe and records its actual producer receipt. Its built-in backend
allowlist is `motionlab` and `motngrfx`; other project runtimes, including explicit
OpenKatana integrations, can be configured as host callbacks. It does not accept
project scripts or `trusted_script` through request JSON.

Parameters are `backend`, `recipe`, optional `font_input`, `font_license`,
`samples`, `shutter_angle`, `asset_id` and `description`. `font_input` references
a declared hashed input of kind `font`. Fonts embedded in a Motion Lab recipe
must also appear among the hashed inputs.

MOTNGRFX produces a `motion_layer`; encoding it as standalone video requires an
explicit encoder adapter. Motion Lab can produce a real layer or video. For a
video request its background must be authored explicitly; the inspection
preview's fallback background is not inferred as a creative choice. Actual
runtime dependencies still have to be installed. The bridge never downloads
them or silently chooses another backend.

The bundled call records zero monetary provider cost because it uses the local
renderer, not a paid provider. This does not claim that CPU time is free. A
failed local render remains a known failed attempt with its report; it cannot
be reused as a valid asset.

## 5. Template instance → actual render

For `operation="template"`, declare a hashed `json` input named `library` and:

```json
{
  "template_id": "explicitly-selected-card-id",
  "params": {"title": "Authored replacement"},
  "inputs": {"graded_video": "declared-video-input-id"}
}
```

`library_input` may name another input; `root` may specify the absolute package
root. Defaults resolve packages relative to the library file. Input-slot IDs
map to actual request inputs with matching media kinds and hashes.

The bridge calls `templates.instantiate_template`, retaining its immutable
source checks and explicit bindings. Without a configured renderer, execution
returns `instantiated_not_rendered` and the instance receipt, with `result=null`.
It exports enough information for an external renderer and can resume that same
instance later. No package script is executed by staging.

A configured callback receives the verified instance receipt and its actual
entry point. It authors/renders through a compatible runtime selected in code and
returns a video or `motion-layer.json` in its new output directory. It must write
caches and outputs outside the immutable instantiated `project/` directory.
Import rechecks every instance file, request parameters, input bindings and
source package. Changed instance bytes invalidate the result.

For a manual external render, pass `template_instance={"path": ..., "sha256":
...}` to `import_result`. A supplied preview is rejected even when copied to a
new output path with a new filename. The original template output description
does not certify a newly adapted result: actual media/frames must pass the
requested output contract. A private scene containing an opaque demo video
does not automatically become an alpha overlay or a solved 3D insertion.

## 6. Source-bound preparation adapters

There is no new ASR, pose estimator, segmentation or tracking algorithm in this
module. Register callbacks that invoke already configured tools and import
their real outputs. The request must contain its current video input and:

```json
{
  "input_id": "source",
  "source_sha256": "<actual source hash>",
  "fps": "30000/1001",
  "frame_count": 900
}
```

This is `source_binding`; optional `start_frame`/`end_frame` identify a required
interval. File validation measures the actual source clock and compares it to
the binding. Preparation JSON uses source time and the same source SHA-256.
Pose/matte contracts represent the full source clock; a planar result may have
partial observations, which remain reported. `full_coverage=true` can explicitly
require every frame of the requested tracking interval.

The production result is then an input to `prepare_analysis`. Preparation still
decides which measured spans support body/hand/planar/matte capabilities. Merely
producing a pose JSON does not establish reliable hand tracking everywhere, and
producing a mask does not establish correct occlusion or perceptual quality.

## 7. Costs, idempotency and unknown jobs

```python
from editorial_engine.workflows import WorkflowLedger

local_need = production_request("local-marker-example", "procedural",
    prompt="Produce the authored transparent orange marker.", output_kind="image",
    adapter_id="local-marker",
    constraints={"width": 64, "height": 64, "require_transparency": True})
ledger = WorkflowLedger("/project/production/ledger.sqlite", budget_limit=5, unit="credits")
execution = execute_request(local_need, "/project/production/local-marker-v1",
                            registry=registry, ledger=ledger, estimated_cost=0)
```

Use an estimate that is a real upper bound and enforce it in the external
adapter. `estimated_cost=0` is appropriate for known local/no-provider-cost
work, not for guessing the price of a remote job. Unknown costs block finite
budgets under the ledger's existing rules.

The ledger reserves before calling the executor. Its job identity includes the
sealed request, configured adapter and hashed inputs. The same job can resume
from another export directory without calling the provider again. Output file
paths do not turn a template into a new paid request. Use the same request and
adapter configuration to resume; an intentional change needs a new request
revision.

`actual_cost` must be reported, including zero. An exception, a submitted/pending
job or missing actual cost leaves execution `unknown`; its reservation stays
held. A known failed result settles its known actual cost. A media-validation
failure after a provider returned a known cost also records that spend instead
of hiding it. A failed job only retries with explicit `retry_failed=True`.
An unknown/running job is never restarted by that flag, by removing the callback
or by replacing it in the same task directory.

The callback's returned job ID and facts are retained in
`attempt-NNN/executor-report.json`. Keep these facts free of credentials. The
execution receipt links that report. For interrupted work, independently confirm
that the worker stopped, obtain its artifact and actual cost, import the artifact
against the same request, then use the existing recovery API:

```python
ledger.reconcile_job(job_key, actual_cost=known_actual_cost,
                     artifact_path="/project/recovered/result.json",
                     artifact_sha256="<hash of the production-result receipt>")
```

The ledger artifact is the **production result receipt**, not only the PNG/MP4.
On resume the production validator also rechecks every nested frame/mask and
current input. Changing a nested file does not trigger an automatic re-render.
Known failure reconciliation omits the artifact and supplies an error instead.

Without a ledger, the task directory provides sequential reuse and retains
unknown state. Use a ledger for concurrent workers and all cost-sensitive
providers. Do not delete attempt records or move to a new request to conceal an
unresolved job. The coordinator remains responsible for that operational scope.

## 8. Receipt states and project integration

| Execution state | Meaning and next action |
|---|---|
| `blocked` | Authoring requirements remain. Refine the request explicitly. |
| `awaiting_external` | Useful manual instructions exported. Obtain the real file in the selected tool. |
| `awaiting_external_generation` | Video prompts/settings exported. The user generates externally and imports the returned clip; no generation callback or new budget reservation. |
| `awaiting_adapter` | Named adapter is not registered. Configure it in host code or use manual import. |
| `instantiated_not_rendered` | Template variant exists, with no produced resource. Render it via an explicit callback/tool. |
| `succeeded` | A typed result is technically verified; inspect its separate `produced_unreviewed`/`simulated_result` status. |
| `failed` | Known attempt failed. Preserve cost/error; decide whether to revise or explicitly retry. |
| `unknown` / `running` | Work may still exist externally. Reconcile the same job; do not duplicate the call. |

Execution events are sealed and retained. `execution.json` is the initial state;
subsequent execution events have immutable hash-based filenames and `latest.json`
points to the most recent one. A manual result import writes `result.json`.
These technical receipts are separate from review history and user approval.

For generation assets, the coordinator can call `validate_result`, check the
expected kind and non-simulated provenance, and bind the real path/hash through
the plan's explicit revision operation. For editing, it can register image or
motion resources in the preparation inventory or pass typed preparation results
to `prepare_analysis`. Audio still needs its own attack/cue/mix contracts; a
voice file does not prove lipsync. Video still needs source clocks, joins and
montage contracts. Fulfillment does not infer those subsequent editorial steps.

Targeted tests in `tests/test_production.py` exercise real PNGs, a real tiny
MOTNGRFX sequence, template-to-RGBA callbacks, decoded local video/audio,
source-bound preparation, stale hashes, preview rejection, cost accounting and
unknown-job recovery. Tests never claim continuous playback, listening or
provider availability.
