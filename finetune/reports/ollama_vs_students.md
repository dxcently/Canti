# Ollama cloud (DeepSeek V4.1 Flash) vs the students

Run on 2026-09-26 with `sweeps/ollama_eval.py`. Per-set JSON is in `sweeps/eval/ollama-dsv41flash.<set>.json`, and the cached answers are in `preds/ollama/<set>.dsv41flash.jsonl`.

## Setup

- **Model:** `deepseek-v4.1-flash`, taken from `https://ollama.com/api/tags` (digest 97308b916fc3, dated 2026-09-10). Called from the PC at `https://ollama.com/api/chat`.
- **Request:**
  - `stream:false`, `think:false` (accepted), temperature 0.
  - `format` is a JSON schema with `{"choice": enum[option keys]}`.
  - The system prompt is the dataset's `policy.txt`.
  - The user message is the row's context plus one `key: option text` line per option.
- **The model ignores `format`.** It answers with free text: usually the bare key (`t9`), sometimes the option line echoed back (`t6: Download (item, bottom)`), and rarely prose.
  - The parser accepts three strict forms: `{"choice": k}` or `"k"`, the bare key, and `k: <start of option k's text>`.
  - Anything else counts as an error: prose, unknown keys (`hiss: go back`), or a key followed by other text.
  - With JSON and bare keys only (first pass, log in `preds/ollama/run1_strict_parse.log`), the error rate was 5–24% per set. The echo form rescues most of that. The app uses the same three forms (`OllamaClient.parseChoice`).
- **Calls:** 1,551 in total, at most 4 at a time, with no 429s. Latency is wall clock from the PC (home connection), with a 20 s client timeout.
- **Students:**
  - jevlike = `sweep-targets-v2-e5-small-e3` for targets and `sweep-v5-e5-small-e3` for v5.
  - Verdict = `verdict-bi-targets-v2` and `verdict-bi-v5`.
  - Both are scored on exactly the same rows. The script aborts if their predictions don't cover or line up with those rows. The metric code is `vox.evaluate.score`, plus the `vox.real_targets` score logic for the acceptable-set accuracy.
- **Two cloud rows per set:**
  - "cloud" is scored on the answered rows only (n is lower when there were errors).
  - "cloud → jevlike" is what the phone would do: the cloud answer if it is valid and inside the budget (2.5 s for targets, 1.5 s otherwise), else jevlike's answer. It covers all rows.
- **Row sets:**
  - targets-v2 `test_unseen_phrasing`: 80 per kind, 480 rows. It also reports accuracy re-weighted to the file's kind mix ("pop.").
  - targets-v2 `test_iid` and `test_unseen_apps`: 100 random rows each.
  - `real-targets-v1/test_emulator`: all rows, from a snapshot of **557 rows** taken 2026-09-26 17:10 (sha256 `90222e3d…c9ccdb4d9c1`) while the dataset agent was still writing it.
  - v5 `test_unseen_phrasing`: kinds `phrase` + `screen_phrase`, 314 rows.
  - Nothing from `real-targets-v1/zflip/` was read or sent.

## Results

Accuracy is shown as acc; for real-targets it is shown as gold / acceptable set. "none rec." is the recall of "none of these" / do-nothing rows, which is 1 − the false-trigger rate. "missed" is the rate of commands answered "none".

| set | model | n | acc | none rec. | missed | p50 ms | p95 ms | errors | in budget |
|---|---|---|---|---|---|---|---|---|---|
| **tv2 unseen phrasing** | cloud | 466 | **0.891** (pop. 0.843) | 0.705 | 0.034 | 397 | 856 | 2.9% (8 invalid, 6 timeouts) | 97.1% |
| | cloud → jevlike | 480 | 0.879 (pop. 0.821) | 0.713 | 0.043 | | | | |
| | jevlike | 480 | 0.592 (pop. 0.545) | 0.912 | 0.263 | | | | |
| | Verdict | 480 | 0.648 (pop. 0.537) | 0.850 | 0.200 | | | | |
| tv2 iid | cloud | 98 | 0.929 | 0.857 | 0.013 | 655 | 868 | 2% (invalid) | 98% |
| | jevlike / Verdict | 100 | 1.000 / 1.000 | 1.000 | 0.000 | | | | |
| tv2 unseen apps | cloud | 97 | 0.948 | 0.789 | 0.013 | 393 | 884 | 3% (timeouts) | 97% |
| | jevlike / Verdict | 100 | 0.970 / 0.980 | 1.000 | 0.037 / 0.025 | | | | |
| **real-targets emulator** | cloud | 555 | **0.903 / 0.951** | 0.714 | 0.011 | 789 | 1176 | 0.4% (invalid) | 99.6% |
| | cloud → jevlike | 557 | 0.901 / 0.950 | 0.718 | 0.013 | | | | |
| | jevlike | 557 | 0.447 / 0.481 | 0.918 | 0.519 | | | | |
| | Verdict | 557 | 0.646 / 0.691 | 0.624 | 0.180 | | | | |
| v5 phrase + screen_phrase | cloud | 310 | 0.800 | 0.659 | 0.023 | 805 | 1165 | 1.3% (invalid) | 97.5% (1.5 s) |
| | cloud → jevlike | 314 | 0.806 | 0.659 | 0.019 | | | | |
| | jevlike | 314 | **0.978** | 0.955 | 0.000 | | | | |
| | Verdict | 314 | 0.911 | 1.000 | 0.011 | | | | |

