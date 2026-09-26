# Jev (TypeSafe AI "System One" decision model) as the VOX decision stage

Research date: 2026-09-26. Jev has been public for about 11 days (early access since 2026-09-15), so everything here may change. Items marked [UNCONFIRMED] come from one secondary source only. Items marked [MEASURED HERE] are probes run from this research box against the live API without an API key, so they only cover the network, TLS and auth layer.

## 1. What Jev is: who built it, versions, architecture claims

### Takeaway
Jev is a hosted, closed-weight "decision model" from TypeSafe AI. You send it a text or JSON state plus typed questions, and it returns a choice, a score or a yes-probability, with probabilities attached. It never returns free text. The only version so far is jev-1.13.0. The architecture claims ("parallel sampling", RLCD training) are described at blog level only. There is no paper and there are no weights.

### Cited Findings
- TypeSafe AI came out of stealth on 2026-09-15 with $40M in seed funding, and Jev was its first public model. — [DataCamp](https://www.datacamp.com/blog/system-one-models-jev)
- TypeSafe AI is based in San Francisco and was founded in 2024. Founders: Diogo Almeida (CEO; about 4 years at OpenAI on RLHF, InstructGPT, ChatGPT and GPT-4), Erik Gafni and Sasha Sheng. The $40M seed round was led by DCVC. Forbes reported a $200M valuation. — [Wikipedia: Jev (AI model)](https://en.wikipedia.org/wiki/Jev_(AI_model))
- The official launch blog names Diogo Almeida (a former OpenAI researcher). It describes Jev as "unstructured state in, typed probabilistic decisions out". Sampling is "Parallel. Generates all outputs in a single query", as opposed to LLMs generating "one token at a time". Training uses "Reinforcement Learning for Calibrated Decisions (RLCD)". The name comes from William Stanley Jevons. — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev). Note: the fetched blog page showed a date of 2026-09-26, while every other source gives 2026-09-15 as the launch date. The page was probably updated.
- TypeSafe describes Jev as transformer-based and trained only on synthetic data. It has not published the exact architecture, the weights or a technical paper. Observers suggest it may be built on open-weight LLMs. — [Wikipedia](https://en.wikipedia.org/wiki/Jev_(AI_model))
- Current model: `jev-1.13.0`. The aliases `jev-latest` and `jev-preview` both point to `jev-1.13.0`, and "There is no preview build available right now." — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- "Every 'openjev' / '-RLCD' Hub repo is either a stock model plus decoding code, or an independently trained head." RLCD "is described only at blog-post level; no public implementation." — [HF Space jev-decision-index, news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- TypeSafe positions Jev for "routing, classification, verification, ranking, or other decision point[s] … where a predictable typed answer matters more than generated prose". — [OpenRouter search listing / Jev guide](https://openrouter.ai/docs/guides/community/jev)

### Inferences
- "Non-autoregressive / parallel" can't be verified from outside. The community reproductions that come closest to Jev (see section 8) are ordinary autoregressive LLM backbones that score candidate options in one forward pass. Jev may well work the same way.

### Gaps
- No architecture paper, parameter count, training data details or model card was found.
- The blog's FAQ entries ("Is Jev just a smaller LLM?", "public benchmarks") had no answer text in the fetched content.

## 2. API: endpoints, auth, schema, question types, OpenRouter, SDKs, and a microcontroller path

### Takeaway
There is one REST endpoint: `POST https://api.typesafe.ai/v1/systemone`. Auth is a Bearer key and the body is JSON. The request carries `state`, `model` and `questions`, a map of named typed questions. The three question types are `choice`, `score` and `noul` (the "null-probability" type in the brief is really **Noul**, a yes/no probability). Several questions can go in one request, and they are evaluated in parallel and independently. OpenRouter carries Jev on its own endpoints, which are **not** OpenAI chat-completions compatible. Plain HTTP/1.1 over TLS 1.2 with an ECDSA P-256 certificate chain works [MEASURED HERE], so a Pico 2 W with lwIP and mbedTLS can call the API directly.

### Cited Findings
**Endpoint and auth**
- `POST https://api.typesafe.ai/v1/systemone`, with headers `Authorization: Bearer <API_KEY>` and `Content-Type: application/json`. — [TypeSafe API reference](https://docs.typesafe.ai/api.md)
- `GET https://api.typesafe.ai/v1/models` lists the aliases. Versioned IDs such as `jev-1.13.0` are accepted even when they are not listed. — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- Errors: `401` (bad or missing key), `422` (validation error), `429` (rate limit), `529 Overloaded`. For 429 and 529, retry with exponential backoff. — [API reference](https://docs.typesafe.ai/api.md)
- [MEASURED HERE] A request with **no** key returned `403` with `{"detail":{"error_type":"authentication_error","message":"Must supply an API key!..."}}`. A request with an invalid key returned `401`. The docs mention only 401, so client code should treat both as auth failures.

**Request schema**
- `state`: string | object | array (required). `model`: string, for example `"jev-latest"` (required). `questions`: map<string, Question> (required). Question keys are your own ids and "not sent to the underlying model". — [API reference](https://docs.typesafe.ai/api.md)
- Every question has `type` and `instructions`. `instructions` can be a string, an object or an array. You can put data inside an object and reference it by name in backticks. — [API reference](https://docs.typesafe.ai/api.md)
- **choice**: `criteria` is a required map from option to description (or null). There can be at most 255 options. — [API reference](https://docs.typesafe.ai/api.md)
- **score**: `criteria` is a required ordered array of level descriptions, at least 2 and at most 10. — [API reference](https://docs.typesafe.ai/api.md)
- **noul**: `criteria` is optional and takes the form `{ "true": "...", "false": "..." }`. — [API reference](https://docs.typesafe.ai/api.md)
- Example request (verbatim from the docs):
  ```json
  {"state": "Help! My payouts have been failing for 3 days.", "model": "jev-latest",
   "questions": {"department": {"type": "choice", "instructions": "Which team should handle this?",
     "criteria": {"billing": "Payments, invoicing, refunds", "technical": "Bugs, outages, integrations", "sales": "Pricing, upgrades, new accounts"}}}}
  ```
  — [API reference](https://docs.typesafe.ai/api.md)

**Response schema**
- The top level holds `model` (the versioned ID that actually answered), `answers` (a map keyed by your question ids) and `usage {input_tokens, output_tokens}`. — [API reference](https://docs.typesafe.ai/api.md)
- Choice answer: `{"type":"choice","choice":"billing","probabilities":{"billing":0.88,"technical":0.12,"sales":0.0},"confidence":0.81}`. Score answer: `score` (a probability-weighted value that can land between levels), `legend`, `probabilities` and `confidence`. Noul answer: `{"type":"noul","noul":0.95}`, with **no** confidence field. — [API reference](https://docs.typesafe.ai/api.md)
- Example usage values: a short state with one noul question gave `input_tokens: 296`. A 3-option choice gave `input_tokens: 318`. — [API reference](https://docs.typesafe.ai/api.md)

**Multiple questions per request**
- "All three question types can be mixed in a single API call." — [TypeSafe docs index](https://docs.typesafe.ai/)
- "All questions see the same state and are evaluated independently." — [TypeSafe docs: State](https://docs.typesafe.ai/concepts/state.md)
- The context budget is 64k tokens for the state plus all questions, and 32k for the state plus the single longest question. — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md). The OpenRouter guide says 32,000 tokens for "state + questions combined" ([OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev)), and eesel also reports 32k ([eesel review](https://www.eesel.ai/blog/typesafe-jev-review)). These conflict. The TypeSafe docs are the primary source.

**OpenRouter**
- Model IDs: `typesafe/jev-1.13` and `~typesafe/jev-latest`. You need an OpenRouter key and no TypeSafe account. — [OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev)
- Endpoints: `POST https://openrouter.ai/api/alpha/decisions` (the "Decisions" API) or the TypeSafe-compatible `POST https://openrouter.ai/api/v1/systemone`. **"Not OpenAI-compatible"**, so you cannot use chat completions. The response includes `usage.cost` in USD. — [OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev)
- [UNCONFIRMED, search snippet only] A third model, `typesafe/jev-router`, was listed on OpenRouter on 2026-09-25 with a context of up to 1,000,000 tokens. — [OpenRouter Typesafe provider page (snippet)](https://openrouter.ai/typesafe)
- The OpenRouter model page `openrouter.ai/typesafe/jev-1.13` returned 404 when fetched, so no OpenRouter latency or throughput stats were retrieved.

**SDKs**
- Python: `pip install typesafe-sdk` (Python 3.10+). JS/TS: `npm install @typesafe-ai/sdk` (Node 20+). Both SDKs read `TYPESAFE_API_KEY`. — [dev.to guide (Valyu)](https://dev.to/valyuai/how-to-use-jev-a-practical-guide-to-typesafes-system-one-model-g5e); the SDK reference pages are listed in [docs llms.txt](https://docs.typesafe.ai/llms.txt)
- Python usage: `TypeSafeClient().system_one(state=..., questions={"x": Choice(instructions=..., criteria={...}), ...})`, then `response.answers["x"].choice / .confidence`. — [dev.to guide](https://dev.to/valyuai/how-to-use-jev-a-practical-guide-to-typesafes-system-one-model-g5e)
- The SDKs retry 429s with backoff and honor `retry-after`. — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- OpenRouter lists TypeScript, Python and Go SDKs, and says the official TypeSafe SDKs work if you change the base URL. — [OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev)
- Third-party integrations: Pydantic AI, LiteLLM pass-through, AI/ML API, Cloudflare AI, and LangChain (`TypeSafeClassifier`). — [search listing: pydantic.dev, docs.litellm.ai, docs.aimlapi.com, developers.cloudflare.com](https://developers.cloudflare.com/ai/models/typesafe/jev/) (not fetched individually)

**Microcontroller (Pico 2 W) path** [MEASURED HERE, 2026-09-26]
- `api.typesafe.ai` sits behind Cloudflare (headers `server: cloudflare`, `cf-ray`, IPv6 anycast `2606:4700::…`) with an Envoy upstream.
- TLS 1.3 by default. **TLS 1.2 is accepted** (negotiated `ECDHE-ECDSA-CHACHA20-POLY1305`). **HTTP/1.1 is accepted** (so HTTP/2 is not required).
- Certificate chain: leaf `CN=typesafe.ai`, issued by `Google Trust Services WE1`. Leaf and intermediate keys are EC prime256v1 (P-256). Level 2 is EC secp384r1.
- The HTTP/1.1 + TLS 1.2 + Bearer header + JSON body path returned a normal JSON 401 for a fake key, so the whole wire path works without an SDK.

### Inferences
- A Pico 2 W can call Jev with lwIP's `altcp_tls` and mbedTLS. It needs ECDHE-ECDSA ciphersuites (AES-GCM or ChaCha20-Poly1305) and the Google Trust Services root (GTS Root R4, the ECC root; check this) in its trust store. Set the SNI to `api.typesafe.ai`. Keep one persistent keep-alive connection, because a full ECDHE/ECDSA handshake on a Cortex-M33 will probably cost hundreds of ms or more (not measured).
- The simpler alternative: let the Pico send features over BLE or UART to a phone, PC or Raspberry Pi that makes the HTTPS call. This keeps the API key off the microcontroller and avoids mbedTLS RAM pressure.
- For an embedded client, OpenRouter's `/api/v1/systemone` adds one more hop and a second vendor dependency. TypeSafe's direct endpoint is the leaner choice.

### Gaps
- There is no official C or embedded SDK and no published guidance on minimum TLS versions or ciphers. The TLS findings above are this box's observations only.
- The full OpenRouter `/alpha/decisions` request schema was not retrieved. It lives at the OpenRouter API reference path cited in their guide.

## 3. Latency, throughput and rate limits

### Takeaway
TypeSafe claims 70-500 ms end to end. The one independent third-party measurement found (the HF Decision Index harness, over HTTP) got **median 252.8 ms and p95 436.6 ms** for jev-1.13.0. Published rate limits are 250k tokens/s and 1,200 requests/min, and TypeSafe warns they "can change without notice". For a cursor controller, about 250 ms per decision plus the Pico's Wi-Fi hop is noticeable, and at 1 Hz polling it rules out continuous smooth control.

### Cited Findings
- TypeSafe: "End-to-end response time is 70ms-500ms". "40x-200x faster" than frontier models, and "193.6x faster" on their workflow evals, "on the higher end". — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- HF Decision Index (third party, jev-1.13.0): latency median **252.8 ms**, p95 **436.6 ms**. Note from the index: "Remote hosted API measured over HTTP. total_wall_ms includes client retries and network; http_wall_ms is the request itself. Local GPU reproductions have no network leg, so these are not a controlled speed comparison." — [HF Space data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
- Rate limits: "250,000 tokens per second / 1,200 requests per minute". A request over either limit returns 429. Warning: "Rate limits are adjusting dynamically … can change without notice … Higher limits are available on custom and enterprise plans." — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- A `529 Overloaded` status code exists. — [API reference](https://docs.typesafe.ai/api.md)
- Vercel's CEO reportedly saw "18x faster (p95)" in production. This is secondhand and not independently verified. — [eesel review](https://www.eesel.ai/blog/typesafe-jev-review)
- [MEASURED HERE] Unauthenticated POST round trips from this box took 137-203 ms total, with a TLS handshake of 26-84 ms, served from the Cloudflare MIA edge. These requests were rejected at auth, so there was **no model inference** in them. They only show the network and edge floor from one location.

### Inferences
- A realistic VOX loop is: end of the sound event, then Pico feature extraction, then Wi-Fi, then about 250 ms median / about 440 ms p95 for Jev, then BLE HID. That adds up to roughly 300-600 ms from the end of a hum to cursor motion. That is fine for discrete commands (click, scroll step) and poor for continuous pointing.
- The only published region information is the Cloudflare front. Where inference actually runs is unknown, so latency from outside North America may be worse.
- 1 call/s is 60 requests/min, about 5% of the published limit. The rate limit is not the constraint for one user.

### Gaps
- No official p50/p95, cold-start figures, SLA, uptime or region/hosting disclosure. The blog says production details were not provided. — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- No measurement with a valid key could be made from here.

## 4. Pricing and a cost estimate for VOX

### Takeaway
Pricing is $0.042 per million input tokens, and output is free. No minimum was found. At 1 call/s for an hour with about 300-1,000 input tokens per call, the cost is roughly **$0.05-$0.15 per hour**, so cost does not matter for VOX. Access still depends on an early-access waitlist.

### Cited Findings
- Input costs "$0.042 / MTok ($42 per billion tokens)". Output is "FREE (too cheap to meter)". — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev); confirmed by the "\$42 / \$0.042" row in [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- On OpenRouter: $0.042/M input and $0/M output. — [OpenRouter search listing](https://openrouter.ai/typesafe)
- Minimal requests are about 300 input tokens (296-318 in the documented examples), which points to a fixed per-request overhead of a few hundred tokens. — [API reference](https://docs.typesafe.ai/api.md)
- eesel reported "there is no pricing page… no published plan tiers or rate limits, and access is gated behind a waitlist". — [eesel review](https://www.eesel.ai/blog/typesafe-jev-review). The TypeSafe Models page now lists both a price and rate limits ([docs](https://docs.typesafe.ai/models.md)), so part of eesel's statement is already out of date. The waitlist and early-access status is confirmed by the [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

### Inferences
- Worked estimate: 3,600 calls/h × 600 tokens = 2.16M tokens, which is about **$0.09/h**. At 1,000 tokens per call it is about $0.15/h. Running 8 h/day for 30 days costs about $22-$36/month at 1 Hz. Event-driven calls (only when a sound is detected) would be far cheaper.

### Gaps
- No documented minimum spend, free tier, or billing granularity was found.

## 5. Calibration, confidence thresholds and abstain/"none"

### Takeaway
Choice and Score answers return a full probability distribution plus a `confidence` value derived from it. For Choice that value is (N·p_max − 1)/(N − 1), per the docs' own widget code. Noul returns only a probability. TypeSafe's calibration claim is self-reported. The third-party HF index measured an **ECE of 0.074 with average confidence above accuracy (0.81 vs 0.74)**, so Jev is somewhat overconfident, and its mid-range bins are overconfident by 7-16 points. The docs recommend a 0.5 confidence floor for "don't act", higher bars for destructive actions, and an explicit `none/other` option.

### Cited Findings
- "Calibrated: higher confidence means higher accuracy". "Always communicates confidence and uncertainty with every output". — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- "`confidence` is a statistic computed from the probability distribution … a flatter distribution means lower confidence". It is returned only on Choice and Score. The full `probabilities` are returned so you can use your own measure. — [TypeSafe docs: Confidence](https://docs.typesafe.ai/confidence.md)
- The docs' interactive widget computes Choice confidence as `max(0, min(1, (count*peak - 1)/(count - 1)))`. — [TypeSafe docs: Confidence (page source)](https://docs.typesafe.ai/confidence.md)
- Recommended pattern: `if confidence < 0.5: don't act / route to human`. Low-stakes actions can proceed. High-stakes actions need `> 0.9` or confirmation. "Start with conservative thresholds, test with your own data, and adjust." — [TypeSafe docs: Confidence](https://docs.typesafe.ai/confidence.md). The dev.to guide shows the same pattern with a 0.85 cut for high stakes. — [dev.to](https://dev.to/valyuai/how-to-use-jev-a-practical-guide-to-typesafes-system-one-model-g5e)
- "Add an `other` or `none of the above` option when the list might not cover every input, so the model can say none of the others fit." — [TypeSafe docs: Choice](https://docs.typesafe.ai/primitives/choice.md)
- Pin a versioned ID (for example `jev-1.13.0`) if you have tuned thresholds, because aliases move and "the answers behind it can change". — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- Consistency caveats: the same question asked as a Noul and as a yes/no Choice gave 0.22 and 0.01. A Noul and its negation summed to 1.19. "Don't carry a threshold tuned on a Noul over to a Choice." — [TypeSafe docs: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- "Calibration does not mean that an individual prediction is guaranteed to be correct." — [community reference gist summarizing TypeSafe docs](https://gist.github.com/pjburnhill/adf8d28efcad9df037bfdece178ef965)
- Third-party calibration results (HF Decision Index 0.2: 32 benchmarks, a 1-in-6 sample, n = 72,594; "confidence is the probability placed on the chosen option"): Jev accuracy 0.7393, mean confidence 0.8115, **ECE 0.074**, Brier 0.3558. Reliability bins by confidence → accuracy: 0.55 → 0.48, 0.64 → 0.52, 0.75 → 0.59, 0.85 → 0.71, 0.98 → 0.93. 53.9% of answers land in the ≥0.9 bin. ECE by area: tools 0.020, language 0.062, knowledge 0.065, arts 0.093, retrieval 0.154. — [HF Space data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
- For comparison on the same index, several open reproductions are **better calibrated** than Jev: AutoJev-27B has ECE 0.018, Decider 35B-A3B 0.023 and Xor 0.015, though their accuracy is lower. — [HF Space data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
- Community view: open scorers "still softmax over candidate logits and the studies find confidence does not reliably flag errors". — [HF Space news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- HN critique: "calibration is a group property … a model calibrated on TypeSafe's data may not stay calibrated on yours." — [HN search summary](https://news.ycombinator.com/item?id=49767192) (via search snippet)

### Inferences
- For VOX: include `"none": "Not a deliberate command: noise, speech, breathing, or ambiguous"` as an option. Take the action only if `choice != none` and `confidence >= threshold`. Start around 0.6-0.7 for movement and higher (about 0.85) for click, because a mis-click is costlier than a mis-move. Then recalibrate on logged VOX data, since the third-party reliability curve shows mid-range confidence overstates accuracy.
- With 7-8 options, the confidence formula penalizes flat distributions heavily. p_max = 0.5 across 8 options gives confidence (8·0.5 − 1)/7 ≈ 0.43, which is below the 0.5 floor.

### Gaps
- TypeSafe publishes no reliability diagram or ECE of its own. Its calibration claim can only be checked through third-party runs like the HF index.

## 6. Input format: text only, weak with numbers, and how to serialize sensor features

### Takeaway
Jev accepts only text or JSON. It has **no numeric, audio or tensor input**, and TypeSafe itself documents that jev-1.13 "struggles with tasks that require numeric precision", "does not count reliably", and does worse with numeric representations than with semantic ones. Sending "pitch 110Hz falling, 400ms, 2 pulses" and asking Jev to apply thresholds works against its documented weaknesses. The official advice is to do the arithmetic in code and send "the computed number or a named bucket".

### Cited Findings
- "Input: Text only. String, JSON object, or array of text values. No image, audio, or video input." "Pre-process non-text inputs (images, audio, video, binaries) into text or structured fields". — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- "Use an object for most requests so each part of the state has a descriptive name". — [TypeSafe docs: State](https://docs.typesafe.ai/concepts/state.md)
- "It struggles with tasks that require numeric precision." "Jev is not a calculator … implement any mathematical logic in code." — [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- "`jev-1.13` does not count reliably … the error grows with the size of the thing being counted." — [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- "`jev-1.13` will perform better on semantic representations than numeric … Given RGB triples or hex values it cannot reliably judge whether two values are near each other … do the conversion in code and pass in either the computed number or a named bucket." — [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- Score outputs should not be used to interpolate magnitudes: "score levels are weak in numerical calibration". — [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- "Literal reading": Jev "answers the question you wrote, not the one you meant". Contradictory instructions and criteria hurt accuracy. A large state with irrelevant detail reduces accuracy. — [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- English is the primary language. Other languages are "handled but not equally well". — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)

### Inferences
- A good VOX state would be a small JSON object of **pre-bucketed categorical features**, computed on the Pico. For example: `{"pitch_band":"low","contour":"falling","duration":"medium (300-600 ms)","pulses":"two","loudness":"normal","sound_type":"voiced hum"}`. Raw Hz, ms and counts should not be the primary signal. Keep "2 pulses" as a word that code has already counted. Jev should not be asked to count.
- Put the gesture→action mapping in the `criteria` descriptions, for example `"up": "A rising pitch glide"` and `"click": "Two short clicks or pulses"`.
- **Skeptical point, stated once:** once the features are bucketed in code, the mapping from bucket to action is a small deterministic table or a tiny classifier. Jev then adds 250-440 ms, a network and vendor dependency, and a per-call cost, and it contributes little judgment. Jev earns its place only where the input is genuinely fuzzy. Examples: telling intentional gestures apart from speech or background noise using a richer text description, or letting users define gestures in natural language ("a short whistle means click"), which Jev maps without retraining.

### Gaps
- No third-party guide was found on serializing sensor or audio features as text specifically for Jev or for text classifiers. The guidance above is TypeSafe's general advice plus inference.

## 7. Customization: fine-tuning, few-shot, per-user adaptation

### Takeaway
Jev has no fine-tuning and no LoRA, and every account is served by the same weights. You adapt it through the request: put examples and reference material in `state`, and put rules and boundary cases in `instructions` and `criteria`. Per-user adaptation therefore means per-user prompt content (for example, that user's gesture definitions and labeled examples) plus per-user thresholds tuned in code.

### Cited Findings
- "Jev is not fine-tuned or LoRA-adapted with customer data … the same weights serve every account. You shape its answers … through the request": proprietary content in `state`, domain rules and boundary cases in `instructions` and `criteria`, broad judgments broken into atomic questions and combined in code, and optionally "training a downstream classical model on Jev's probabilities". — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- State can hold "related context, examples, and other information". — [TypeSafe docs: State](https://docs.typesafe.ai/concepts/state.md)
- Criteria can be objects describing "what an option covers, what it doesn't cover, and some examples". — [TypeSafe docs: Choice](https://docs.typesafe.ai/primitives/choice.md)
- "Jev is not trained on customer requests or responses." ZDR is offered for enterprise. — [TypeSafe docs: Models](https://docs.typesafe.ai/models.md)
- An HN commenter suggested fine-tuning could come "once available". This is speculation with no official roadmap. — [HN thread](https://news.ycombinator.com/item?id=49745752)

### Inferences
- A VOX per-user profile could be a JSON block inside `state`, for example `"user_gestures": {"click": "two short tongue clicks", ...}`, plus a few recent labeled examples. This costs tokens but no training.

### Gaps
- No documentation says how much in-prompt examples improve accuracy.

## 8. Open-source counterparts and local alternatives (including the HF "Jev Decision Index")

### Takeaway
Dozens of open "Jev-like" reproductions appeared within 10 days. They are tracked by the community HF Space **multimodalart/jev-decision-index**, which is unofficial and not affiliated with TypeSafe. On its 40-benchmark index, the best open model (AutoJev-27B, a Qwen 27B full fine-tune) roughly matches Jev: 50.94 vs 51.67 chance-corrected, and it is better calibrated. Models small enough for a Raspberry Pi (under 1B, encoders or GLiNER types) score far lower on that general panel (roughly 2-17 vs 52). They are still plausible for VOX's narrow 7-class task **if trained or tuned on VOX data**. For VOX, though, the strongest "local alternative" is probably not a language model at all.

### Cited Findings
**What the Space is**
- The HF Space `multimodalart/jev-decision-index` is a static Space titled "Jev Reproductions Tracker": "Who is rebuilding TypeSafe's Jev (System One / RLCD) in the open?". It has an **Index** tab (the leaderboard) and a **News** tab (artifacts grouped as Decoding, Diffusion, Trained, Prior art and Explainers). It is "Unofficial and community-maintained; not affiliated with TypeSafe AI". It has 238 likes, 84 commits and 9 contributors. — [HF Space README](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/README.md); [file listing](https://huggingface.co/spaces/multimodalart/jev-decision-index/tree/main)
- Data pipeline: `data/index.json` is built by `evaluation/reproductions/build_leaderboard.py` in a `typesafe-diffusion-lab` checkout. "Engagement metrics are a snapshot (2026-09-24)". — [README](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/README.md)

**Methodology**
- The current edition is **Decision Index 0.2**: 40 benchmarks in 5 equally weighted areas (Knowledge & Reasoning, Language Understanding, Retrieval & Classification, Tools, Arts). The headline number is chance-corrected, with each benchmark mapped to (score − chance)/(1 − chance), "so 0 is random guessing and 100 perfect". MMLU, ARC-Easy, ARC-Challenge and SimpleBench are kept off the index. Six interactive environments are dropped "because no reproduction has run them". — [README](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/README.md)
- The suite has 121,057 requests (120,615 scoreable) across 43 benchmarks, with Jev run on 42. Local reproductions ran on "1 x NVIDIA RTX PRO 6000", against jev-1.13.0. Benchmarks include GPQA Diamond, GSM8K, ChessBench, MuSR, MMLU-Pro, BBH, ContractNLI, ToolRet, BRIGHT, RouterBench and ForecastBench. For calibration, "Rows an entrant trained on count as wrong here too." — [data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
- Stated limits: deterministic hash sampling, "no outcome-based selection". Some benchmarks were adapted for Jev with "authored semantic option spaces" (one household suite is "Custom … authored for this suite … Not a native public benchmark"). Tool benchmarks test "Tool-name selection only, not argument/execution success". Jev's latency includes network while local models' does not. — [data/methodology.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/methodology.json); [data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)

**Results (Decision Index 0.2, chance-corrected headline / raw; accuracy; ECE; latency median/p95 ms; params)** — all from [data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
| Model | Index (skill) | Raw | Acc | ECE | Lat. med/p95 | Params | Type / base | Weights |
|---|---|---|---|---|---|---|---|---|
| **Jev (jev-1.13.0, API)** | **51.67** | 63.87 | 0.739 | 0.074 | 252.8 / 436.6 (HTTP) | n/a | closed | none |
| AutoJev-27B | 50.94 | 63.37 | 0.730 | 0.018 | 104.9 / 1229 | 27.8B | full FT, Qwen3.8-27B | denis-pplx/autojev-27b |
| Surogate Rune 26B-A4B (Q6_K) | 47.23 | 59.39 | 0.695 | 0.171 | 679.7 / 5789 | 25.8B MoE | full FT, Gemma-4-26B-A4B | surogate/rune-26b-a4b-GGUF |
| Jevfire | 45.73 | 59.17 | 0.689 | 0.052 | 77.9 / 710.8 | 27.8B | inference technique, Qwen3.8-27B | code only |
| Winnow-12B (Q8_0) | 45.05 | 58.0 | 0.670 | 0.168 | 49.2 / 359.9 | 12B | LoRA, Gemma-4-12B | EldanRing/Winnow-12B |
| Decider 35B-A3B (NVFP4) | 43.5 | 57.24 | 0.696 | 0.023 | 99.1 / 210.1 | 36B MoE | full FT, Qwen3.5-35B-A3B | Mapika/decider-35b-a3b-nvfp4 |
| Decider 4B | 36.58 | 52.1 | 0.649 | 0.084 | 23.4 / 217.2 | 4.7B | full FT, Qwen3.5-4B | Mapika/decider-4b |
| JevK5 | 36.44 | 52.17 | 0.648 | 0.027 | 21.9 / 253.7 | 4.7B | LoRA, Qwen3.5-4B | alibiserikbay/JevK5 |
| Decider 2B (FP8) | 26.11 | 44.5 | 0.586 | 0.077 | 40.6 / 1003 | 2.3B | full FT | Mapika/decider-2b |
| Decision 1.0 Eos | 17.49 | 38.22 | 0.480 | 0.083 | 36.3 / 101.2 | 0.87B | head/adapter, Qwen3.5-0.8B | llm-semantic-router/Decision-1.0-Eos-0.8B |
| Kev 0.8B | 13.26 | 35.51 | 0.484 | 0.074 | 41.2 / 108 | 0.87B | LoRA+head | jaredpalmer/kev-0.8b |
| GLiNER2.5-Decide | 9.98 | 31.94 | 0.434 | 0.088 | 93.2 / 1259 | 0.49B | GLiNER full FT | fastino/GLiNER2.5-Decide |
| Decision 1.0 Kai | 7.03 | 29.0 | 0.358 | 0.185 | 30.0 / 34.4 | 0.31B | encoder (mmBERT-base) | llm-semantic-router/Decision-1.0-Kai |
| GLiNER 2.5 small | 3.88 | 27.9 | 0.332 | 0.161 | 14.5 / 38.4 | 0.07B | GLiNER | fastino/gliner2.5-small-v1 |
| Verdict | 1.82 | 12.4 | 0.369 | 0.154 | 10.6 / 61.4 | 0.15B | ModernBERT/GLiClass | heman10x/rlcd-modernbert-151m |
| system-one-gemma | 4.85 | 26.48 | 0.322 | 0.239 | 32.0 / 108.2 | 0.27B | LoRA+head, Gemma-3-270m | code only |
- The index lists 55 entrants in total. Categories of technique: "Decoding" (parallel constrained decoding on stock models, no new weights), "Diffusion" (text diffusion in "Jev mode", for example the diffusiongemma-based open-jev at 44.16), "Trained" (heads and fine-tunes) and "Prior art". — [README](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/README.md); [data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
- Several reproductions expose a drop-in System One API. Examples: Hanno-Labs `jev-compatible-server`, and Kev ("Drop-in System One API. Kev-4B trains in 40 min on one H100; out of domain Kev-8B hits 79.6% vs Jev's 85.7%"). Decider ships Apache-2.0 weights and `pip install decider-ai`. — [HF Space news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- "Still not in the open": TypeSafe's weights, the RLCD algorithm, and "A trained open model matching Jev's calibration claims. The best open scorers now reach ~90% agreement with Jev". — [HF Space news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)
- A liquid LFM2.5 parallel-constrained-decoding entry is described as "Inference-only: 8–63× faster, field accuracy still ~60%". — [HF Space news.html](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/news.html)

### Inferences
- **Methodology caveats for the index:** it is maintained by the community around the reproductions (its data is built inside a `typesafe-diffusion-lab` checkout), so its authors have a stake in the results. Jev is measured over the network while local models run on a $8k+ datacenter GPU, so the latency columns are not comparable. The panel is general knowledge and reasoning, not short-sensor-description classification, so rankings may not carry over to VOX. Also, Jev's own numbers come from a single API version on a given date.
- **Raspberry Pi 4/5 feasibility (inference, not measured):** 0.07-0.5B encoder or GLiNER models (GLiNER 2.5 small, Verdict, Decision 1.0 Kai/Lex) should run on a Pi 5 CPU with ONNX or int8, likely in the tens to low hundreds of ms per call. 0.8B decoders (Decision 1.0 Eos, Kev 0.8B, Tev1-0.8B) may run via llama.cpp in GGUF form at a few hundred ms or more. 2-4B models (Decider 4B, JevK5) are borderline on a Pi 5 (8GB) at Q4 and likely too slow for interactive use. Anything at 12B or above is out of reach.
- **Better-fitting local options for VOX specifically:** (a) Hand-written rules on the bucketed features. These are deterministic and run in microseconds on the Pico itself. (b) A tiny trained classifier (a decision tree, logistic regression, or a small MLP with TFLite Micro) on the numeric features, with softmax plus temperature scaling for calibrated confidence and a "none" class. This runs on the RP2350 with no network. (c) If natural-language gesture definitions are wanted, a local zero-shot NLI or GLiClass-style model on a Pi 5, or constrained decoding with a small local LLM (for example via llama.cpp grammars), with a hosted Jev as an optional fallback. The Decision Index shows that small open models are weak zero-shot, so (a) or (b) will likely beat any language model on this narrow, numeric task.

### Gaps
- No Pi-specific benchmarks for any of these reproductions were found. Pi latency figures above are estimates only.
- The Space's UI (index.html) is JavaScript-rendered and was read through its JSON data files. The per-benchmark results for Jev were not exhaustively extracted.

## 9. Verified facts vs marketing, and independent reviews

### Takeaway
Two claims are verifiable. "Zero type errors" holds by construction, because outputs are constrained to your option set. The pricing is also verifiable. "Cannot hallucinate" is marketing: Jev can return a wrong valid value with high confidence. The "40x-200x faster" and "444.6x cheaper" figures are TypeSafe's own, self-run comparisons against slow reasoning LLMs. A third party found Jev's accuracy roughly equal to the best open 27B reproduction, and found its calibration good but not the best.

### Cited Findings
- TypeSafe claims: "can't hallucinate", type errors "0%", "193.6x faster", "444.6x cheaper". TypeSafe admits that "some bias could exist" in evals built by its own team. The references were "the smartest models (Astra and Fable)". — [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- The dev.to guide's table of self-run numbers: Jev accuracy 67.8% vs GPT-5.6 Terra 67.9% vs Claude Opus 5 73.1%, with Jev at about $0.0004 per case and 70-500 ms vs 3-329 s. It is caveated as "TypeSafe's own numbers, self-run and unreproduced". — [dev.to guide](https://dev.to/valyuai/how-to-use-jev-a-practical-guide-to-typesafes-system-one-model-g5e)
- The HN thread criticized the shift in messaging from "no type errors" to "can't hallucinate". A commenter noted that the model "can't emit an invalid type, but it can still emit a wrong valid value". — [HN (search summary)](https://news.ycombinator.com/item?id=49767192)
- "Because Jev has no way to spend compute at inference time … its intelligence ceiling is structurally bounded." — [search summary of reviews](https://www.eesel.ai/blog/typesafe-jev-review)
- eesel's own trial (284 live chats, a 100-ticket validation set): triage accuracy **93%**, spam caught at 100% with zero false positives. They called "can't hallucinate" oversold and the benchmark framing misleading, because the chart puts Jev on the efficiency frontier, not at maximum accuracy. — [eesel review](https://www.eesel.ai/blog/typesafe-jev-review)
- Third-party independent index: Jev scored 51.67 and the best open model 50.94. Jev's ECE was 0.074 against 0.015-0.023 for the best-calibrated open entrants. — [HF Space data/index.json](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
- TypeSafe's own jaggedness page lists failure modes: literal reading, math and counting, dates, indirection, context rot, adversarial state, and inconsistency across structurally equivalent questions. — [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)
- Mainstream coverage exists (Forbes, 2026-09-22, "Why Everyone Is Talking About Jev"). It was not fetched. — [Forbes](https://www.forbes.com/sites/ronschmelzer/2026/09/22/why-everyone-is-talking-about-jev-the-ai-that-doesnt-chat/)

### Inferences
- The speed advantage is real relative to *reasoning* LLMs. Relative to a local classifier on VOX's numeric features, Jev is orders of magnitude slower and adds a network dependency. The marketing comparison class is not VOX's comparison class.
- Early-access status, dynamically changing rate limits, alias drift and 529s all argue for VOX having a **local fallback path** (rules or a tiny classifier) even if Jev is used, so the cursor still works offline or during API trouble.

### Gaps
- No Reddit thread was found or fetched. The HN threads were only partly read, through search snippets and one fetched sub-thread.
- No independent latency measurement exists outside the HF index. No one has published a cold-start figure.
