# Real 3D device scenes

`visual_fidelity.device_scene` renders an authored product camera and real
smartphone geometry in the installed Blender. It never invokes a video generator.
The chassis has thickness, rounded corners and bevels. The front glass, UV
display, rear panel, camera bar/island, three lens barrels, rings and buttons are
separate meshes. Display artwork remains local to the device while the device
and camera move independently.

## Run

```bash
python -m visual_fidelity.device_scene validate /absolute/path/recipe.json
python -m visual_fidelity.device_scene render /absolute/path/recipe.json --threads 4
python -m visual_fidelity.device_scene render /absolute/path/recipe.json --frames 0,15,30
```

The `output` directory contains `scene.blend`, `recipe.resolved.json`, numbered
RGBA PNGs, per-frame projection JSON and `render-manifest.json` with actual
render timings. Rendering selected frames overwrites those frame files and the
manifest. Use separate output directories for concurrent workers. Private
textures, recipes, renders and `.blend` scenes belong outside the Git repository.

## Coordinates and camera

| Property | Convention |
|---|---|
| Local/world axes | X right, Y up, +Z out of the display |
| Device origin | Center of the chassis |
| Default dimensions | Width 0.78, height 1.634, depth 0.0875 |
| Units | Arbitrary consistent units, not certified physical measurements |
| Device Euler | `rotation_deg:[x,y,z]`, Blender XYZ order, degrees |
| Quaternion | `rotation_quaternion_wxyz:[w,x,y,z]`, local to world |
| Rotation matrix | `rotation_matrix`, proper 3×3 local-to-world rotation |
| Camera aim | `location`, `target`, world-up `[0,1,0]`, `roll_deg` |
| Direct camera pose | Quaternion or matrix; local −Z forward and +Y up |
| Camera sensor | Perspective, horizontal sensor fit, width 36 mm by default |
| Pixel coordinates | Origin at top left; x right, y down |
| Display UV | `(0,0)` bottom left; `(1,1)` top right |

A quaternion/matrix frame override replaces a base Euler rotation, and vice
versa. Supply only one orientation representation in each pose. `camera.up`
can explicitly change the look-at up-vector. Camera orientation is authored or
calibrated by the caller; this renderer does not claim to recover the original
camera automatically.

## Minimal recipe

```json
{
  "schema": "editor-ultra.device-scene.v1",
  "output": "./renders",
  "resolution": [720, 1280],
  "fps": 30,
  "engine": "BLENDER_EEVEE_NEXT",
  "samples": 4,
  "transparent": true,
  "auto_border": true,
  "camera": {
    "location": [0, 0, 2.8],
    "target": [0, 0, 0],
    "lens_mm": 50
  },
  "devices": [{
    "id": "phone",
    "screen_texture": "./screen.png",
    "front_sensor": false,
    "camera_layout": "bar",
    "geometry": {"screen_margin": 0.01}
  }],
  "frames": [
    {"frame": 0, "devices": {"phone": {"rotation_deg": [30, -15, -9]}}},
    {"frame": 1, "devices": {"phone": {"rotation_deg": [30, -14.8, -8.9]}}},
    {"frame": 2, "devices": {"phone": {"rotation_deg": [30, -14.6, -8.8]}}}
  ]
}
```

Every authored row is a snapshot overriding the **base** camera and devices,
not the preceding frame. The renderer emits exactly the listed frames. For a
30 fps final sequence, author every required frame; a sparse recipe is only a
set of inspection frames. Animated transforms are also saved in `.blend` with
linear interpolation between supplied keys.

The JSON is authoritative for changing textures and surface styles. These
per-frame switches are applied by the renderer and are not baked as interactive
Blender shader animation. Camera and object trajectories, lights, meshes and
the initial texture remain editable in the `.blend`.

## Geometry, materials and visibility

`devices` may contain multiple independently placed devices. Each accepts
`location`, `rotation_deg`/quaternion/matrix, `scale:[x,y,z]`, and `visible`.
The same keys can appear under `frames[].devices.<id>`.

`geometry` accepts `width`, `height`, `depth`, `corner_radius`, `screen_margin`,
`edge_bevel` and `corner_segments`. Geometry is constructed once per render;
changing these fields in individual frames does not rebuild topology.

