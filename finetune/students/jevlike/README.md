# jevlike student

`train.py` trains a **VoxScorer**: a Hugging Face encoder that reads the context and each option, then the jevlike `AttentionHead` scores the options against the context. Top encoder layers train (`--train-layers`, -1 = all), and teacher soft labels can be mixed in (`--teacher-probs`, `--alpha`).

```bash
python students/jevlike/train.py data/v5/train.jsonl --validation data/v5/validation.jsonl --output runs/name.pt \
    [--hf-model intfloat/e5-small-v2] [--batch-size 32] [--encoder-lr 5e-5]
python students/jevlike/train.py data/v5/test_iid.jsonl --predict runs/name.pt --out preds/name.test_iid.jsonl [--device cpu]
```
- The `jevlike` package itself (data validation, collator, AttentionHead) is installed in `.venv` from the user's `~/jevlike` repo. Don't modify that repo from here.
- Checkpoints hold only the trainable weights plus the config; `build()` reloads the base encoder from Hugging Face.
- The server `servers/systemone.py` loads these checkpoints as model `vox-jevlike`.
