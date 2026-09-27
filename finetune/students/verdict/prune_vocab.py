"""Prune a Verdict bi run's 250k-token vocabulary (96M of its 118M parameters) to the tokens it can plausibly see.

Kept: the special tokens, every token that occurs in the given data files (contexts + options, all real and synthetic
sets), every single-character piece (so rare scripts / emoji fall back to characters, not <unk>), and then the
highest-scoring unigram pieces until --n tokens in total (the unigram log-probabilities rank pieces by corpus frequency,
so this is the common multilingual vocabulary).

Why this is lossless for covered text: XLM-R's tokenizer is a Unigram model (Viterbi over pieces). Removing pieces that
a text's best segmentation does not use leaves that segmentation optimal, so the token sequence is unchanged (ids are
remapped). Text whose best segmentation used a removed piece is segmented into smaller kept pieces instead.

    python students/verdict/prune_vocab.py students/verdict/runs/<run> --out students/verdict/runs/<run>-pruned [--n 60000]

Verification (printed and written to <out>/prune.json): token-sequence identity and cosine of pruned vs unpruned
embeddings on every context and option of the verification files (default: emulator val + dev-test + Z Flip val).
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path

import vlib  # noqa: F401
import torch
from safetensors.torch import load_file, save_file

FT = Path(__file__).resolve().parents[2]
DATA = ["data/real-targets-v2/zflip/train_real_all.jsonl", "data/real-targets-v2/zflip/val_real_all.jsonl",
        "data/real-targets-v2/test_real.jsonl", "data/real-targets-v2/test_real_old.jsonl", "data/real-targets-v2/zflip/diag_x_opus.jsonl",
        "data/targets-v2/train.jsonl", "data/targets-v2/validation.jsonl", "data/targets-v2/test_iid.jsonl",
        "data/targets-v2/test_unseen_apps.jsonl", "data/targets-v2/test_unseen_phrasing.jsonl"]
VERIFY = ["data/real-targets-v2/val_real.jsonl", "data/real-targets-v2/test_real.jsonl", "data/real-targets-v2/zflip/val_real_all.jsonl"]


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def texts_of(rows, q="query: ", p="passage: "):
    out = []
    for r in rows:
        out.append(q + r["context"])
        out += [p + o for o in r["options"]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=60000)
    ap.add_argument("--data", nargs="*", default=DATA)
    ap.add_argument("--extra-data", nargs="*", default=[], help="more jsonl files whose tokens must be kept")
    ap.add_argument("--verify", nargs="*", default=VERIFY)
    ap.add_argument("--verify-only", action="store_true", help="re-run the verification of an existing --out")
    ap.add_argument("--device", default="cuda", help="verification device (fp32, no autocast)")
    a = ap.parse_args()
    if a.verify_only:
        return verify(Path(a.run), Path(a.out), json.loads((Path(a.out) / "vocab_map.json").read_text()), a)
    from transformers import AutoTokenizer
    src, out = Path(a.run), Path(a.out)
    if out.exists():
        raise SystemExit(f"{out} exists")
    tok = AutoTokenizer.from_pretrained(src)
    tj = json.loads((src / "tokenizer.json").read_text())
    vocab = tj["model"]["vocab"]
    used = set()
    n_txt = 0
    for f in a.data + a.extra_data:
        if not (FT / f).exists():
            continue
        tx = texts_of(jl(FT / f))
        n_txt += len(tx)
        for i in range(0, len(tx), 2048):
            for ids in tok(tx[i:i + 2048], add_special_tokens=False)["input_ids"]:
                used.update(ids)
    special = {t["id"] for t in tj["added_tokens"]}
    single = {i for i, (p, _) in enumerate(vocab) if len(p.replace("▁", "")) <= 1}
    keep = set(special) | used | single
    by_score = sorted(range(len(vocab)), key=lambda i: -vocab[i][1])
    for i in by_score:
        if len(keep) >= a.n:
            break
        keep.add(i)
    keep = sorted(keep)
    remap = {o: n for n, o in enumerate(keep)}
    print(f"texts {n_txt}; used tokens {len(used)}; single-char {len(single)}; kept {len(keep)} of {len(vocab)}", flush=True)

    # tokenizer.json
    nt = copy.deepcopy(tj)
    nt["model"]["vocab"] = [vocab[i] for i in keep]
    nt["model"]["unk_id"] = remap[tj["model"]["unk_id"]]
    for t in nt["added_tokens"]:
        t["id"] = remap[t["id"]]
    for k, v in nt["post_processor"]["special_tokens"].items():
        v["ids"] = [remap[i] for i in v["ids"]]
    shutil.copytree(src, out, ignore=shutil.ignore_patterns("onnx", "*.log", "suite.*"))
    (out / "tokenizer.json").write_text(json.dumps(nt, ensure_ascii=False))
    # embeddings
    sd = load_file(str(src / "model.safetensors"))
    key = [k for k in sd if k.endswith("word_embeddings.weight")]
    assert len(key) == 1, key
    W = sd[key[0]]
    sd[key[0]] = W[torch.tensor(keep)].contiguous()
    save_file(sd, str(out / "model.safetensors"), metadata={"format": "pt"})
    cfg = json.loads((out / "config.json").read_text())
    cfg["vocab_size"] = len(keep)
    cfg["pad_token_id"] = remap.get(cfg.get("pad_token_id", 0), 0)
    (out / "config.json").write_text(json.dumps(cfg, indent=2))
    tc = json.loads((out / "tokenizer_config.json").read_text())
    tc.pop("added_tokens_decoder", None)
    (out / "tokenizer_config.json").write_text(json.dumps(tc, indent=2))
    meta = json.loads((out / "student.json").read_text())
    meta["pruned_from"] = str(src)
    meta["vocab_kept"] = len(keep)
    (out / "student.json").write_text(json.dumps(meta, indent=2))
    (out / "vocab_map.json").write_text(json.dumps(keep))
    verify(src, out, keep, a, {"used_in_data": len(used)})


def verify(src: Path, out: Path, keep: list[int], a, extra: dict | None = None):
    """Same token sequences (after remap) and cosine of pruned vs unpruned embeddings on every verification text."""
    from transformers import AutoTokenizer
    remap = {o: n for n, o in enumerate(keep)}
    vocab_n = len(json.loads((src / "tokenizer.json").read_text())["model"]["vocab"])
    ta, tb = AutoTokenizer.from_pretrained(src), AutoTokenizer.from_pretrained(out)
    ma = vlib.Student(str(src), "bi", device=a.device).eval()
    mb = vlib.Student(str(out), "bi", device=a.device).eval()
    rep = {"kept": len(keep), "of": vocab_n, **(extra or {}), "files": {}}
    for f in a.verify:
        rows = jl(FT / f)
        tx = texts_of(rows)
        ia = ta(tx)["input_ids"]
        ib = tb(tx)["input_ids"]
        same = sum([remap.get(i, -1) for i in x] == y for x, y in zip(ia, ib))
        unk_b = sum(tb.unk_token_id in y for y in ib)
        cos = []
        with torch.no_grad():
            for i in range(0, len(tx), 64):
                ch = tx[i:i + 64]
                cos += (ma.embed(ch) * mb.embed(ch)).sum(-1).tolist()
        rep["files"][f] = {"texts": len(tx), "same_tokens": same, "unk_after": unk_b, "cos_min": min(cos), "cos_mean": sum(cos) / len(cos)}
        print(f, rep["files"][f], flush=True)
    sz = lambda p: p.stat().st_size  # noqa: E731
    rep["safetensors_mb"] = {"before": round(sz(src / "model.safetensors") / 1e6, 1), "after": round(sz(out / "model.safetensors") / 1e6, 1)}
    rep["tokenizer_json_mb"] = {"before": round(sz(src / "tokenizer.json") / 1e6, 1), "after": round(sz(out / "tokenizer.json") / 1e6, 1)}
    (out / "prune.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if k != "files"}))


if __name__ == "__main__":
    main()
