# finetune: the VOX decision model

This workspace trains and serves the model that turns a sound line, the screen context and the user's rules into a phone action. It is a Jev-style typed choice: pick one of the listed options, with calibrated probabilities.

## Layout

| Folder | What the code does |
|---|---|
| [`vox/`](vox/README.md) | **Data and scoring.** The action/gesture vocabulary (`schema.py`), the synthetic data generator for gesture decisions (`generate.py`) and for intent-cursor target picking (`targets.py`), the wording banks and their leak filter, the shared evaluator, and the no-training baselines |
| [`students/`](students/README.md) | **Models we train.** jevlike (the current best: a small encoder + option-attention head), Kev 0.8B, and Verdict-118M, plus `common.py` shared by Kev and Verdict |
| [`teachers/`](teachers/README.md) | **Open Jev-like models used as references and soft labels:** Decider 4B and JevK5, batched on the GPU, with parity checks against their own runtimes |
| [`servers/`](servers/README.md) | **`/v1/systemone` stand-in.** A FastAPI server with the Jev wire format, backed by decider-4b, jevk5 or our student; the Android app talks to it unchanged |
| [`sweeps/`](sweeps/README.md) | **Training sweeps.** Driver script, `runs.jsonl` (one row per run, with data version, command and metrics), per-test eval JSON, and the results tables |
| [`briefs/`](briefs/README.md) | Task briefs handed to the executor agents that run sweeps and write wording banks |
| [`wordings_llm/`](wordings_llm/README.md) | LLM-written wording bank (how people phrase actions and gestures), the ambiguity list, and its validator |
| `data/` | Generated datasets, **untracked**. See [`data/README.md`](data/README.md) for the versions and how to regenerate them |
| `third_party/` | Upstream clones of Kev and Verdict, **untracked**. See [`third_party/README.md`](third_party/README.md) |
| `runs/`, `preds/`, `logs/` | Checkpoints, prediction files and logs, **untracked** |

## Environment

```bash
cd ~/VOX/finetune
nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c 'source ./env.sh; source .venv/bin/activate; export CC=gcc; <command>'
```
- `env.sh` puts the C/C++ runtime libraries that the ROCm torch wheels need onto `LD_LIBRARY_PATH`.
- Never replace the ROCm torch in `.venv`.
- On CPU, Qwen3.5 models need flash-linear-attention hidden (`sys.modules["fla"] = None`); `servers/systemone.py` does this when `VOX_DEVICE=cpu`.

## Typical loop

```bash
python -m vox.generate --output data/v5 --bank wordings_llm/bank.json      # regenerate a data version (deterministic)
python students/jevlike/train.py data/v5/train.jsonl --validation data/v5/validation.jsonl --output runs/x.pt
python students/jevlike/train.py data/v5/test_unseen_phrasing.jsonl --predict runs/x.pt --out preds/x.jsonl
python -m vox.evaluate data/v5/test_unseen_phrasing.jsonl preds/x.jsonl --markdown
```

**Rule:** only compare models scored on the *same* test files. Every data version has its own tests; see `data/README.md`.
