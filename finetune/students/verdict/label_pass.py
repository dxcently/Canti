"""Label-noise pass (STEP 3.11): a blind second Opus labelling of every real row, then adjudication of disagreements.

    python students/verdict/label_pass.py prep    --build data/real-targets-v2/b2      # batches for the blind pass
    python students/verdict/label_pass.py compare --build data/real-targets-v2/b2      # agreement + adjudication batches
    python students/verdict/label_pass.py apply   --build data/real-targets-v2/b2      # adjudicated label files for the next build

Rows: the held-in pool (train + val, emulator and Z Flip) and the dev-test (test_real). Never the locked test and never
the X diagnostic rows. Everything is written under <build>/zflip/label_pass/ (it contains Z Flip text: local only, Opus
only; nothing here goes to any cloud model).

Blind pass: per screen, the options (index i = box i on the marks image) and the phrases, WITHOUT the first label.
Answer per phrase: the labelling guide's format (data/real-targets-v2/emulator/labelling_guide.txt): {pid, gold, acceptable,
ambiguous, confidence, note} or {pid, drop, reason}. A second-pass drop goes to adjudication.
Agreement: the second best is in the first acceptable set AND the first gold is in the second acceptable set.
One-sided containment (only one of the two) is "partial" and also goes to adjudication.
Adjudication: the adjudicator sees both answers as A / B in random order (it does not know which is the original).
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

FT = Path(__file__).resolve().parents[2]


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def rows_of(build: Path):
    out = []
    for f in ("zflip/train_real_all.jsonl", "zflip/val_real_all.jsonl", "test_real.jsonl", "test_exact.jsonl"):
        if not (build / f).exists():
            continue
        for r in jl(build / f):
            r["_file"] = f
            out.append(r)
    return out


def idx_name(r, i):
    return "none" if i == len(r["options"]) - 1 else i


def cmd_prep(a):
    B = FT / a.build
    rows = [r for r in rows_of(B) if r["screen_id"].startswith(tuple(a.prefix))] if a.prefix else rows_of(B)
    by_s = defaultdict(list)
    for r in rows:
        by_s[r["screen_id"]].append(r)
    sids = sorted(by_s)
    random.Random(0).shuffle(sids)
    od = B / "zflip" / "label_pass"
    od.mkdir(parents=True, exist_ok=True)
    if any(od.glob("blind_*.json")):
        raise SystemExit(f"{od} already has blind batches: not overwriting")
    screens = []
    for sid in sids:
        rs = by_s[sid]
        r0 = rs[0]
        lines = r0["context"].split("\n")
        screens.append({"screen_id": sid, "app": lines[1] if len(lines) > 1 else "", "screen": lines[2] if len(lines) > 2 else "",
                        "marks_image": str(FT / r0["marks"]) if r0.get("marks") else "",
                        "options": r0["options"][:-1],
                        "phrases": [{"pid": r["meta"]["pid"], "phrase": r["phrase"]} for r in rs]})
    n = 0
    for j in range(0, len(screens), a.screens_per_batch):
        (od / f"blind_{j // a.screens_per_batch:02d}.json").write_text(json.dumps(screens[j:j + a.screens_per_batch], indent=1, ensure_ascii=False))
        n += 1
    print(f"{len(rows)} rows, {len(screens)} screens -> {n} batches in {od}")


def load_pass(od: Path, prefix: str):
    out = {}
    for f in sorted(od.glob(f"{prefix}_*.jsonl")):
        for v in jl(f):
            out[v["pid"]] = v
    return out


def norm(x, r):
    return len(r["options"]) - 1 if x == "none" else int(x)


def cmd_compare(a):
    B = FT / a.build
    od = B / "zflip" / "label_pass"
    rows = {r["meta"]["pid"]: r for r in rows_of(B)}
    p2 = load_pass(od, "pass2")
    missing = [p for p in rows if p not in p2]
    st, by_kind, by_conf, dis = Counter(), defaultdict(Counter), defaultdict(Counter), []
    for pid, r in rows.items():
        v = p2.get(pid)
        if v is None:
            continue
        acc1, gold1 = set(r["acceptable"]), r["label"]
        if v.get("drop"):
            cls, acc2, best2 = "drop2", [], None
        else:
            b2 = v.get("gold", v.get("best"))
            try:
                acc2 = {norm(x, r) for x in (v.get("acceptable") or [b2])} | {norm(b2, r)}
                best2 = norm(b2, r)
            except (ValueError, TypeError, KeyError):
                st["unparseable"] += 1
                continue
            agree = best2 in acc1 and gold1 in acc2
            cls = "agree" if agree else ("partial" if (best2 in acc1 or gold1 in acc2) else "disagree")
        st[cls] += 1
        by_kind[r["kind"]][cls] += 1
        by_conf[r.get("confidence", "high")][cls] += 1
        if cls != "agree":
            dis.append((pid, r, sorted(acc1), gold1, sorted(acc2), best2, v))
    rng = random.Random(1)
    adj = defaultdict(list)
    for pid, r, acc1, gold1, acc2, best2, v in dis:
        first = {"best": idx_name(r, gold1), "acceptable": [idx_name(r, i) for i in acc1]}
        second = ({"drop": True, "reason": v.get("reason", "")} if best2 is None else
                  {"best": idx_name(r, best2), "acceptable": [idx_name(r, i) for i in sorted(acc2)]})
        swap = rng.random() < 0.5
        A, Bn = (second, first) if swap else (first, second)
        lines = r["context"].split("\n")
        adj[r["screen_id"]].append({"pid": pid, "phrase": r["phrase"], "A": A, "B": Bn, "_a_is_first": not swap})
    items = []
    for sid, ps in sorted(adj.items()):
        r0 = next(r for r in rows.values() if r["screen_id"] == sid)
        lines = r0["context"].split("\n")
        items.append({"screen_id": sid, "app": lines[1], "screen": lines[2], "marks_image": str(FT / r0["marks"]) if r0.get("marks") else "",
                      "options": r0["options"][:-1], "phrases": [{k: v for k, v in p.items() if not k.startswith("_")} for p in ps]})
    key = {p["pid"]: p["_a_is_first"] for ps in adj.values() for p in ps}
    (od / "adjud_key.json").write_text(json.dumps(key))
    for j in range(0, len(items), a.screens_per_batch):
        (od / f"adjud_{j // a.screens_per_batch:02d}.json").write_text(json.dumps(items[j:j + a.screens_per_batch], indent=1, ensure_ascii=False))
    rep = {"rows": len(rows), "pass2": len(p2), "missing": len(missing), "classes": dict(st),
           "agree_rate": round(st["agree"] / max(1, sum(st.values())), 4),
           "by_kind": {k: dict(v) for k, v in sorted(by_kind.items())}, "by_confidence": {k: dict(v) for k, v in by_conf.items()},
           "by_file": dict(Counter(r["_file"] for _, r, *_ in dis)), "adjud_screens": len(items), "adjud_rows": len(dis)}
    (od / "compare.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


def cmd_apply(a):
    """Adjudication answers {pid, verdict: "A"|"B"|"both"|"neither", best, acceptable, drop?} -> label files in the
    build's input format (emulator: data/real-targets-v2/emulator/labels/zz_adjudicated.jsonl; Z Flip:
    data/real-targets-v2/zflip/labels_adjudicated.jsonl), only for rows whose label changes."""
    B = FT / a.build
    od = B / "zflip" / "label_pass"
    rows = {r["meta"]["pid"]: r for r in rows_of(B)}
    adj = load_pass(od, "adjud")
    emu, zf, st = [], [], Counter()
    for pid, v in adj.items():
        r = rows[pid]
        st[v.get("verdict")] += 1
        if v.get("drop"):
            new = {"pid": pid, "drop": True, "note": "label pass: " + v.get("why", "")}
        else:
            lab = lambda x: "none" if x == "none" else int(x)  # noqa: E731  (the label files' format: int index or "none")
            best = lab(v["best"])
            acc = sorted({lab(x) for x in (v.get("acceptable") or [best])} | {best}, key=lambda x: (x == "none", x if x != "none" else 0))
            old_acc = sorted((idx_name(r, i) for i in r["acceptable"]), key=lambda x: (x == "none", x if x != "none" else 0))
            if best == idx_name(r, r["label"]) and acc == old_acc:
                st["unchanged"] += 1
                continue
            new = {"pid": pid, "screen_id": r["screen_id"], "phrase": r["phrase"], "gold": best, "acceptable": acc,
                   "confidence": v.get("confidence", "med"), "note": ("label pass: " + v.get("why", "")).strip(),
                   "ambiguous": len(acc) > 1, "adjudicated": True}
        (zf if r["screen_id"].startswith("zf") else emu).append(new)
    D = FT / "data" / "real-targets-v2"
    (D / "emulator" / "labels").mkdir(exist_ok=True)
    # one file per build, so a later build's pass never overwrites an earlier one (b2 -> zz_adjudicated.jsonl)
    suffix = "" if B.name == "b2" else f"_{B.name}"
    (D / "emulator" / "labels" / f"zz_adjudicated{suffix}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in emu))
    (D / "zflip" / f"labels_adjudicated{suffix}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in zf))
    print(dict(st), f"changed: emulator {len(emu)}, zflip {len(zf)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("prep", cmd_prep), ("compare", cmd_compare), ("apply", cmd_apply)):
        s = sub.add_parser(name)
        s.add_argument("--build", default="data/real-targets-v2/b2")
        s.add_argument("--screens-per-batch", type=int, default=20)
        s.add_argument("--prefix", nargs="*", default=None, help="prep: only screens whose id starts with one of these (e.g. emu3)")
        s.set_defaults(func=fn)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
