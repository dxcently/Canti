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
    ap.add_argument("--select-best", action="store_true",
                    help="score --val after every epoch and keep the best epoch's weights (early stopping by selection)")
    ap.add_argument("--watch", default="", help="extra split scored after every epoch (logged only, e.g. synthetic validation)")
    ap.add_argument("--watch-limit", type=int, default=1000)
    ap.add_argument("--none-weight", type=float, default=1.0, help="loss weight for rows whose label is the none option (last)")
    ap.add_argument("--none-floor", type=float, default=0.0, help="--select-best: prefer epochs whose val none-recall >= this (then by val acc)")
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--loss", choices=["ce", "acceptable"], default="ce",
                    help="acceptable: -log sum of p over the row's acceptable options (rows with one acceptable option = CE)")
    ap.add_argument("--lowconf-weight", type=float, default=1.0, help="loss weight of rows labelled confidence 'low'")
    ap.add_argument("--label-smoothing", type=float, default=0.0, help="CE label smoothing (single-answer rows)")
    ap.add_argument("--option-format", choices=["v1", "v2"], default="v1",
                    help="option text format of the training data (OptionFormat.kt); rows that carry option_format must all match. "
                         "Saved in student.json and the ONNX export; the app only sends v2 text to a model that declares v2")
    ap.add_argument("--decay-norm-bias", type=int, choices=[0, 1], default=0,
                    help="1 = old recipe (v1a-v1e): weight decay on LayerNorm weights and biases too; 0 (default since 2026-09-27) = no decay on them")
    a = ap.parse_args()

    torch.manual_seed(a.seed); rng = random.Random(a.seed)
    out = Path(a.out)
    rows = load_rows(a.train, a.limit or None)

    def row_loss(z, r):
        """Recipe loss for one row (defaults = the v1a-v1e loss: CE on the label, or the teacher mix)."""
        t = teacher.get(r["id"])
        if t is not None and a.alpha > 0:
            return mixed_loss(z, r["label"], t, a.alpha, a.tau)
        acc = r.get("acceptable") or [r["label"]]
        if a.loss == "acceptable" and len(acc) > 1:
            return -torch.logsumexp(torch.log_softmax(z.float(), -1)[torch.tensor(acc, device=z.device)], 0)
        return torch.nn.functional.cross_entropy(z.float()[None], torch.tensor([r["label"]], device=z.device), label_smoothing=a.label_smoothing)
    fmts = {r.get("option_format", "v1") for r in rows}
    if fmts != {a.option_format}:
        raise SystemExit(f"--option-format {a.option_format} but the training rows are {sorted(fmts)}: never mix formats")
    teacher = load_teacher(a.teacher_probs or None, rows)
    val_rows = load_rows(a.val, a.val_limit or None) if a.val_limit else []
    m = vlib.Student(a.init, a.arch, max_len=a.max_len, device=a.device)
    if not a.train_embeddings:
        m.enc.get_input_embeddings().weight.requires_grad_(False)
    head = list(m.head.parameters()) if a.arch == "cross" else []
    head_ids = {id(p) for p in head}
    named = [(n, p) for n, p in m.named_parameters() if p.requires_grad and id(p) not in head_ids]
    no_decay = lambda n, p: not a.decay_norm_bias and (p.ndim < 2 or "LayerNorm" in n or "layer_norm" in n or n.endswith(".bias"))  # noqa: E731
    groups = [{"params": [p for n, p in named if not no_decay(n, p)], "lr": a.lr, "weight_decay": a.weight_decay},
              {"params": [p for n, p in named if no_decay(n, p)], "lr": a.lr, "weight_decay": 0.0}]
    groups = [g for g in groups if g["params"]]
    if head: groups.append({"params": head, "lr": a.head_lr, "weight_decay": a.weight_decay})
    opt = torch.optim.AdamW(groups, weight_decay=a.weight_decay)
    print(f"weight decay {a.weight_decay} on {sum(p.numel() for p in groups[0]['params'])/1e6:.2f}M params; "
          f"no decay on {sum(p.numel() for g in groups[1:2] for p in g['params']) if len(groups) > 1 and groups[1]['weight_decay'] == 0 else 0} (LayerNorm/bias)", flush=True)
    steps = max(1, int(-(-len(rows) // a.batch) * a.epochs))
    warm = max(1, int(a.warmup * steps))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: (s + 1) / warm if s < warm else max(0.0, (steps - s) / max(1, steps - warm)))
    n_tr = sum(p.numel() for g in groups for p in g["params"])
    print(f"arch={a.arch} init={a.init} trainable {n_tr/1e6:.1f}M; {len(rows)} train rows, {steps} steps", flush=True)
    autocast = torch.autocast("cuda", dtype=torch.bfloat16, enabled=bool(a.bf16) and a.device.startswith("cuda"))

    micro = a.micro or (a.batch if a.arch == "bi" else 4)   # cross archs: ~11 pairs per row
    watch_rows = load_rows(a.watch, a.watch_limit or None) if a.watch else []

    def eval_acc(rs):
        m.eval(); ok = 0; nll = 0.0; nn_ = nok = 0
        with torch.no_grad(), autocast:
            for i in range(0, len(rs), 32):
                ch = rs[i:i + 32]
                for r, z in zip(ch, m.logits(ch)):
                    z = z.float(); ok += int(z.argmax().item() == r["label"])
                    nll += float(torch.logsumexp(z, -1) - z[r["label"]])
                    if r["label"] == len(r["options"]) - 1:
                        nn_ += 1; nok += int(z.argmax().item() == r["label"])
        m.train()
        eval_acc.none_recall = nok / max(1, nn_)
        return ok / max(1, len(rs)), nll / max(1, len(rs))

    def key(acc):   # selection key: meets the none-recall floor first, then accuracy
        return (eval_acc.none_recall >= a.none_floor, acc)

    best = ((False, -1.0), None, 0); epoch_log = []
    m.train(); step = seen = 0; t0 = time.time(); lsum = lok = ln = 0
    epoch = 0
    while step < steps:
        if epoch and (a.select_best or watch_rows):
            rec = {"epoch": epoch, "step": step}
            if a.select_best and val_rows:
                rec["val_acc"], rec["val_nll_T1"] = eval_acc(val_rows); rec["val_none_recall"] = eval_acc.none_recall
                if key(rec["val_acc"]) > best[0]:
                    best = (key(rec["val_acc"]), {k: v.detach().to("cpu", copy=True) for k, v in m.state_dict().items()}, epoch)
            if watch_rows:
                rec["watch_acc"], _ = eval_acc(watch_rows)
            epoch_log.append(rec); print("epoch", json.dumps(rec), flush=True)
        epoch += 1
        order = rows[:]; rng.shuffle(order)
        for i in range(0, len(order), a.batch):
            if step >= steps: break
            batch = order[i:i + a.batch]
            opt.zero_grad(set_to_none=True); zs = []; loss_v = 0.0
            for j in range(0, len(batch), micro):
                part = batch[j:j + micro]
                with autocast:
                    zp = m.logits(part)
                loss = torch.stack([row_loss(z, r) * (a.none_weight if r["label"] == len(r["options"]) - 1 else 1.0)
                                    * (a.lowconf_weight if r.get("confidence") == "low" else 1.0) for z, r in zip(zp, part)]).sum() / len(batch)
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
    if a.select_best or watch_rows:   # score the final weights too, then restore the best epoch
        rec = {"epoch": epoch, "step": step, "final": True}
        if a.select_best and val_rows:
            rec["val_acc"], rec["val_nll_T1"] = eval_acc(val_rows); rec["val_none_recall"] = eval_acc.none_recall
            if key(rec["val_acc"]) > best[0]:
                best = (key(rec["val_acc"]), None, epoch)
        if watch_rows:
            rec["watch_acc"], _ = eval_acc(watch_rows)
        epoch_log.append(rec); print("epoch", json.dumps(rec), flush=True)
        if a.select_best and best[1] is not None:
            m.load_state_dict(best[1]); print(f"restored epoch {best[2]} (meets none floor {best[0][0]}, val acc {best[0][1]:.4f})", flush=True)

    report = {"epochs": epoch_log, "best_epoch": best[2]} if epoch_log else {}
    if val_rows:
        m.eval(); raw = {}
        with torch.no_grad(), autocast:
            for i in range(0, len(val_rows), 32 if a.arch == "bi" else micro):
                chunk = val_rows[i:i + (32 if a.arch == "bi" else micro)]
                for r, z in zip(chunk, m.logits(chunk)):
                    raw[r["id"]] = z.float().cpu().tolist()
        T = fit_temperature([raw[r["id"]] for r in val_rows], [r["label"] for r in val_rows])
        m.temperature = T
        report.update({"temperature": T, "val_T1": score(val_rows, {k: softmax(v, 1.0) for k, v in raw.items()}),
                  "val_T": score(val_rows, {k: softmax(v, T) for k, v in raw.items()})})
        print(f"val acc {report['val_T']['accuracy']} ece T=1 {report['val_T1']['ece']} -> T={T} ece {report['val_T']['ece']} "
              f"(fitted and scored on the same {len(val_rows)} rows: optimistic)", flush=True)
    m.save(out, {"base": a.init, "option_format": a.option_format, "args": vars(a)})
    metrics = {"wall_seconds": round(wall, 1), "rows_seen": seen, "steps": step, "train_rows_per_s": round(seen / wall, 2),
               "peak_gpu_bytes": torch.cuda.max_memory_allocated() if a.device.startswith("cuda") else 0, "teacher_rows": len(teacher), **report}
    (out / "training_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v for k, v in metrics.items() if not k.startswith("val_")}), flush=True)
    print("saved", out, flush=True)


if __name__ == "__main__":
    main()
