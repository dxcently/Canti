# Teacher smoke test: Decider 4B and JevK5 on VOX v0 (first 300 rows of two test splits)

Date 2026-09-26. The GPU is a Radeon 8060S (gfx1151), using torch 2.11.0+rocm7.13, bf16, and fla Triton kernels. Each row
gets one `choice` question: state = `context`, instructions = `data/v0/policy.txt`, criteria = the option texts. Labels
are in `teachers/labels/`. The metrics come from `vox.evaluate.score`, via `python -m teachers.smoke` (raw output in
`teachers/logs/smoke_metrics.md`). The rows where either teacher is wrong are in
`teachers/labels/<split>.disagreements.jsonl`.

## Headline

| split | teacher | acc | ECE | NLL | false trigger | missed cmd | rows/s | tokens/s |
|---|---|---|---|---|---|---|---|---|
| test_iid | decider4b | **0.790** | 0.092 | **0.651** | **0.306** | 0.051 | 1.35* | 631* |
| test_iid | jevk5 | 0.707 | **0.047** | 0.813 | 0.671 | **0.000** | 1.65 | 1091 |
| test_unseen_phrasing | decider4b | 0.687 | 0.093 | 0.954 | **0.304** | 0.126 | 2.56 | 1211 |
| test_unseen_phrasing | jevk5 | **0.693** | **0.046** | **0.934** | 0.710 | **0.009** | 1.55 | 1038 |

- The top choices of the two teachers agree on 0.697 of test_iid rows and 0.620 of unseen_phrasing rows. Both are wrong
  with the same answer on 25 and 26 rows.
- **Neither teacher is good enough to replace the code labels.** At 0.69–0.79 accuracy they are about as far from the
  code labels as a weak student would be. They are useful as a *second opinion*: soft targets on the ambiguous kinds, and
  a way to find generator bugs (below).
- The two teachers fail in opposite directions:
  - JevK5 acts on almost everything: 67–71 % of the rows labelled "do nothing" get an action.
  - Decider is conservative: it misses 5–13 % of real commands and calls long flat hums and click-click "none".
  - JevK5 is much better calibrated (ECE 0.047 against 0.092).

\* The first test_iid Decider pass includes the Triton JIT compile and autotune. The warm Decider rate is the
unseen_phrasing figure.

## Accuracy by kind (decider4b / jevk5; "both" = rows where both teachers agree on the same wrong answer)

| kind | iid n | iid decider | iid jevk5 | iid both | unseen n | unseen decider | unseen jevk5 | unseen both |
|---|---|---|---|---|---|---|---|---|
| app_rule | 48 | 0.94 | 0.90 | 1 | 38 | 0.68 | 0.87 | 1 |
| cursor | 34 | 0.47 | 0.53 | 4 | 44 | 0.48 | 0.55 | 3 |
| default | 32 | 0.75 | 0.94 | 0 | 44 | 0.66 | 0.91 | 2 |
| disabled | 16 | 0.50 | 0.12 | 7 | 21 | 0.67 | 0.10 | 5 |
| global_rule | 26 | 0.92 | 0.81 | 0 | 22 | 0.50 | 0.23 | 7 |
| not_deliberate | 42 | 0.86 | 0.52 | 4 | 31 | 0.81 | 0.55 | 5 |
| phrase | 21 | 0.86 | 0.52 | 2 | 19 | 0.95 | 0.68 | 0 |
| phrase_rule | 21 | 1.00 | 1.00 | 0 | 26 | 1.00 | 1.00 | 0 |
| sequence | 42 | 0.83 | 0.98 | 1 | 49 | 0.69 | 0.98 | 1 |
| unbound | 18 | 0.56 | 0.17 | 6 | 6 | 0.33 | 0.00 | 2 |

- Easy for both: phrase_rule and app_rule.
- JevK5 wins on default and sequence.
- Decider wins on not_deliberate, disabled and phrase.
- Both are weak on cursor (about 0.5), unbound, and disabled.

## Where the teachers overrule the code label systematically: generator issues

The code labels are right according to the policy in most of the rows where both teachers agree against them. The teachers
are misreading the rules (see the next section). The 5 issues below, however, are problems in the **generated contexts or
splits**. In each case the teachers are reacting to something that really is in the input.

### 1. `sequence:` contradicts the sound that was heard (not_deliberate and cursor-junk rows). Most important.

