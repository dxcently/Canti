"""Screen-swap hard-negative CANDIDATES (STEP 3.9): a target phrase from screen A shown with screen B of another app
family. They are none rows only if nothing on B fits the phrase, so every candidate is verified by Opus
(vox.verdict_aug swap --verified) before use.

Hardness: v1d's highest non-none probability on B (the model is fooled -> informative). Candidates whose gold label text
is also on B are skipped up front (certain matches). Caps: at most --per-screen per B screen and one per A phrase.
Emulator rows only (no Z Flip row is read).

    python students/verdict/swap_cands.py --build data/real-targets-v2/b2 --n 900
Round 2 (after round 1's verification showed position / generic phrases match almost any screen):
    python students/verdict/swap_cands.py --round r2 --kinds name function appearance casual --lex-filter 1 \
        --exclude data/real-targets-v2/b2/aug/swap_cands.jsonl --per-screen 3 --n 900
Writes <build>/aug/swap_cands.jsonl ({cid, hard, row}) and <build>/aug/swap_verify/batch_NN.json (what the verifier sees:
phrase, app, screen line, option texts, marks image path).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import vlib  # noqa: F401
import torch

FT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FT))
from vox import normalize as NZ  # noqa: E402
from vox.real_targets_v2 import APP_FAMILIES  # noqa: E402

FAM = {a: f for f, apps in APP_FAMILIES.items() for a in apps}
LAB = re.compile(r"^(.*) \([a-z ]+, [a-z ]+\)$")


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def lab(o):
    m = LAB.match(o)
    return (m.group(1) if m else o).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="data/real-targets-v2/b2")
    ap.add_argument("--model", default="students/verdict/runs/verdict-bi-real-v1d")
    ap.add_argument("--n", type=int, default=900)
    ap.add_argument("--per-a", type=int, default=6, help="B screens tried per A phrase")
    ap.add_argument("--per-screen", type=int, default=2)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--round", default="", help="round tag: '' -> swap_cands.jsonl / swap_verify/, 'r2' -> swap_cands_r2.jsonl / swap_verify_r2/")
    ap.add_argument("--kinds", nargs="*", default=None, help="A phrase kinds to use (default: all but near_none)")
    ap.add_argument("--lex-filter", type=int, default=0,
                    help="1 = skip a pair when a content word of the phrase appears in an option label of B")
    ap.add_argument("--exclude", nargs="*", default=[], help="earlier candidate files: their A phrases and (A, B) pairs are not reused")
    a = ap.parse_args()
    B = FT / a.build
    rng = random.Random(a.seed)
    pool = [r for f in ("zflip/train_real_all.jsonl", "zflip/val_real_all.jsonl") for r in jl(B / f)]
    emu = [r for r in pool if r["screen_id"].startswith("emu") and "-zf-" not in r["id"] and "serial" not in r
           and "HIDDEN" not in r.get("label_note", "")]
    screens = {}
    for r in emu:
        screens.setdefault(r["screen_id"], r)
    used = {c["row"]["swap_of"] for f in a.exclude for c in jl(f)}
    A = [r for r in emu if r["label"] != len(r["options"]) - 1 and r["kind"] not in ("near_none",) and r.get("phrase")
         and (a.kinds is None or r["kind"] in a.kinds) and r["id"] not in used]
    STOP = {"the", "a", "an", "to", "of", "on", "in", "at", "for", "and", "or", "my", "me", "i", "it", "that", "this", "thing", "one",
            "button", "icon", "tap", "press", "hit", "open", "go", "click", "select", "want", "please", "can", "you", "with", "from",
            "top", "bottom", "left", "right", "middle", "corner", "side", "screen", "page", "option", "menu", "list", "item", "back"}
    words = lambda t: {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in STOP}  # noqa: E731
    fam = lambda app: FAM.get(app, app)  # noqa: E731
    sids = sorted(screens)
    pairs = []
    for r in A:
        gold = lab(r["options"][r["label"]])
        tried = 0
        for sid in rng.sample(sids, min(len(sids), 4 * a.per_a)):
            s = screens[sid]
            if fam(s["app"]) == fam(r["app"]) or gold in {lab(o) for o in s["options"][:-1]}:
                continue
            if a.lex_filter and words(r["phrase"]) & set().union(*(words(lab(o)) for o in s["options"][:-1])):
                continue
            pairs.append((r, s))
            tried += 1
            if tried >= a.per_a:
                break
    print(f"{len(A)} A phrases, {len(screens)} B screens, {len(pairs)} pairs", flush=True)
    m = vlib.Student(str(FT / a.model), "bi", device="cuda").eval()
    hard = []
    rows = [{**s, "context": NZ.with_phrase(s["context"], r["phrase"])} for r, s in pairs]
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        for i in range(0, len(rows), 64):
            for z in m.logits(rows[i:i + 64]):
                p = torch.softmax(z.float() / m.temperature, -1)
                hard.append(float(p[:-1].max()))
    order = sorted(range(len(pairs)), key=lambda i: -hard[i])
    per_s, per_a, out = Counter(), set(), []
    for i in order:
        r, s = pairs[i]
        if per_s[s["screen_id"]] >= a.per_screen or r["id"] in per_a:
            continue
        per_s[s["screen_id"]] += 1
        per_a.add(r["id"])
        ni = len(s["options"]) - 1
        row = {**{k: s[k] for k in ("options", "option_keys", "screen_id", "app", "package", "tag", "marks", "extract", "options_source", "split")},
               "context": NZ.with_phrase(s["context"], r["phrase"]), "label": ni, "acceptable": [ni], "kind": "none",
               "phrase": r["phrase"], "phrase_source": "swap:" + r["phrase_source"], "phrase_app": r["app"], "swap_of": r["id"],
               "confidence": "high", "id": f"aug-swap-{len(out)}", "meta": {"target": "none"}}
        out.append({"cid": f"c{len(out):04d}", "hard": round(hard[i], 4), "row": row})
        if len(out) >= a.n:
            break
    (B / "aug").mkdir(exist_ok=True)
    tag = f"_{a.round}" if a.round else ""
    for c in out:
        c["cid"] = f"{a.round}{c['cid']}"
        c["row"]["id"] = f"aug-swap{a.round}-{c['row']['id'].rsplit('-', 1)[1]}"
    (B / "aug" / f"swap_cands{tag}.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out))
    vd = B / "aug" / f"swap_verify{tag}"
    vd.mkdir(exist_ok=True)
    for j in range(0, len(out), a.batch):
        view = [{"cid": c["cid"], "phrase": c["row"]["phrase"], "app": c["row"]["context"].split("\n")[1],
                 "screen": c["row"]["context"].split("\n")[2], "marks_image": str(FT / c["row"]["marks"]) if c["row"].get("marks") else "",
                 "options": c["row"]["options"][:-1]} for c in out[j:j + a.batch]]
        (vd / f"batch_{j // a.batch:02d}.json").write_text(json.dumps(view, indent=1, ensure_ascii=False))
    print(f"{len(out)} candidates (hardness p50 {sorted(c['hard'] for c in out)[len(out) // 2]:.3f}); "
          f"val-screen candidates {sum(c['row']['split'] == 'val' for c in out)}; batches in {vd}")


if __name__ == "__main__":
    main()
