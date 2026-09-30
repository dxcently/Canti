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
import os
import sys
import time
from pathlib import Path

# ROCm/gfx1151: without this, SDPA falls back to the math kernel (as in students/verdict/vlib.py). Kernel choice only.
os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")

import torch  # noqa: E402
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset

from jevlike.data import ChoiceExample, HuggingFaceCollator, validate
from jevlike.model import AttentionHead

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # finetune root, for the students.* namespace package
from students.jevlike.selection import selection_improves


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
    def __init__(self, data: VoxRows, base: HuggingFaceCollator, teacher_skip_none: bool = False) -> None:
        self.data, self.base = data, base
        # jl9 --teacher-skip-none: gold-none rows (label = last option) get no teacher, i.e. the same loss as rows without
        # teacher probs (hard-label CE share only); the teacher still speaks on every other row.
        self.teacher_skip_none = teacher_skip_none

    def __call__(self, idx: list[int]):
        batch = self.base([self.data.examples[i] for i in idx])
        width = batch["option_mask"].shape[1]
        soft = torch.zeros(len(idx), width)
        has = torch.zeros(len(idx), dtype=torch.bool)
        for row, i in enumerate(idx):
            probs = self.data.teacher.get(self.data.rows[i]["id"])
            ex = self.data.examples[i]
            if self.teacher_skip_none and ex.label == len(ex.options) - 1:
                probs = None
            if probs is not None and len(probs) == len(ex.options):
                soft[row, :len(probs)] = torch.tensor(probs)
                has[row] = True
        batch["soft"], batch["has_soft"] = soft, has
        batch["index"] = torch.tensor(idx)
        return batch


