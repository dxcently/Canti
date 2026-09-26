# students: the VOX models we train

Each student learns the VOX policy from the generated data, optionally distilled from teacher soft labels (`teachers/`). They all write predictions in the shared format `{"id", "probs"}` for `vox.evaluate`.

| Folder | Model | Notes |
|---|---|---|
| [`jevlike/`](jevlike/README.md) | A pretrained text encoder (e5-small/base, ModernBERT) plus the jevlike option-attention head, with the top layers fine-tuned | **Current best** (see `sweeps/runs.jsonl`). About 33M parameters with e5-small; latency is tens of ms on GPU |
| [`kev/`](kev/README.md) | Kev 0.8B (Qwen3.5-based typed-decision model) fine-tuned on VOX | Upstream in `third_party/kev`; needs Triton (gcc) |
| [`verdict/`](verdict/README.md) | Verdict-118M bi-encoder/cross-encoder, fine-tuned, with an int8 ONNX export for the phone | Upstream in `third_party/verdict`; ~8 ms on CPU (ONNX int8) |
| `common.py` | Shared by Kev and Verdict: data loading (`VOX_DATA` picks the data version), teacher soft labels, the mixed CE+KL loss, metrics and output writing | |
| `queue_v5.sh` | Queue: train and score Verdict and Kev on data/v5 once the GPU is free | |
| `smoke_predict.sh` | Quick smoke predictions for both students | |
