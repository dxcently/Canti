# Verdict student (multilingual-e5-small on VOX)

Verdict ([Manavarya09/verdict](https://github.com/Manavarya09/verdict), Apache-2.0; cloned at `third_party/verdict`)
scores options with a bi-encoder: `logit_k = 20 * cos(E("query: " + state), E("passage: " + option_k))`. The encoder is
`multilingual-e5-small` (118M parameters, MIT) fine-tuned into `Manav2op/verdict-small`. Every run here starts from
`Manav2op/verdict-small` and is fine-tuned on VOX rows. `state` is the row's `context` string, used verbatim.
`policy.txt` is not used: the rules that matter for a row are already written into its context.

There are three architectures, all built on the same weights, so they differ only in how option and context interact:

| `--arch` | Scoring | Cost per decision | Extra params |
|---|---|---|---|
| `bi` | Verdict's own: context and option are encoded separately and compared by cosine | 1 encoder pass (option embeddings cached; VOX has 49 fixed option texts) | none |
| `cross` | `"query: ctx </s></s> passage: opt"` pair, mean-pool, then `Linear(384, 1)` | K pair passes (K = 6–16, mean 11) | 385 |
| `cross_cos` | the same pair pass, scored as `20 * cos(mean(context-span tokens), mean(option-span tokens))` | K pair passes | none |

`cross_cos` is the smallest change that adds cross-attention without discarding Verdict's cosine geometry. At step 0 it
is the bi-encoder with the option tokens able to see the context. `cross` starts from a random linear head.

## Is a bi-encoder able to follow rules written in the state?

I was asked to be skeptical about this. My conclusion is that it is less of a problem on VOX than it first looks.

- **What a bi-encoder cannot do.** Its answer depends only on the state embedding, compared against option embeddings
  that were computed without seeing the state. It cannot react to *which* options are offered, and it cannot read an
  option wording it has never seen as a function of the state.
- **Why that does not hurt here.** On VOX, every rule, binding and gesture lives in the context. The context encoder has
  full self-attention over all of it. The model's job is "map this state to one of 49 fixed prototypes", and a 12-layer
  encoder can learn that. `test_unseen_phrasing` changes wording inside the context and introduces **no** new option
  texts, so VOX does not test the bi-encoder's real weakness.
- **Evidence.** See the results below. After 2,000 rows the bi-encoder gets the rule kinds (`app_rule`, `global_rule`,
  `phrase_rule`, `disabled`) at 95–100% on both test splits. Its errors are in `not_deliberate`, `unbound`, `cursor`
  and `default`; judging by the names, those are about the gesture signal, not about a written rule. Kev, which reads
  everything jointly, also has most of its errors in `cursor`. Adding cross-attention (`cross`, `cross_cos`) did
  **not** help; it hurt, including on the rule kinds.
- **Where it will break.** Unseen option texts, per-row option descriptions, or options whose meaning depends on the
  state (for example "the app named in rule 3"). If VOX adds any of these, re-run `cross_cos`.

## Files

| File | Purpose |
|---|---|
| `vlib.py` | `Student` (all three archs), save/load format, e5 prefixes, `span_cos`. |
| `train.py` | Trains with CE on hard labels, plus optional KL-to-teacher (`--teacher-probs`, `--alpha`, `--tau`). Fits T on validation. Writes `runs/<name>`. |
| `export_onnx.py` | `<run>/onnx/{encoder,cross,cross_cos}.onnx`, plus a per-channel dynamic int8 copy and a parity check. |
| `predict.py` | Writes `preds/<split>.<name>.jsonl` with `{id, probs, latency_ms_gpu?, latency_ms_cpu?, latency_ms_onnx_int8?}` and a `.summary.json` with accuracy by `kind`, ECE, NLL, Brier, ONNX-int8 accuracy and latency percentiles. |
| `../common.py` | Data, teacher loading, loss, metrics and temperature fit. Shared with Kev. |

## Commands

Run from `/home/khoa/VOX/finetune`.

```bash
RUN='nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c'
PRE='source ./env.sh; source .venv/bin/activate; export CC=gcc;'

# smoke training: 2,000 rows, 3 epochs, batch 16 (375 steps)
$RUN "$PRE python students/verdict/train.py --arch bi        --train train --limit 2000 --epochs 3 --batch 16 --lr 5e-5 --out students/verdict/runs/verdict-bi-smoke"
$RUN "$PRE python students/verdict/train.py --arch cross     --train train --limit 2000 --epochs 3 --batch 16 --lr 5e-5 --out students/verdict/runs/verdict-cross-smoke"
$RUN "$PRE python students/verdict/train.py --arch cross_cos --train train --limit 2000 --epochs 3 --batch 16 --lr 5e-5 --out students/verdict/runs/verdict-crosscos-smoke"

# with teacher soft labels
$RUN "$PRE python students/verdict/train.py --arch bi --train train --teacher-probs teachers/train.<teacher>.jsonl --alpha 0.5 --tau 1 --out students/verdict/runs/verdict-bi-<teacher>"

# ONNX export (fp32 + int8) -- run before predict.py so that it can score and time the int8 model
$RUN "$PRE python students/verdict/export_onnx.py students/verdict/runs/verdict-bi-smoke"

# predictions: bulk probs on GPU; batch-1 latency on GPU (all rows), torch CPU (first 50), ONNX int8 CPU (all rows)
$RUN "$PRE python students/verdict/predict.py --run students/verdict/runs/verdict-bi-smoke --split test_iid --limit 300 --latency-cpu 50"

# zero-shot baseline
$RUN "$PRE python students/verdict/predict.py --run Manav2op/verdict-small --arch bi --split test_iid --limit 300 --name verdict-zeroshot"
```

`--micro` sets the micro-batch used for gradient accumulation. It defaults to `--batch` for `bi` and to 4 rows (about
44 pairs) for the cross archs. Token embeddings are frozen by default (`--train-embeddings` unfreezes them), which
leaves 21.6M trainable parameters. The 250k-token vocabulary matrix is 96M of the 118M parameters, and VOX uses a small part of it.

## Smoke results (2,000 train rows, 3 epochs, batch 16, lr 5e-5; 300 rows per test split)

These were measured on a shared box: another agent was training on the same GPU the whole time, and the CPU load average
was about 26. Read the latency figures as upper bounds and the accuracy figures as ±2.5 points (binomial 95% CI at
n = 300).

| Run | Split | Acc | ECE | NLL | Acc ONNX int8 | Train rows/s | Peak GPU |
|---|---|---|---|---|---|---|---|
| `bi` | test_iid | **0.947** | 0.022 | 0.120 | 0.963 | 33.8 | 2.2 GB |
| `bi` | test_unseen_phrasing | **0.957** | 0.028 | 0.155 | 0.943 | | |
| `cross` | test_iid | 0.727 | 0.043 | 0.755 | 0.700 | 6.5 | 5.2 GB |
| `cross` | test_unseen_phrasing | 0.587 | 0.073 | 1.031 | 0.590 | | |
| `cross_cos` | test_iid | 0.667 | 0.069 | 0.857 | 0.650 | 14.0* | 5.2 GB |
| `cross_cos` | test_unseen_phrasing | 0.653 | 0.073 | 0.915 | 0.630 | | |
| zero-shot `verdict-small` (bi) | test_iid | 0.140 | 0.206 | 2.929 | | | |

\* The `cross_cos` run happened while the GPU was less contended. `cross` and `cross_cos` do the same work per step, so
the gap in rows/s comes from contention, not from the architecture.

Accuracy by `kind` (test_iid / test_unseen_phrasing):

| kind | bi | cross | cross_cos |
|---|---|---|---|
| app_rule | 1.00 / 1.00 | 0.85 / 0.55 | 0.60 / 0.61 |
| global_rule | 1.00 / 0.95 | 0.92 / 0.95 | 0.65 / 0.68 |
| phrase_rule | 1.00 / 1.00 | 1.00 / 1.00 | 0.86 / 0.81 |
| disabled | 1.00 / 1.00 | 0.69 / 0.33 | 1.00 / 0.81 |
| unbound | 0.83 / 0.83 (n=6) | 0.72 / 0.83 | 0.61 / 0.83 |
| not_deliberate | 0.83 / 0.87 | 0.95 / 0.94 | 0.86 / 0.94 |
| cursor | 0.91 / 0.89 | 0.44 / 0.39 | 0.59 / 0.61 |
| default | 0.91 / 1.00 | 0.25 / 0.20 | 0.38 / 0.50 |
| phrase | 1.00 / 1.00 | 0.81 / 0.79 | 0.76 / 0.79 |
| sequence | 1.00 / 0.96 | 0.67 / 0.53 | 0.60 / 0.45 |

Latency at batch size 1, end to end per row, median (p90), in ms:

| Run | GPU torch bf16 | CPU torch fp32, 4 threads | CPU ONNX int8, 4 threads |
|---|---|---|---|
| `bi` (test_iid / unseen) | 17.5 (24.3) / 13.1 | 611 (798) / 811 | **7.9 (9.7)** / 14.6 |
| `cross` | 41 (60) / 32 | 957 / 1447 | 128 (249) / 158 |
| `cross_cos` | 75 / 43 | 1086 / 1108 | 128 / 111 |

What these results show:

- **`bi` works.** It reaches 0.95 on both splits after 2,000 rows, with ECE of about 0.02–0.03 after temperature scaling.
  It does not drop on unseen phrasing. ONNX int8 accuracy is within noise of torch (+1.7 / −1.3 points).
- **Neither cross-encoder is competitive at this budget.** I expected `cross` to lag because of its random head, but
  `cross_cos` has no new parameters and starts from Verdict's cosine geometry, and it did no better (0.65–0.67).
  My reading: e5 was pre-trained and Verdict fine-tuned as a bi-encoder, so a `query ... </s></s> passage ...` pair is
  out of distribution. Each pair is also scored on its own, whereas `bi` gets one shared state embedding, which amounts
  to a 49-way classifier. 2,000 rows (about 22k pairs) is not enough to re-learn the pair encoding. With more data a
  cross-encoder might catch up, but on VOX it has nothing to gain (see above) and costs about 11× the compute per
  decision. I do not recommend spending the full run on it.
- **Temperature** was fitted on 300 validation rows: 1.23 (bi), 0.95 (cross), 1.12 (cross_cos). At T = 1, test ECE
  is 0.032 / 0.036 for bi, so the gain from fitting T is small but consistent.

## Recommended full run (bi)

`--arch bi --train train --epochs 3 --batch 32 --lr 5e-5 --warmup 0.06 --val-limit 2000`, with `--teacher-probs ...
--alpha 0.5 --tau 2` once the teacher labels exist. At about 34 rows/s on this GPU (shared), 3 × 40k rows takes about
1 hour. Keep the frozen token embeddings. Fit T on the full 2k validation split, not on 300 rows. Export with
`export_onnx.py`, then check `metrics_onnx_int8` on all four test splits, including `test_unseen_apps`, which was not
run in the smoke.

## Caveats

- **Licence.** Verdict code and `Manav2op/verdict-small` are Apache-2.0. The base model
  `intfloat/multilingual-e5-small` is MIT. Fine-tuned runs can be shipped under Apache-2.0.
- **`verdict.Verdict(model=<bi run dir>)`.** A bi run directory also contains sentence-transformers module files, and
  Verdict chooses e5 prefixes when the path contains `/verdict-`, so the directory loads. Verdict's own API, however,
  renders a *structured* state through `jev.py` before encoding it. These students were trained on VOX's raw context
  string, so pass the context string as the state, or the input distribution changes.
- **ROCm.** `vlib.py` sets `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`. Without it, SDPA on gfx1151 falls back to
  math attention, and the cross archs (about 44 pairs × 300 tokens per micro-batch) run out of memory on the shared GPU.
- **ONNX int8.** `quantize_dynamic` uses per-channel QInt8 weights. On VOX contexts, embeddings from per-tensor int8
  had mean cosine 0.918 to fp32, and per-channel 0.967. The worst single case is still about 0.73. The accuracy impact
  is small for `bi` (see the results; it was noise-level here) and a few points for `cross`. Always check
  `metrics_onnx_int8` in the summary, and keep the fp32 ONNX (470 MB) as a fallback (`--onnx-fp32`).
- **Temperature.** `train.py` fits T on the first `--val-limit` validation rows and prints ECE on the same rows, so that
  number is optimistic. Use the test-split summaries.
- **torch-CPU latency on this box is not representative.** e5-small fp32 takes about 600 ms per 135-token forward in
  torch here at 4 threads (the load average was about 26 during the runs). onnxruntime on the same CPU and threads takes
  about 8 ms. Quote the ONNX figures.
- **Phone feasibility: good for `bi`, marginal for the cross archs.**
  - `bi`: the int8 ONNX is 118 MB, and a decision is one encoder pass (about 8 ms on 4 desktop threads here; expect
    roughly 20–60 ms on a mid-range phone CPU). Option embeddings are precomputed.
  - `cross` / `cross_cos`: K pair passes per decision, about 11× the compute (about 130 ms on 4 desktop threads here),
    and there is no cache.
  - The upstream `verdictml` package already ships an ONNX engine (`engines/onnx.py`). An `onnx/encoder_int8.onnx`
    from `export_onnx.py` is the drop-in artifact for Android (onnxruntime-mobile) or iOS.
