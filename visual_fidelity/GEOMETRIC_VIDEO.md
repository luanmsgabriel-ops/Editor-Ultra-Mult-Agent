# Geometric video editing from new raw footage

`python -m visual_fidelity.geometric_video timeline.json output.mp4`

Version 1.0.1 uses geometric_replay 1.0.1. The renderer opens only sources explicitly
bound in the manifest. It never loads reference footage implicitly.

A manifest supplies canvas width/height, frames/fps, assets, optional audio and
one frame binding for every output frame. Each source binding supplies an asset
key, integer source frame and an optional normalized center/zoom viewport
`[center_x,center_y,zoom]`. Views preserve aspect ratio and clamp to image bounds.

Frame fields:
- `base`, `insert`: image/video source bindings.
- `mask`: a geometric_replay specification; or `mask_file`: a grayscale alpha
  in base-source coordinates. The exact base viewport is also applied to it.
- `foreground`: source binding, `matte` path and optional normalized destination
  `box:[x,y,width,height]`. RGB and alpha share the same crop; placement uses
  premultiplied interpolation to prevent colored transparent-edge contamination.
- `tint`: optional RGB fill through a newly supplied matte and geometric mask.

Use a source-specific matte for every new subject. A portal anchored to an object
requires its own tracked/annotated mask; geometry from another helmet is not a
tracking result. Declare interpolated anchors and visible limitations. A fixed
view of the source may be digitally cropped; this is not a new camera angle or
3D scene reconstruction.

The example `examples/reference_replays/330494_application` reuses the geometric
families of reference329796 on new raw footage. Its photographic inserts are
crops from the new footage. One generated empty scene plate supports the collage
without a duplicated background subject. Source clocks and assets are explicit;
no photographic layer from the old reference enters this visual render.

Audio is separately bound, not inherited by the masks. A start and tempo may be
specified; default speed is 1. Do not infer publication rights from a private test.
The renderer writes the actual input, manifest, engine and export hashes.

Tests cover shared crop alignment, aspect preservation and premultiplied edge
interpolation; these are technical checks, not aesthetic approval.

`fit_insert_to_mask:true` fits the bound photographic insert into the current
portal bounds after transforming its matte. This uses a 2D aspect-preserving crop,
not a 3D optical reflection or a calibrated surface projection.


## Versão1.1.0 — contrato musical e de assets

Consulte REFERENCE_PLANNING.md e MUSIC_SYNC.md. O renderer exige music_sync e asset_plan para evitar repetição de fontes inadequadas e edição sem eventos musicais. Exceções editoriais ao sincronismo precisam ser declaradas no manifesto. A versão1.0.1 permanece congelada nos pacotes anteriores.
