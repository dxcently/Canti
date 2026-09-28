"""Verdict-style students on multilingual-e5-small (118M): a bi-encoder (Verdict's own mechanism) and a cross-encoder
over (context, option) pairs built from the same weights.

bi     logits_k = SCALE * cos(E("query: " + context), E("passage: " + option_k))        SCALE = 20, as in Verdict
       The context is embedded once with no knowledge of the options, options once with no knowledge of the context;
       option embeddings can be cached, so a decision is one encoder pass over the context.
cross  logits_k = w . meanpool(E("query: " + context  </s></s>  "passage: " + option_k)) + b
       Every option token attends to every context token (and vice versa): K encoder passes (one batch) per decision.
cross_cos  the same (context, option) pair pass, but scored like the bi-encoder instead of with a fresh linear head:
       logits_k = SCALE * cos(meanpool(context-span tokens), meanpool(option-span tokens)) of the joint encoding.
       At step 0 this is the bi-encoder plus cross-attention, so it starts from Verdict's cosine geometry; no new params.

Run directory layout (both archs): HF encoder (config.json, model.safetensors, tokenizer), student.json
({arch, scale, temperature, max_len, q_prefix, p_prefix, base}), head.pt (cross only). A bi run also gets
sentence-transformers module files (mean pooling + normalize), so `verdict.Verdict(model="<run dir>")` loads it when the
directory name contains "verdict-" (Verdict picks the e5 prefixes from the name).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# ROCm/gfx1151: without this, SDPA falls back to the math kernel (full L x L attention matrices): the cross-encoder
# (~11 pairs x 400 tokens per row) then runs out of memory at 4 rows per micro-batch. It changes the kernel only.
os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")

import torch  # noqa: E402
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # students/common.py

DEFAULT_INIT = "Manav2op/verdict-small"   # Verdict's released encoder (e5-small fine-tuned on its typed-decision mix)
Q_PREFIX, P_PREFIX = "query: ", "passage: "
SCALE = 20.0


def resolve(name: str) -> str:
    if Path(name).is_dir():
        return name
    from huggingface_hub import snapshot_download
    return snapshot_download(name, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "1_Pooling/*", "2_Normalize/*"])


def mean_pool(h, mask):
    m = mask.unsqueeze(-1).to(h.dtype)
    return (h * m).sum(1) / m.sum(1).clamp_min(1e-9)


def span_cos(h, attention_mask, opt_mask):
    """SCALE * cos(mean of context-span tokens, mean of option-span tokens), per pair."""
    c = mean_pool(h, attention_mask * (1 - opt_mask)).float()
    o = mean_pool(h, opt_mask).float()
    return (F.normalize(c, dim=-1) * F.normalize(o, dim=-1)).sum(-1) * SCALE


class Student(nn.Module):
    def __init__(self, path: str, arch: str, max_len: int = 512, device="cpu"):
        super().__init__()
        from transformers import AutoModel, AutoTokenizer
        src = resolve(path)
        self.src = src
        self.arch, self.max_len, self.device = arch, max_len, device
        self.tok = AutoTokenizer.from_pretrained(src)
        self.enc = AutoModel.from_pretrained(src, attn_implementation="sdpa")
        cfg = Path(src) / "student.json"
        self.meta = json.loads(cfg.read_text()) if cfg.exists() else {}
        self.temperature = float(self.meta.get("temperature", 1.0))
        self.q_prefix, self.p_prefix = self.meta.get("q_prefix", Q_PREFIX), self.meta.get("p_prefix", P_PREFIX)
        if arch == "cross":
            self.head = nn.Linear(self.enc.config.hidden_size, 1)
            nn.init.normal_(self.head.weight, std=0.02); nn.init.zeros_(self.head.bias)
            if (Path(src) / "head.pt").exists():
                self.head.load_state_dict(torch.load(Path(src) / "head.pt", map_location="cpu"))
        self._opt_cache: dict[str, torch.Tensor] = {}
        # jl9 opt-in (train.py --fast-embed): embed() encodes length-sorted chunks padded only to the chunk's longest text
        # (<= embed_chunk_tokens padded tokens per chunk) instead of one batch padded to the longest. Same function (padding
        # is masked; XLM-R position ids skip padding); only float noise and, in training, dropout draws differ.
        self.fast_embed = False
        self.embed_chunk_tokens = 4096
        self.to(device)

    # ------------------------------------------------------------------ encoding
    def _tok(self, texts, pairs=None, max_len=None, spans=False):
        kw = dict(padding=True, truncation="only_first" if pairs is not None else True, max_length=max_len or self.max_len, return_tensors="pt")
        b = self.tok(texts, pairs, **kw) if pairs is not None else self.tok(texts, **kw)
        out = {k: v.to(self.device) for k, v in b.items()}
        if spans:   # option-span mask (second sequence of the pair); the context span is everything else that is real
            out["opt_mask"] = torch.tensor([[int(s == 1) for s in b.sequence_ids(i)] for i in range(len(texts))], device=self.device)
        return out

    def embed(self, texts, max_len=None):
        if self.fast_embed and len(texts) > 1:
            return self._embed_chunked(texts, max_len)
        b = self._tok(texts, max_len=max_len)
        h = self.enc(**b).last_hidden_state
        return F.normalize(mean_pool(h, b["attention_mask"]).float(), dim=-1)

    def _embed_chunked(self, texts, max_len=None):
        enc = self.tok(texts, truncation=True, max_length=max_len or self.max_len)["input_ids"]
        order = sorted(range(len(enc)), key=lambda i: -len(enc[i]))
        out = [None] * len(enc)
        i = 0
        while i < len(order):
            L = max(1, len(enc[order[i]]))
            sel = order[i:i + max(1, self.embed_chunk_tokens // L)]
            b = self.tok.pad({"input_ids": [enc[j] for j in sel]}, return_tensors="pt")
            b = {k: v.to(self.device) for k, v in b.items()}
            h = self.enc(**b).last_hidden_state
            v = F.normalize(mean_pool(h, b["attention_mask"]).float(), dim=-1)
            for j, row in zip(sel, v):
                out[j] = row
            i += len(sel)
        return torch.stack(out)

    def option_embeddings(self, options, cache=False):
        if not cache:
            return self.embed([self.p_prefix + o for o in options], max_len=64)
        miss = [o for o in dict.fromkeys(options) if o not in self._opt_cache]
        if miss:
            for o, v in zip(miss, self.embed([self.p_prefix + o for o in miss], max_len=64)):
                self._opt_cache[o] = v.detach()
        return torch.stack([self._opt_cache[o] for o in options])

    # ------------------------------------------------------------------ scoring
    def logits(self, rows, cache_options=False):
        """-> list of 1-D fp32 logits (T = 1), one per row, aligned with row["options"]."""
        if self.arch == "bi":
            X = self.embed([self.q_prefix + r["context"] for r in rows])
            uniq = list(dict.fromkeys(o for r in rows for o in r["options"]))
            O = self.option_embeddings(uniq, cache=cache_options)
            idx = {o: i for i, o in enumerate(uniq)}
            return [(O[torch.tensor([idx[o] for o in r["options"]], device=X.device)] @ X[i]) * SCALE for i, r in enumerate(rows)]
        ctx = [self.q_prefix + r["context"] for r in rows for _ in r["options"]]
        opt = [self.p_prefix + o for r in rows for o in r["options"]]
        if self.arch == "cross_cos":
            b = self._tok(ctx, opt, spans=True)
            om = b.pop("opt_mask")
            h = self.enc(**b).last_hidden_state
            z = span_cos(h, b["attention_mask"], om)
            return list(z.split([len(r["options"]) for r in rows]))
        b = self._tok(ctx, opt)
        h = self.enc(**b).last_hidden_state
        z = self.head(mean_pool(h, b["attention_mask"]).to(self.head.weight.dtype)).squeeze(-1).float()
        return list(z.split([len(r["options"]) for r in rows]))

    # ------------------------------------------------------------------ saving
    def save(self, out: Path, extra: dict):
        out.mkdir(parents=True, exist_ok=True)
        self.enc.save_pretrained(str(out)); self.tok.save_pretrained(str(out))
        if self.arch == "cross":
            torch.save({k: v.cpu() for k, v in self.head.state_dict().items()}, out / "head.pt")
        else:   # sentence-transformers module files, for verdict.Verdict(model=<run>)
            for f in ["modules.json", "sentence_bert_config.json", "config_sentence_transformers.json", "1_Pooling", "2_Normalize"]:
                s = Path(self.src) / f
                if s.is_dir(): shutil.copytree(s, out / f, dirs_exist_ok=True)
                elif s.exists(): shutil.copy(s, out / f)
        meta = {"arch": self.arch, "scale": None if self.arch == "cross" else SCALE, "temperature": self.temperature, "max_len": self.max_len,
                "q_prefix": self.q_prefix, "p_prefix": self.p_prefix, **extra}
        (out / "student.json").write_text(json.dumps(meta, indent=2))
