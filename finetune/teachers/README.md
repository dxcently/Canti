# VOX teachers: Decider 4B and JevK5, local on the Radeon 8060S (gfx1151, ROCm)

Two open "Jev-like" decision models label the VOX synthetic data. Each reads the row's `context` as the state, the policy
text as the question's instructions, and the row's `options` as the choice criteria. It returns a calibrated probability for
every option from **one forward pass**, with no generated tokens.

| teacher | HF repo (pinned revision) | base | licence | readout |
|---|---|---|---|---|
| `decider4b` | `Mapika/decider-4b` @ `eb5fbdf` (v2.1) | Qwen3.5-4B-Base, full FT + merged LoRA | Apache-2.0 (weights and `decider-ai` code) | plain state-first prompt, letter logits at `Answer: (`, softmax / T=1.11 (choice) |
| `jevk5` | `alibiserikbay/JevK5` @ `c4f7fdb` (v0.3) | Qwen3.5-4B + merged LoRA r16 | Apache-2.0 (weights and `jevk5` runtime) | SemIf JSON prompt in the chat template (thinking off), letter logits, softmax / T=1.22 |

Licence notes: both base models are Qwen3.5 (Apache-2.0). JevK5's card says 14,138 of its training questions were written by
"GPT-6 Luna" through OpenAI's API, "generated under OpenAI's terms, which govern their use; review them for your use case".
Distilling VOX students from JevK5 labels is a second-hand use of those outputs, so flag it if the students ship
commercially. Decider-4b was trained on Qwen3.6-27B-written questions and public datasets, with no stated third-party terms.
The flash-linear-attention kernels are MIT. The fallback teacher, Hopper, is under a custom "research-and-demo" licence and
was not needed.

## How it runs (and why it is not the upstream servers)

`scorer.py` is an in-process batched scorer. For every row it builds **exactly** the prompt that each project's own runtime
builds for a `/v1/systemone` choice request, using the projects' own prompt code (`decider.systemone.render_question` +
`decider.prompt.build`; `jevk5.prompt.decision_options` + `messages` + the chat template). It then scores many rows in one
right-padded batch and reads the label-letter logits at the last token. The 1.27 GB embedding table stays in CPU RAM, and only the K label rows of `lm_head` go to the GPU. Both upstream engines also run right-padded with no
mask. Every Qwen3.5 layer is causal, so padding cannot change the last real token. `parity.py` checks the scorer against the
upstream `Decider.system_one` and `JevK5.decide`; see `parity.json`.

Why not the upstream servers as they are: the JevK5 runtime runs one request at a time through CUDA graphs, and Decider's
engine uses `torch.compile` plus CUDA graphs. Neither batches arbitrary rows, and neither runs on ROCm without the kernel
patches below. `jevk5-serve` and `python -m decider.serve` should work once `teachers.rocm_compat.apply()` has run, but they
were not needed and were not tested.

### ROCm / gfx1151 fixes (`rocm_compat.py`, kernels only)
1. transformers' fallback depthwise causal conv calls `F.conv1d(groups=C)`, and MIOpen fails on gfx1151 with
   `miopenStatusUnknownError`. It is rebound to flash-linear-attention's Triton `causal_conv1d`: the same math, 3.7 ms
   against 116–150 ms for the torch fallbacks.
2. Triton's autotuner (`triton.testing.do_bench`) divides by a HIP-event estimate that is about 0 ms for tiny fla kernels.
   It then either raises `ZeroDivisionError` or loops about 1e8 times and hangs. It is replaced by a fixed 10-repetition
   timing.
3. Triton needs a C compiler at runtime to build its launcher, so `nixpkgs#gcc` must be in the nix shell.
4. The gated delta rule uses fla's Triton `chunk_gated_delta_rule` (transformers binds it when `fla` imports).

## Setup (already done on this machine)

```bash
cd /home/khoa/VOX/finetune
nix shell nixpkgs#python313 nixpkgs#uv -c bash -c 'source ./env.sh; source .venv/bin/activate;
  uv pip install "transformers==5.17.0" psutil einops
  uv pip install --no-deps accelerate "flash-linear-attention==0.5.2" "fla-core==0.5.2" "decider-ai==1.5.0" \
      "jevk5 @ git+https://github.com/allebee/jevk5@1e5ae1b533b9eb80c0cbe3fbd010607d0b4e26ae"
  python -c "import torch;print(torch.__version__)"   # must still say +rocm7.13'
```

`--no-deps` is required: `decider-ai` pins `numpy<2` and pulls PyPI torch, and `fla-core` and `jevk5` also depend on torch.
Weights download on first use to `~/.cache/huggingface` at the pinned revisions. They are about 8.4 GB each, bf16.

## Commands

Every command runs from `/home/khoa/VOX/finetune` through `teachers/run.sh`. It is the documented nix shell plus
`nixpkgs#gcc` (Triton needs a C compiler), `env.sh`, the venv, and `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`:

```bash
teachers/run.sh <command>
# the same as: nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c 'source ./env.sh; source .venv/bin/activate; <command>'
```

| what | `<command>` |
|---|---|
| one-row demo | `python -m teachers.scorer jevk5` (or `decider4b`) |
| parity against the upstream runtimes | `python -m teachers.parity --rows 24` (writes `teachers/parity.json`) |
| smoke labels (as run: 300 rows × 2 splits × 2 teachers) | `python -m teachers.label test_iid test_unseen_phrasing --limit 300 --token-budget 8192` |
| smoke metrics | `python -m teachers.smoke --splits test_iid,test_unseen_phrasing --limit 300 > teachers/logs/smoke_metrics.md` |
| full split, one teacher (NOT run yet) | `python -m teachers.label train --teachers jevk5` |
| score with vox's evaluator | `python -m vox.evaluate data/v0/test_iid.jsonl teachers/labels/test_iid.jevk5.jsonl --markdown` |

`label.py` takes one or more split names or `.jsonl` paths. Each teacher is loaded once and runs over all the splits, then
the next teacher is loaded. Options:
- `--teachers decider4b,jevk5`
- `--limit N` (the first N rows)
- `--token-budget 16384`: the maximum padded tokens per forward pass. The smoke run used 8192 because the GPU was shared.
- `--max-batch 64`
- `--chunk 512`: rows flushed together.
- `--criteria text|keyed`: keyed writes `*.keyed.jsonl`.
- `--out teachers/labels`

When a batch hits OOM it is halved and retried. A single row that still OOMs waits 30 s and retries.

Output: `teachers/labels/<split>.<teacher>.jsonl`, one line per row:
`{"id", "probs": [aligned with options], "top": index, "confidence": probs[top], "jev_confidence": (N*p_max-1)/(N-1)}`.
`confidence` is the calibrated top probability, which is what the ECE in `vox.evaluate` measures.
`jev_confidence` is TypeSafe's rescaled statistic (0 for a uniform distribution, 1 for a one-hot one), the value
Decider's `/v1/systemone` reports as `confidence`. `<split>.<teacher>.meta.json` records revision, temperature, kernels and
throughput.

Resuming: rerun the same command. Ids already in the output file are skipped, and rows are appended and flushed every
`--chunk` rows. A torn last line from a kill is ignored and that row is redone.

## Sharing the GPU

The 8060S is shared with the student training jobs and an idle `llama-server` that holds about 7.6 GB. One teacher needs
about 7.1 GB on the GPU (its embedding table stays in CPU RAM) plus activations, so check `amd-smi process` first. If a load fails with OOM, wait or lower
`--token-budget`. Throughput in `smoke_report.md` was measured while other jobs were running.