### Accuracy by kind

**tv2 unseen phrasing:**

| model | item | name | name_pos | none | position | unlabeled |
|---|---|---|---|---|---|---|
| cloud | 1.000 | 0.853 | 0.868 | 0.705 | 0.910 | 1.000 |
| jevlike | 0.150 | 0.400 | 0.588 | 0.912 | 0.562 | 0.938 |
| Verdict | 1.000 | 0.388 | 0.537 | 0.850 | 0.475 | 0.637 |

**real-targets emulator (gold):**

| model | appearance | casual | function | name | near_none | none | position |
|---|---|---|---|---|---|---|---|
| cloud | 0.938 | 0.989 | 0.958 | 0.979 | 0.818 | 0.714 | 0.838 |
| jevlike | 0.450 | 0.220 | 0.312 | 0.305 | 0.182 | 0.918 | 0.545 |
| Verdict | 0.662 | 0.670 | 0.562 | 0.832 | 0.364 | 0.624 | 0.566 |

- On real-targets, the cloud scores 0.65 / 0.91 on ambiguous rows (gold / acceptable) and 0.96 on unambiguous rows.

**v5 phrases, split by whether the phrase is in the app's phrase table** (`schema.PHRASES` + the pause/play words, which the rule decider resolves exactly):

| phrase | n | cloud (answered) | jevlike |
|---|---|---|---|
| known wording | 180 | 125/176 = 0.71 (screen_phrase 77/123 = 0.63) | 178/180 = 0.99 |
| unknown wording | 134 | 123/134 = 0.92 | 129/134 = 0.96 |

### Latency, timeouts and tokens (all 1,551 calls)

- **Latency:** p50 715 ms, p95 1,085 ms, p99 1,392 ms. The server's own time is about 200 ms p50, so most of the wall time is network and queueing.
- **Slow calls:** 20 calls (1.3%) took over 1.5 s. 9 calls (0.6%) hung until the 20 s client timeout; on the phone, the 2.5 s / 1.5 s deadline cuts these off and falls back locally.
- **Tokens:** 449,875 prompt and 5,818 output in total. That's about 220–235 prompt tokens per target question, about 550 per v5 action question (the full rules and defaults text), and 3–5 output tokens.
- **Cost:** Ollama cloud is billed by subscription plan with usage limits, not per token. At about 300 tokens per call, a heavy day of use (a few hundred escalations) is a few hundred thousand tokens, small next to this eval.

## Caveats

- **Possible same-family advantage.** Every real-targets phrase was written by **DeepSeek V4 Pro** (`phrase_source` is `deepseek-v4-pro` for all 557 rows; there are no `user` rows in the emulator set yet). The model under test is from the same family, so its real-targets score may be inflated. A by-source breakdown can't separate this until user-written phrases exist. The synthetic tv2 sets were written by the generator and the wording bank, not DeepSeek, and show the same gap (0.89 vs 0.59/0.65 on unseen phrasing).
- **`none` is the cloud's weak spot.** It picks something when it should say "none of these": recall is 0.71 on real-targets and 0.70 on tv2. That's why its answers must be confirmed before a tap (see below).
- **The students have learned the synthetic distribution.** They score 1.00 on tv2 iid, but they fall apart on unseen phrasing and real screens. The cloud is steadier across sets.
- **The v5 phrase rows use the reduced option lists** the students were scored on. The app sends the full 24–25 option table.
- **Latency was measured from a PC on home broadband.** Phone latency on mobile data will be higher; the phone's event log records the real numbers.

## Verdict

- **Target picking: yes, route it to the cloud.**
  - On real screens the cloud is +26 points over Verdict (0.90 vs 0.65 gold; 0.95 vs 0.69 acceptable).
  - On unseen phrasing it is +24–30 points.
  - 97–99.6% of calls come back inside 2.5 s.
  - Because of the weak `none` recall and the lack of a calibrated confidence, a cloud pick should be highlighted and confirmed with a pop rather than tapped outright.
- **Phrases: not as a first stop.**
  - For phrases in the app's table, the rule decider is exact and the cloud gets 0.71. It mostly breaks the screen tie-break rule ("pause" when already paused means do nothing).
  - For unknown wordings the cloud (0.92) is close to jevlike (0.96), so it is a good fallback when no local model is reachable or the local model is unsure. It is not a replacement.
- **Latency:** p50 0.7 s and p95 1.1 s is fine for targets and phrase fallbacks. It is far too slow for bound hum gestures, which stay local.
