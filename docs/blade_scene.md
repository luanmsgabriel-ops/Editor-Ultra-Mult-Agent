# Curved foreground blades

`visual_fidelity.blade_scene` renders real, closed curved solids over transparent
backgrounds. It is useful for metallic vertical strips that pass in front of
typography. It does not reuse phone pixels, phone meshes or perspective warps.

```bash
LP_NUM_THREADS=2 python -m visual_fidelity.blade_scene recipe.json --threads 2
LP_NUM_THREADS=2 python -m visual_fidelity.blade_scene recipe.json --frames 12,18
python -m unittest tests.test_blade_scene -v
```

## Authored scene contract

```json
{
  "schema": "editor-ultra.blade-scene.v1",
  "output": "./blade-renders",
  "resolution": [720, 1280],
  "fps": 30,
  "engine": "BLENDER_EEVEE_NEXT",
  "samples": 4,
  "viewport_height": 3.2,
  "auto_border": true,
  "geometry": {"length": 3.05, "width": 0.075, "depth": 0.045},
  "material": {"color": [0.13, 0.18, 0.25], "metallic": 0.85, "roughness": 0.35},
  "blades": [
    {"id": "left", "geometry": {"bow": -0.08}, "location": [-0.7, 0, 0]},
    {"id": "right", "geometry": {"bow": 0.08}, "location": [0.7, 0, 0]}
  ],
  "frames": [
    {"frame": 0, "blades": {"left": {"location": [-0.7, 2.0, 0]}}},
    {"frame": 1, "blades": {"left": {"location": [-0.7, 1.5, 0]}}}
  ]
}
```

Each frame overrides the base blade definitions independently. `location`,
`rotation_deg` (XYZ), `scale`, `visible`, and `opacity` are animatable. All frames
to render must be explicitly authored. `frames[].opacity` applies to all blades
unless a particular blade overrides it.

Optional per-blade `tip_darkening` (0–1) shades the lower third of the real solid
with a local quadratic material falloff. It can reproduce a dark trailing tip
during entrance and return to0 when the full blade settles. It does not replace
motion blur or change the geometry's projected position.

The volume is a swept elliptical cross-section with rounded ends. `bow` curves
the centerline along X; `z_bow` curves it along the viewing axis. `taper` controls
the width remaining at the lower end. `steps` and `sides` control tessellation;
additional rings densely sample the rounded caps, preventing pointed tips.

Camera coordinates are X right, Y up, Z toward the camera. The default
orthographic viewport has height3.2 units; at720×1280 that is400px per scene unit.
For pixel coordinate `(x,y)`, use world `[(x-360)/400,(640-y)/400,z]`.
Camera projection, material shading and occlusion are rendered by Blender.

`lights` accepts area lights with `location`, `target`, `energy`, `size`,
`size_y`, and RGB `color`. Material colors use scene-linear values. EEVEE uses
no ray tracing or shadows here, to keep isolated transparent foreground layers
quick to render; the curved metal surfaces still respond to the authored lights.

Outputs are full-resolution RGBA PNGs named `NNNNNN.png`, an editable
`blades.blend`, the recipe and a timing manifest. Composite the RGBA over the
typography before resizing or moving the whole viewport. The optional render
border retains the full raster and excludes hidden blade meshes.

Reference-specific timing adapters, source frames, textures and generated
layers belong outside the repository. The generic module contains no media
or hard-coded frame timings from a particular reference video.
