# Editor Ultra | 332300 | Fidelity integration (draft)

## Status (2026-11-17)
This PR is **not deployed** and does not contain an approved reconstruction v2.
The live project `4d5673a2-1f96-45fe-89f1-5e53cd95217f` must retain its recorded
`clone.rejected` decision for the v1 artifact.

## Verified source clock
Original `332300.mp4`: 1276x718, 30/1 FPS, 2214 frames, last valid index **2213**.
MP4 container duration can include the audio tail; `round(duration*fps)` cannot
be used to sample the last frame. `reference_fidelity.sample_frame_indices`
selects indices from FFprobe's **video stream frame count** instead.

## QA surfaces

### `editor_compare_clone`
Required: project ID, current revision. Optional: explicit frame indices.
Selects up to 16 uniform source frames by default, without retiming, crop or resize.
Persists a report and source/candidate/difference contact sheet under evidence IDs.
Output status is `diagnostic_not_approved`, not a fidelity grade.

### `editor_compare_temporal`
Required: project ID, revision, request ID, `center_s` in source seconds.
Queued execution compares approximately three seconds around selected playback
time at the exact original frame clock. It logs 2D frame change and downscaled
optical flow for consecutive reference/candidate frames, reporting the largest gaps.
It does not recover camera geometry, object identity, depth or motion blur.
Evidence is marked stale whenever either media SHA changes.

### `editor_register_reference_scenes`
Required: source-bound manifest `editor-ultra-reference-scenes/1`.
Every frame must be covered by an ordered non-overlapping scene. Each scene lists
its elements, observed events, and unresolved claims. No automatic event discovery
or visual approval is inferred.

## Typed local motion producer: experimental, explicitly bounded
`editor_queue_bundled_motion` accepts an authored `motionlab-scene/1` recipe,
2D only, up to **120 frames**, **1280x720**, **60 FPS**, no font files and an
unfilled transparent background. It queues a `production-request/1` using
`editorial_engine.project.queue_production` and the already pinned `bundled.motion`
adapter. It cannot execute arbitrary Python, shell or external generation endpoints.

`editor_execute_bundled_motion` runs the currently queued request through
`editorial_engine.project.produce`, preserving the workflow ledger and
returning a real manifest when the renderer and vendor dependencies are available.
A request, a render receipt and perceptual review are three **distinct** states.
A motion-layer JSON does not become an approved clone or a full-film output.
This producer path needs end-to-end runtime tests before deployment.

### Example short scene recipe

```json
{
  "schema_version": "motionlab-scene/1",
  "id": "test-panel",
  "mode": "2d",
  "width": 640,
  "height": 360,
  "fps": "30/1",
  "frame_count": 60,
  "background": null,
  "nodes": [
    {"id":"panel","type":"rect","width":120,"height":60,
     "x":100,"y":100,"fill":"#4F39D6"}
  ],
  "tracks": [
    {"target":"panel","property":"x",
     "keys":[{"t":0,"value":80},{"t":1.9667,"value":510}]}
  ]
}
```

This validates producer mechanics, **not** the original ZED, glass or phone effect.

## Evidence from the rejected v1
A five-window local QA pass analyzed 390 consecutive frame pairs. Frame **1174**
(39.133 s) showed reference interframe intensity change 0.234885 vs clone
0.000962; measured downscaled flow was 2.977432 vs 0.024273 pixels/frame.
These are source/candidate differences, not original 3D velocities. The missing
forest transition must be rebuilt, not smoothed away with retiming.

## Release blockers
1. Run the entire CI gate including media-real adapter tests and frontend syntax.
2. Verify Studio and MCP tools in a **staging environment** with real uploads.
3. Execute a bounded authored motion producer end to end; inspect exported PNG
   sequence, alpha, frame count and ledger receipt.
4. Calibrate reference scenes independently: lettering, 3D pose, materials,
   segmented figures, masks and measured camera paths.
5. Render the ZED, phone and optical-material proofs and compare aligned motion.
6. Keep v1 rejected and v2 unapproved until a user explicitly reviews new bytes.

No automatic merge, deploy, approval, or whole-film v2 is performed by this PR.

## Hybrid clone rendering

The Studio's clone request now directs the host to inspect each scene for a
missing visual resource. Generate a transparent PNG for a silhouette, emblem
or texture when it supports the observed composition. Use animated geometry
where camera movement reveals depth or a previously hidden surface.

1. Call `editor_request_clone_images` with the asset ID, scene ID, exact
   `[first,last)` frame interval, reference frame, placement and visual
   rationale. The app stores the request and returns a viewable still from the
   scoped reference. Open the still and generate the isolated artwork in the
   ChatGPT host. This action remains in the host's workflow with image
   generation access.
2. Import the actual PNG with `editor_import_file(role="clone_resource")`.
   The adapter checks the PNG contents and requires both transparent and
   visible pixels. Import the independently produced plate as `footage`.
3. Call `editor_prepare(kind="clone", reconstruction=...)` with the plate ID
   and a mapping from each image request ID to its returned asset ID. The
   reference and plate must share the same constant frame clock and raster.
   If scene assessment finds no need for a generated asset, supply
   `no_generated_images_reason` in place of an image request. The renderer
   takes its base pixels and audio from the imported plate.
   Put any intended audio mix on that plate before preparation.
4. Bind every requested image to an effect in the plan across its declared
   interval. Use `native.overlay` in screen space, `native.behind_subject`
   with a matte, `native.projected_asset` with planar tracking, or
   `native.projected_behind` with both. The app validates the planned
   placement and coverage before accepting direction.
5. Render and compare the result. Receipts identify the plate, reference,
   selected PNG bytes, plan and resources actually consumed. Review the
   resulting MP4 explicitly.

Protection, pose, and projection JSON use the reconstruction plate's SHA-256
and source clock. For multiple authored tracks, `projection_assets` maps a
track ID to each verified JSON receipt. `measured_projection` maps one measured
element explicitly from the clock-aligned reference or plate with continuous
frame coverage. That mapping applies 2D motion and its provenance remains part
of the tracking receipt. It requires an unrotated matching raster. Set
`shutter_fraction` on a planar effect for motion blur sampled from adjacent
quads. This samples projected movement on the plate; it does not estimate a
physical 3D camera shutter.

Use a matte ZIP containing `alpha.json` and one `000000.png`-style mask for every
frame. Assign verified TTF and OTF uploads to `font_asset_id` and
`script_font_asset_id`. `motion_layers` takes project-owned Motion Lab result
IDs. The renderer checks source and clock coverage when preparing or consuming
each resource.

Local release evidence covers a real shield segment of 332300 from frame
896 through 927. The engine projected a generated, transparent six-piece
icon onto the independent shield geometry at 30 fps (32 frames).
The shoulders, lighting, HUD elements and layered glow in that shot still
differ from the reference. The input video and generated artwork stay outside
Git. The local proof has no user approval and the whole-film v2 remains open.

The deployment image bundles the pinned Motion Lab renderer and verifies that
Node can import its native Canvas dependency and Three.js during the build.
