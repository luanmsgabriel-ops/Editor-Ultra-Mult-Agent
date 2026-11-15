# Portable reference package

Freeze source media, instructions, fonts, layer assets, and scene bindings before
adaptation. The package is portable: no absolute root path is written in the
manifest. Verification checks bytes and declared required slots, never visual
similarity. User review remains `pending` or `rejected`; the command cannot grant
approval. Preserve the frozen manifest separately if a trusted baseline is
needed: hashes detect changes against that baseline, not malicious replacement
of both the assets and manifest.

```sh
python -m visual_fidelity.reference_bundle freeze /path/package /path/package/bundle.json --scene-map /path/scenes.json
python -m visual_fidelity.reference_bundle verify /path/package/bundle.json --root /path/package
```

Minimal scene map:

```json
{
  "user_approval": "pending",
  "scenes": [{
    "id": "opening",
    "required_slots": ["reference", "instructions"],
    "bindings": [
      {"slot": "reference", "path": "media/reference.mp4", "role": "reference-video", "layer": "source", "placement": {"frame_range": [0, 48]}},
      {"slot": "instructions", "path": "instructions.md", "role": "constraints", "layer": "metadata", "placement": {}}
    ]
  }]
}
```

Each scene declares unique required slots. Each binding has a unique slot, file
path, role, layer, and placement object. `placement` preserves project metadata;
it does not infer a camera, validate coordinates against an image, or execute a
compositor. Every binding must point to an inventoried file, including optional
bindings. Freeze attaches SHA256 and size; verify checks both against the file
and inventory. Directories must be represented by their actual asset files.

Default exclusions cover `.git`, `__pycache__`, `.cache`, `*.pyc`, and `*.log`.
The exact POSIX glob list is recorded, plus the output manifest's own path.
`--exclude 'previews/**'` adds a recorded exclusion. `--no-default-excludes`
keeps only explicit exclusions and the output manifest. A required binding to
an excluded file is an error. All symlinks outside excluded paths are rejected.

Verify is strict by default: extra unrecorded files also fail. `--allow-extra`
checks recorded assets and bindings while permitting added files. Missing,
altered, traversing, absolute, or duplicate asset paths always fail. CLI errors
return exit status 2 and a JSON error; success never implies accepted artwork.
