# Local effect phase diagnostics

The operator can predeclare fixed optical regions, frame indices, thresholds
and hash-bound media in an `ultra-phase-pair/1` contract and run:

```sh
python -m editorial_engine.effect_phase_review \
  --active active.mp4 --control zero-strength.mp4 --contract comparison.json
```

Use a control encoded from the same source, pose, color, geometry, layering and
settings, with only refraction disabled. The diagnostic checks frame geometry,
presentation timestamps and file identity before analyzing decoded motion.
Recipe equivalence is checked outside this diagnostic by the operator. Exit
code 2 means at least one required optical phase is weak or not measurable;
0 means only that these numeric diagnostics meet their declared floors.
Neither result decides fidelity to a reference, final eligibility or approval.
Keep the same normalized regions and thresholds across variants. Regions must
be chosen independently before observing candidate metrics.

`visual_fidelity.motion_smear.smear` performs shot-local shutter integration on a
single, already placed, premultiplied RGBA foreground artwork. Supply three
bounded positions in output pixel coordinates and independently defined
protected regions. It does not smear the live video, create additional graphics
or extrapolate across shot boundaries. It implements translation, not optical
flow, rotation, focal blur or new footage generation. In the stock compositor
the consumer can integrate its output directly before a single composite; when
the consumer requires straight-alpha PNG, convert once at the renderer boundary.
The receipt records execution geometry; use a decoded on/off comparison to
verify actually visible changes.

These are local verifier and compositor components. No hosted independent
verifier authority or automatic preset selection is provided by them.
