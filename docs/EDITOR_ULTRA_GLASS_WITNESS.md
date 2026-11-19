# Native refractive glass and delivery witnesses

The native planner can select `native.liquid_glass` with a verified runtime, an
explicit screen envelope, and bound protected regions on the source frame clock.
It reads the current framebuffer; it does not require a rendered badge or copy
pixels from a reference clip. The screen envelope includes an allowance for the
halo. If required evidence or per-frame execution is missing, the route fails
closed. It does not infer face masks, move the region with a hand, or claim visual
equivalence to a reference.

The renderer records refractive displacement estimates, affected pixels and
protection checks before encoding. These measurements establish execution, not
aesthetic fidelity: a smooth source can produce little visible optical change
even with a non-zero displacement map. A separate verifier can measure scoped
pixel changes before encoding and visible texture displacement after decoding,
using an aligned, otherwise identical zero-refraction control. Keep the same
verifier parameters across candidates. Do not infer leakage or visual approval
from a difference image of two lossy encodes. Bind accepted evidence to the
source, reference, recipe and final render with the per-effect gate.

Run targeted coverage with:

```sh
python -m pytest -q tests/test_glass_route.py tests/test_effect_witness.py
```

The tests exercise native MP4 creation and reject omitted source-clock evidence,
invalid inputs, and out-of-scope pixel changes. The witness is a reusable
verification component, not an automatic hosted acceptance workflow.
