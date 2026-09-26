# Kev student (Kev-0.8B on VOX)

Kev ([jaredpalmer/kev](https://github.com/jaredpalmer/kev), Apache-2.0; cloned at `third_party/kev`) is a Qwen3.5-0.8B-Base
backbone with a rank-16 LoRA and a pointer head. The head scores each option's `</opt>` hidden state against a final
`<decide>` token. Here it is warm-started from `jaredpalmer/kev-0.8b` (adapter + head + its pinned base revision) and
fine-tuned on VOX rows.

A VOX row maps to one Kev Choice question:

| Kev field | VOX source |
|---|---|
| state | `context` |
| instructions | `data/v0/policy.txt` (the same for every row) |
| options | `options`, in row order, no descriptions |

`probs` therefore line up with `options`. This is the same record `kev.serve` builds from a `/v1/systemone` choice request
with `criteria = {option_text: null}`, so a run directory serves unchanged with `python -m kev.serve --run <run>`.

## Files

| File | Purpose |
|---|---|
| `kevlib.py` | Record format and ROCm workarounds (see Caveats). |
| `train.py` | Trains with CE on hard labels, plus optional KL-to-teacher (`--teacher-probs`, `--alpha`, `--tau`). Fits a temperature on validation and writes a Kev checkpoint to `runs/<name>`. |
| `predict.py` | Writes `preds/<split>.<name>.jsonl` with `{id, probs, latency_ms_gpu?, latency_ms_cpu?}` and a `.summary.json` with accuracy by `kind`, ECE, NLL, Brier and latency percentiles. |
| `../common.py` | Data loading, teacher loading, loss, metrics and temperature fit. Shared with the Verdict student. |

## Commands

Run from `/home/khoa/VOX/finetune`. `nixpkgs#gcc` is required: Triton compiles its HIP launcher at runtime for the
flash-linear-attention DeltaNet kernels.

```bash
RUN='nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c'
PRE='source ./env.sh; source .venv/bin/activate; export CC=gcc;'

# smoke training: 2,000 rows, 1 epoch, 125 optimizer steps
$RUN "$PRE python students/kev/train.py --train train --limit 2000 --epochs 1 --batch 4 --accum 4 --lr 5e-5 --val-limit 300 --out students/kev/runs/smoke"

# with teacher soft labels (when teachers/train.<teacher>.jsonl exists)
$RUN "$PRE python students/kev/train.py --train train --teacher-probs teachers/train.<teacher>.jsonl --alpha 0.5 --out students/kev/runs/<name>"

# predictions + latency (GPU batch 1 on every row, CPU batch 1 on the first 20 rows, 4 threads)
$RUN "$PRE python students/kev/predict.py --run students/kev/runs/smoke --split test_iid --limit 300 --name kev-smoke --latency-cpu 20"

# zero-shot baseline (released checkpoint, no VOX training)
$RUN "$PRE python students/kev/predict.py --run jaredpalmer/kev-0.8b --split test_iid --limit 300 --name kev-zeroshot"

# serve (TypeSafe /v1/systemone wire format; needs `uv pip install fastapi uvicorn` first, not installed yet)
$RUN "$PRE cd third_party/kev && python -m kev.serve --run ../../students/kev/runs/smoke --port 8009"
```

Loss per row is `(1-alpha)*CE(label) + alpha*tau^2*KL(teacher || student)`. Rows with no teacher entry use CE only, and
a teacher row whose `probs` length differs from the number of options is an error.

## Smoke results

Training used 2,000 rows, 1 epoch, 125 optimizer steps (batch 4 × accum 4), lr 5e-5, LoRA r=16, warm start from
`jaredpalmer/kev-0.8b`, bf16 autocast and gradient checkpointing. Each test split was predicted on its first 300 rows.
The GPU was shared with another agent's training throughout, and the CPU load average was about 26. Latency and
throughput are upper bounds; accuracy is ±2.5 points (binomial 95% CI at n = 300).

| Run | Split | Acc | ECE | NLL | ECE at T=1 |
|---|---|---|---|---|---|
| kev-smoke | test_iid | **0.980** | 0.027 | 0.058 | 0.014 |
| kev-smoke | test_unseen_phrasing | **0.923** | 0.031 | 0.243 | 0.051 |
| kev-0.8b zero-shot | test_iid | 0.493 | 0.109 | 1.337 | 0.306 |

T = 1.77 was fitted on 300 validation rows. Kev-0.8b's own T (2.35) was used for the zero-shot row.

Accuracy by `kind` (test_iid / test_unseen_phrasing):

| kind | kev-smoke | zero-shot (iid) |
|---|---|---|
| app_rule | 1.00 / 0.87 | 0.40 |
| global_rule | 1.00 / 0.95 | 0.15 |
| phrase_rule | 1.00 / 1.00 | 0.90 |
| disabled | 1.00 / 1.00 | 1.00 |
| unbound | 0.94 / 1.00 (n=6) | 0.94 |
| not_deliberate | 1.00 / 0.94 | 1.00 |
| cursor | 0.85 / 0.77 | 0.26 |
| default | 1.00 / 0.93 | 0.00 |
| phrase | 1.00 / 1.00 | 0.48 |
| sequence | 1.00 / 0.96 | 0.29 |

Speed:

| | Value |
|---|---|
| Training | 1.21 rows/s (522 tokens/s, 432 tokens per row), peak 4.0 GB, 1,653 s for 2,000 rows |
| Bulk inference, batch 16, GPU | 6.4 rows/s (contended) to 12.5 rows/s |
| Latency, batch 1, GPU bf16 | median 282 ms (p90 346) while contended; median 65 ms (p90 73) in the quieter unseen-split run |
| Latency, batch 1, CPU fp32, 4 threads, torch reference kernels | 9.5 s (test_iid, n=10) to 17.6 s (unseen, n=10) median |

What these results show:

- **Fine-tuning works and is data-efficient.** The zero-shot score is 0.49. After 125 steps, Kev reaches 0.98 on
  test_iid, the best of all the students.
- **Kev generalises worse to unseen phrasing than the Verdict bi-encoder.** Kev drops 5.7 points (0.980 to 0.923),
  mostly on `app_rule` (1.00 to 0.87) and `cursor` (0.85 to 0.77). Verdict-bi went from 0.947 to 0.957. With only
  2,000 rows, Kev may be matching surface wording. More data and a teacher KL term should help; check this first in the
  full run.
- **The fitted T helped on unseen phrasing** (ECE 0.051 to 0.031) **but hurt on test_iid** (0.014 to 0.027). With 300
  validation rows this is not settled. Fit T on the full validation split.

## Recommended full run

`--train train --epochs 1 --batch 4 --accum 4 --lr 5e-5 --val-limit 2000`, plus `--teacher-probs ... --alpha 0.5
--tau 2` when teacher labels exist. That is about 2,500 optimizer steps.

- **Time.** At 1.2 rows/s on this shared GPU, one epoch of 40k rows takes about 9 hours. Either rent a cloud GPU
  (expect well over 10× faster), train on a 10–15k subset (the smoke run was already at 0.98 iid after 2k rows), or
  implement the policy-prefix cache described below first.
- **Learning rate.** Use lr 2e-5 if Kev's general Choice ability matters as well as VOX; 5e-5 is for VOX only.
- **Evaluation.** Evaluate `test_unseen_phrasing` and `test_unseen_apps` early (at 2k–5k rows), because they are where
  Kev is weakest.

## Caveats

- **Licence.** Kev code and weights are Apache-2.0. Qwen3.5-0.8B-Base is Apache-2.0 as well, per Kev's README; I did not
  check the Qwen licence text myself.
- **ROCm / gfx1151 workarounds** (all in `kevlib.py`; they change kernels only, not the maths):
  1. MIOpen has no working solver for the depthwise causal `conv1d` in the DeltaNet layers (`miopenStatusUnknownError`
     in both fp32 and bf16), so `torch.backends.cudnn.enabled = False` for this process.
  2. HIP event timing returns 0 ms, which makes Triton's autotuner (`do_bench`) divide by zero. It is replaced with a
     wall-clock benchmark.
  3. Triton needs a C compiler at runtime: `nixpkgs#gcc` plus `CC=gcc`.
  4. On CPU, the fla kernels must be hidden before transformers is imported (`VOX_NO_FLA=1`, set automatically for
     `--device cpu`). transformers binds the kernel at import time and never checks the device.
- **torch pin.** Kev's `pyproject.toml` pins `torch<2.9`. The repo is used from source via `sys.path`, not
  pip-installed, so the ROCm torch 2.11 stays in place. `peft` and `accelerate` were installed with `--no-deps`.
- **Temperature.** `train.py` fits T on the first `--val-limit` validation rows. The val ECE it prints is fitted and
  scored on the same rows, so it is optimistic. The test-split numbers from `predict.py` are the honest ones.
- **Phone feasibility: poor.** 0.87B parameters is about 1.7 GB in bf16 and about 0.5 GB at int4. Kev has no GGUF,
  ONNX or LiteRT export. The hybrid Qwen3.5 backbone (Gated DeltaNet + attention) is not supported by the usual phone
  runtimes as a custom pointer-head model, so porting it would mean re-implementing the head on top of llama.cpp or
  MLC. On this box, the GPU needs about 65–280 ms per decision, and CPU fp32 takes 10–18 s. Kev is a
  teacher-grade or laptop-grade student, not a phone model.
- **Input length.** A row is about 420 tokens: roughly 250 context, 160 policy and 10 option-list tokens. The policy is
  identical for every row. Moving it to the start of the state and caching its KV/DeltaNet prefix would cut about 40% of
  the compute per decision. Kev's serve path already caches the state prefix. I have not implemented this.