For not_deliberate rows, `junk_sound()` draws a random contour, but the `sequence:` line keeps the originally sampled
gesture. `make_cursor`'s junk path replaces `heard` but keeps `sc.sequence`. The result is a context that says, in effect,
"you heard a level hum, the recognised sequence is `fall`".

Counts:
- train: 4007 / 4995 single-sound not_deliberate rows (about 80 %) and 458 / 4311 cursor rows.
- first 300 rows: 199 / 251 of test_iid and 208 / 249 of unseen_phrasing.

Both teachers follow the `sequence:` line. A student trained on these rows learns "ignore `sequence:`", which is wrong
for every other kind.

```
test_iid-0  kind=not_deliberate why=short_flat  gold=none
  sound 1: hum that stays level; pitch change small; duration short (150-400 ms); ... sounds like hum
  sequence: fall
  -> decider4b swipe_down 0.917, jevk5 swipe_down 0.708
test_iid-66  kind=not_deliberate why=background music  gold=none
  sound 1: hum that rises from low to high; pitch change medium; ... sounds like background music
  sequence: dip
  -> decider4b swipe_left 0.955, jevk5 swipe_left 0.687
test_iid-185  kind=cursor  gold=none
  sound 1: hum that rises then falls; ... sounds like coughing
  sequence: pop
  -> both move_up_right_slow (0.28 / 0.48)
```

**The issue is still present in data/v1 and data/v2.** A rough contour check over test_iid finds a mismatched sequence on
191 of 244 not_deliberate rows. The fix is to derive `sequence:` from the heard sounds. The alternative is to drop the line for junk sounds, or to render
it as `sequence: (not recognised)`.

### 2. Flat hums with a medium or large pitch change

`junk_sound` draws the excursion from `EXCURSION[1:]` even when the contour is `flat`. This produces "stays level; pitch
change large". Counts: 894 train rows and 36 in the first 300 of test_iid.

```
test_unseen_phrasing-10  kind=not_deliberate why=coughing  gold=none
  sound 1: hum that stays level; pitch change large (over 4 semitones); duration medium; tone breathy; sounds like coughing
  sequence: dip
  -> decider4b swipe_left 0.979, jevk5 swipe_left 0.724
```

This row also shows issue 1. The fix is to force a small excursion for flat hums.

### 3. Policy wording collision: "very short"

The policy says "if … a hum is noisy, **very short**, … choose do nothing". Every discrete sound (pop, click, hiss) is
rendered with "duration very short (under 150 ms)". Read literally, the rule only covers hums, but both teachers apply it
to clicks. 11167 of the 23879 actionable gesture rows in train contain such a sound.

```
test_unseen_phrasing-15  kind=default  gold=enter_cursor_mode
  sound 1/2: a tongue click; duration very short (under 150 ms) ...   sequence: click then click
  -> decider4b none 0.682, jevk5 none 0.588
```

The fix is to drop the duration bucket for discrete sounds, or to reword the policy as "a *hum* shorter than 150 ms".

### 4. Held-out phrases are not held out

"previous", "turn it down", "enlarge", "app switcher" and "favourite" are all in `schema.PHRASES`, so
test_unseen_phrasing is not fully unseen for phrases. Check the split logic before treating that split as an OOD number.

### 5. Ambiguous phrase labels

```
test_iid-243  kind=phrase  spoken phrase: "go to the last one"  gold=previous_item
  -> decider4b next_item 0.688, jevk5 next_item 0.578
```

"Last" can mean either previous or final. Such phrases should be dropped, or the label softened.

## Teacher weaknesses (the code label is correct)

- **Disabled rules are ignored.** test_iid-119, 126, 149 and 213 contain "Disable a pop followed by a lip pop in X".
  Both teachers still pick `back` at about 0.93. JevK5 scores 0.10–0.12 on disabled rows.
- **Unbound sequences are prefix-matched.** For example, test_iid-28 "dip then fall" gets swipe_left. JevK5 scores 0.00–0.17
  on unbound rows.
- **Paraphrased gesture words in global rules are not mapped.**
  - unseen-33: "upward glide" should give notifications; both pick swipe_up.
  - unseen-87: "lip smack" should give recents; both pick tap.
  - unseen-132: "clicking noise followed by a lip smack" should give home; both pick listen_for_phrase.
  - Result: global_rule on unseen_phrasing drops to 0.50 (Decider) and 0.23 (JevK5).
- **Cursor direction and speed.** test_iid-284: "fall" should give move_down_slow; both pick move_up_slow. Cursor accuracy
  is about 0.5 for both.
