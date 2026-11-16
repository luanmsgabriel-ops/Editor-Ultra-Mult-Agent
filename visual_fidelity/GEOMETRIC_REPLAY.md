# Geometric replay compositor

`geometric_replay` supplies reusable geometry and compositing. Photographic
layers are external assets; their provenance and missing/occluded areas remain
the adapter's responsibility. The module does not infer hidden imagery, motion,
font geometry, or camera depth, and does not certify reference similarity.

```python
from visual_fidelity.geometric_replay import mask, compose, evaluate, frame_schedule

reveal = {
    "kind": "strip", "center": [0.5, 0.5], "angle": -35, "width": 0,
    "keyframes": [{"frame": 0, "width": 0}, {"frame": 18, "width": 1.6}]
}
alpha = mask(reveal, width=720, height=1280, frame=9)
output = compose(base_rgb, inserted_rgb_or_rgba, alpha, foreground=optional_rgba)
times = frame_schedule("24000/1001", frames=240)
```

## Exact API

- `mask(spec, width, height, frame=None)` returns float32 `(height,width)` coverage
  in `[0,1]`. Pass a frame for animated specifications. Antialias transition is
  approximately one output pixel; polygons use 4× area sampling.
- `evaluate(spec, frame)` returns a new specification with inclusive integer
  keyframes resolved. Numeric parameters and equal-topology arrays interpolate
  linearly. Fields omitted by a key inherit the previous key. Values hold before
  the first and after the last key. Nested child masks may have their own keys.
  Discrete shape kinds/topology cannot interpolate.
- `compose(base, insert, mask, foreground=None)` returns a NumPy array matching
  the base's dtype and RGB/RGBA channel count. Inputs must share dimensions and
  be straight RGB/RGBA, either uint8 or floating `[0,1]`. Insert alpha multiplies
  coverage, and optional foreground overlays it using its own alpha. Arithmetic
  uses premultiplied RGB internally, then returns straight color. A foreground
  with only RGB is fully opaque. No implicit resize, color-space conversion,
  missing-area reconstruction, or alpha estimation is performed.
- `frame_schedule(fps, frames, start_frame=0)` returns float64 times calculated
  independently from a rational frame clock. FPS accepts positive numbers or
  rational strings. The endpoint is excluded: 24 frames at 24 fps are
  `0 … 23/24`, with an encoded duration of one second.

## Mask specifications

Normalized x uses image width; normalized y uses image height. Offscreen centers
and polygon points are allowed for entrances/exits. Angles are degrees clockwise
from image +x. Pixel centers are `(x+.5,y+.5)`.

| Kind | Parameters | Meaning |
| --- | --- | --- |
| `full`, `empty` | — | Constant one or zero coverage |
| `polygon` | `points:[[x,y],…]` | At least three finite normalized vertices enclosing area |
| `strip` | `center:[x,y]`, `angle`, `width` | Infinite strip; full thickness is `width × image height`, independent of angle/aspect ratio; angle 0 is horizontal |
| `x` | `center`, `angles:[-45,45]`, `width` | Union of two strips, same thickness convention |
| `bands` | `axis:"x"` or `"y"`, `intervals:[[start,end],…]` | Multiple intervals normalized to the selected axis; `vertical` aliases x, `horizontal` aliases y |
| `linear_gradient` | `axis:"x"` or `"y"`, `start`, `end` | Coverage 1 before start, linearly fading to 0 at end; defaults x, .61, .79; `invert:true` reverses coverage |
| `ellipse` | `center`, `radii:[rx,ry]`, `angle` | Pixel-space rotated ellipse; radii normalized to width/height respectively |
| `union` | `shapes:[spec,…]` | Maximum coverage |
| `intersection` | `shapes:[spec,…]` | Minimum coverage |
| `subtract` | `shapes:[a,b]` | Clamped coverage difference `a-b` |

An authored visor can use an ellipse or polygon without introducing any special
reference-specific coordinates. Every kind accepts `opacity` in `[0,1]` and
boolean `invert`, applied after shape evaluation. Zero-width strips, zero-area
bands, and zero-radius ellipses are empty. Polygon degeneracy is rejected.

Masks describe screen geometry only; use a separate RGBA foreground to preserve
occlusion by a helmet, motorcycle, person, or lettering. Validate the actual
result at scene boundaries and movement extremes, especially when photographic
layers have only partially recovered coverage.

For `linear_gradient`, start/end are normalized along the selected axis and
`end > start` is required. Sampling uses pixel centers; horizontal means x and
vertical means y. Unlike a geometric edge antialias, the gradient spans the
whole authored interval and can crossfade recovered photographic layers.

## Soft composite decomposition (1.0.1)

`decompose_observed(observed, base_guess, coverage)` accepts matching uint8 RGB
rasters and a finite [0,1] alpha mask. It returns an adjusted base and insert.
The guessed base is constrained to a feasible color interval before solving the
insert, preventing clipped highlights/vertical seams in feathered composites.
This is a non-unique coupled decomposition of observed pixels, not recovery of
hidden photography. Validate new geometry against the assets' observed support.
The regression test recomposes a synthetic high-contrast gradient within one
8-bit level, including alpha endpoints, without mutating the supplied guess.
