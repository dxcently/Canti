# Roadmap: six phases, an A-versus-B shoot-out and a VOX-trained model

[Index](index.md) · [Hardware](hardware.md) · [Signal processing](signal-processing.md) · [Gestures and phrases](gesture-vocabulary.md) · [Decision models](decision-models.md) · [Phone control](phone-control.md) · [Prior art](prior-art.md) · [Latency and risks](latency-and-risks.md) · [Roadmap](roadmap.md) · [Sources](sources.md)

**Summary.** Every phase leaves a working demo:

1. A recording harness.
2. A Pico that works as a BLE HID device.
3. An Android app with profiles.
4. The baseline decision models (rules + Jev, Designs A and B, cursor mode, spoken phrases), benchmarked head to head.
5. **The VOX student pipeline, the main ML deliverable**, which starts once the baseline works end to end. An implementation is **being started in `~/VOX/finetune/`**.

Effort figures are judgment, not measurements.

## Phases

| Phase | Build | Exit test | Effort (judgment) |
|---|---|---|---|
| **0. Harness** | Python on the workstation or a Pi. Replay recordings through the exact float pipeline ([Signal processing](signal-processing.md)); record the first gesture and negative sets on the real mic chain | f0 and gate agreement with hand labels | ~1 week |
| **1. Pico HID** | I2S PIO+DMA, MPM via CMSIS-DSP FFT, features, gates, rule + DTW matcher with button-driven enrolment, fixed sound phrases; composite HOG mouse + keyboard + consumer control ([Phone control](phone-control.md#phase-1-ble-hid-without-an-app)); DWT cycle counts | Scroll a feed and a gallery on Android and iPhone | ~1–2 weeks |
| **2. Android app** | Encrypted GATT (EVENT, CONTOUR, STREAM, CONFIG) alongside HID; AccessibilityService with foreground-app tracking, profile resolver (global + per-app, fixed + rule), executor, overlay; re-record and binding UI; timestamp logging | End-to-end latency distribution; per-app bindings work | ~2–4 weeks |
| **3. Baseline decision models** | Rules + Jev end to end. Design A and B behind one flag; Jev cursor mode (intent overlay + grid sub-mode); open Jev-likes on the workstation behind the same `/v1/systemone` interface; opt-in push-to-talk spoken phrases | Head-to-head benchmark (below) | ~2–3 weeks |
| **4. VOX student (main ML deliverable)** | Pipeline below, in `~/VOX/finetune/` | Student vs RF vs Jev on held-out rules, users, negatives and latency | open (no time budget) |
| **5. Optional** | Local continuous cursor (pitch → velocity); PESTO ([arXiv 2508.01488](https://arxiv.org/html/2508.01488)) / YAMNet experiments; iOS configuration app | Fitts' throughput vs 1.65 bits/s ([ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)) | open |

## Phase 4: the VOX student pipeline

**Implementation status (2026-09-26).** Steps 1, 3 and 4 run end to end in `~/VOX/finetune/`: generator (v0–v5), three students, a shared evaluator and a sweep driver. Step 2 (teachers) runs but is weak, so it is secondary. Step 5 (phone export) waits on the Android app skeleton in `~/VOX/android/`. Results are in [Decision models](decision-models.md#results-so-far).

**Planning basis.** The fine-tune is not planned against a time budget. It runs step by step, and the smoke test measures real throughput first. Details and sources are in [Decision models](decision-models.md#fine-tuning-a-vox-student-main-ml-deliverable).

**Target.** Not label → action. The student learns to follow unseen plain-language rules, use foreground-app context, separate intent from none, produce cursor-mode intent, and map spoken text to actions.

**Day-one smoke test.** Push about **1,000 examples** through all five steps end to end: generation → teacher labels → a short student fine-tune → eval → ONNX export and a phone latency check. This measures real throughput on the workstation and proves the gfx1151 ROCm/PyTorch stack works before the full run.

| Step | What happens | Inputs | Output |
|---|---|---|---|
| **1. Synthetic generation** | Code samples states (gesture labels or phrases, spoken text, app, profile rules, recent actions, cursor context) and computes answers from the rule. **Rule templates and apps are held out** for eval. Real VOX recordings turned into features add heavy none negatives | Action catalogue, rule templates, Phase 2–3 logs | JSONL in Kev's `state` / `questions` / `label` format ([Kev](https://github.com/jaredpalmer/kev)) |
| **2. Teacher labelling** | For fuzzy cases, **JevK5 + Decider 4B** run locally behind `/v1/systemone` with a batched single-forward-pass option-logit readout ([news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)). Keep agreements; disagreements go to a small human- or Jev-checked review set. Jev also serves as a spot-check reference and for the calibration/eval split, subject to its terms | Step 1 fuzzy subset | Labels + soft probabilities |
| **3. Student fine-tune** | **jevlike** e5 scorer (leading), **Verdict-118M** ([Verdict](https://github.com/Manavarya09/verdict)) and **Kev 0.8B** LoRA ([Kev](https://github.com/jaredpalmer/kev)), compared on the same tests; data mixing after Together's recipe ([Together AI](https://www.together.ai/blog/how-to-train-your-own-jev)). No 4B student | Steps 1–2 | Checkpoint |
| **4. Calibration + eval** | Temperature fit; held-out rules, held-out users, none/false-trigger set, latency; RF vs student vs Jev | Held-out splits | Report: accuracy, false triggers/min, ECE, p50/p95 |
| **5. ONNX export + phone latency** | ONNX int8 in the Android app behind a local `/v1/systemone`-compatible interface, so a URL change switches models. Kev has no documented ONNX path, so verify it or use llama.cpp on Android | Calibrated checkpoint | On-device model + latency |

**Compute.** The user's **Strix Halo workstation** (Ryzen AI Max+ 395, Radeon 8060S gfx1151, 32 GiB GPU carve-out, NixOS with ollama, llama.cpp and HIP) is the main option. It is trainer, teacher host, synthetic-data host and benchmark laptop tier. PyTorch ROCm on gfx1151 is recent and pre-release, so **verify it** ([llm-tracker](https://llm-tracker.info/_TOORG/Strix-Halo)). A **rented H100** is the fallback, about $1 per Kev-4B run ([Kev](https://github.com/jaredpalmer/kev)).

**Licences.** The user accepted the contractual risk of distilling from JevK5 and Jev outputs for this class project. Decider is Apache-2.0 ([Decider](https://github.com/Mapika/decider)).

## Benchmark protocol

Every model uses the same protocol.

**Data:**

- Record on the Pico mic path at 16 kHz.
- Full plan: ≥10 users × 8 classes × 3 sessions × ≥20 repetitions, plus ≥30 min of negative audio per user (speech, laughter, coughs, TV, typing).
- Class-scale minimum: ~5 users × 2 sessions, with wider CIs.
- Add VocalSound negatives ([arXiv 2205.03433](https://arxiv.org/abs/2205.03433)).

**Fairness:**

- Every text model gets the **identical state and option list**, replayed from storage.

**Splits:**

- Leave-one-user-out.
- Per-user enrolment on the first 5 repetitions.
- A separate calibration split for every model, Jev included.
- **Held-out rules** for anything that reads rules.

**Metrics:**

- Macro-F1, **false triggers/min on negative audio**, misses.
- ECE over 15 bins, selective accuracy vs coverage.
- **p50/p95/p99 latency** logged on the device over ≥1,000 calls, on WiFi and on LTE/5G.
- Errors, cost, offline behaviour.
- Bootstrap 95% CIs and McNemar tests.

The protocol follows harnesses such as jev-benchmarks and DecisionBench ([news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)).

**Tiers** (each behind `/v1/systemone` where applicable):

| Tier | Models |
|---|---|
| Pico | rules + DTW, emlearn RF ([emlearn](https://github.com/emlearn/emlearn)) |
| Phone | YAMNet + prototypes ([MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/audio/audio_classifier)), Verdict, VOX student |
| Laptop (the workstation) | Decider 4B, JevK5, Kev |
| Cloud | Jev |

## A vs B head-to-head

Run over a few sessions per participant, since performance improves across days ([CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)).

| Task | Conditions | Metric |
|---|---|---|
| **Swipe task** (scripted feed, gallery, open-then-Back) | Design A; Design B with and without `template_match` | Completion time, errors, false actions |
| **Fitts'-style pointing** | Jev cursor mode; grid sub-mode; a local rule-driven cursor with the same intent schema | Throughput in bits/s vs Vocal Joystick 1.65 and a mouse's 4–6 ([ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)) |
| **False-trigger rate** | Every mode on negative audio | False triggers/min |

**Decision rule.** A network model earns its place only if both of these hold:

- It beats the local baseline on false triggers at equal recall, or on macro-F1 beyond the CI.
- Its p95 fits the action. For a tap, "< 300 ms" is already tighter than Jev's 437 ms ([HF index](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)).

## Open questions / to verify on hardware

- Is the **class-scale participant count** (about 5 users) enough, or can more be recruited?
- Does the **gfx1151 PyTorch ROCm** stack work under NixOS? This is the smoke test's first gate.
- **Smoke-test throughput** decides the full-run data size. There is no fixed budget.
- **JevK5 licence and TypeSafe terms** must be settled before Step 2 uses them.
- Which **Phase 3 logs** can be reused as real features for Step 1 without privacy issues?