class VoxScorer(nn.Module):
    def __init__(self, model_name: str, rank: int, train_layers: int, freeze_embeddings: bool = False) -> None:
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
        if freeze_embeddings:  # e.g. a 250k-token XLM-R vocabulary (Verdict's recipe keeps it frozen)
            self.encoder.get_input_embeddings().requires_grad_(False)
        self.head = AttentionHead(self.encoder.config.hidden_size, rank)
        # fast option encoding (opt-in, --fast-options): encode each distinct option once per batch and trim token
        # padding per length-sorted chunk. Same function (padding is masked, positions start at 0); only float noise
        # differs. In training, a repeated option shares one dropout mask instead of drawing one per copy.
        self.fast_options = False
        self.option_chunk_tokens = 4096

    def _encode_options(self, ids, mask):
        """Mean-pooled embeddings of option rows ids [N, L] (padded rows already removed)."""
        if not self.fast_options:
            hidden = self.encoder(input_ids=ids, attention_mask=mask).last_hidden_state
            m = mask.unsqueeze(-1)
            return (hidden * m).sum(1) / m.sum(1).clamp_min(1)
        uniq, inv = torch.unique(ids, dim=0, return_inverse=True)
        # the mask of a unique row: take it from any occurrence (identical ids -> identical mask)
        first = torch.empty(uniq.shape[0], dtype=torch.long, device=ids.device).scatter_(0, inv, torch.arange(ids.shape[0], device=ids.device))
        umask = mask[first]
        lens = umask.sum(1)
        order = torch.argsort(lens, descending=True)
        lens_sorted = lens[order].tolist()
        pooled = None
        i = 0
        while i < len(order):
            L = max(1, int(lens_sorted[i]))
            n = max(1, self.option_chunk_tokens // L)
            sel = order[i:i + n]
            cm = umask[sel, :L]
            h = self.encoder(input_ids=uniq[sel, :L], attention_mask=cm).last_hidden_state
            m = cm.unsqueeze(-1)
            p = (h * m).sum(1) / m.sum(1).clamp_min(1)
            if pooled is None:
                pooled = torch.zeros(uniq.shape[0], p.shape[-1], device=p.device, dtype=p.dtype)
            pooled = pooled.index_copy(0, sel, p)
            i += n
        return pooled[inv]

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
        enc = self._encode_options(flat_ids[keep], flat_mask[keep])
        pooled[keep] = enc.to(pooled.dtype)
        options = pooled.reshape(shape[0], shape[1], -1)
        return self.head(context, batch["context_mask"], options, batch["option_mask"])


class OptionCache:
    """jl9 inference cache. In VoxScorer an option's vector is mean-pool(encoder(option tokens)) and depends on the option
    text only (the option is encoded alone; the head's option side, LayerNorm -> query, is per option too); only the
    context encoding and the head's context attention depend on the context. So option vectors are cached by option text
    (after the p-prefix) and a decision costs one encoder pass over the context plus the head. Tokenisation, truncation and
    masking follow jevlike's HuggingFaceCollator exactly. Misses are encoded together (length-sorted chunks, no extra
    padding: the --fast-options function). Cached vectors are stored in the dtype they were computed in (bf16 under
    autocast), exactly what the uncached path feeds the head. Bounded: cleared when it reaches max_items."""

    def __init__(self, model: "VoxScorer", collate, max_items: int = 100_000) -> None:
        self.model = model
        base = collate.base if isinstance(collate, PrefixCollator) else collate
        self.q, self.p = (collate.q, collate.p) if isinstance(collate, PrefixCollator) else ("", "")
        self.tok, self.ctx_len, self.opt_len = base.tokenizer, base.context_tokens, base.option_tokens
        self.pad = self.tok.pad_token_id
        self.store: dict[str, torch.Tensor] = {}
        self.max_items = max_items
        self.hits = self.misses = 0

    def _fill(self, texts: list[str], device):
        ids = self.tok([self.p + t for t in texts], truncation=True, max_length=self.opt_len, add_special_tokens=True)["input_ids"]
        L = max(map(len, ids))
        x = torch.full((len(ids), L), self.pad, dtype=torch.long)
        for i, t in enumerate(ids):
            x[i, :len(t)] = torch.tensor(t)
        x = x.to(device)
        fast = self.model.fast_options
        self.model.fast_options = True     # misses: distinct options, length-sorted chunks (same function as the plain path)
        try:
            v = self.model._encode_options(x, x.ne(self.pad))
        finally:
            self.model.fast_options = fast
        if len(self.store) + len(texts) > self.max_items:
            self.store.clear()
        for t, e in zip(texts, v):
            self.store[t] = e.detach()

    @torch.no_grad()
    def logits(self, rows: list[dict], device) -> list[torch.Tensor]:
        """-> fp32 logits (T = 1) over each row's real options."""
        miss = [o for o in dict.fromkeys(o for r in rows for o in r["options"]) if o not in self.store]
        self.misses += len(miss)
        self.hits += sum(len(r["options"]) for r in rows) - len(miss)
        if miss:
            self._fill(miss, device)
        ctx = self.tok([self.q + r["context"] for r in rows], truncation=True, max_length=self.ctx_len, add_special_tokens=True)["input_ids"]
        Lc, K = max(map(len, ctx)), max(len(r["options"]) for r in rows)
        cid = torch.full((len(rows), Lc), self.pad, dtype=torch.long)
        for i, t in enumerate(ctx):
            cid[i, :len(t)] = torch.tensor(t)
        cid = cid.to(device)
        cmask = cid.ne(self.pad)
        context = self.model.encoder(input_ids=cid, attention_mask=cmask).last_hidden_state
        opts = torch.zeros(len(rows), K, context.shape[-1], device=device, dtype=context.dtype)
        omask = torch.zeros(len(rows), K, dtype=torch.bool, device=device)
        for i, r in enumerate(rows):
            opts[i, :len(r["options"])] = torch.stack([self.store[o] for o in r["options"]]).to(context.dtype)
            omask[i, :len(r["options"])] = True
        z = self.model.head(context, cmask, opts, omask).float()
        return [z[i, :len(r["options"])] for i, r in enumerate(rows)]


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
    model = VoxScorer(cfg["hf_model"], cfg["rank"], cfg["train_layers"], cfg.get("freeze_embeddings", False)).to(device)
    base = HuggingFaceCollator(tok, cfg["context_tokens"], cfg["option_tokens"])
    qp, pp = cfg.get("q_prefix", ""), cfg.get("p_prefix", "")
    return model, (PrefixCollator(base, qp, pp) if qp or pp else base)


class PrefixCollator:
    """Prepend e5-style prefixes ("query: " to the context, "passage: " to each option) before tokenising."""

    def __init__(self, base, q_prefix: str, p_prefix: str) -> None:
        self.base, self.q, self.p = base, q_prefix, p_prefix

    def __call__(self, examples):
        return self.base([ChoiceExample(self.q + e.context, tuple(self.p + o for o in e.options), e.label) for e in examples])


@torch.no_grad()
def evaluate(model, loader, device, keep_logits: list | None = None):
    """(acc, nll at T = 1); appends (logits over the real options, label) per row to keep_logits when given."""
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
        if keep_logits is not None:
            for z, m, y in zip(logits.cpu(), b["option_mask"].cpu(), b["labels"].cpu().tolist()):
                keep_logits.append((z[m].tolist(), y))
    return hits / total, nll / total


def nll_at(pairs, T: float) -> float:
    s = 0.0
    for z, y in pairs:
        m = max(z)
        s -= z[y] / T - (math.log(sum(math.exp((v - m) / T) for v in z)) + m / T)
    return s / max(1, len(pairs))


def train(a):
    torch.manual_seed(a.seed)
    device = torch.device(a.device)
    cfg = {"hf_model": a.hf_model, "rank": a.rank, "train_layers": a.train_layers,
           "context_tokens": a.context_tokens, "option_tokens": a.option_tokens}
    if a.q_prefix or a.p_prefix:
        cfg.update(q_prefix=a.q_prefix, p_prefix=a.p_prefix)
    if a.freeze_embeddings:
        cfg["freeze_embeddings"] = True
    model, base = build(cfg, device)
    tr = VoxRows(a.train, a.teacher_probs)
    if a.limit:
        tr.rows, tr.examples = tr.rows[:a.limit], tr.examples[:a.limit]
    va = VoxRows(a.validation)
    va.rows, va.examples = va.rows[:a.val_limit], va.examples[:a.val_limit]
    tl = DataLoader(tr, batch_size=a.batch_size, shuffle=True, collate_fn=Collate(tr, base, a.teacher_skip_none), num_workers=2)
    vl = DataLoader(va, batch_size=64, collate_fn=Collate(va, base))
    params = [p for p in model.parameters() if p.requires_grad]
    enc = [p for n, p in model.named_parameters() if p.requires_grad and n.startswith("encoder.")]
    head = [p for n, p in model.named_parameters() if p.requires_grad and not n.startswith("encoder.")]
    opt = torch.optim.AdamW([{"params": head, "lr": a.lr}, {"params": enc, "lr": a.encoder_lr}], weight_decay=0.01)
    steps = a.epochs * math.ceil(len(tr) / a.batch_size)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[a.lr, a.encoder_lr], total_steps=steps, pct_start=0.06)
    n_skip = sum(1 for r, e in zip(tr.rows, tr.examples) if r["id"] in tr.teacher and e.label == len(e.options) - 1) if a.teacher_skip_none else 0
    print(json.dumps({"train_rows": len(tr), "teacher_rows": len(tr.teacher), "teacher_skipped_gold_none": n_skip, "trainable_params": sum(p.numel() for p in params),
                      "steps": steps, "device": str(device)}), flush=True)
    if a.fast_options:
        model.fast_options = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # students/common.py
    from common import fit_temperature
    # --select acc (default, jl7 behaviour): keep the epoch with the best val acc (ties: earliest).
    # --select nll: lowest val NLL at T = 1.  --select nll_t: lowest val NLL after fitting T on val for that epoch.
    # --tie later: on an exact selection-metric tie keep the later epoch instead of the earliest.
    better = lambda m, b: selection_improves(m, b, a.select, a.tie == "later")
    best, t0, step = None, time.time(), 0
    no_improve = 0
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
        pairs = [] if (a.fit_temperature or a.select == "nll_t") else None
        acc, nll = evaluate(model, vl, device, pairs)
        m = {"epoch": epoch + 1, "acc": acc, "nll": nll}
        rec = {"epoch": epoch + 1, "val_acc": round(acc, 4), "val_nll": round(nll, 4)}
        if pairs is not None:
            T = fit_temperature([z for z, _ in pairs], [y for _, y in pairs])
            m.update(T=T, nll_t=nll_at(pairs, T))
            rec.update(val_T=T, val_nll_T=round(m["nll_t"], 4))
        rec["rows_per_s_epoch"] = round(step * a.batch_size / (time.time() - t0), 1)
        print(json.dumps(rec), flush=True)
        state = None
        if best is None or better(m, best):
            best = m
            ck_cfg = dict(cfg)
            if a.fit_temperature:
                ck_cfg["temperature"] = T
            if a.select != "acc" or a.fit_temperature:
                ck_cfg["selected"] = {"by": a.select, "epoch": epoch + 1, "val_acc": round(acc, 4), "val_nll": round(nll, 4),
                                      **({"val_nll_T": round(m["nll_t"], 4), "val_T": T} if "T" in m else {})}
            state = {n: p.detach().cpu() for n, p in model.named_parameters() if p.requires_grad}
            torch.save({"config": ck_cfg, "state_dict": state}, out)
            no_improve = 0
        else:
            no_improve += 1
        if a.save_every_epoch:
            if state is None:
                state = {n: p.detach().cpu() for n, p in model.named_parameters() if p.requires_grad}
            ep_cfg = dict(cfg)
            if a.fit_temperature:
                ep_cfg["temperature"] = T
            ep_cfg["selected"] = {"by": "every_epoch", "epoch": epoch + 1, "val_acc": round(acc, 4), "val_nll": round(nll, 4),
                                  **({"val_nll_T": round(m["nll_t"], 4), "val_T": T} if "T" in m else {})}
            torch.save({"config": ep_cfg, "state_dict": state}, out.with_name(f"{out.stem}.e{epoch + 1}.pt"))
        if a.patience and no_improve >= a.patience:
            print(json.dumps({"early_stop": epoch + 1}), flush=True)
            break
    print(json.dumps({"checkpoint": str(out), "best_val_acc": best["acc"], "selected_epoch": best["epoch"], "select": a.select,
                      **({"temperature": best["T"]} if a.fit_temperature else {}),
                      "train_rows_per_s": round(step * a.batch_size / max(1e-9, time.time() - t0), 1),
                      "minutes": round((time.time() - t0) / 60, 1)}))


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
    cache = OptionCache(model, base) if a.cache_options else None
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for b in loader:
            b = to(b, device)
            if device.type == "cuda":
                torch.cuda.synchronize()
            t = time.perf_counter()
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
                z = cache.logits([data.rows[int(b["index"][0])]], device)[0][None] if cache else model(b).float()
                probs = (z / payload["config"].get("temperature", 1.0)).softmax(-1)[0]
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
    ap.add_argument("--q-prefix", default="", help='prepended to every context (e.g. "query: " for a Verdict/e5 encoder)')
    ap.add_argument("--p-prefix", default="", help='prepended to every option (e.g. "passage: ")')
    ap.add_argument("--freeze-embeddings", action="store_true", help="keep the token-embedding matrix frozen")
    ap.add_argument("--teacher-probs", nargs="*")
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--teacher-skip-none", action="store_true",
                    help="gold-none rows (label = last option) get no teacher: hard-label CE share only, as rows without teacher probs")
    ap.add_argument("--fast-options", action="store_true",
                    help="encode each distinct option once per batch, length-sorted chunks without extra padding (same outputs up to float noise)")
    ap.add_argument("--select", choices=("acc", "nll", "nll_t"), default="acc",
                    help="checkpoint selection on val: acc (default), nll (T = 1) or nll_t (NLL after fitting T on val)")
    ap.add_argument("--tie", choices=("earliest", "later"), default="earliest",
                    help="on an exact selection-metric tie keep the earliest epoch (default, reproduces old runs) or the later one")
    ap.add_argument("--save-every-epoch", action="store_true",
                    help="also save each epoch's state as <output stem>.e<N>.pt (same format as the final checkpoint)")
    ap.add_argument("--patience", type=int, default=0,
                    help="early stop after N consecutive epochs without a better selection metric (0 = off, default)")
    ap.add_argument("--fit-temperature", action="store_true", help="fit T on val (common.fit_temperature) and store it in the checkpoint config")
    ap.add_argument("--cache-options", action="store_true", help="--predict: cache option vectors by option text (OptionCache)")
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
