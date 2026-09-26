"""Train a jevlike option-attention scorer on VOX data, with a trainable pretrained encoder.

jevlike's own FrozenTransformerScorer keeps the encoder frozen and trains on hard labels.
Rule-following needs the encoder to contextualise ("this rule is about the current app"),
so this script reuses jevlike's AttentionHead and collator but lets the top encoder layers
train, and mixes in soft teacher labels when given.

Usage (from finetune/):
  python students/jevlike/train.py data/v0/train.jsonl --validation data/v0/validation.jsonl \
      --output runs/jevlike-e5.pt [--teacher-probs teachers/train.decider.jsonl --alpha 0.5]
  python students/jevlike/train.py --predict runs/jevlike-e5.pt data/v0/test_iid.jsonl \
      --out preds/test_iid.jevlike.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset

from jevlike.data import ChoiceExample, HuggingFaceCollator, validate
from jevlike.model import AttentionHead


class VoxRows(Dataset):
    """jevlike examples plus the row id and optional teacher distribution."""

    def __init__(self, path: str, teacher_files: list[str] | None = None) -> None:
        self.rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        self.examples = [validate(r) for r in self.rows]
        self.teacher: dict[str, list[float]] = {}
        for tf in teacher_files or []:
            # average several teachers; keep only rows they all covered
            got = {r["id"]: r["probs"] for r in map(json.loads, Path(tf).read_text().splitlines()) if r}
            if not self.teacher:
                self.teacher = got
            else:
                self.teacher = {k: [a + b for a, b in zip(v, got[k])] for k, v in self.teacher.items() if k in got}
        if teacher_files:
            n = len(teacher_files)
            self.teacher = {k: [x / n for x in v] for k, v in self.teacher.items()}

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return i


class Collate:
    def __init__(self, data: VoxRows, base: HuggingFaceCollator) -> None:
        self.data, self.base = data, base

    def __call__(self, idx: list[int]):
        batch = self.base([self.data.examples[i] for i in idx])
        width = batch["option_mask"].shape[1]
        soft = torch.zeros(len(idx), width)
        has = torch.zeros(len(idx), dtype=torch.bool)
        for row, i in enumerate(idx):
            probs = self.data.teacher.get(self.data.rows[i]["id"])
            if probs is not None and len(probs) == len(self.data.examples[i].options):
                soft[row, :len(probs)] = torch.tensor(probs)
                has[row] = True
        batch["soft"], batch["has_soft"] = soft, has
        batch["index"] = torch.tensor(idx)
        return batch


class VoxScorer(nn.Module):
    def __init__(self, model_name: str, rank: int, train_layers: int) -> None:
        super().__init__()
        from transformers import AutoModel

        self.encoder = AutoModel.from_pretrained(model_name)
        self.encoder.requires_grad_(False)
        layers = self._layers()
        if train_layers < 0:
            self.encoder.requires_grad_(True)
        elif train_layers > 0:
            for layer in layers[-train_layers:]:
                layer.requires_grad_(True)
        self.head = AttentionHead(self.encoder.config.hidden_size, rank)

    def _layers(self):
        for path in ("encoder.layer", "layers", "transformer.layer"):
            obj = self.encoder
            try:
                for part in path.split("."):
                    obj = getattr(obj, part)
                return list(obj)
            except AttributeError:
                continue
        raise ValueError("could not find encoder layers")

    def forward(self, batch):
        context = self.encoder(input_ids=batch["context_ids"], attention_mask=batch["context_mask"]).last_hidden_state
        shape = batch["option_ids"].shape
        flat_ids = batch["option_ids"].reshape(-1, shape[-1])
        flat_mask = batch["option_token_mask"].reshape(-1, shape[-1])
        keep = flat_mask.any(1)  # skip padded option slots
        pooled = torch.zeros(flat_ids.shape[0], context.shape[-1], device=context.device, dtype=context.dtype)
        hidden = self.encoder(input_ids=flat_ids[keep], attention_mask=flat_mask[keep]).last_hidden_state
        m = flat_mask[keep].unsqueeze(-1)
        pooled[keep] = (hidden * m).sum(1) / m.sum(1).clamp_min(1)
        options = pooled.reshape(shape[0], shape[1], -1)
        return self.head(context, batch["context_mask"], options, batch["option_mask"])


def to(batch, device):
    return {k: v.to(device) for k, v in batch.items()}


def loss_fn(logits, batch, alpha: float):
    ce = F.cross_entropy(logits, batch["labels"])
    if alpha <= 0 or not batch["has_soft"].any():
        return ce
    logp = logits.log_softmax(-1)[batch["has_soft"]]
    soft = batch["soft"][batch["has_soft"]]
    valid = batch["option_mask"][batch["has_soft"]]
    kl = (soft * (soft.clamp_min(1e-9).log() - logp)).masked_fill(~valid, 0).sum(-1).mean()
    return (1 - alpha) * ce + alpha * kl


def build(cfg, device):
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(cfg["hf_model"])
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = VoxScorer(cfg["hf_model"], cfg["rank"], cfg["train_layers"]).to(device)
    return model, HuggingFaceCollator(tok, cfg["context_tokens"], cfg["option_tokens"])


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    hits = total = 0
    nll = 0.0
    for b in loader:
        b = to(b, device)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits = model(b).float()
        nll += float(F.cross_entropy(logits, b["labels"], reduction="sum"))
        hits += int(logits.argmax(-1).eq(b["labels"]).sum())
        total += b["labels"].numel()
    return hits / total, nll / total


def train(a):
    torch.manual_seed(a.seed)
    device = torch.device(a.device)
    cfg = {"hf_model": a.hf_model, "rank": a.rank, "train_layers": a.train_layers,
           "context_tokens": a.context_tokens, "option_tokens": a.option_tokens}
    model, base = build(cfg, device)
    tr = VoxRows(a.train, a.teacher_probs)
    if a.limit:
        tr.rows, tr.examples = tr.rows[:a.limit], tr.examples[:a.limit]
    va = VoxRows(a.validation)
    va.rows, va.examples = va.rows[:a.val_limit], va.examples[:a.val_limit]
    tl = DataLoader(tr, batch_size=a.batch_size, shuffle=True, collate_fn=Collate(tr, base), num_workers=2)
    vl = DataLoader(va, batch_size=64, collate_fn=Collate(va, base))
    params = [p for p in model.parameters() if p.requires_grad]
    enc = [p for n, p in model.named_parameters() if p.requires_grad and n.startswith("encoder.")]
    head = [p for n, p in model.named_parameters() if p.requires_grad and not n.startswith("encoder.")]
    opt = torch.optim.AdamW([{"params": head, "lr": a.lr}, {"params": enc, "lr": a.encoder_lr}], weight_decay=0.01)
    steps = a.epochs * math.ceil(len(tr) / a.batch_size)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[a.lr, a.encoder_lr], total_steps=steps, pct_start=0.06)
    print(json.dumps({"train_rows": len(tr), "teacher_rows": len(tr.teacher), "trainable_params": sum(p.numel() for p in params),
                      "steps": steps, "device": str(device)}), flush=True)
    best, t0, step = -1.0, time.time(), 0
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(a.epochs):
        model.train()
        for b in tl:
            b = to(b, device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(b).float()
            loss = loss_fn(logits, b, a.alpha)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            sched.step()
            step += 1
            if step % a.log_every == 0:
                print(json.dumps({"step": step, "loss": round(float(loss), 4),
                                  "rows_per_s": round(step * a.batch_size / (time.time() - t0), 1)}), flush=True)
        acc, nll = evaluate(model, vl, device)
        print(json.dumps({"epoch": epoch + 1, "val_acc": round(acc, 4), "val_nll": round(nll, 4)}), flush=True)
        if acc > best:
            best = acc
            state = {n: p.detach().cpu() for n, p in model.named_parameters() if p.requires_grad}
            torch.save({"config": cfg, "state_dict": state}, out)
    print(json.dumps({"checkpoint": str(out), "best_val_acc": best, "minutes": round((time.time() - t0) / 60, 1)}))


@torch.no_grad()
def predict(a):
    device = torch.device(a.device)
    payload = torch.load(a.predict, map_location="cpu", weights_only=False)
    model, base = build(payload["config"], device)
    model.load_state_dict(payload["state_dict"], strict=False)
    model.eval()
    data = VoxRows(a.train)
    n = min(len(data), a.limit or len(data))
    loader = DataLoader(list(range(n)), batch_size=1, collate_fn=Collate(data, base))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for b in loader:
            b = to(b, device)
            if device.type == "cuda":
                torch.cuda.synchronize()
            t = time.perf_counter()
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
                probs = model(b).float().softmax(-1)[0]
            if device.type == "cuda":
                torch.cuda.synchronize()
            ms = (time.perf_counter() - t) * 1000
            i = int(b["index"][0])
            k = len(data.examples[i].options)
            f.write(json.dumps({"id": data.rows[i]["id"], "probs": [round(float(x), 6) for x in probs[:k]],
                                "latency_ms": round(ms, 2)}) + "\n")
    print(json.dumps({"predictions": str(out), "rows": n}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("train", help="training JSONL (or the split to predict with --predict)")
    ap.add_argument("--validation")
    ap.add_argument("--output", default="runs/jevlike.pt")
    ap.add_argument("--predict", help="checkpoint path: run prediction instead of training")
    ap.add_argument("--out", help="prediction output JSONL")
    ap.add_argument("--hf-model", default="intfloat/e5-small-v2")
    ap.add_argument("--rank", type=int, default=128)
    ap.add_argument("--train-layers", type=int, default=-1, help="-1 = whole encoder, 0 = frozen (jevlike default)")
    ap.add_argument("--context-tokens", type=int, default=512)
    ap.add_argument("--option-tokens", type=int, default=24)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--encoder-lr", type=float, default=5e-5)
    ap.add_argument("--teacher-probs", nargs="*")
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--val-limit", type=int, default=1000)
    ap.add_argument("--log-every", type=int, default=100)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if a.predict:
        predict(a)
    else:
        if not a.validation:
            sys.exit("--validation is required for training")
        train(a)


if __name__ == "__main__":
    main()
