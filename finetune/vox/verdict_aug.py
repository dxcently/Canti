"""Verdict none-data and augmentation sets (STEP 3.9). Every output is TRAINING-only (crossfit.py --extra / a mix's
real rows) except where noted; ids are new ("aug-..."), and each row keeps the app it belongs to so the leave-apps-out
cross-fit only uses it when that app (and, for swaps, the phrase's app) is a training app of the fold.

    python -m vox.verdict_aug pool   --build data/real-targets-v2/b2          # pool minus the HIDDEN-OPTIONS rows
    python -m vox.verdict_aug icon   --build data/real-targets-v2/b2          # icon-word hard positives (emulator)
    python -m vox.verdict_aug filler --build data/real-targets-v2/b2          # filler augmentation, every kind (emulator)
    python -m vox.verdict_aug swap   --build data/real-targets-v2/b2 --verified FILE   # Opus-verified screen-swap nones

Sources: emulator rows only (DeepSeek phrases, Opus labels). No Z Flip row is read by icon / filler / swap, so no
Z Flip text is ever re-phrased or re-labelled by anything but Opus. Outputs go under <build>/aug/ (pool: <build>/zflip/aug/,
as it contains Z Flip rows).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

from . import normalize as NZ

FT = Path(__file__).resolve().parents[1]
V1_OPT = re.compile(r"^(?P<label>.*) \((?P<role>[a-z ]+), (?P<pos>[a-z ]+)\)$")

# Icon names people use for common icon-only controls (label as the tree gives it, lower case). Only buttons / images /
# items (never list items or text fields: "Settings" as a list row is not a gear).
ICON_WORDS = {
    "more options": ["three dots", "the three dots", "the dots menu", "the vertical dots", "the kebab menu"],
    "more": ["three dots", "the dots"],
    "search": ["the magnifying glass", "magnifying glass", "the search icon", "the lens icon"],
    "navigate up": ["the back arrow", "the arrow in the corner", "the left arrow"],
    "back": ["the back arrow", "the left arrow"],
    "settings": ["the gear", "the gear icon", "the cog", "the cog wheel"],
    "share": ["the share icon", "the share arrow"],
    "close": ["the x", "the cross", "the little x"],
    "clear": ["the x", "the little x"],
    "open navigation drawer": ["the hamburger menu", "the three lines", "the hamburger"],
    "delete": ["the trash can", "the bin icon", "the garbage can"],
    "edit": ["the pencil", "the pencil icon", "the pen"],
    "new": ["the plus", "the plus button"], "add": ["the plus", "the plus button"],
    "sort by": ["the sort icon", "the arrows icon"], "sort": ["the sort icon"],
    "filter": ["the funnel", "the filter icon"],
    "refresh": ["the circular arrow", "the refresh arrow"],
    "favorite": ["the star", "the heart"], "favourite": ["the star", "the heart"],
    "play": ["the triangle", "the play triangle"], "pause": ["the two bars", "the pause bars"],
    "voice search": ["the mic", "the microphone"], "microphone": ["the mic"],
    "notifications": ["the bell", "the bell icon"],
    "download": ["the down arrow", "the download arrow"],
    "send": ["the paper plane", "the arrow to send"],
    "attach": ["the paperclip"], "camera": ["the camera icon"],
    "home": ["the house", "the house icon"],
}
# Where such a label is an icon rather than a text button (a dialog's "Close" at the bottom is text, not an x).
TOP = {"top left", "top", "top right"}
ICON_POS = {**{k: TOP for k in ("close", "clear", "navigate up", "back", "open navigation drawer")},
            **{k: TOP | {"right", "left"} for k in ("search", "more options", "more", "settings", "share", "edit", "delete", "sort by",
                                                   "sort", "filter", "refresh", "notifications", "favorite", "favourite", "home")}}
ICON_T = ["{w}", "tap {w}", "press {w}", "hit {w}", "{w} please", "I want {w}"]


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def wjl(p, rows):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return rows


def pool_rows(build: Path):
    return jl(build / "zflip" / "train_real_all.jsonl") + jl(build / "zflip" / "val_real_all.jsonl")


def is_emu(r):
    return r["screen_id"].startswith("emu") and "-zf-" not in r["id"] and "serial" not in r


def sidecar(out: Path, args, rows, inputs):
    meta = {"args": {k: v for k, v in vars(args).items() if k != "func"}, "rows": len(rows),
            "kinds": dict(Counter(r["kind"] for r in rows)), "inputs": {str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in inputs},
            "code_sha": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12],
            "out_sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k in ("rows", "kinds")}), "->", out)


def cmd_pool(a):
    b = FT / a.build
    rows = pool_rows(b)
    keep = [r for r in rows if "HIDDEN" not in r.get("label_note", "")]
    out = b / "zflip" / "aug" / "pool_nohidden.jsonl"
    wjl(out, keep)
    print(f"dropped {len(rows) - len(keep)} HIDDEN-OPTIONS rows")
    sidecar(out, a, keep, [b / "zflip" / "train_real_all.jsonl", b / "zflip" / "val_real_all.jsonl"])


def cmd_icon(a):
    b = FT / a.build
    rng = random.Random(a.seed)
    rows = [r for r in pool_rows(b) if is_emu(r)]
    by_screen = {}
    for r in rows:
        by_screen.setdefault(r["screen_id"], r)
    out = []
    for sid, r in sorted(by_screen.items()):
        parsed = [V1_OPT.match(o) for o in r["options"][:-1]]
        labels = [m["label"].lower() if m else None for m in parsed]
        for i, m in enumerate(parsed):
            if not m or labels.count(labels[i]) != 1 or m["role"] not in ("button", "image", "item"):
                continue
            words = ICON_WORDS.get(labels[i])
            if not words or m["pos"] not in ICON_POS.get(labels[i], {m["pos"]}):
                continue
            for w in rng.sample(words, min(a.per_target, len(words))):
                ph = rng.choice(ICON_T).format(w=w)
                ph = ph[0].lower() + ph[1:] if not ph.startswith("I ") else ph
                out.append({**{k: r[k] for k in ("options", "option_keys", "screen_id", "app", "package", "tag", "marks", "extract", "options_source")},
                            "context": NZ.with_phrase(r["context"], ph), "label": i, "acceptable": [i], "kind": "icon",
                            "phrase": ph, "phrase_source": "template-icon", "confidence": "high", "split": r["split"],
                            "id": f"aug-icon-{len(out)}", "meta": {"target": f"t{i}", "icon_word": w},
                            **({"option_format": r["option_format"]} if r.get("option_format") else {})})
    o = FT / a.build / "aug" / "icon_pos.jsonl"
    wjl(o, out)
    sidecar(o, a, out, [b / "zflip" / "train_real_all.jsonl", b / "zflip" / "val_real_all.jsonl"])


def cmd_filler(a):
    """Perturb the phrase (filler / heavy / restart), then apply the app's normaliser (TargetQuery.kt port): the row is
    what the model sees on the phone after normalisation. Kept only when that differs from the clean phrase."""
    b = FT / a.build
    rng = random.Random(a.seed)
    rows = [r for r in pool_rows(b) if is_emu(r) and r.get("phrase")]
    out = []
    for r in rows:
        if rng.random() >= a.frac:
            continue
        kind = rng.choice(["filler", "heavy", "restart"])
        seen = NZ.normalize_phrase(NZ.PERTURB[kind](r["phrase"], rng))
        if seen == NZ.normalize_phrase(r["phrase"]):
            continue
        out.append({**r, "context": NZ.with_phrase(r["context"], seen), "phrase": seen, "id": f"aug-fill-{r['id']}",
                    "aug_of": r["id"], "aug": kind + "+norm"})
    o = FT / a.build / "aug" / "filler.jsonl"
    wjl(o, out)
    print(f"{len(out)} of {len(rows)} emulator rows changed after perturb+normalise")
    sidecar(o, a, out, [b / "zflip" / "train_real_all.jsonl", b / "zflip" / "val_real_all.jsonl"])


def cmd_swap(a):
    """Opus-verified screen swaps -> none rows. --verified: jsonl {cid, verdict: "none"|"match"|"unsure"} for the
    candidates in <build>/aug/swap_cands.jsonl. Only "none" is kept. Rows whose screen is a val screen go to
    swap_none_val.jsonl (the ~60 hard nones for val), the rest to swap_none.jsonl."""
    b = FT / a.build
    cfiles = [Path(f) for f in a.cands] if a.cands else [b / "aug" / "swap_cands.jsonl"]
    cands = {c["cid"]: c for f in cfiles for c in jl(f)}
    assert len(cands) == sum(len(jl(f)) for f in cfiles), "duplicate candidate ids across rounds"
    ver = {v["cid"]: v for f in a.verified for v in jl(f)}
    keep = [cands[c] for c, v in ver.items() if v.get("verdict") == "none" and c in cands]
    tr = [c["row"] for c in keep if c["row"]["split"] != "val"]
    va = [c["row"] for c in keep if c["row"]["split"] == "val"]
    wjl(b / "aug" / "swap_none.jsonl", tr)
    wjl(b / "aug" / "swap_none_val.jsonl", va)
    print(f"verified {len(ver)}: {Counter(v.get('verdict') for v in ver.values())}; kept train {len(tr)}, val {len(va)}")
    sidecar(b / "aug" / "swap_none.jsonl", a, tr, [*cfiles, *map(Path, a.verified)])


# jl10 icon-word NONE rows (the mirror of `icon`): an icon phrase on a screen where no listed option can be that icon.
# Concept -> (icon phrases, label words that mean the concept may be on screen). A screen qualifies for a concept only
# if NO option label (any role) contains one of its words, and the screen has no unlabeled / generic icon-role option
# (an unnamed image could be the icon). Train screens only (val stays clean for selection), emulator only.
ICON_NONE = {
    "settings": (["the gear", "the gear icon", "the cog", "the little gear"], {"setting", "settings", "preference", "preferences", "configure", "config", "options", "gear", "cog"}),
    "search": (["the magnifying glass", "the search icon", "the little magnifier"], {"search", "find", "look", "lookup", "query", "filter"}),
    "more options": (["the three dots", "the dots menu", "the kebab menu", "the vertical dots"], {"more", "option", "options", "menu", "overflow", "action", "actions"}),
    "navigation drawer": (["the hamburger menu", "the three lines", "the hamburger"], {"navigation", "drawer", "menu", "navigate", "sidebar"}),
    "add": (["the plus sign", "the plus button", "the little plus"], {"add", "new", "create", "plus", "compose", "write", "insert"}),
    "delete": (["the trash can", "the bin icon", "the garbage can"], {"delete", "remove", "trash", "bin", "discard", "clear", "erase"}),
    "edit": (["the pencil", "the pencil icon"], {"edit", "rename", "modify", "pencil", "change", "write", "compose"}),
    "share": (["the share icon", "the share arrow"], {"share", "send", "forward", "export"}),
    "notifications": (["the bell", "the bell icon"], {"notification", "notifications", "alert", "alerts", "bell", "reminder", "reminders"}),
    "favorite": (["the star", "the heart", "the star icon"], {"favorite", "favourite", "favorites", "favourites", "star", "starred", "like", "bookmark", "bookmarks", "save", "saved", "heart", "rate"}),
    "microphone": (["the mic", "the microphone"], {"voice", "mic", "microphone", "speak", "record", "audio", "dictate"}),
    "filter": (["the funnel", "the filter icon"], {"filter", "filters", "sort", "refine"}),
    "refresh": (["the circular arrow", "the refresh arrow"], {"refresh", "reload", "sync", "update", "retry"}),
    "camera": (["the camera icon"], {"camera", "photo", "photos", "picture", "scan", "capture", "image"}),
    "download": (["the down arrow", "the download arrow"], {"download", "downloads", "offline", "save"}),
    "close": (["the x", "the little x", "the cross"], {"close", "cancel", "dismiss", "clear", "exit", "x", "done"}),
}
ICON_NONE_GENERIC = {"unlabeled", "image", "icon", "button", "media image", "channel image", "more", "menu", "options"}


def _label_words(opt: str) -> set[str]:
    m = V1_OPT.match(opt)
    lab = (m["label"] if m else opt).split(" · ")[0].lower()
    return set(re.findall(r"[a-z]+", lab))


def cmd_iconnone(a):
    b = FT / a.build
    rng = random.Random(a.seed)
    rows = [r for r in jl(b / "zflip" / "train_real_all.jsonl") if is_emu(r)]
    by_screen = {}
    for r in rows:
        by_screen.setdefault(r["screen_id"], r)
    out, skipped = [], Counter()
    for sid, r in sorted(by_screen.items()):
        parsed = [V1_OPT.match(o) for o in r["options"][:-1]]
        if any(m and m["role"] in ("button", "image", "item") and m["label"].lower() in ICON_NONE_GENERIC for m in parsed) or not all(parsed):
            skipped["unnamed icon-role option"] += 1
            continue
        words = set().union(*(_label_words(o) for o in r["options"][:-1])) if len(r["options"]) > 1 else set()
        absent = [c for c, (_, al) in ICON_NONE.items() if not (words & al)]
        if not absent:
            skipped["every concept may be present"] += 1
            continue
        for c in rng.sample(absent, min(a.per_screen, len(absent))):
            w = rng.choice(ICON_NONE[c][0])
            ph = rng.choice(ICON_T).format(w=w)
            ph = ph[0].lower() + ph[1:] if not ph.startswith("I ") else ph
            ni = len(r["options"]) - 1
            out.append({**{k: r[k] for k in ("options", "option_keys", "screen_id", "app", "package", "tag", "marks", "extract", "options_source")},
                        "context": NZ.with_phrase(r["context"], ph), "label": ni, "acceptable": [ni], "kind": "icon_none",
                        "phrase": ph, "phrase_kind": "appearance", "phrase_source": "template-icon-none", "confidence": "high",
                        "split": r["split"], "id": f"aug-iconnone-{len(out)}", "meta": {"target": "none", "icon_word": w, "concept": c},
                        **({"option_format": r["option_format"]} if r.get("option_format") else {})})
    o = FT / a.build / "aug" / "icon_none.jsonl"
    wjl(o, out)
    print(f"screens {len(by_screen)}; skipped {dict(skipped)}; rows {len(out)}; concepts {dict(Counter(x['meta']['concept'] for x in out))}")
    sidecar(o, a, out, [b / "zflip" / "train_real_all.jsonl"])


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("pool", cmd_pool), ("icon", cmd_icon), ("filler", cmd_filler), ("swap", cmd_swap), ("iconnone", cmd_iconnone)):
        s = sub.add_parser(name)
        s.add_argument("--build", default="data/real-targets-v2/b2")
        s.add_argument("--seed", type=int, default=0)
        s.set_defaults(func=fn)
        if name == "icon":
            s.add_argument("--per-target", type=int, default=1)
        if name == "iconnone":
            s.add_argument("--per-screen", type=int, default=2)
        if name == "filler":
            s.add_argument("--frac", type=float, default=0.5)
        if name == "swap":
            s.add_argument("--verified", nargs="+", required=True, help="verdict jsonl files {cid, verdict}")
            s.add_argument("--cands", nargs="*", default=None, help="candidate files (default <build>/aug/swap_cands.jsonl)")
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
