# Alternative decision models for VOX (other than Jev): accuracy fit, latency, cost, where they run

Research date: 2026-09-26. Scope: models that could replace or benchmark against Jev at VOX's decision stage (features → typed action up/down/left/right/click/scroll/mode/none), plus models that skip the text step and classify audio directly. Tiers: on-Pico (RP2350), **on-phone (Android first, iOS documented; now the main design: Pico → BLE GATT → companion app)**, Pi 5 / laptop, and cloud.

Jev background (API, 252.8 ms median / 436.6 ms p95, $0.042/M input, ECE 0.074, and its weakness with numbers) is in `jev.md` and is not repeated here. The Decision Index table in `jev.md` §8 covers the headline entrants. This file adds the small entrants, licences, runtimes and drop-in servers.

Markers: **[MEASURED]** means a number someone measured and published. **[EST]** is my estimate or arithmetic. **[VENDOR]** is a self-reported vendor claim.

---

## 1. Open Jev reproductions / System-One-style models: which fit a Pi 5, laptop or phone, and which ship a drop-in System One server?

### Takeaway
Many open reproductions exist. Only the sub-1B ones fit a phone, a Pi 5 or a laptop CPU at interactive speed: Decision 1.0 Eos/Kai/Lex, Kev 0.8B, Bosun v3.1 0.6B, MoJev, Tev1-0.8B, GLiNER 2.5, Verdict and Laya. On the general Decision Index they score only 2–17 chance-corrected, against Jev's 51.7. The 4B tier (Decider 4B, JevK5, Hopper) reaches about 36–37 with good calibration (JevK5 ECE 0.027), but it is laptop-GPU or Apple-Silicon class, not Pi class. Several projects ship a wire-compatible `/v1/systemone` server, so VOX could switch between Jev and a local model by changing the base URL. None of them has published measured latency on a Pi 5 or an Android phone.

### Cited Findings
**Small entrants on Decision Index 0.2** (chance-corrected skill / raw / accuracy / ECE / latency median-p95 in ms on 1× RTX PRO 6000; params). All figures are from [HF Space data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json), extracted with jq.

| Model | Params | Skill | Acc | ECE | Lat. med / p95 | Base / kind | Weights repo |
|---|---|---|---|---|---|---|---|
| Jev 1.13.0 (reference, HTTP) | n/a | 51.67 | 0.739 | 0.074 | 252.8 / 436.6 | closed | none |
| Hopper | 4.66B | 37.00 | 0.643 | 0.083 | 46.0 / 345.5 | Qwen3.5-4B LoRA | HopitAI/hopper |
| Decider 4B | 4.66B | 36.58 | 0.649 | 0.084 | 23.4 / 217.2 | Qwen3.5-4B full FT | Mapika/decider-4b |
| JevK5 | 4.66B | 36.44 | 0.648 | **0.027** | 21.9 / 253.7 | Qwen3.5-4B LoRA | alibiserikbay/JevK5 |
| Kev 4B | 4.66B | 31.31 | 0.616 | 0.176 | 52.5 / 196.8 | Qwen3.5-4B LoRA+head | jaredpalmer/kev-4b |
| Tev1-4B-experimental | 4.66B | 26.32 | 0.635 | 0.104 | 31.4 / 157.9 | Qwen3.5-4B full FT | togethercomputer/Tev1-4B-experimental |
| Decider 2B | 2.27B | 26.11 | 0.586 | 0.077 | 40.6 / 1003 | Qwen3.5-2B full FT | Mapika/decider-2b |
| this-that 1.2 (FLock) | 1.88B | 25.03 | 0.588 | 0.198 | 38.6 / 80.0 | from decider-2b | flock-io/this-that-model-1.2 |
| Decision 1.0 Sol | 2.27B | 22.90 | 0.544 | 0.115 | 39.6 / 135.7 | Qwen3.5-2B head | llm-semantic-router/Decision-1.0-Sol |
| Bosun v3.1 1.7B | 1.72B | 17.91 | 0.524 | 0.130 | 104.9 / 893.7 | Qwen3-1.7B LoRA+head | Hanno-Labs/bosun-v3.1-1.7b |
| Decision 1.0 Eos | 0.87B | 17.49 | 0.480 | 0.083 | 36.3 / 101.2 | Qwen3.5-0.8B head | llm-semantic-router/Decision-1.0-Eos-0.8B |
| Kev 0.8B | 0.87B | 13.26 | 0.484 | 0.074 | 41.2 / 108.0 | Qwen3.5-0.8B LoRA+head | jaredpalmer/kev-0.8b |
| Bosun v3.1 0.6B | 0.60B | 12.72 | 0.450 | 0.142 | 107.0 / 577.3 | Qwen3-0.6B LoRA+head | Hanno-Labs/bosun-v3.1-0.6b |
| Tev1-0.8B-experimental | 0.87B | 11.58 | 0.502 | 0.126 | 32.1 / 151.2 | Qwen3.5-0.8B full FT | togethercomputer/Tev1-0.8B-experimental |
| MoJev | 0.87B | 10.90 | 0.425 | 0.125 | 41.1 / 68.0 | Qwen3.5-0.8B tree-mask | MoLeMo-Lab/mojev |
| GLiNER2.5-Decide | 0.49B | 9.98 | 0.434 | 0.088 | 93.2 / 1259 | GLiNER full FT | fastino/GLiNER2.5-Decide |
| Decision 1.0 Kai | 0.31B | 7.03 | 0.358 | 0.185 | 30.0 / 34.4 | mmBERT-base encoder | llm-semantic-router/Decision-1.0-Kai |
| jeff | 0.58B | 6.74 | 0.382 | 0.097 | 21.4 / 69.5 | GLiFormer-large encoder | code only |
| Laya | 0.42B | 5.51 | 0.377 | 0.140 | 18.4 / 61.9 | ModernBERT-large + head | convaiinnovations/laya |
| system-one-gemma | 0.27B | 4.85 | 0.322 | 0.239 | 32.0 / 108.2 | Gemma-3-270m LoRA+head | code only |
| GLiNER 2.5 small | 0.07B | 3.88 | 0.332 | 0.161 | 14.5 / 38.4 | GLiNER | fastino/gliner2.5-small-v1 |
| Verdict (heman10x) | 0.15B | 1.82 | 0.369 | 0.154 | 10.6 / 61.4 | ModernBERT/GLiClass | heman10x/rlcd-modernbert-151m |

- The latency column is local GPU time with no network, which is not comparable to Jev's HTTP time. The panel is general knowledge and reasoning, not sensor classification. — [index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json); caveats in [jev.md §8](./jev.md)