`camera_layout:"island"` creates a compact camera island; `"bar"` spans almost
the full width of the upper rear. `rear_cameras:false`, `front_sensor:false`
and `side_buttons:false` disable those parts. With square dimensions and those
features disabled, the same solid device can be used as an extruded app tile.

`materials` accepts RGB triples for `chassis`, `back`, and `camera_island`.
The renderer interprets these material values as scene-linear RGB. Artwork
files use sRGB. `style` can switch per frame between `studio` (original
materials), `clay` (uniform diffuse body), and `matte` (original colors with
rough nonmetal surfaces). `clay_color` sets the clay RGB.

`screen_texture` may change every frame. `screen_mode:"black"` temporarily
disables artwork; `"color"` uses `screen_color`; `"texture"` uses the image.
`screen_emission`, `screen_reflection` and `screen_roughness` control the display.
Black mode still renders physical glass reflection. Display textures should
contain just flat UI artwork, without a baked phone, perspective or scenery.

An optional `back_texture` is attached to the back panel, not the camera bar.
It is an opaque panel texture; prepare the intended rear surface color as part
of that image when including a logo.

## Cards lifted off the display

Cards are actual geometry parented to the phone. They preserve perspective,
occlusion and depth separation while the device rotates. Declare them in the
base device so the meshes exist before rendering:

```json
{
  "cards": [{
    "id": "tile",
    "texture": "./tile.png",
    "rect_uv": [0.40, 0.13, 0.31, 0.21],
    "lift": 0.08,
    "rotation_deg": [-5, 10, 0],
    "thickness": 0.001,
    "visible": true
  }]
}
```

`rect_uv` is `[left,bottom,width,height]`, normalized to the active display.
The card origin is the rectangle center; rotations apply there, in phone-local
axes. `lift` is distance along the phone's +Z, beyond the display. Values can
extend outside the display rectangle to reproduce a pop-out. `radius` is the
rounded-corner radius in scene units.

Per-frame `cards:[{"id":"tile","lift":0.12,"rotation_deg":[0,15,0]}]`
overrides that card's base values. Unmentioned cards retain their base state.
Use `visible:false` to hide one. New card IDs must be declared in the base.

## Focus, alpha, passes and performance

Camera `dof` accepts `enabled`, `fstop`, and world-space `focus_target`.
`motion_blur:true` uses Blender motion blur and optional `shutter`; the camera
and device poses are keyed so actual transforms drive it. Large gaps between
sparse authored frames are not a substitute for a measured motion trajectory.

`transparent:true` produces RGBA PNG. Optional `passes:["depth","normal",
"object_index"]` additionally writes a scene-linear multilayer EXR, subject to
the selected engine's supported passes. PNG display colors and EXR linear
values should not be mixed without color-space conversion.

`auto_border:true` bounds visible device/card meshes, keeps `border_padding`
pixels (default48), and preserves the complete requested output raster. Increase
padding for strong DOF/motion blur, or disable the border for diagnosis. Hidden
devices do not enlarge this region. Geometry intersecting the camera near plane
falls back to the full raster.

Both Cycles CPU and EEVEE execute on Blender4.3.2. The environment's particular
build may lack OpenImageDenoise: do not enable `denoise` until supported. The
provided diagnostic run confirmed that this installation rejects it.

EEVEE options include `raytracing:false`, `shadows:false`, and
`shadow_resolution_scale` (default0.5). Disabling shadows is a conscious
photographic tradeoff for isolated product shots: lens/card contact shadows
will not be physically present. Area-light reflections remain. Measure the
first shader-compilation frame separately from subsequent frames. The actual
per-frame times are recorded in `render-manifest.json`; macro and DOF shots
cost more than small devices against transparent backgrounds.

## Projection and verification

Each frame JSON includes camera matrix, device matrix, four active-display
bounding-corner coordinates in world and pixels, camera depth and front-facing
status. Corner order is top-left, top-right, bottom-right, bottom-left. These
are the outer rectangle around the rounded display, not exact curved corners.
Use these values to position downstream overlays or compare reference matches.

```bash
python -m unittest tests.test_device_scene -v
blender -b --factory-startup --threads 4 --python-exit-code 1 \
  --python tests/blender_device_scene_smoke.py
```

The CPU tests check closed solid volume, screen orientation and independent
frame snapshots. The Blender smoke test actually renders a four-color UV target
under camera motion and device rotation, samples the projected expected colors,
checks world-Y-up framing and verifies rear camera geometry. No source video or
private texture is required by either test.
