# Studio editor 0.8.0

A reusable manifest-driven editor for extracted studio footage and reference-led motion.
It calls the motion-kit 0.7 primitives directly; it does not copy those implementations
into a private video script. Media, project-specific words, source clocks and seeds
remain in the project bundle, outside Git.

## Run

```bash
python -m visual_fidelity motion-kit list
python -m visual_fidelity motion-kit check project/motion-kit-manifest.json
python -m visual_fidelity studio-edit project/edit47.json output.mp4
```

`--start` and `--end` use output frame indices, end exclusive. `--video-only`
supports independent render segments followed by one continuous audio mux. Each
export writes a `.render.json` report with the manifest hash, exact imported engine
file hashes, range, duration and the explicit source reuse clocks.

## Manifest contract

Pin `version: "0.8.0"`, set `source`, `mattes`, optional `audio`, `fps`, `frames`
and contiguous `shots`. Paths resolve relative to the manifest. This version
requires a normalized 720×1280 source and alpha sequence named `0000.png` etc.

A shot has `id`, `start`, `end`, `layers` and optional `background`, `person`,
`source`, `orbit`, and transition. A source clock has `start` and `speed`, in source
frame units. Out-of-range frames are errors unless `loop: true` is explicit.
Audio is a separately authored, continuous master: slowing a visual does not
silently stretch speech. Preserve the same source clock at visible speech cuts.

A transform has x/y, scale, angle, opacity, pivot and optional ordered normalized
keyframes in `keys`. Complete text layers can overlap without destructively cutting
glyphs. Supported layers: text, metric arc, transparent image/panel, PNG sequence,
and live optical lens. Lens x/y is the center; `radius`, `zoom` and angle control
the sampled enlargement and rim. This is a screen-space optical effect, not ray tracing.

Layers with negative z sit behind the subject. Other layers sit in front. An orbit
has separate front/back surfaces and uses the subject alpha only once. Sequence
backgrounds can carry real animated Blender camera passes. `quad_file` holds a
per-frame image quadrilateral, allowing a complete Portuguese poster to remain
attached to the matching wall plane.

## Subject extraction

`studio_matte.py` supplies supervised temporal GrabCut for fixed-camera, simple
studio footage. Supply a project-specific initial trimap. Persistent foreground
seeds protect white shoes and other foreground colors shared by the background.
Flow propagation and reports expose temporal instability. Source RGB is preserved.
This is not subpixel hair matting and is not a general background remover.

The subject remains a 2D cutout card. A 3D architecture pass does not make the
person volumetric, and cannot reveal unseen views. The authored contact shadow is
an approximation designed for a seated subject in this normalized studio layout.
Do not call this recovered camera/lighting or exact reconstruction.

## Lessons captured by this revision

- Preserve light clothing and thin chair legs with persistent internal seeds.
- Do not apply the rear-orbit alpha attenuation twice at a soft subject edge.
- Perspective layers must still respect their opacity and transforms.
- A magnifier must sample/enlarge the actual underlying pixels, rather than cover
  them with an opaque decorative disk.
- Test the actual words: a generated font's V may resemble U despite valid Unicode.
  Prefer a known font when visual glyph QA fails. Record the substitution.
- Preserve original spoken clauses and explicitly distribute them through longer
  graphic sequences when the user authorizes extending short footage.
- Inspect the encoded output, especially source reuses, shot joins, facial crops,
  text contrast and independent foreground layers. Tests do not certify likeness.

## Validation

90 Python tests pass in the exercised environment (2026-11-15), including 13 new
matte, studio renderer and lens tests. The 47.2917-second project actually executes
this editor and the existing orbit, sweep, type layout and layer modules. Physical
3D camera, target and keyhole PNG sequences are reused from the prior Cycles run;
they are not newly inferred 3D footage. User approval remains pending.
