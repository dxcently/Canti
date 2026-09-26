# Latency and risks: the budget the design is built around

[Index](index.md) · [Hardware](hardware.md) · [Signal processing](signal-processing.md) · [Gestures and phrases](gesture-vocabulary.md) · [Decision models](decision-models.md) · [Phone control](phone-control.md) · [Prior art](prior-art.md) · [Latency and risks](latency-and-risks.md) · [Roadmap](roadmap.md) · [Sources](sources.md)

**Summary.** A contour gesture is known only when the hum ends, and no model removes that floor. The Design A fast path finishes a swipe in about 0.2–0.45 s after the sound ends. A Jev path takes about 0.45–0.9 s, and an on-phone student about 0.2–0.5 s (all [EST]). In cursor mode, the local stop on silence is what keeps overshoot small.

## Latency budget (from end of sound)

| Step | Fast path (A) | Model path (A rules/rejects, all of B) | Cursor mode (per decision) |
|---|---|---|---|
| End-of-event detection | ~50–150 ms; taps and phrase prefixes wait ~300–600 ms | same | n/a (rolling 250–500 ms window) |
| Features, gates, DTW on Pico | < 1 ms | same | < 1 ms |
| BLE notify | ~15–50 ms ([AOSP](https://android.googlesource.com/platform/packages/apps/Bluetooth/+/31c02c5a770c0c12becb0856b2c7132470a49939%5E2..31c02c5a770c0c12becb0856b2c7132470a49939/)) | same | ~15–50 ms |
| Decision | ~0 (table or cache) | Jev **252.8 / 436.6 ms** ([HF index](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)) + ~40 ms mobile RTT ([Opensignal](https://insights.opensignal.com/2025/11/benchmarking-readiness-for-advanced-5g-consumer-services/dt)); student on phone ~10–40 ms [EST] | same; stop on silence is local |
| Execution | 100–250 ms stroke ([project-gameface](https://github.com/google/project-gameface)) | same | overlay animates at display rate |
| **Total** | **~0.2–0.45 s** | **~0.45–0.9 s (Jev); ~0.2–0.5 s (student)** | direction lag ~0.3–0.5 s; stop lag ~50–150 ms |

**Reference points:**

- Nielsen: 0.1 s is "instant" and 1 s keeps "flow" ([NN/g](https://www.nngroup.com/articles/response-times-3-important-limits/)).
- MacKenzie & Ware: errors rose from 3.6% to 11.3% at 225 ms lag ([MacKenzie & Ware 1993](https://www.yorku.ca/mack/CHI93b.html)).

**Rules:**

- Put a **hard timeout of about 600 ms** on every model call.
- Drop stale answers.
- In cursor mode, stop on timeout.

## Risk register

| Risk | Why it is real | Mitigation |
|---|---|---|
| Jev access and stability | Early access; rate limits "can change without notice"; 529 Overloaded ([TypeSafe docs](https://docs.typesafe.ai/models.md)) | Pin version; OpenRouter route; local fallback; timeout; VOX student |
| Miscalibration on VOX data | ECE 0.074 vs 0.246 depending on the benchmark ([HF index](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json); [Wilson Wu](https://wilsonwu.me/en/blog/2026/jev-vs-laya/)) | Recalibrate every model on a VOX split |
| False triggers | No published per-hour rate; studies used headsets in quiet rooms ([Mahmud et al.](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)) | Gate stack, arming, VocalSound negatives ([arXiv 2205.03433](https://arxiv.org/abs/2205.03433)), actions/min on negative audio |
| Cursor overshoot | 2–4 decisions/s is Speech Cursor territory ([ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)) | Local stop on silence; speed buckets; grid sub-mode |
| Phrase and tap delays | Prefixes wait for the gap window | Prefix-tree warnings; ≤3-element phrases ([Gestures](gesture-vocabulary.md)) |
| BLE injection | An unencrypted link drives an accessibility service | LE Secure Connections, key size 16 ([BTstack](https://github.com/bluekitchen/btstack/blob/master/example/gatt_streamer_server.gatt)), bonding, button-gated pairing |
| Android policy, installs, background mic | Autonomy clause ([Play policy](https://support.google.com/googleplay/android-developer/answer/10964491)); while-in-use mic limits ([FGS types](https://developer.android.com/develop/background-work/services/fgs/service-types)) | ADB install; `isAccessibilityTool`; user-initiated actions only; push-to-talk |
| iPhone ceiling | No touch injection ([Apple forums](https://developer.apple.com/forums/thread/129316)); Sound Actions overlap | HID only; state the honest value |
| Student fails on unseen rules | Verdict shown on intent data, not rule-reading ([Verdict](https://github.com/Manavarya09/verdict)) | Held-out-rules split; Kev 0.8B fallback; Jev stays available |
| Licences and terms | JevK5 licence unverified; TypeSafe output terms not found | Check before distilling; Decider is Apache-2.0 ([Decider](https://github.com/Mapika/decider)) |
| Parts and toolchain | INMP441 not recommended for new designs ([Digi-Key](https://www.digikey.com/en/products/detail/tdk-invensense/INMP441ACEZ-R7/2606606)); CMSIS ABI ([RPi forum](https://forums.raspberrypi.com/viewtopic.php?t=389775)); pico-tflmicro ([#18](https://github.com/raspberrypi/pico-tflmicro/issues/18)) | Spares; build from source; no NN on the Pico |
| Workstation training stack | gfx1151 PyTorch ROCm is recent and pre-release ([llm-tracker](https://llm-tracker.info/_TOORG/Strix-Halo)); NixOS packaging | Verify in the smoke test; rented H100 fallback |

## Open questions / to verify on hardware

- **Jev p50/p95/p99 from the phone** on WiFi and LTE/5G, over ≥1,000 calls.
- **End-of-event detection latency** for each gesture class on real recordings.
- **BLE notify latency** on the target phone.
- **On-phone latency of the student** in ONNX int8 on the actual device.
- **False triggers per minute** on ≥30 min of negative audio per user, in each mode.
- Whether users find the **~300–400 ms tap delay** acceptable.
