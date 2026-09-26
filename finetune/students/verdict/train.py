"""Verdict student: fine-tune multilingual-e5-small (from Verdict's released encoder) on VOX decision rows,
as a bi-encoder (Verdict's mechanism) or a cross-encoder over (context, option) pairs.

    python students/verdict/train.py --arch bi    --limit 2000 --epochs 3 --out students/verdict/runs/verdict-bi-smoke
    python students/verdict/train.py --arch cross --limit 2000 --epochs 3 --out students/verdict/runs/verdict-cross-smoke
    ... --teacher-probs teachers/train.<teacher>.jsonl --alpha 0.5

Loss per row: (1 - alpha) * CE(hard label) + alpha * tau^2 * KL(teacher || student); rows without teacher probs use CE.
The full encoder is trained (token embeddings frozen by default, as in Verdict's train/finetune_typed.py: 96M of the
118M parameters are the 250k-token embedding table). A temperature is fitted on --val rows afterwards and stored.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import torch
import vlib
from common import fit_temperature, load_rows, load_teacher, mixed_loss, score, softmax


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", choices=["bi", "cross", "cross_cos"], required=True)
    ap.add_argument("--train", default="train")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--teacher-probs", default="")
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--tau", type=float, default=1.0)
    ap.add_argument("--val", default="validation")
    ap.add_argument("--val-limit", type=int, default=300)
    ap.add_argument("--init", default=vlib.DEFAULT_INIT, help="Hub id or directory (e.g. intfloat/multilingual-e5-small)")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--batch", type=int, default=16, help="rows per optimizer step")
    ap.add_argument("--micro", type=int, default=0, help="rows per forward pass (0 = --batch for bi, 4 for cross: ~11 pairs per row)")
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--head-lr", type=float, default=1e-3, help="cross-encoder scoring head")
    ap.add_argument("--warmup", type=float, default=0.06)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--train-embeddings", action="store_true")
    ap.add_argument("--bf16", type=int, choices=[0, 1], default=1)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log-every", type=int, default=20)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    torch.manual_seed(a.seed); rng = random.Random(a.seed)
    out = Path(a.out)
    rows = load_rows(a.train, a.limit or None)
    teacher = load_teacher(a.teacher_probs or None, rows)
    val_rows = load_rows(a.val, a.val_limit or None) if a.val_limit else []
    m = vlib.Student(a.init, a.arch, max_len=a.max_len, device=a.device)
    if not a.train_embeddings:
        m.enc.get_input_embeddings().weight.requires_grad_(False)
    head = list(m.head.parameters()) if a.arch == "cross" else []
    head_ids = {id(p) for p in head}
    groups = [{"params": [p for p in m.parameters() if p.requires_grad and id(p) not in head_ids], "lr": a.lr}]
    if head: groups.append({"params": head, "lr": a.head_lr})
    opt = torch.optim.AdamW(groups, weight_decay=0.01)
    steps = max(1, int(-(-len(rows) // a.batch) * a.epochs))
    warm = max(1, int(a.warmup * steps))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: (s + 1) / warm if s < warm else max(0.0, (steps - s) / max(1, steps - warm)))
    n_tr = sum(p.numel() for g in groups for p in g["params"])
    print(f"arch={a.arch} init={a.init} trainable {n_tr/1e6:.1f}M; {len(rows)} train rows, {steps} steps", flush=True)
    autocast = torch.autocast("cuda", dtype=torch.bfloat16, enabled=bool(a.bf16) and a.device.startswith("cuda"))

    micro = a.micro or (a.batch if a.arch == "bi" else 4)   # cross archs: ~11 pairs per row
    m.train(); step = seen = 0; t0 = time.time(); lsum = lok = ln = 0
    while step < steps:
        order = rows[:]; rng.shuffle(order)
        for i in range(0, len(order), a.batch):
            if step >= steps: break
            batch = order[i:i + a.batch]
            opt.zero_grad(set_to_none=True); zs = []; loss_v = 0.0
            for j in range(0, len(batch), micro):
                part = batch[j:j + micro]
                with autocast:
                    zp = m.logits(part)
                loss = torch.stack([mixed_loss(z, r["label"], teacher.get(r["id"]), a.alpha, a.tau) for z, r in zip(zp, part)]).sum() / len(batch)
                loss.backward(); loss_v += loss.item(); zs += [z.detach() for z in zp]
            torch.nn.utils.clip_grad_norm_([p for g in groups for p in g["params"]], 1.0)
            opt.step(); sched.step(); step += 1; seen += len(batch)
            lsum += loss_v * len(batch); ln += len(batch); lok += sum(int(z.argmax().item() == r["label"]) for z, r in zip(zs, batch))
            if step % a.log_every == 0 or step == steps:
                el = time.time() - t0
                print(f"step {step}/{steps} loss {lsum/ln:.4f} train_acc {lok/ln:.3f} lr {sched.get_last_lr()[0]:.2e} {seen/el:.1f} rows/s", flush=True)
                lsum = lok = ln = 0
    if a.device.startswith("cuda"): torch.cuda.synchronize()
    wall = time.time() - t0

    report = {}
    if val_rows:
        m.eval(); raw = {}
        with torch.no_grad(), autocast:
            for i in range(0, len(val_rows), 32 if a.arch == "bi" else micro):
                chunk = val_rows[i:i + (32 if a.arch == "bi" else micro)]
                for r, z in zip(chunk, m.logits(chunk)):
                    raw[r["id"]] = z.float().cpu().tolist()
        T = fit_temperature([raw[r["id"]] for r in val_rows], [r["label"] for r in val_rows])
        m.temperature = T
        report = {"temperature": T, "val_T1": score(val_rows, {k: softmax(v, 1.0) for k, v in raw.items()}),
                  "val_T": score(val_rows, {k: softmax(v, T) for k, v in raw.items()})}
        print(f"val acc {report['val_T']['accuracy']} ece T=1 {report['val_T1']['ece']} -> T={T} ece {report['val_T']['ece']} "
              f"(fitted and scored on the same {len(val_rows)} rows: optimistic)", flush=True)
    m.save(out, {"base": a.init, "args": vars(a)})
    metrics = {"wall_seconds": round(wall, 1), "rows_seen": seen, "steps": step, "train_rows_per_s": round(seen / wall, 2),
               "peak_gpu_bytes": torch.cuda.max_memory_allocated() if a.device.startswith("cuda") else 0, "teacher_rows": len(teacher), **report}
    (out / "training_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v for k, v in metrics.items() if not k.startswith("val_")}), flush=True)
    print("saved", out, flush=True)


if __name__ == "__main__":
    main()
