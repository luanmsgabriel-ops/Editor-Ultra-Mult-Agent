# Verifying warm-to-cool emissive light

A frame with a warm spot does not demonstrate a transition. A spatially
uniform grade or an isolated compression spike is not an emitter.

`editorial_engine.thermal_emitter.analyze_thermal_pair` measures decoded BGR
frames from a render and an otherwise identical zero-emitter control. It binds
both inputs by SHA-256, requires a matching presentation clock, and checks a
warm-right pulse before a cool-left pulse in operator-defined windows. Each
phase needs consecutive frames with sufficient area and energy on the intended
side; samples outside both pulses serve as negative controls. The verifier
uses chromatic channel differences, so neutral brightness changes do not count.

Keep the time windows and thresholds outside the renderer's recipe. Verify
separately that the renderer disabled only this emitter in the control.
This diagnostic does not certify the source look, validate emitter material
identity, authenticate a hosted QA witness, or approve a render.
