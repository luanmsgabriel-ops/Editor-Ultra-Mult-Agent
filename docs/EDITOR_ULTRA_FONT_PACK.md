# Reusable font resources for independent reconstruction

1. Identify an original with reuse rights first. If unavailable, review reference frames, record which glyphs were observed versus inferred, and create an authorized reconstruction or an original approximation. An atlas or an image of letters is not an installable font. Keep the atlas, editable outlines and static TTF or OTF with the authorized private asset package.
2. Import the fonts as `clone_resource`, using `font/ttf` or `font/otf`. Compute the SHA-256 of the exact font bytes. After review by a person, import the manifest as `clone_resource`, MIME `application/json`. Never commit private video or font files.
3. Pass the JSON asset ID as `reconstruction.font_pack_asset_id`. Do not combine that with direct font IDs. The optional `script_font` face is for kinetic subtitles; if absent the headline face must cover them too. This route does not change Motion Lab. Existing direct bindings remain backward compatible.
4. Preparation verifies static font bytes, declared rights and review, and file hashes. Direction checks glyph coverage for the actual titles and subtitles, with NFC accents. Render still verifies the bytes under the project path; neither this check nor the declared review establishes visual similarity or verifies a license independently.

Schema example (use your verified asset ID and replace the SHA-256):

```json
{
  "schema": "editor-ultra-font-pack/1",
  "styles": {
    "font": {
      "font_asset_id": "my-private-font-id",
      "format": ".ttf",
      "sha256": "replace-with-the-exact-sha256",
      "source_kind": "original_approximation",
      "rights_status": "reuse_verified",
      "provenance_note": "Approved original drawing; retain a link to rights and the glyph audit in the private project record.",
      "visual_review": "approved",
      "claims_exact_original": false
    }
  }
}
```

Allowed origins: `licensed_original`, `authorized_reconstruction`, `original_approximation`. The last two must declare `claims_exact_original: false`. Keep layout instructions, animation and compositing separate from the font.
