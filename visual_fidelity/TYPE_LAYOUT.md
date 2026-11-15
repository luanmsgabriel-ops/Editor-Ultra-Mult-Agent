# Complete lettering and curved baseline typesetting

`type_layout.py` supplies two reusable operations. The words and frame numbers
belong in the reference adapter or preset, never in these primitives.

## Independent whole-word layers

Render each complete word using `text_mask(text, font)` or supply an authored
complete RGBA lettering. Declare `LetteringProvenance` honestly and place the
layers with `compose_layers`. Composition sorts by `z` and never subtracts the
foreground alpha from a lower source image. When the top word moves away, the
lower word remains whole.

Observed contours from an occluded frame are **fragments**. Setting
`complete=True` on `observed_fragment` without a reconstruction explanation
raises an error. The normal composition path rejects incomplete lettering.
Reconstruction may use a known font, an explicitly disclosed substitute, or
authored missing strokes. None of these is proof of exact original recovery.

Apply highlights to the intact layer before positioning and overlapping. The
independent `light_sweep` module preserves the alpha shape.

## Arc layout

`glyph_metrics` uses real glyph advances and pair kerning. `layout_arc` converts
their baseline distances into positions and tangent rotations on a circle.
`render_arc` draws each glyph about its baseline origin; space consumes its
proper advance without painting pixels. The API accepts an arbitrary Latin
phrase, font, center, radius, center angle, tracking and RGBA color.

```python
from PIL import ImageFont
from visual_fidelity.type_layout import render_arc
font = ImageFont.truetype('/path/to/licensed-font.ttf', 90)
image = render_arc((720,1280), 'Texto em curva', font,
                   center=(360,600), radius=330, center_angle=10,
                   tracking=-1, color=(255,255,255,255))
```

This is 2D layout, not geometric extrusion. The compositor can add shallow
shadows or use the returned positions in a separate 3D renderer. It deliberately
disables ligatures during individual glyph positioning. NFC composed Latin
text is supported; combining marks that cannot be NFC-composed should be passed
as complete shaped lettering layers. Joining scripts need a shaping-aware run
renderer, not independent character rotation. Pillow's RAQM text features must
be available for the feature-controlled kerning path.

## Regression evidence

`tests/test_type_layout.py` checks unequal-width advances, pair kerning,
tracking, source-alpha preservation through occlusion and reveal, fragment
provenance guards, descenders/overhangs and invalid geometry. Tests establish
these contracts; they do not certify likeness to a particular reference.

The private 329687 adapter uses full substitute-font words and a wide Montserrat
Black arc. Font identity, full-layer status and manual trajectory are recorded
in its asset provenance. Reference-specific media and fonts stay out of Git.
