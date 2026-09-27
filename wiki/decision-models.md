# Decision models: Jev, open Jev-likes and a VOX-trained student

[Index](index.md) · [Hardware](hardware.md) · [Signal processing](signal-processing.md) · [Gestures and phrases](gesture-vocabulary.md) · [Decision models](decision-models.md) · [Phone control](phone-control.md) · [Prior art](prior-art.md) · [Latency and risks](latency-and-risks.md) · [Roadmap](roadmap.md) · [Sources](sources.md)

**Summary.**

- **Jev** is a hosted, text-in "System One" decision model. It is fast for an LLM (252.8 / 436.6 ms median/p95) but slow for a controller, and its calibration depends on the task.
- **Design A (hybrid, recommended)** calls it only for rule bindings, rejected sounds and spoken text. **Design B** calls it for every action, and **Jev cursor mode** is Design B applied to pointing. Both are benchmarked against A.
- There are **no audio-native Jev-likes**.
- The main ML deliverable, after the baseline works, is a **VOX student**: Verdict-118M, with Kev 0.8B as fallback. It is distilled from JevK5 + Decider 4B on the user's Strix Halo workstation and deployed as ONNX int8 behind `/v1/systemone`.
  - **Update 2026-09-27 (librarian):**
    - Kev 0.8B was dropped ([D061](decisions.md#d061)).
    - Verdict is the chosen phone model ([D041](decisions.md#d041)). It is being retrained on real screens.
    - It is not served anywhere yet: there is no ONNX runtime in the app, and `systemone.py` serves only jevlike,
      decider-4b and jevk5.
    - Hard cases go to DeepSeek V4.1 Flash on Ollama cloud, not to Jev.
    - See [training.md](training.md) and [architecture.md](architecture.md#models-and-how-they-are-served).

## What Jev is, and which claims hold

Jev (jev-1.13.0) is a hosted, closed-weight model from TypeSafe AI, launched on 15 September 2026 ([Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model))). It takes a text or JSON `state` and named questions of three types: **choice** (up to 255 options), **score** (2–10 levels) and **noul** (a yes-probability). It returns typed answers with probabilities from `POST https://api.typesafe.ai/v1/systemone` ([TypeSafe API reference](https://docs.typesafe.ai/api.md); [State](https://docs.typesafe.ai/concepts/state.md)). Input costs **$0.042 per million tokens and output is free** ([Models](https://docs.typesafe.ai/models.md)). Access is still early access ([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)), and OpenRouter proxies the same format ([OpenRouter](https://openrouter.ai/docs/guides/community/jev)). Simon Willison: Jev "is currently not great with numbers, dates, or 'adversarial content'", and "evals and structured experiments are even more important" ([Simon Willison](https://simonwillison.net/2026/Sep/21/jev/)).

| Claim | Source | Status |
|---|---|---|
| "End-to-end response time is 70ms-500ms" | [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Vendor claim. Measured **252.8 / 436.6 ms** ([HF index](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)) and 236–276 ms ([Wilson Wu](https://wilsonwu.me/en/blog/2026/jev-vs-laya/)). **No phone/LTE figure** |
| "Calibrated" | [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | **Contested**: ECE 0.074 on the HF index, with mid bins overconfident by 7–16 points ([HF index](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)); **ECE 0.246** on a typed-decisions benchmark ([Wilson Wu](https://wilsonwu.me/en/blog/2026/jev-vs-laya/)) |
| "0%" type errors | [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | True by construction |
| "Can't hallucinate" | [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Marketing: it "can still emit a wrong valid value" ([HN](https://news.ycombinator.com/item?id=49767192)); "oversold" ([eesel](https://www.eesel.ai/blog/typesafe-jev-review)) |
| 40–200× faster, 444.6× cheaper | [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Compared against reasoning LLMs, the wrong class for VOX |
| Parallel sampling, RLCD training | [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Unverifiable |
| General-panel skill | [HF index](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json) | 51.67 vs 50.94 for the best open 27B; community-run index |
| 1,200 requests/min | [Models](https://docs.typesafe.ai/models.md) | "Can change without notice"; 429/529 exist |

## Designing the request: categorical state, only relevant rules

Jev "struggles with tasks that require numeric precision" and "does not count reliably". The docs say to "pass in either the computed number or a named bucket" ([Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)). Irrelevant detail lowers accuracy (same source). So the state holds **named buckets computed on the device**, the **foreground app**, the **profile rules that apply to that app** and any **recognised spoken phrase**. The options are the action catalogue plus an explicit `none` ([Choice](https://docs.typesafe.ai/primitives/choice.md)):

```json
{
  "model": "jev-1.13.0",
  "state": {
    "foreground_app": "Maps",
    "phrase": ["rise"],
    "gesture_details": {"sound_type": "voiced hum, clear tone", "contour": "rising", "excursion": "large (5-8 semitones)", "duration": "medium"},
    "template_match": "rise, strong match",
    "spoken_phrase": null,
    "profile_rules": ["In Maps, rise means zoom in and fall means zoom out"],
    "recent_actions": "none in the last few seconds"
  },
  "questions": {
    "action": {
      "type": "choice",
      "instructions": "Using the profile rules for the foreground app, which catalogue action did the user deliberately request?",
      "criteria": {
        "swipe_up": null, "swipe_down": null, "swipe_left": null, "swipe_right": null,
        "tap": null, "long_press": null, "back": null, "home": null,
        "pinch_out_zoom_in": "Spread two fingers to zoom in", "pinch_in_zoom_out": "Pinch two fingers to zoom out",
        "none": "Not a deliberate command, or no rule covers it: speech, laughter, cough, noise, ambiguous"
      }
    }
  }
}
```

- **Acting.** Act only when `choice != none` and confidence clears a threshold. The docs suggest not acting below 0.5 and confirming high-stakes actions above 0.9 ([Confidence](https://docs.typesafe.ai/confidence.md)). Start at about 0.6–0.7 for swipes and about 0.85 for tap, long-press and Back [design].
- **Confidence.** Jev reports confidence as (N·p_max − 1)/(N − 1), so with 11 options p_max 0.5 becomes 0.45 [EST].
- **Pin `jev-1.13.0`** ([Models](https://docs.typesafe.ai/models.md)).
- **Don't reuse a noul threshold for a choice question.** The same question asked both ways returned 0.22 and 0.01 ([jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)).
- **Recalibrate on VOX logs.** One out-of-domain study refit Jev's temperature to 2.7 ([news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)).
- **No fine-tuning.** Jev cannot be fine-tuned, so per-user adaptation lives in `state` ([Models](https://docs.typesafe.ai/models.md)).

## Design A vs Design B for discrete gestures

| | **Design A: hybrid (recommended default)** | **Design B: Jev decides every action** |
|---|---|---|
| Who decides | A fixed binding or template match within the reject threshold acts at once. The model handles rule bindings (cached per app), gated sounds that fail every template, and spoken phrases | Every gated event goes to the model with categorical labels, app and rules; local code only executes |
| Sound-end → finished swipe | ~0.2–0.45 s fast path [EST] | ~0.45–0.9 s (Jev 250/440 ms + ~40 ms RTT + BLE + stroke) [EST] |
| Continuous drag | Possible via `continueStroke` | Discrete swipes only; long-press is a fixed-duration press |
| Offline | Fast path works | Needs a local fallback, which turns B into A |
| Tests | Whether the model helps rejection, rules and speech at the margin | Whether a model beats rules on accuracy and false triggers enough to pay for latency |
| Main risk | Rejects get slower exactly when the user is unsure | Sluggishness: errors rose from 3.6% to 11.3% at 225 ms lag ([MacKenzie & Ware](https://www.yorku.ca/mack/CHI93b.html)) |

**Critique, stated once.** Fixed bindings are a lookup table, and rules can be cached per (app, phrase, rule version). So the model earns a per-event call only for open-ended inputs: sounds that match nothing, and spoken text. Run Design B **with and without** the `template_match` field. Otherwise the benchmark cannot tell the model's judgment apart from it agreeing with the template.

## Jev cursor mode is Design B applied to pointing

Only the device button toggles cursor mode ([Gestures](gesture-vocabulary.md)). It is not a model action. The overlay shows a distinct cursor and a "CURSOR" badge. The model returns **intent, not positions**. Three parallel questions go in one request:

| Question | Type | Options |
|---|---|---|
| `direction` | choice | N, NE, E, SE, S, SW, W, NW, none |
| `speed` | choice | slow, medium, fast |
| `control` | choice | continue, stop, click, recentre |

- **State.** A categorical summary of the last ~250–500 ms of the STREAM characteristic: pitch offset from start (well above / above / level / below / well below), contour slope, voicing, loudness bucket, pops, current cursor region ("upper-left third"), and the profile's cursor rules in words.
- **Animation.** The overlay animates at display rate along the last direction and speed.
- **Request cadence.** A new request every ~250–300 ms without waiting for the previous one (2–4 decisions/s, about 240 requests/min, a fifth of the published limit). Keep only the newest answer and discard out-of-order ones [design].

**Local safety rules:**

1. **Stop the instant the hum stops.** The Pico detects it, and the model is not consulted. This keeps the Vocal Joystick's property that the cursor "moves only while the user is vocalizing" ([ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)). Without it, overshoot is about 130 px at 300 px/s and 440 ms p95 [EST]. That is the failure of the constant-velocity "Speech Cursor", which took 155 s against 49 s on a 600-px circle (same source).
2. **Stop on model timeout** (~600 ms).
3. **Recentre** command, because users who lose the cursor cannot recover it by voice ([Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)).

**Click:** a pop (preferred) or dwell. Dwell carries the Midas-touch risk of head-tracker clicking ([eViacam](https://eviacam.crea-si.com/index.php/en/)).

**Direction mapping from hums** is an open problem. The default proposal: vertical from pitch offset above or below start; horizontal from arch- or dip-shaped modulation or a per-profile rule. The fallback is 4 directions.

**Grid-jump sub-mode.** The overlay draws a 3×3 grid, and the user picks a cell:

- Row by contour: rise = top, level = middle, fall = bottom.
- Column: dip = left, pop = centre, arch = right.
- Or a spoken "top left" when the speech module is on.

The model maps the input to one of 9 cells, "up a level" or none, and the grid refines recursively. On 1080 × 2400, three levels narrow the target to about 40 × 89 px [EST], and a pop taps the centre. This copies Dragon's Mouse Grid, which matched the Vocal Joystick for novices ([ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)). Model latency hurts least here.

Cursor mode is Android-only ([Phone control](phone-control.md)).

## Alternatives: the floor and the obvious candidates

| Candidate | Where | Evidence | Role in VOX |
|---|---|---|---|
| Rules + DTW | Pico | [design] | Fast path |
| emlearn ExtraTrees/RF (MIT) | Pico | 2–10 KB flash, < 2 KB RAM ([emlearn](https://github.com/emlearn/emlearn)); a 10-tree model matched a DL baseline ([Hackaday.io](https://hackaday.io/project/194511-1-dollar-tinyml/log/227053-activity-recognition-using-accelerometer-with-tree-based-ml-models)) | Benchmark floor; can't read rules |
| YAMNet + prototypes | Phone | 12.29 ms on Pixel 6 ([MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/audio/audio_classifier)) | Pops and none; audio-native |
| Hosted LLM with logprobs | Cloud | Mostly gone: Gemini 3.x ([forum](https://discuss.ai.google.dev/t/missing-logprobs-support-in-the-newest-gemini-models-3-1-pro-3-6-flash-on-vertex-ai-and-ai-studio/176557)), Groq ([docs](https://console.groq.com/docs/openai)), GPT-5 ([community](https://community.openai.com/t/logprobs-deprecated-for-gpt-5-models/1355427)). Haiku 4.5 $1/M ([pricing](https://platform.claude.com/docs/en/about-claude/pricing)) | Not recommended |
| Small LLM on Pi 5 | Pi | Qwen3-0.6B prefill 61.76 tok/s ([Adafruit](https://learn.adafruit.com/local-llms-on-raspberry-pi/qwen3)), which means seconds per call | Not recommended |

## Open Jev-likes compared

Index = chance-corrected skill / ECE on the community Decision Index 0.2, a general panel ([HF index](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)). None of these fit on the Pico. The "workstation" column refers to the user's Strix Halo machine (see [below](#the-workstation-is-trainer-teacher-host-and-laptop-tier)).

| Model (developer) | Size | Licence | Index / ECE | Runs on | `/v1/systemone` server |
|---|---|---|---|---|---|
| **Jev 1.13.0** (TypeSafe) | undisclosed | closed API | 51.67 / 0.074 | cloud | native |
| AutoJev-27B | 27.8B | unverified | 50.94 / 0.018 | workstation at Q4 **if a GGUF exists** (verify) | none found |
| Decider (Mapika) | 0.8/1.9/4.2B, 35B-A3B | Apache-2.0 | 4B: 36.58 / 0.084; 35B-A3B: 43.5 / 0.023 | 4B: laptop GPU / Mac (M1 Pro ≈ 133 ms) / workstation | yes, `pip install decider-ai` ([GitHub](https://github.com/Mapika/decider)) |
| **JevK5** | 4.66B | **unverified** | 36.44 / **0.027** | laptop GPU / workstation | wire-compatible runtime ([news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)) |
| Hopper (HopitAI) | 4.66B | unverified | 37.00 / 0.083 | laptop GPU | none found |
| Kev (Jared Palmer) | 0.8/4/9/27B | Apache-2.0 | 0.8B: 13.26 / 0.074; 4B: 31.31 / 0.176 | 0.8B on a 4 GB GPU; CUDA/ROCm/MLX | yes, `python -m kev.serve` ([GitHub](https://github.com/jaredpalmer/kev); [dev.to](https://dev.to/yanng981/open-source-jev-alternatives-system-one-models-you-can-self-host-i5e)) |
| Tev1 (Together) | 0.8B / 4B | unverified | 11.58 / 0.126; 26.32 / 0.104 | laptop; serverless $0.042/M | separate API ([dev.to](https://dev.to/yanng981/open-source-jev-alternatives-system-one-models-you-can-self-host-i5e)) |
| Bosun v3.1 (Hanno Labs) | 0.6B / 1.7B | unverified | 12.72 / 0.142; 17.91 / 0.130 | Pi 5 / laptop (GGUF) | yes, `jev-compatible-server` ([GitHub](https://github.com/Hanno-Labs/jev-compatible-server)) |
| Decision 1.0 Eos / Kai | 0.87B / 0.31B | Apache-2.0 | 17.49 / 0.083; 7.03 / 0.185 | phone / Pi | not stated |
| OpenThai-SystemOne | 0.8B | Apache-2.0 | not indexed | phone / laptop [EST] | Thai + English ([invide](https://blog.invidelabs.com/system-one-models-jev-laya-open-alternatives/)) |
| **Laya** (ConvAI Innovations) | 321–421M encoder | Apache-2.0 | 5.51 / 0.140 (base) | CPU, phone-class; 32.8 ms/question on T4 | yes, `laya-serve`, Ollaya ([awesome-jev](https://github.com/cobanov/awesome-jev)) |
| **Verdict** | 118M bi-encoder | Apache-2.0 | not indexed | phone/browser, ONNX int8 ~120 MB | yes, with `abstain` ([GitHub](https://github.com/Manavarya09/verdict)) |
| Von | 395M | Apache-2.0 | not indexed | CPU ([dev.to](https://dev.to/yanng981/open-source-jev-alternatives-system-one-models-you-can-self-host-i5e)) | not stated |
| GLiNER2.5-Decide | 0.49B (340M per dev.to) | not stated | 9.98 / 0.088 | CPU | not stated |
| Nimble (Bespoke Labs) | 9B | open source | not indexed; 292/324 vs Jev 302 ([invide](https://blog.invidelabs.com/system-one-models-jev-laya-open-alternatives/)) | workstation | **no**, custom API |

**Fine-tuning matters more than base scores.** Laya scored 0.34–0.36 zero-shot vs Jev's 0.727. Fine-tuned, it reached **0.766**, with ECE 0.081 after refitting temperature ([Wilson Wu](https://wilsonwu.me/en/blog/2026/jev-vs-laya/)).

## Audio-native Jev-likes do not exist yet

As of **2026-09-26** none were found:

- **Jev is text-only**: "No image, audio, or video input" ([Models](https://docs.typesafe.ai/models.md)).
- **All the open reproductions above are text-in.** Community catalogues list vision variants (Laya Vision, PlayJev) but no audio ones ([awesome-jev](https://github.com/cobanov/awesome-jev)).
- **Closest audio-native options:**
  - **Audio embeddings plus prototype classifiers.** YAMNet; EfficientAT mn04, 0.98M params ([EfficientAT](https://github.com/fschmid56/EfficientAT)); CLAP, where few-shot prototypes add 2–9 points ([arXiv 2507.20036](https://arxiv.org/html/2507.20036)).
  - **Audio LLMs**, which are poor at pitch. PitchBench puts frontier higher-vs-lower judgments at 52–65% (about 64% for the best; chance is 50%), and contour at "near 0%" ([arXiv 2605.26176](https://arxiv.org/html/2605.26176v1)). Contours must stay in DSP.
- **The gap.** A VOX-specific Jev-like, trained on VOX's categorical labels and rules, is a gap this project can fill.

## Fine-tuning a VOX student (main ML deliverable)

**Sequencing.** This comes after the baseline (rules + Jev) works end to end, because the baseline produces the schema, logs and eval harness.

**Target: not label → action**, which a tree already does. The student must learn:

- Following **unseen natural-language rules** (per-app profiles, custom bindings).
- Using **foreground-app** context.
- **Intent vs none.**
- **Cursor-mode intent**: direction, speed, stop, grid cell.
- **Spoken phrase text** → catalogue action.

**Pipeline** (no time budget; implementation being started in `~/VOX/finetune/`, see [Roadmap](roadmap.md#phase-4-the-vox-student-pipeline)):

1. **Synthetic generation.** Code samples (labels or phrases, spoken text, app, rules, recent actions, cursor context) and computes the answer from the rule. **Whole rule templates and apps are held out.** Kev's JSONL format (`state`, `questions`, a `label` per question) mirrors the `/v1/systemone` schema ([Kev](https://github.com/jaredpalmer/kev)).
2. **Teacher labelling on the workstation.** This is for fuzzy cases: intent vs none on real feature descriptions, loosely worded rules, spoken text. Run **JevK5** (ECE 0.027) and **Decider 4B** locally behind `/v1/systemone`, reading answers with a batched single-forward-pass option-logit readout ([news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)). **Keep agreements.** Disagreements go to a small review set checked by a human or by Jev. Also add **real VOX recordings turned into features, with heavy none negatives**.
3. **Student fine-tune.** Three students, compared on the same data: the user's **jevlike** option-attention scorer on a trainable e5 encoder (currently leading, see [results](#results-so-far)); **Verdict-118M** (on-phone ONNX int8 with abstain, [Verdict](https://github.com/Manavarya09/verdict)); and **Kev 0.8B** (rank-16 LoRA + pointer head on Qwen3.5, Apache-2.0, fits 4 GB, [Kev](https://github.com/jaredpalmer/kev)). Together's recipe (Qwen3.5-4B, 38,000 questions from 8 datasets) is a data-mixing reference ([Together AI](https://www.together.ai/blog/how-to-train-your-own-jev)). A 4B student is out of scope.
4. **Calibration + eval.** Temperature fit, then held-out rules, held-out users, the none/false-trigger set, and latency. Compare RF vs student vs Jev on accuracy, false triggers/min, ECE, and p50/p95.
5. **ONNX export and on-phone latency check.** Serve behind a local `/v1/systemone`-compatible interface, so switching models is a URL change. Kev documents no ONNX/GGUF export, so verify it or use llama.cpp on Android.

**Smoke test first.** Run about 1,000 examples through all five steps to measure real throughput before the full run.

**Terms and licences.** No law forbids distillation in general. The limits are contractual: model licences and API terms. The user accepted that risk for this non-commercial class project on 2026-09-26. Decider is Apache-2.0 ([Decider](https://github.com/Mapika/decider)); JevK5's and TypeSafe's terms are still unread.

### Results so far

All numbers come from synthetic data made by `vox/generate.py` and scored by `vox/evaluate.py`. There are no real recordings yet. Each data version has its own tests, so **only compare numbers within one test set**. Accuracies are top-1 over the options shown.

**Student: jevlike scorer, e5-small-v2 (33.5M), whole encoder trained, 40k rows, 3 epochs, ~41 min on the 8060S.**

| Training data | Test set | iid | Unseen phrasing | Unseen apps | ECE (unseen phrasing) |
|---|---|---|---|---|---|
| v1 (paraphrased action wordings) | v1 | 0.993 | 0.858 | 0.992 | 0.090 |
| v2 (larger training wording banks) | v1 | 0.993 | **0.918** | 0.992 | 0.055 |

The weak spots are rules worded in ways never seen in training. From v1 to v2, app rules went 0.686 → 0.802 and multi-sound sequences 0.669 → 0.826. Unseen apps are easy (0.99), because the app name is just a string to match against the rule.

**Small-budget comparison (4k training rows, v1 tests).**

| Model | Trained on | iid | Unseen phrasing | Unseen apps |
|---|---|---|---|---|
| jevlike e5-small | v1 | 0.953 | 0.755 | 0.950 |
| Verdict-118M bi-encoder | v0 | 0.935 | 0.783 | 0.930 |
| Kev 0.8B | v0 | 0.940 | not run (GPU OOM) | not run |

v0 data quoted the option text inside rules, so v0-trained models were first reported at ~95% on reworded rules. That number was string matching. On the fixed tests, Verdict-bi is on par with jevlike, not ahead.

**Local teachers (300-row smoke, v0 tests).** Decider 4B: 0.790 iid / 0.687 unseen. JevK5: 0.707 / 0.693, and it acted on 67–71% of rows that should be "none". The two agree on only 62–70%. They are used at most as a secondary soft target, never on the none / unbound / disabled / cursor kinds.

**Latency.** jevlike batch-1 on the iGPU: p50 22–44 ms. Verdict ONNX int8 on CPU: 7.9 ms. Jev: 253 ms median.

**Data versions.**
- **v3** fixed four label bugs that teacher disagreement exposed: junk sounds had a sequence line contradicting the sound; flat junk hums had big pitch changes; pops and clicks were described as "very short", like rejected hums; and held-out phrases leaked into training.
- **v4** adds an LLM-written wording bank, filtered against held-out wordings. It was written blind to the test set, and 13 of its wordings were exact copies of test wordings.
- **v5** is the target task. It uses the new defaults (hiss = back; pop-pop and click-click unbound; cursor mode on the button), adds a `screen:` line from the accessibility tree, and adds a `screen_phrase` kind where the screen settles a tie. The mode-switch actions are removed, and ~30% of rows list every option in table order, as the phone does, to avoid train/serve skew. Each test also has a full-option copy (`*.fullopts.jsonl`). Sweeps on v3–v5 are running.

### The workstation is trainer, teacher host and laptop tier

**Specs.** AMD Ryzen AI Max+ 395 (Strix Halo, 16C/32T), Radeon 8060S iGPU (gfx1151, RDNA 3.5), unified memory split into a 32 GiB GPU carve-out and about 30 GiB for the system. It runs NixOS with ollama, llama.cpp and HIP.

| Role | Notes |
|---|---|
| Student trainer (main option) | LoRA on Verdict-118M / Kev 0.8B should be comfortable. Kev lists ROCm ([Kev](https://github.com/jaredpalmer/kev)). **Verify PyTorch ROCm on gfx1151 first**: builds with gfx1151 kernels are recent and pre-release ([llm-tracker](https://llm-tracker.info/_TOORG/Strix-Halo)). NixOS packaging is also to verify |
| Local teachers | JevK5 + Decider 4B in bf16 (~9–10 GB each [EST]) side by side; AutoJev-27B Q4 (~16 GB [EST]) only if a GGUF exists (verify) |
| Benchmark "laptop tier" | Same `/v1/systemone` interface |
| Synthetic data host | Generation and labelling |
| Throughput caveat | ~256 GB/s theoretical, ~215 GB/s measured ([llm-tracker](https://llm-tracker.info/_TOORG/Strix-Halo)), much slower than an H100, so runs take hours |
| Fallback | Rented H100. Kev quotes "about $1" per Kev-4B run ([Kev](https://github.com/jaredpalmer/kev)); Together's tutorial ran ~25 min for ~$17 ([Together AI](https://www.together.ai/blog/how-to-train-your-own-jev)) |

## Open questions / to verify on hardware

- **Jev p50/p95 from the phone on LTE and WiFi**, logged on the device over ≥1,000 calls.
- **Jev's calibration on VOX data**: 0.074 or 0.246? Refit the temperature per model.
- **Answered:** PyTorch ROCm on gfx1151 under NixOS works (TheRock gfx1151 nightly, 28.3 bf16 TFLOPS measured). Verdict's bi-encoder follows held-out rules only as well as jevlike at 4k rows (0.783 vs 0.755); a full-size comparison is pending.
- Does **screen context** help phrase decisions without leaking into gesture decisions? Measure v5's `screen_phrase` vs the gesture kinds with adversarial screens.
- **Kev → ONNX** export path, or llama.cpp on Android as the alternative.
- Does an **AutoJev-27B GGUF** exist?
- **8-way cursor direction** from hums, or only 4?
- Cursor mode's **request cadence vs rate limits** (240/min against the published 1,200/min).