**Drop-in `/v1/systemone` servers and their runtimes**
- **Hanno-Labs `jev-compatible-server`** implements "the Jev API contract" (`POST /v1/systemone`, choice/score/noul). It has **llama.cpp (GGUF), Transformers and CPU backends**, and runs with `uvx --from 'jev-compatible-server[transformers]' jev-compatible-server --model bosun-v3.1-0.6b`. Its "readouts" include token logits, decision tokens, pointer heads and hidden-state probes. No licence or latency was stated on the page. — [GitHub Hanno-Labs/jev-compatible-server](https://github.com/Hanno-Labs/jev-compatible-server)
- **Kev** (Jared Palmer): **Apache-2.0**, sizes 0.8B/4B/9B (Qwen3.5 bases) and 27B. The server is `python -m kev.serve --run jaredpalmer/kev-4b`. Runtime is Transformers on CUDA/ROCm or **MLX on Apple Silicon**, with no native CPU path mentioned and no GGUF. **[MEASURED by author]** Kev-0.8B takes **149 ms on an M5 Mac for new text and 28 ms cached**. Kev-4B takes 18.1 ms on H100 and 41.5 ms on L40S for six questions. Fine-tuning costs "about $1" per run on an H100. — [GitHub jaredpalmer/kev](https://github.com/jaredpalmer/kev)
- **Decider** (Mapika): **Apache-2.0 for code and weights**, sizes 0.8B/1.9B/4.2B/35B-A3B. Install with `pip install decider-ai`. The server speaks TypeSafe's `/v1/systemone` wire format and also has `/decide`. Backends are CUDA, **MPS (M1 Pro ≈ 133 ms median)**, **CPU (bf16, eager)** and vLLM. No GGUF is mentioned. Held-out ECE is 0.041–0.15. — [GitHub Mapika/decider](https://github.com/Mapika/decider)
- **Verdict** (Manavarya09; a different project from the heman10x "Verdict" in the index table): **Apache-2.0**. It is a multilingual-e5-small **118M** bi-encoder with prototype or logistic heads. It serves `/v1/systemone` ("point any Jev, Laya or impossibl client at `http://localhost:8000/v1/systemone`") and adds an `abstain` flag. **[MEASURED by author]** CPU latency is "single-digit ms" per query and 0.5–0.8 ms per example batched. The **ONNX int8 model is about 120 MB**, needs only onnxruntime + tokenizers, and runs in the browser. Fitting 16 labels per class takes **0.9 s on a laptop CPU**. Calibration is temperature scaling plus conformal (LAC) abstention. Scores: Banking77 0.86 at 16 shots, CLINC150 0.93 at 16 shots. — [GitHub Manavarya09/verdict](https://github.com/Manavarya09/verdict)
- Other wire-compatible servers:
  - **reflex**: stock Qwen3.5 behind `/v1/systemone`, WebGPU demo. "Temperature scaling gets Qwen3.5-4B to 0.039 ECE vs Jev's 0.031."
  - **LitJev**: any Qwen checkpoint, exact Jev schema.
  - **sgoedecke/system-one**: "wire-compatible with TypeSafe".
  - **snapjudge**: MLX.
  - **snellingio/system-one**: MLX Qwen3.
  - **daseinlabs/open-jev**: Gemma 3 4B MLX shim.
  - **openjev-sglang**: Qwen3.6-35B-A3B.
  - **JevK5**: CUDA-graph runtime.
  - **Xor**: Juspay.
  - **razorback16/openjev**: public host at api.codiv.ai.
  - **GitHub Next LocalJev**, which "prompts for JSON probabilities instead of reading logits: wire-compatible, not equivalent".

  — [HF Space news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- **Tev1-4B-experimental** (Together AI) is "on Together serverless at $0.042/M input", which is Jev's price. It comes with a data recipe and a train-your-own tutorial. — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html); [Together blog](https://www.together.ai/blog/how-to-train-your-own-jev)
- **Decision 1.0** (vLLM Semantic Router team) is **Apache-2.0**. Kai and Lex are 572M-class encoders (the index lists 0.31B served params). Sol is 1.88B and Nox 4.21B; Eos-0.8B and Lux-9B followed. — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- **rlcd-modernbert-151m** (heman10x) is Apache-2.0, "scoring 25 candidate slots, abstention included, in under 35ms", with a WebGPU playground. — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- **PocketJev** runs Qwen3-VL locally on an iPhone via MLX and returns direct option logits in about 1 s. — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- "jev-on-a-laptop": Qwen 2.5 7B reaches 73.8% agreement with Jev's cases (Jev itself 86.6%) at **0.4–2 s per decision** on a laptop. The author "Finds confidence does not reliably flag errors." — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- Licence flags:
  - Gemma-based entrants (system-one-gemma, Winnow, Rune, Jev-Omni) inherit the **Gemma licence** (use restrictions), not Apache — [Gemma3-1B-IT card lists "License: Gemma"](https://huggingface.co/litert-community/Gemma3-1B-IT).
  - The Qwen3.5-based Kev and Decider state Apache-2.0 ([Kev](https://github.com/jaredpalmer/kev), [Decider](https://github.com/Mapika/decider)).

### Inferences
- **Fit for VOX:** VOX's decision is a narrow 8-way choice over a few bucketed features. General-panel skill understates what a small model can do once it is **fine-tuned on VOX data**, and overstates what it does zero-shot. Kev's fine-tune example (67.7% → 73.6% on custom routing) and Verdict's 16-shot results suggest few-shot fitting is the right mode, not zero-shot prompting.
- **Pi 5 / phone feasibility [EST]:** encoders of 0.07–0.5B (Verdict-118M, GLiNER 2.5 small, Decision Kai/Lex, rlcd-modernbert-151m) via ONNX Runtime should land at single-digit to tens of ms on a phone or Pi 5 CPU. Verdict's author measures single-digit ms on laptop CPUs, and a Pi 5 is perhaps 3–6× slower. 0.6–0.9B decoders (Bosun 0.6B via GGUF, Kev/Eos/Tev1 0.8B) are probably a few hundred ms on a Pi 5 CPU with prompt caching and about 1–3 s without it (see §2 for Pi prefill rates). The 4B tier is 1–10+ s on a Pi 5 and not interactive.
- **Most practical drop-in:** Hanno's server is the only one found that advertises both llama.cpp GGUF and CPU, so it is the natural Pi/laptop harness. Verdict is the natural phone or browser candidate: ONNX, 120 MB, wire-compatible, with abstain built in.

### Gaps
- No published Pi 5 or Android latency exists for any Jev reproduction.
- Licence text was not verified for Bosun, JevK5, Hopper, Tev1 or MoJev.
- GGUF availability for Decider, Kev and Decision 1.0 was not found.

---

## 2. Small local LLMs with constrained decoding as classifiers (Pi 5 / laptop), and getting calibrated class probabilities

### Takeaway
For a one-token classification, **prefill speed (prompt tokens/s) is what matters, not generation speed**. On a Pi 5, sub-2B models prefill at only about 60–180 tok/s (Ollama) or 29–61 tok/s in some llama.cpp builds. A 300-token prompt therefore costs about 2–5 s unless the fixed prefix (instructions plus option list) is KV-cached so that only about 20–40 feature tokens are new, which gives an estimated 0.2–0.7 s. Laptops are 5–10× faster. For Jev-like probabilities, **read the logits of single-token option labels** (restricted softmax over the option tokens), then temperature-scale on VOX data. Do not trust generated JSON "confidence" fields.

### Cited Findings
**Pi 5 measured throughput**
- **[MEASURED]** Pi 5 8 GB, Ollama `qwen3:0.6b`: **prompt eval 61.76 tok/s, eval 16.62 tok/s**, load 155 ms. — [Adafruit: Local LLMs on Raspberry Pi – Qwen3](https://learn.adafruit.com/local-llms-on-raspberry-pi/qwen3)
- **[MEASURED]** Pi 5 16 GB, Ollama:

  | Model | Prompt tok/s | Gen tok/s | TTFT |
  |---|---|---|---|
  | deepseek-r1:1.5b | 183.1 | 11.5 | 0.243 s |
  | gemma4:e2b | 99.2 | 7.6 | 0.585 s |
  | qwen2.5:3b | 178.4 | 6.0 | 0.661 s |
  | llama3.2:3b | 164.1 | 5.9 | 0.629 s |

  Native llama.cpp (DotProd build) on the same board had *lower* prefill: 60.7, 45.4 and 28.9 tok/s for 1.5B, E2B and 3B. — [GitHub pi5-llm-arena](https://github.com/leemailto2008/pi5-llm-arena). Note: the prompt lengths differ between the two runs, so the Ollama vs llama.cpp prefill gap may be an artefact of the test.
- **[MEASURED]** Pi 5 8 GB, Llama 3.2 3B: 4.61 tok/s eval. Framework 13 (Ryzen AI 5 340) laptop: 23.81 tok/s. — [geerlingguy/ai-benchmarks](https://github.com/geerlingguy/ai-benchmarks)
- Survey of 25 models (Ollama, q4_k_m) on a Pi 5: sub-360M models > 20 tok/s, up to 1.5B at 5–15 tok/s, 3B at 2–5 tok/s. Pi 4: ≥1B models < 5 tok/s. — [arXiv 2511.07425](https://arxiv.org/html/2511.07425v1)
- Gemma 3 1B reportedly runs at about 10–22 tok/s generation on a Pi 5. The figures come from secondary blog posts and conflict. — [kunalganglani Gemma 3 Pi 5](https://www.kunalganglani.com/blog/gemma-3-raspberry-pi-5-benchmark) (search snippet only)
- **[MEASURED by author]** On Apple Silicon: Kev-0.8B takes 149 ms uncached and 28 ms cached ([Kev](https://github.com/jaredpalmer/kev)). Decider on an M1 Pro has a median of about 133 ms ([Decider](https://github.com/Mapika/decider)).

**Constrained decoding runtimes**
- llama.cpp server `/completion` options:
  - `grammar` (GBNF) and `json_schema` for "grammar-based sampling".
  - `n_probs`: "the probabilities of top N tokens for each generated token given the sampling settings".
  - `post_sampling_probs`: probabilities "after applying sampling chain".
  - `cache_prompt`: default enabled.
  - `logit_bias`.

  The `/v1/chat/completions` endpoint supports `response_format` json_schema. The README does not mention logprobs for chat. — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- Ollama structured outputs: the `format` field takes a JSON schema, which Ollama uses for grammar-constrained decoding. Reported caveats: property `description` is silently ignored, and there is an open adherence issue for Qwen 3.5/3.6 (April 2026). — [Ollama docs](https://docs.ollama.com/capabilities/structured-outputs); [makandra card (secondary)](https://makandracards.com/makandra/626409-ollama-structured-input-output)
- **Ollama logprobs** have been in the native and OpenAI-compatible APIs since **v0.12.11**, via `logprobs: true` and `top_logprobs: N`. `top_logprobs` is capped at 20, and a PR proposes 100. A separate PR proposes `logprob_tokens` to get logprobs for caller-named tokens, because at present "Cannot get the log probability of a specific token unless it ranks in top_logprobs". — [Ollama v0.12.11 release](https://newreleases.io/project/github/ollama/ollama/release/v0.12.11); [PR #18591](https://github.com/ollama/ollama/pull/18591); [PR #18580](https://github.com/ollama/ollama/pull/18580); [issue #18579](https://github.com/ollama/ollama/issues/18579)
- XGrammar computes grammar masks in **< 40 µs per token** for JSON schema. It has been the default in vLLM, SGLang and TensorRT-LLM (as of March 2026). llama.cpp's grammar sampler walks the full vocabulary (about 152k tokens for Qwen3.5) per token on the CPU, which one source puts "on the order of the 1.5 ms LM head" (a GPU figure). — [XGrammar paper](https://arxiv.org/pdf/2411.15100); [MLC blog](https://blog.mlc.ai/2024/11/22/achieving-efficient-flexible-portable-structured-generation-with-xgrammar); [zolotukhin.ai](https://zolotukhin.ai/blog/2026-07-22-constrained-decoding-scans-the-vocabulary-twice-per-token/)

**Probability readout techniques used by reproductions**
- Jobe: "the restricted softmax over the options' answer-letter logits on a frozen Qwen3.5-4B … one forward pass … No training." openjev reads option logits: "21 decisions in 1.02s vs 5.33s for JSON". sgoedecke: "Batched single-token choice inference". Xor and reflex-27B score "forward and reverse option order", then calibrate. Hopper sets temperature "by option count, state length, answer type and entropy". — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- reflex: temperature scaling brings stock Qwen3.5-4B to **ECE 0.039**. — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- mini-jev is a preregistered study of letter-logit vs grammar-JSON decoding on frozen Qwen3-4B with CLINC150. — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- An independent calibration study of Jev refit temperature 2.7 on an unseen rule-generated task, vs 0.96–1.35 on benchmarks. — [scienthoon/jev-ood-calibration via news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)

### Inferences
- **Recipe for Jev-style confidence from a local LLM [design]:**
  1. Give each action a label that tokenizes to one distinct token (A–H, or single-token words).
  2. Ask for one token with `n_predict=1` and read `n_probs ≥ 8` (llama.cpp) or `top_logprobs ≥ 8` (Ollama, cap 20). Renormalize over the 8 option tokens only. Don't use a JSON grammar here: it adds tokens and the "confidence" field is generated text, not a probability.
  3. Average the probabilities over two option orders to cancel position bias.
  4. Fit one temperature T on a held-out VOX calibration split (minimize NLL).
  5. Compute Jev's confidence as (N·p_max − 1)/(N − 1), so the thresholds carry over.
- **Latency arithmetic [EST], Pi 5, Qwen3-0.6B, about 60 tok/s prefill:**
  - Uncached 300-token prompt: about 5 s.
  - With `cache_prompt` and a fixed prefix, and only about 30 new tokens: about 0.5 s, plus 1 decode step (about 60 ms). Roughly **0.5–0.7 s**.
  - For 1.5B at about 180 tok/s (Ollama): about 0.2–0.3 s cached.
  - These are slower than Jev's p50 and give a worse accuracy prior. The Pi tier only makes sense for offline or privacy use.
- **Laptop [EST]:** 0.6–1B models on a modern laptop CPU should prefill at several hundred to about 1,000+ tok/s, so a cached call is roughly **30–150 ms**, consistent with Kev-0.8B's 28–149 ms on an M5.

### Gaps
- No Pi 5 llama-bench pp512 numbers were found for Qwen3/3.5 0.6–1.7B, Gemma 3 1B, Llama 3.2 1B or SmolLM specifically. Only Ollama eval rates were found.
- No measurement exists of llama.cpp grammar overhead on an ARM CPU.
- Outlines was not researched in depth; XGrammar and llama.cpp cover the same function.

---

## 3. Hosted LLM APIs with structured outputs for classification

### Takeaway
Every major hosted small model supports JSON-schema output. **Few still return logprobs.** Anthropic offers none (see Gaps). Google confirmed logprobs are "no longer returned for 3.X models". OpenAI's GPT-5-family reasoning models reject `logprobs`, and Groq rejects them with a 400. Logprob-capable hosted options are now legacy non-reasoning models: `gpt-4.1-nano`/`mini`, `gpt-4o-mini`, and Gemini 2.5 Flash, whose Flash-Lite sibling retires on 2026-10-16. TTFT for a short call is about 0.3–0.6 s at the fast end, comparable to or slower than Jev. Price per decision is 2–25× Jev's.

### Cited Findings
**Prices** (per 1M tokens, input / output)
- OpenAI:
  - `gpt-5-nano` $0.05 / $0.40
  - `gpt-5.4-nano` $0.20 / $1.25
  - `gpt-5-mini` $0.25 / $2.00
  - `gpt-4.1-nano` $0.10 / $0.40
  - `gpt-4.1-mini` $0.40 / $1.60
  - `gpt-4o-mini` $0.15 / $0.60

  — [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- Google:
  - `gemini-2.5-flash-lite` $0.10 / $0.40
  - `gemini-3.1-flash-lite` $0.25 / $1.50
  - `gemini-3.5-flash-lite` $0.30 / $2.50
  - `gemini-3.6/3.7/3.8-flash` $0.75 / $3.75
  - All have a free tier with "limited access".

  — [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing). Gemini 2.5 Flash-Lite retires on **16 Oct 2026** — [CloudZero (secondary)](https://www.cloudzero.com/blog/gemini-pricing/)
- Anthropic: **Claude Haiku 4.5 $1 / $5**, cache hits $0.10, batch $0.50 / $2.50. — [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- Groq:
  - `llama-3.1-8b-instant` $0.05 / $0.08 — [CloudZero (secondary)](https://www.cloudzero.com/blog/groq-pricing/).
  - Groq reportedly told users on 2026-06-17 that llama-3.1-8b-instant **shuts down on 2026-08-16**, with gpt-oss-20b/120b and qwen3.6-27b as replacements — [search summary citing Groq](https://console.groq.com/docs/model/llama-3.1-8b-instant). Groq's models page (fetched today) **still lists Llama 3.1 8B at 560 tps**, so the two sources conflict.
  - GPT-OSS 20B: $0.075 / $0.30 at about 1,000 tps. — [Groq models](https://console.groq.com/docs/models)

**Logprobs**
- Groq: `logprobs`, `top_logprobs` and `logit_bias` are unsupported and return 400. — [Groq OpenAI compatibility](https://console.groq.com/docs/openai)
- OpenAI reasoning models (o-series, GPT-5 family including nano) don't accept `logprobs`/`top_logprobs`/`logit_bias`/`temperature`. For GPT-5.5+, the API rejects logprobs when reasoning effort is left at the default. — [OpenAI community](https://community.openai.com/t/logprobs-deprecated-for-gpt-5-models/1355427); [Azure reasoning docs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning)
- Gemini: a Google representative wrote on 2026-08-05, "logprobs are no longer returned for 3.X models" (working as intended). Gemini 2.5 Flash still works. — [Google AI dev forum](https://discuss.ai.google.dev/t/missing-logprobs-support-in-the-newest-gemini-models-3-1-pro-3-6-flash-on-vertex-ai-and-ai-studio/176557)

**Latency**
- **[MEASURED, 3 runs, Toronto, ~200-token prompt]** TTFT p50:

  | Model | TTFT p50 |
  |---|---|
  | Claude Haiku 4.5 | ~597 ms |
  | Gemini 2.5 Flash | ~450 ms |
  | GPT-4.1 | ~1,100 ms |
  | GPT-4.1 mini | ~2,400 ms |

  — [kunalganglani LLM API latency 2026](https://www.kunalganglani.com/blog/llm-api-latency-benchmarks-2026)
- Artificial Analysis (via search snippets): Gemini 2.5 Flash-Lite (non-reasoning) TTFT **0.30 s**, the lowest listed. Groq Llama 3.1 8B TTFT 0.81 s. — [Artificial Analysis](https://artificialanalysis.ai/models); [AA Llama 3.1 8B providers](https://artificialanalysis.ai/models/llama-3-1-instruct-8b/providers) (snippets, not fetched)
- An "imposter Jev" gateway on Cerebras with Qwen 3.8 27B was found to have "Similar quality and speed; TypeSafe far cheaper." — [iammrduncan/typesafe-ai-benchmark via news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)

### Inferences
- **Cost per decision [EST]**, assuming 300 input + 3 output tokens:

  | Model | Cost per call | Multiple of Jev |
  |---|---|---|
  | Jev | $0.0000126 | 1× |
  | gpt-4.1-nano / Gemini 2.5 Flash-Lite | ≈$0.000031 | 2.5× |
  | gpt-5-nano | ≈$0.000016 + hidden reasoning tokens | — |
  | Gemini 3.1 Flash-Lite | ≈$0.00008 | — |
  | Claude Haiku 4.5 | ≈$0.000315 | 25× |

  At 3,600 decisions per hour, Haiku costs about $1.13/h and gpt-4.1-nano about $0.11/h. All are cheap in absolute terms for one user.
- **Calibration:** without logprobs you only get verbalized confidence. For a "should I click?" gate, only **gpt-4.1-nano/mini or gpt-4o-mini** (logprobs available) can be calibrated the Jev way. They are legacy models, so there is deprecation risk.
- **Latency:** none of these beats Jev's 253 ms median. Over mobile data, add cellular RTT (§7).

### Gaps
- No Anthropic doc was found stating that logprobs are absent. None of the pricing and feature pages reviewed list a logprob feature, and this was not confirmed against the Messages API reference in this session.
- No first-party TTFT p95 was found for any provider. Cerebras pricing and model list were not fetched.

---

## 4. Classic lightweight classifiers on the Pico (the baseline Jev must beat)

### Takeaway
Tree ensembles, Gaussian NB, small MLPs and kNN over the numeric features (f0 mean/slope, duration, energy, pulse count, flatness) export to C with **emlearn (MIT, maintained)**. They fit in **about 2–10 kB of flash and under 2 kB of RAM**, and infer in **microseconds to about 100 µs**, on the Pico itself with no radio in the loop. With the vote fraction or softmax plus a calibration step and an explicit "none" class, they give calibrated confidence. This is the floor any model must beat on accuracy, and no model can beat it on latency.

### Cited Findings
- **emlearn**: MIT licence. Supports Random Forest, Extra Trees, Decision Trees, MLP, Gaussian Naive Bayes, and Elliptic Envelope / GMM for anomaly detection. Works on "anywhere that has working C99 compiler" (ESP32, AVR, Cortex-M STM32, …). "Small code size (from 2kB FLASH)", "Small RAM size (from 50 bytes RAM)". Some models support integer/fixed-point. — [GitHub emlearn](https://github.com/emlearn/emlearn)
- **emlearn-micropython** adds **kNN with on-device learning**, RF/DT, CNN (via TinyMaix), linear regression with on-device learning, K-means, and FFT/IIR feature modules. Claims "inference times down to 100 microseconds, RAM usage <2 kB, FLASH usage <2 kB". Runs on most MicroPython ports via native `.mpy` modules, including RP2040/RP2350. — [emlearn-micropython README](https://github.com/emlearn/emlearn-micropython/blob/master/README.md)
- **[MEASURED]** Accelerometer activity RF with emlearn on a Puya PY32F003 (4 kB RAM / 32 kB flash): 50 trees at depth 9 took about 50 kB. **10 trees took about 10 kB (loadable) or about 5 kB (inline, 8-bit integer)** and matched the deep-learning baseline. The whole model plus buffers fit under 2 kB of RAM. — [Hackaday.io "1 dollar TinyML"](https://hackaday.io/project/194511-1-dollar-tinyml/log/227053-activity-recognition-using-accelerometer-with-tree-based-ml-models)
- Optimized RF kernels reach **4.5 µs** latency on RISC-V MCUs. — [IEEE TCAD 2022 (abstract)](https://dl.acm.org/doi/abs/10.1109/TCAD.2022.3199903)
- On an nRF52840 (Cortex-M4), Random Forest had the lowest inference time of the ANN/RF/GNB models compared, with similar accuracy at high SNR. — [emlearn "Made with"](https://emlearn.readthedocs.io/en/latest/made_with.html) (search summary)
- **micromlgen**: MIT. Exports SVC, OneClassSVM, RVM, DecisionTree, RandomForest, **XGBoost**, GaussianNB, SEFR and PCA to C++ headers. The repository was **archived on 2024-05-25**, and the author points to `tinyml4all-python` as its successor. — [GitHub micromlgen](https://github.com/eloquentarduino/micromlgen)

### Inferences
- **Which classic model:**
  - **ExtraTrees or RF (10–20 trees, depth ≤ 8) on about 10–20 numeric features plus a "none" class** is the first baseline. Train it with background, speech, cough and laugh negatives.
  - A **logistic regression or 1-hidden-layer MLP** is the second. It gives smoother probabilities for ECE.
  - **kNN over per-user enrolment examples** (emlearn-micropython supports on-device learning) is the per-user variant. It pairs with the DTW templates in `signal_processing_and_ml.md` §6.
- **Calibration [design]:** RF vote fractions are not calibrated. Fit Platt or isotonic calibration (or softmax temperature for LR/MLP) offline in sklearn and bake the mapping into a small lookup table on the Pico. Report ECE the same way as for Jev.
- **Size and speed on RP2350 [EST]:** at 150 MHz, a 10-tree depth-8 forest is about 80 compare/branch steps, so **< 20 µs**. An MLP of 16→32→9 is about 800 MACs, so **< 50 µs** in float with the M33 FPU. Both are negligible next to BLE and are 4–5 orders of magnitude faster than any network model.
- **GBDT:** emlearn does not list gradient boosting. Use micromlgen's XGBoost export (archived but functional) or m2cgen (not researched here).

### Gaps
- No measured RP2350 inference time was found for emlearn trees or MLPs. The figures above are extrapolated.
- m2cgen and tinyml4all were not reviewed.

---

## 5. Audio-native models that skip the text step

### Takeaway
Skipping serialization is attractive, but **pitch direction is the key VOX feature, and audio LLMs are bad at it**. On PitchBench, frontier audio LLMs judge higher vs lower at only 52–65% (chance 50%), and discrete melodic contour at near 0% for most models. General audio embeddings (YAMNet, EfficientAT, BEATs, CLAP) work at the scale of about 1 s windows and are tuned for sound *categories* (cough, laugh, whistle), not "rising vs falling hum". Their realistic role is a **few-shot prototype classifier for discrete events** (click, pop, hiss, whistle, double-click) and a **"none/not-a-gesture" rejector**, alongside the DSP pitch tracker. Phone-class options: YAMNet (about 12 ms on a Pixel 6), EfficientAT mn04 (0.98M params, 0.11 GMACs).

### Cited Findings
**Zero-shot audio-text (CLAP)**
- **[MEASURED]** LAION CLAP-HTSAT-unfused (**153M params**), top-1 accuracy:

  | Dataset | Zero-shot, single prompt | Zero-shot, prompt ensemble | Transductive |
  |---|---|---|---|
  | **VocalSound** (laugh, sigh, cough, throat-clear, sneeze, sniff) | 65.72% | 75.27% | 79.84% |
  | ESC-50 | 85.15% | 89.10% | 94.75% |
  | UrbanSound8K | 73.83% | 73.29% | 81.10% |

  — [arXiv 2606.17160](https://arxiv.org/html/2606.17160v1)
- LAION-CLAP checkpoints reach about 89–90% zero-shot on ESC-50. MS-CLAP reaches 93.9%. — [LAION-AI/CLAP README](https://github.com/LAION-AI/CLAP/blob/main/README.md) (search summary)
- **[MEASURED]** MS-CLAP 2023 zero-shot: ESC-50 94.8% and an internal 24-class set 62.3%. Adding **few-shot audio prototypes / LDA with 10–50 samples per class** raised these to 97.0% and 67.8–71.6%. — [arXiv 2507.20036](https://arxiv.org/html/2507.20036)

**Audio event classifiers and embeddings**
- **EfficientAT** (MIT):

  | Model | Params | MACs | AudioSet mAP |
  |---|---|---|---|
  | mn04_as | 0.983M | 0.11 G | 43.2 |
  | dymn04_as | 1.97M | 0.12 G | 45.0 |
  | mn10_as | 4.88M | 0.54 G | 47.1 |
  | mn40_as | 68.4M | 8.03 G | 48.4 |

  Its authors describe the models as "excellent at extracting high-quality audio embeddings". — [GitHub fschmid56/EfficientAT](https://github.com/fschmid56/EfficientAT); [arXiv 2303.01879](https://arxiv.org/html/2303.01879)
- **YAMNet** via MediaPipe Audio Classifier: **[MEASURED by Google] average latency 12.29 ms on a Pixel 6 (CPU/GPU)**, with an input of about 0.975 s of audio. — [MediaPipe audio classification guide](https://ai.google.dev/edge/mediapipe/solutions/audio/audio_classifier). YAMNet specs (3.7M weights, 521 classes) are in `signal_processing_and_ml.md` §7.
- **BEATs**: 90M params (12-layer Transformer, 768-d). AudioSet-2M mAP 48.6 single / 50.6 ensemble. ESC-50 98.1%. — [arXiv 2212.09058](https://arxiv.org/abs/2212.09058)

**Audio LLMs**
- **PitchBench** (28 pitch experiments; [arXiv 2605.26176](https://arxiv.org/html/2605.26176v1)), mean accuracy:

  | Model | Mean accuracy |
  |---|---|
  | Qwen-3.5 Omni Plus | 47.7% |
  | Qwen-3.5 Omni Flash | 34.2% |
  | Gemini 3.1 Pro | 17.8% |
  | Audio Flamingo Next | 15.4% |
  | Gemini 3 Flash | 14.0% |
  | GPT-4o audio | 8.4% |

  Higher/lower judgment (chance 50%): Gemini 3.1 Pro 63.6%, Qwen Plus 65.2%. Discrete melodic contour: "most models near 0%". Conclusion: "Current ALMs do not yet possess stable pitch perception, even for controlled synthetic and instrumental stimuli."
- Audio LLMs struggle with non-standard vocal sounds such as whispering and mumbling. WESR-whisper gets 64.4% recall on whispering vs **Gemini-3-Pro's 37.1%**. — [WESR arXiv 2601.04508](https://arxiv.org/pdf/2601.04508) (search summary); [Stanford CS191 report](https://cs191.stanford.edu/projects/Spring2025/Laya___Iyer_.pdf) (search summary)
- **Qwen3-Omni-30B-A3B** (Instruct / Thinking / **Captioner**) is **Apache-2.0**. The Captioner is described as a "low-hallucination yet highly detailed universal audio caption model", with audio recommended at ≤ 30 s. — [QwenLM/Qwen3-Omni](https://github.com/QwenLM/Qwen3-Omni); [HF Qwen3-Omni-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct). Qwen2.5-Omni-7B is Apache-2.0 ([Wikipedia: Qwen](https://en.wikipedia.org/wiki/Qwen)). The Qwen3.5-Omni weight licence is unconfirmed ([Spheron (secondary)](https://www.spheron.network/blog/deploy-qwen3-5-omni-gpu-cloud/)).
- **Voxtral Mini 3B** (Apache-2.0) is a Whisper-large-v3 encoder feeding Ministral-3B, at 375 audio tokens per 30 s. It is positioned for "speech transcription, translation and audio understanding". GGUF and ONNX ports exist. — [Mistral Voxtral](https://mistral.ai/news/voxtral/); [cstr GGUF README](https://huggingface.co/cstr/voxtral-mini-3b-2507-GGUF/blob/main/README.md); [onnx-community](https://huggingface.co/onnx-community/Voxtral-Mini-3B-2507-ONNX/blob/main/README.md)
- **Gemini audio input**: "32 tokens per second of audio", and "Gemini understands non-speech sounds (birdsong, sirens, etc.)". Google recommends the Live API for real-time use. — [Gemini audio docs](https://ai.google.dev/gemini-api/docs/audio)
- **OpenAI realtime**: `gpt-realtime` audio input $32/M tokens and `gpt-realtime-mini` $10/M. — [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- **Gemma 3n E2B** (on-device, Gemma licence) accepts **audio** input ("recognize speech, transcribe … identify information in audio data"). — [google/gemma-3n-E2B-it-litert-lm](https://huggingface.co/google/gemma-3n-E2B-it-litert-lm)

### Inferences
- **Fit per gesture type:**
  - **Pitch glides and contours (up/down/left/right):** keep these in DSP (YIN/PESTO), not in any model. Audio LLMs are near chance on contour. Generic embeddings are trained on categories and are likely to confuse direction [EST].
  - **Discrete percussive or noisy gestures (click, pop, hiss, whistle vs hum, double-pulse):** EfficientAT mn04 or YAMNet embeddings with **per-user nearest-prototype** (5–10 enrolment samples per gesture) are a strong audio-native option. The CLAP few-shot study shows prototypes beat zero-shot text prompts (+2 to +9 points).
  - **"none" / false-trigger rejection:** embeddings plus prototypes can separate speech, laughter, cough and music from deliberate gestures. VocalSound-style classes are what these models know best.
- **Where they run [EST]:** YAMNet and mn04 run in about 10–20 ms on a phone (measured 12.29 ms for YAMNet on a Pixel 6), and plausibly 20–60 ms on a Pi 5 CPU. They cannot run on the Pico (mn04 is 0.11 GMACs, about 40× the DS-CNN-S budget in `signal_processing_and_ml.md` §5). CLAP-HTSAT (153M) and BEATs (90M) are Pi 5 / laptop / high-end-phone class at roughly 100–500 ms. Audio LLMs are cloud-only or laptop-GPU. Gemma 3n on a phone is possible, but 1 s of audio adds hundreds of prefill tokens.
- **Architecture consequence:** the audio-native path requires streaming raw audio (or a log-mel) from the Pico to the phone over BLE instead of a few feature bytes. 16 kHz 16-bit audio is 256 kbit/s, which is at or above practical BLE GATT throughput unless compressed (for example Opus, or 8 kHz mu-law at 64 kbit/s) [EST; see `hardware_and_output.md`]. Sending a 40-band log-mel at 50 fps in int8 is 16 kbit/s, which is easy. That is a strong argument for computing the log-mel on the Pico and running the embedding on the phone.
- **Audio LLM latency and cost [EST]:** a 1 s clip is 32 Gemini audio tokens plus the prompt, so cost is trivial. But TTFT is 0.3–1 s or more, pitch perception is unreliable, and there are no logprobs on the Gemini 3.x family. Not recommended as the main decision stage. At most use one as an offline labeller or an "is this a deliberate gesture?" judge during data collection.

### Gaps
- No benchmark was found that tests audio LLMs, CLAP or embeddings on **hums, whistles, tongue clicks or glides as deliberate commands**. The VocalSound, NonverbalVocalization and PitchBench results are proxies.
- No measured Pi 5 or phone latency was found for EfficientAT, CLAP or BEATs. SCENEBench (assistive audio benchmark, [arXiv 2603.09853](https://arxiv.org/pdf/2603.09853)) could not be text-extracted.
- Audio-token rates for OpenAI realtime and Qwen-Omni were not found. Gemini Flash-Lite audio-input prices were not captured from the pricing page.
- No published measurement of Gemini Live or GPT-realtime turn latency for short non-speech clips was found.

---

## 6. Recommended candidates to benchmark against Jev, and a fair protocol

### Takeaway
Benchmark five candidates, one or two per tier, all fed the **same labelled gesture set**. For text models, use the same serialized features and the same 8+1 option list with "none":
1. **On-Pico:** calibrated ExtraTrees/RF via emlearn, plus the DTW/kNN user-template variant.
2. **On-phone, text path:** Verdict-118M (ONNX, `/v1/systemone`-compatible, few-shot heads). Optionally a 0.8–1B decoder (Kev/Decision-Eos/Tev1-0.8B, or Gemma 3 1B via LiteRT) with option-logit readout.
3. **On-phone, audio-native:** EfficientAT mn04 or YAMNet embeddings with per-user nearest-prototype, for discrete gestures and "none".
4. **Laptop / Pi:** Bosun v3.1 0.6B through Hanno's `jev-compatible-server` (GGUF/CPU). If a laptop GPU or Mac is available, JevK5 or Decider 4B as the "best open small" reference.
5. **Cloud:** Jev itself, plus one logprob-capable hosted LLM (`gpt-4.1-nano`) as the general-LLM control. Together's Tev1-4B at Jev's price is an optional hosted open alternative.

### Cited Findings
- Relevant existing harnesses:
  - **jev-benchmarks** (AbdelStark): "Calibration, selective risk and latency evals for typed decision models, Jev or open."
  - **DecisionBench** (Hanno Labs): an open benchmark released with Bosun.
  - **jev-ood-calibration**: refits temperature on unseen tasks.

  — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- Jev ECE and reliability-bin methodology ("confidence is the probability placed on the chosen option", reliability bins, Brier): [index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
- The Decision Index measures Jev over HTTP and local models on a GPU with no network, and flags that as "not a controlled speed comparison". — [index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)

### Inferences
**Summary comparison [mix of MEASURED and EST; see the sections above for sources]**

| Candidate | Tier | Size / licence | Decision latency (p50) | Network | Cost / 1k decisions | Calibrated probs? | Expected fit for VOX |
|---|---|---|---|---|---|---|---|
| emlearn ExtraTrees/RF + "none" | Pico | ~5–10 kB, MIT | < 0.1 ms [EST] | none | $0 | yes, after Platt/isotonic | High for bucketed/numeric features; the baseline |
| DTW / kNN user templates | Pico | ~8–30 kB | ~0.1–0.3 ms [EST] | none | $0 | distance → threshold | High for per-user gestures |
| Verdict-118M (ONNX int8) | Phone / Pi / laptop | 120 MB, Apache-2.0 | single-digit ms laptop [MEASURED]; ~10–40 ms phone [EST] | none | $0 | temp-scaled + conformal abstain | Good once fit on VOX labels |
| Kev / Decision-Eos / Tev1 0.8B, Gemma 3 1B | Phone / laptop | 0.5–1 GB int4, Apache or Gemma | 28–149 ms M5 [MEASURED Kev]; ~0.1–0.4 s phone [EST] | none | $0 | logit readout + T | Medium; needs fine-tune |
| Bosun v3.1 0.6B via jev-compatible-server | Pi 5 / laptop | 0.6B, licence unverified | ~0.3–0.7 s Pi 5 cached [EST] | LAN | $0 | readout probs | Medium-low zero-shot |
| JevK5 / Decider 4B | Laptop GPU / Mac | 4.7B, Apache (Decider) | 22–23 ms GPU [MEASURED]; ~133 ms M1 Pro (Decider) | LAN | $0 | ECE 0.027 / 0.084 (general) | Best open small; overkill |
| EfficientAT mn04 / YAMNet + prototypes | Phone (Pi) | 1–4M params, MIT / Apache | ~12 ms Pixel 6 YAMNet [MEASURED] | none | $0 | distance softmax + T | High for discrete sounds and "none"; low for pitch direction |
| **Jev 1.13.0** | Cloud | closed | 253 ms / p95 437 ms [MEASURED, HTTP] | yes | ~$0.013 | yes (ECE 0.074, general) | Reference |
| gpt-4.1-nano (logprobs) | Cloud | closed | ~0.3–1 s TTFT [EST from peers] | yes | ~$0.03 | logprobs + T | Medium; legacy model risk |
| Claude Haiku 4.5 | Cloud | closed | ~0.6 s TTFT [MEASURED, 3 runs] | yes | ~$0.32 | verbalized only | Low value for this task |
| Gemini / GPT-realtime / Qwen-Omni (audio in) | Cloud | closed / Apache (Qwen3-Omni) | ≥0.3–1 s [EST] | yes | low | no logprobs (Gemini 3.x) | Poor on pitch (PitchBench) |

**Fair benchmark protocol [design]**
1. **Dataset:**
   - At least 10 users × 8 gestures × 3 sessions (different days and mic positions), with ≥ 20 reps per gesture per session.
   - **Negative set:** ≥ 30 min per user of continuous non-gesture audio (speech, laughter, coughs, breathing, typing, TV/music, room noise).
   - Record raw audio at 16 kHz on the actual Pico mic path, so every model sees the same capture chain.
2. **Inputs:** every text model gets the *identical* serialized state (same buckets, same JSON, same option names and descriptions, same "none" description). Audio-native models get the same segmented clips. Store the features and clips once and replay them.
3. **Splits:**
   - (a) leave-one-user-out, for cold start;
   - (b) per-user enrolment, where the first K = 5 reps per gesture are available to few-shot or template methods and to Jev's `state` examples;
   - (c) a separate calibration split, for temperature/Platt fitting on *every* model including Jev. Jev's ECE is known to shift out of domain.
4. **Metrics:**
   - Accuracy and macro-F1 over the 8 actions.
   - **False-trigger rate** (actions per minute on the negative stream, at the operating threshold).
   - Miss rate.
   - **ECE** (15 equal-width bins) plus a reliability diagram and Brier score.
   - **Selective accuracy vs coverage** (accuracy at 90/95% precision thresholds).
   - **p50/p95/p99 end-to-end latency**, from gesture end (the onset detector's end marker) to the HID event on the phone, measured on-device with timestamps. Run separately for Wi-Fi and LTE/5G for cloud models, over ≥ 1,000 calls at different times of day, recording timeouts and 429/529 errors.
   - Cost per 1,000 decisions.
   - Offline availability.
   - Phone battery and thermal impact per hour for on-phone models.
5. **Controls:**
   - Pin model versions (`jev-1.13.0`, dated OpenAI snapshots).
   - Reuse a warm keep-alive connection for cloud calls, and also report the cold-connection p95.
   - Use temperature 0 or logit readout.
   - Report bootstrap 95% CIs and use paired tests (McNemar) on the same items.
   - Log model inputs and outputs for error analysis.
6. **Decision rule:** Jev (or any network model) is worth including only if it beats the on-Pico or on-phone baseline on false-trigger rate at equal recall, or on macro-F1 by a margin larger than the CI, **and** its p95 latency fits the action (for example < 300 ms for click, which is tighter than Jev's measured p95).

### Gaps
- No public labelled dataset of deliberate hums, whistles, clicks and glides for cursor control was found (see `signal_processing_and_ml.md` §8). VOX must record its own.

---

## 7. On-phone tier (scope update: Pico → BLE GATT → Android/iOS companion app)

### Takeaway
On a current flagship phone, a **1B-class LLM classification call is about 0.1–0.4 s**: Gemma 3 1B prefills at 2,531 tok/s on GPU and 379 tok/s on CPU on a Galaxy S24 Ultra. **Encoders and audio embeddings take about 10–40 ms** (YAMNet 12.29 ms on a Pixel 6). On iOS 26, Apple's Foundation Models framework gives a free on-device ~3B model with `@Generable` constrained decoding at about 0.6 ms per prompt token and about 30 tok/s on an iPhone 15 Pro, but no token-probability API was found. Calling hosted Jev from the phone over mobile data adds cellular RTT, so expect roughly **0.3–0.6 s median and ≥ 0.6 s p95** [EST]. On-phone models remove that entirely and keep working offline.

### Cited Findings
- **Gemma 3 1B IT (LiteRT, int4 QAT, 2048 ctx), Samsung S24 Ultra, [MEASURED by Google]:**

  | Backend | Prefill | Decode | Other |
  |---|---|---|---|
  | CPU | 379 tok/s | 55 tok/s | TTFT ~1 s; 1,009 MB RSS |
  | GPU | **2,531 tok/s** | 49 tok/s | — |
  | NPU (S25 Ultra, a16w4, 1280 ctx) | **5,836 tok/s** | 85 tok/s | — |

  Model size 529 MB. The files work with both the **MediaPipe LLM Inference API** and the **LiteRT-LM** runtime on Android, iOS and Web. **Licence: Gemma.** — [litert-community/Gemma3-1B-IT](https://huggingface.co/litert-community/Gemma3-1B-IT); [Google Developers Blog](https://developers.googleblog.com/gemma-3-on-mobile-and-web-with-google-ai-edge/)
- **Gemma 3n E2B (LiteRT-LM, int4 weights) [MEASURED by Google]:**

  | Device | Backend | Prefill | Decode |
  |---|---|---|---|
  | S24 Ultra | CPU | 110.5 tok/s | 16.1 tok/s |
  | S24 Ultra | GPU | 816.4 tok/s | 15.6 tok/s |
  | Vivo X300 Pro | NPU | 1,671 tok/s | 28.4 tok/s |
  | MacBook Pro M3 | CPU | 232.5 tok/s | 27.6 tok/s |

  Accepts text, image, video and **audio**. Gemma licence. — [google/gemma-3n-E2B-it-litert-lm](https://huggingface.co/google/gemma-3n-E2B-it-litert-lm)
- Gemma 4 E2B on LiteRT-LM reaches 52 tok/s decode on GPU (OpenCL) on an S26 Ultra. — [HF litert-community/gemma-4-E2B-it-litert-lm](https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm) (search summary)
- **Apple Foundation Models framework (iOS 26):**
  - On-device model of about 3B parameters, compressed to **2 bits per weight** with QAT.
  - **Guided generation** via `@Generable`, implemented with "constrained decoding and speculative decoding".
  - Developers can train **rank-32 adapters** with Apple's Python toolkit, but "adapters must be retrained with each new version of the base model".
  - Audio input is not mentioned.

  — [Apple ML Research, 2025 updates](https://machinelearning.apple.com/research/apple-foundation-models-2025-updates)
- Apple's earlier figure: **about 0.6 ms per prompt token TTFT and 30 tok/s on an iPhone 15 Pro** — [Apple ML Research, 2024](https://machinelearning.apple.com/research/introducing-apple-foundation-models). A secondary source says TTFT is under 1 ms per prompt token on the iPhone 15 Pro and 17 Pro (search summary).
- **YAMNet via MediaPipe Audio Classifier: 12.29 ms average on a Pixel 6 (CPU/GPU)** — [MediaPipe audio classifier guide](https://ai.google.dev/edge/mediapipe/solutions/audio/audio_classifier)
- Verdict ships an ONNX int8 build of about 120 MB that runs with only onnxruntime and tokenizers (so ONNX Runtime Mobile is a natural host). — [GitHub Manavarya09/verdict](https://github.com/Manavarya09/verdict). PocketJev does direct option-logit decisions with Qwen3-VL on an iPhone via MLX in about 1 s, including an image. — [news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- Jev's measured latency over HTTP from the index harness is 252.8 ms median / 436.6 ms p95 — [index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json). This is a fixed-network measurement, not mobile.

### Inferences
- **On-phone LLM call arithmetic [EST]:** assume a 300-token prompt, 1–3 output tokens, and a KV-cached fixed prefix where the runtime supports it.
  - **Gemma 3 1B GPU:** 300/2,531 ≈ 0.12 s prefill, plus about 20–60 ms decode, so **~0.15–0.2 s**. CPU: about 0.8 s uncached, or about 0.1–0.15 s if only about 40 tokens are new.
  - **Gemma 3n E2B GPU:** about 0.4 s.
  - **Apple FM:** 300 × 0.6 ms ≈ 0.18 s, plus 1–5 tokens at 30 tok/s, so **~0.2–0.35 s**. Call `prewarm()` to keep the model resident. Apple FM needs an Apple-Intelligence-capable device (not verified here).
- **Probabilities on phone:**
  - llama.cpp on Android exposes logits, so the §2 recipe works.
  - Whether the MediaPipe LLM Inference API or LiteRT-LM exposes per-token logprobs was **not confirmed**.
  - The Apple FM framework appears to return only generated or guided values, not token probabilities. For calibrated confidence on iOS, prefer a Core ML / ONNX classifier (tree/MLP, Verdict-style encoder, or audio embedding plus prototypes) over the FM framework.
- **Hosted API from a phone over mobile data [EST]:**
  - LTE RTT is typically about 30–100 ms and variable. 5G NSA is often about 20–40 ms.
  - A warm keep-alive HTTPS call to Jev ≈ Jev's server time + 1 RTT, so roughly **0.3–0.35 s median and 0.5–0.7 s p95 on LTE**.
  - A cold connection adds a TCP + TLS 1.3 handshake of about 2 RTTs (+60–200 ms).
  - Radio wake from idle (RRC connected transition) can add a further 50–200+ ms on the first request after a pause, which matters for sporadic gestures.
  - The BLE hop Pico → phone adds one connection interval (typically 7.5–30 ms) [EST; see `hardware_and_output.md`].
- **Phone recommendations:**
  - **Android:** run the on-Pico tree model as the primary path, or mirror it in Kotlin. Add the EfficientAT mn04 / YAMNet prototype model (LiteRT) for discrete sounds and "none", and optionally Verdict via ONNX Runtime Mobile for the text-schema path. Use Jev only as an optional online arbiter for low-confidence cases.
  - **iOS:** the same, using Core ML / ONNX. Apple FM is useful only for natural-language gesture *setup* (mapping "two short clicks means right-click" to a config), not for per-gesture decisions.
- **Battery and thermal [EST]:** a tree or embedding model per gesture is negligible. Keeping a 1B LLM resident costs about 0.5–1.2 GB RSS (Gemma 3 1B CPU RSS is 1,009 MB) and risks being killed in the background, which is a real concern for an always-on accessibility app.

### Gaps
- No measured end-to-end latency was found for Jev or any hosted LLM called from a phone on LTE/5G. The mobile RTT figures above are general estimates. A 5G/4G measurement paper ([arXiv 2312.00957](https://arxiv.org/pdf/2312.00957)) was found but could not be text-extracted.
- Logprob/logit access in the MediaPipe LLM Inference API, LiteRT-LM and the Apple FM framework was not verified from docs.
- No mid-range Android phone numbers were found (all Google figures are flagships). ONNX Runtime Mobile and Core ML latency for Verdict-class encoders on phones was not measured by anyone found.
- Apple FM framework device requirements and background-execution limits were not checked.
