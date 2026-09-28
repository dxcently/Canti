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

## jl8 additions (2026-09-28)

- `train.py` sets `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` (as `students/verdict/vlib.py` does; kernel choice only).
- `--fast-options` (opt-in): each distinct option is encoded once per batch, in length-sorted chunks with no extra token
  padding. fp32 logits are identical to the old path; bf16 differences (max 0.0065 logit, 1.3% grad) are below the old
  path's own bf16-vs-fp32 gap (0.010, 3.1%). One dropout mask per distinct option in training. 152.6 -> 307.5 rows/s
  (AOTriton alone: 211.7). Log: `sweeps/logs/jl8-speed.log`.
- `--select acc|nll|nll_t` (default acc = old behaviour) and `--fit-temperature` (T fitted on val with
  `common.fit_temperature`, stored as config `temperature` plus a `selected` record). `suite_jl.py` and `--predict` apply the
  stored T (checkpoints without one: T = 1).
- Honest teacher: `oof_teacher.py` turns a leave-apps-out cross-fit (`students/verdict/crossfit.py`) into soft labels for
  the mix. The mix's real rows are exact copies (`<id>-r<k>`, same context/options/label) of pool rows, so each gets the
  logits of the fold model that never saw its app, on its own option list (checked row by row). The jl8 teacher cross-fit
  (`jl8teach_lossacc_drop15_train`, `sweeps/jl8_teacher.sh`) uses the TRAIN rows only, so no val row reaches the student
  through the teacher (val stays clean for selection and T). Synthetic rows get no teacher (fold models are
  in-sample on targets-v2); 45 real rows whose ids the pool dropped get none either.
- `seedpool.py`: seed-pooled paired comparison (mean over seeds, screen-cluster bootstrap shared across seeds).
- Queue/post: `sweeps/queue_jl8.sh`, `sweeps/post_jl8.sh`, `sweeps/jl8_chain*.sh`.

## jl9 additions (2026-09-28)

- `--teacher-skip-none` (opt-in): gold-none rows get no teacher (hard-label CE share only, like teacher-less rows). The
  honest Verdict teacher under-calls none (OOF none recall 0.63), and KL on those rows pulled J4's none recall down.
  J5b = J4 + this flag restores none recall to the control's level (test_old 0.848 vs J4 0.747, p<0.001) and keeps J4's
  accuracy gain. J5c = J5b at 3 epochs is the best jevlike so far (test_old acc 0.833, NLL 0.617; dev_test 0.748).
- `oof_teacher.py --none-bias <b>|fit` (opt-in): adds b to the teacher's none logit after /T, before the softmax, per
  cross-fit seed. `fit` = OOF-NLL-fitted (+0.61/+0.58 for the jl8 teacher). J5a (this teacher) moved none recall little.
- `OptionCache` (train.py) + `suite_jl.py --latency ... --jl-cache` + `train.py --predict ... --cache-options`: option
  vectors are context-independent in VoxScorer (each option is encoded alone and mean-pooled; the head's option side is
  per option), so they are cached by option text and a decision is one context pass plus the head. fp32 = uncached to
  1e-5; bf16 drift is within the uncached path's own bf16 noise. Batch-1 p50 7.8 -> 3.9 ms GPU, 756 -> 322 ms CPU.
- `opgate.py`: cf_eval's operating-point fit (none bias, t_tap, t_none under a wrong-tap bound) on val_all, frozen and
  applied to dev_test/test_old, with paired screen-bootstrap utility. `--bound cp95` (the gate) is barely feasible on
  497 val rows; `--bound point` compares at matched 5% observed wrong/tap.
- `seedpool.py` tables now include none recall and none AUROC.
- Queue/post: `sweeps/queue_jl9.sh`, `sweeps/post_jl9.sh` (+ `sweeps/jl9_*.py|sh` checks). Only the best-val seed of
  J5a (s9) and J5b (s7) is kept, so seedpool/opgate reruns over those recipes need retraining; J5c keeps all seeds.