- **Decider under-acts on long flat hums.**
  - unseen-7: flat, medium, whistle. Decider says none 0.705; JevK5 is correct with long_press 0.762.
  - unseen-55: Decider says none 0.436; JevK5 is correct with long_press 0.806.
- **JevK5 over-triggers.** It has a false-trigger rate of 0.67–0.71 on none-labelled rows.

Suggested use: distil from the code labels. Use the teachers only as an auxiliary soft target on kinds where they are
reliable, or as a disagreement filter for finding bad rows. If they are used as soft targets, keep them off disabled,
unbound, not_deliberate and cursor rows. Fix issues 1–3 first, and relabel with the teachers only after that. Their current
errors on not_deliberate rows are mostly caused by issue 1.

## Throughput

- The input is about 470 tokens per row for Decider and about 665 for JevK5 (JevK5's SemIf JSON prompt is longer).
- The measured rate is 1.3–2.6 rows/s per teacher, or 630–1200 input tokens/s, at `--token-budget 8192`. That is about
  9 TFLOP/s effective.
- The runs **shared the GPU with 2–3 student training jobs and llama-server**, and free VRAM swung between 0.5 and 11 GB.
  These numbers are a lower bound, not the capability of the card.
- At this rate the 40k × 2 teachers run would take about 9 h, and it would compete with training.
- The throughput has not been profiled on an idle GPU. `--token-budget 16384` (the default) is expected to help only if
  there is VRAM for it.

## Parity with the upstream runtimes (`teachers/parity.py`, `teachers/parity.json`)

- **decider4b.** Compared against `Decider.system_one` at batch 1 with a mask, on 24 rows (12 iid and 12 unseen). Ours used
  padded batches of 6. The max |Δp| is 0.0185, and the argmax matches on 23 of 24 rows. The details of the one flip were
  not recorded in that run. This result is from the run before the embedding moved to the CPU.
- **jevk5.** The upstream `JevK5.decide` pass completed, but our pass OOMed because the shared GPU had no free memory.
  A rerun at 05:48 started with 13.6 GB free. It OOMed while loading the upstream Decider, because other jobs took the
  memory back within seconds. JevK5 parity, and a recheck of Decider on the CPU-embedding path, are **still open**. Run
  `teachers/run.sh python -m teachers.parity --rows 24` when the GPU is quiet.

## Licences

- **decider-4b** (`Mapika/decider-4b`, `decider-ai` code). Licence: Apache-2.0. It is trained on questions written by
  Qwen3.6-27B and on public datasets, with no stated third-party terms.
- **JevK5** (`alibiserikbay/JevK5`, `jevk5` runtime). Licence: Apache-2.0. The card says 14,138 of its training questions
  were written by "GPT-6 Luna" through the OpenAI API, "generated under OpenAI's terms". Distilling VOX students from
  JevK5 labels is a downstream use of those outputs, so flag it if a student ships commercially.
- **Qwen3.5-4B base** (both teachers). Licence: Apache-2.0.
- **flash-linear-attention.** Licence: MIT.
- **Hopper / Tev1-4B** (the fallback). It has a custom research-and-demo licence. It was not needed, because JevK5 runs on
  ROCm as a merged model.

## What failed and how it was fixed

1. The MIOpen depthwise `conv1d` failed with `miopenStatusUnknownError` on gfx1151. The fix rebinds it to fla's Triton
   causal conv (`teachers/rocm_compat.py`).
2. Triton failed with "Failed to find C compiler" (NixOS). The fix adds `nixpkgs#gcc` to the shell; `teachers/run.sh`
   does this.
3. Triton's autotuner `do_bench` failed on HIP event timing: first a `ZeroDivisionError`, then a hang of about 1e8
   iterations. The fix is a bounded 10-rep `do_bench` (`rocm_compat.py`).
4. OOM on the shared GPU. The idle llama-server holds 7.6 GB and the student jobs take 4–14 GB. Fixes:
   - the embedding and lm_head stay on the CPU (1.27 GB saved)
   - the model loads on the CPU first
   - `expandable_segments`
   - recursive batch halving on OOM
   - wait loops before starting

   torch reports the device capacity as 15.49 GiB even though sysfs says there is 32 GiB of VRAM. Budget memory for the
   smaller number.
5. `/v1/systemone` servers were not used. Both upstream engines run one request at a time behind CUDA graphs and
   `torch.compile`. The in-process scorer rebuilds each project's exact prompt with its own prompt code and batches rows
   (see README).
