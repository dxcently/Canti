"""Kev student: LoRA + pointer-head fine-tune of Kev-0.8B (Qwen3.5-0.8B-Base) on VOX decision rows.

    python students/kev/train.py --train train --limit 2000 --epochs 1 --out students/kev/runs/smoke
    python students/kev/train.py --train train --teacher-probs teachers/train.<teacher>.jsonl --alpha 0.5 --out ...

Loss per row: (1 - alpha) * CE(hard label) + alpha * tau^2 * KL(teacher || student), teacher from --teacher-probs
({id, probs} aligned with options); rows without a teacher entry use CE only. Defaults follow Kev's own delta fine-tune
recipe (README "Fine-Tune on Your Own Data"): warm start adapter + head from jaredpalmer/kev-0.8b, LoRA r=16 on every
attention/MLP/DeltaNet projection, bf16 autocast over fp32 weights, OneCycle LR, grad-norm clip 1.0.

After training, one temperature is fitted on --val rows (NLL) and stored in head.pt, like Kev's released checkpoints.
The run directory is a regular Kev checkpoint: `python -m kev.serve --run <out>` serves it at /v1/systemone.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import random
import sys
import time
from pathlib import Path

import kevlib  # sets sys.path, ROCm workarounds
import torch
from common import fit_temperature, load_rows, load_teacher, mixed_loss, policy_text, score, softmax

from kev.checkpoint import Checkpoint, Meta, write_meta
from kev.model import DecisionModel, load_tokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="train", help="split name or JSONL path")
    ap.add_argument("--limit", type=int, default=0, help="use the first N training rows (0 = all)")
    ap.add_argument("--teacher-probs", default="", help="teachers/<split>.<teacher>.jsonl with {id, probs}")
    ap.add_argument("--alpha", type=float, default=0.5, help="weight of KL-to-teacher (rows with teacher probs only)")
    ap.add_argument("--tau", type=float, default=1.0, help="distillation temperature")
    ap.add_argument("--val", default="validation")
    ap.add_argument("--val-limit", type=int, default=300, help="validation rows for the temperature fit and the val report")
    ap.add_argument("--base", default=kevlib.DEFAULT_BASE)
    ap.add_argument("--base-revision", default=kevlib.DEFAULT_REVISION)
    ap.add_argument("--init-from", default=kevlib.DEFAULT_INIT, help="warm start (Hub id or run dir); '' = fresh LoRA + head")
    ap.add_argument("--lora", type=int, default=16)
    ap.add_argument("--head-dim", type=int, default=256)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--batch", type=int, default=4, help="rows per forward pass")
    ap.add_argument("--accum", type=int, default=4, help="micro-batches per optimizer step")
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--head-lr", type=float, default=0.0, help="0 = same as --lr")
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--weights-dtype", choices=["fp32", "bf16"], default="fp32", help="frozen backbone dtype (bf16 halves memory)")
    ap.add_argument("--checkpointing", type=int, choices=[0, 1], default=1)
    ap.add_argument("--shuffle-options", type=int, choices=[0, 1], default=0, help="re-permute option order each epoch (teacher probs follow)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    torch.manual_seed(a.seed); rng = random.Random(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = load_rows(a.train, a.limit or None)
    teacher = load_teacher(a.teacher_probs or None, rows)
    val_rows = load_rows(a.val, a.val_limit or None) if a.val_limit else []
    policy = policy_text()

    tok = load_tokenizer(a.base, revision=a.base_revision)
    wdt = torch.bfloat16 if a.weights_dtype == "bf16" else torch.float32
    model = DecisionModel(a.base, tok, a.device, lora=a.lora, revision=a.base_revision, head_dim=a.head_dim, lora_targets="all", dtype=wdt)
    if a.checkpointing:
        model.lm.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.lm.config.use_cache = False
    meta = Meta(base=a.base, base_revision=a.base_revision, lora=a.lora, head_dim=a.head_dim, weights_dtype=a.weights_dtype)
    init = None
    if a.init_from:
        init = Checkpoint(a.init_from).warm_start(model, meta)
        print(f"warm start from {a.init_from}: {init['tensors']} adapter tensors + pointer head", flush=True)
    n_train = sum(p.numel() for p in model.trainable_parameters())
    print(f"trainable params {n_train/1e6:.1f}M; {len(rows)} train rows; {len(val_rows)} val rows", flush=True)

    head_ids = {id(p) for p in model.head.parameters()}
    groups = [{"params": [p for p in model.trainable_parameters() if id(p) not in head_ids], "lr": a.lr},
              {"params": list(model.head.parameters()), "lr": a.head_lr or a.lr}]
    opt = torch.optim.AdamW(groups, lr=a.lr, weight_decay=a.weight_decay)
    per_epoch = -(-len(rows) // (a.batch * a.accum))
    steps = max(1, int(per_epoch * a.epochs))
    if a.max_steps: steps = min(steps, a.max_steps)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[a.lr, a.head_lr or a.lr], total_steps=steps, pct_start=0.1)
    autocast = torch.autocast("cuda", dtype=torch.bfloat16) if a.device.startswith("cuda") else contextlib.nullcontext()

    def permuted(r):
        if not a.shuffle_options: return r, teacher.get(r["id"])
        perm = list(range(len(r["options"]))); rng.shuffle(perm)
        t = teacher.get(r["id"])
        return ({**r, "options": [r["options"][j] for j in perm], "label": perm.index(r["label"])},
                [t[j] for j in perm] if t else None)

    model.train()
    step, seen, tokens, log_loss, log_n, log_ok = 0, 0, 0, 0.0, 0, 0
    t0 = time.time(); done = False; epoch = 0
    while not done:
        order = rows[:]; rng.shuffle(order)
        micro = [order[i:i + a.batch] for i in range(0, len(order), a.batch)]
        for mi, chunk in enumerate(micro):
            items = [permuted(r) for r in chunk]
            encs = [kevlib.encode_row(model, tok, r, policy) for r, _ in items]
            with autocast:
                zs = kevlib.logits_batch(model, encs)
            losses = [mixed_loss(z, r["label"], t, a.alpha, a.tau) for z, (r, t) in zip(zs, items)]
            loss = torch.stack(losses).mean()
            (loss / a.accum).backward()
            seen += len(chunk); tokens += sum(len(e["ids"]) for e in encs)
            log_loss += loss.item() * len(chunk); log_n += len(chunk)
            log_ok += sum(int(z.argmax().item() == r["label"]) for z, (r, _) in zip(zs, items))
            if (mi + 1) % a.accum == 0 or mi == len(micro) - 1:
                torch.nn.utils.clip_grad_norm_(model.trainable_parameters(), 1.0)
                opt.step(); opt.zero_grad(set_to_none=True); step += 1
                if step < steps: sched.step()
                if step % a.log_every == 0 or step == steps:
                    el = time.time() - t0
                    print(f"ep{epoch} step {step}/{steps} loss {log_loss/log_n:.4f} train_acc {log_ok/log_n:.3f} "
                          f"lr {sched.get_last_lr()[0]:.2e} {seen/el:.2f} rows/s {tokens/el:.0f} tok/s", flush=True)
                    log_loss = log_n = log_ok = 0
                if step >= steps: done = True; break
        epoch += 1
    torch.cuda.synchronize() if a.device.startswith("cuda") else None
    wall = time.time() - t0
    peak = torch.cuda.max_memory_allocated() if a.device.startswith("cuda") else 0

    # save as a Kev checkpoint (adapter + head.pt + tokenizer)
    model.lm.save_pretrained(str(out))
    meta.head = {k: v.detach().cpu() for k, v in model.head.state_dict().items()}

    # fit the temperature on validation rows (eval mode, raw logits)
    val_report = {}
    if val_rows:
        model.eval(); raw = {}
        with torch.no_grad(), autocast:
            for i in range(0, len(val_rows), 16):
                chunk = val_rows[i:i + 16]
                for r, z in zip(chunk, kevlib.logits_batch(model, [kevlib.encode_row(model, tok, r, policy) for r in chunk])):
                    raw[r["id"]] = z.float().cpu().tolist()
        T = fit_temperature([raw[r["id"]] for r in val_rows], [r["label"] for r in val_rows])
        meta.temperature = T
        val_report = {"temperature": T, "val_T1": score(val_rows, {k: softmax(v, 1.0) for k, v in raw.items()}),
                      "val_T": score(val_rows, {k: softmax(v, T) for k, v in raw.items()})}
        print(f"val acc {val_report['val_T']['accuracy']} ece T=1 {val_report['val_T1']['ece']} -> T={T} ece {val_report['val_T']['ece']} "
              f"(fitted and scored on the same {len(val_rows)} rows: optimistic)", flush=True)
    meta.extra = {"args": vars(a), "init_source": init, "vox": {"policy_in": "question instructions", "state": "context"}}
    write_meta(str(out), meta)
    tok.save_pretrained(str(out))
    metrics = {"wall_seconds": round(wall, 1), "rows_seen": seen, "optimizer_steps": step, "train_rows_per_s": round(seen / wall, 2),
               "train_tokens_per_s": round(tokens / wall, 1), "mean_tokens_per_row": round(tokens / max(1, seen), 1),
               "peak_gpu_bytes": peak, "teacher_rows": len(teacher), **val_report}
    (out / "training_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v for k, v in metrics.items() if not k.startswith("val_")}), flush=True)
    print("saved", out, flush=True)


if __name__ == "__main__":
    main()
