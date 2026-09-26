#!/usr/bin/env python3
"""Offline analyses on the per-event feature export (features.py). Nothing here changes the extractor.

  ./run python eval_real/cues.py --tag frozen        # -> results/real_cues.md

1. Which cues separate hums from the voiced negatives ACROSS SPEAKERS (for fp1 and the v6 categories).
   AUC of each cue for hum vs X on two levels: events, and per-speaker medians (one point per speaker,
   so a cue that only works because one prolific speaker differs does not score). 0.5 = useless,
   1.0 / 0.0 = perfect (below 0.5 = the cue is LOWER for X). "sep" = max(AUC, 1 - AUC).
2. The brightness rule (hypothesis from the user's yells): a voiced sound with f0 < 900 Hz and
   (E1k > 0.30 or E3.5 > 0.85) would be tagged "talking" (so never an action). False rejects on hums
   that currently fire; catches (FA groups / min before -> after) on the negatives.
3. A per-user pitch-range gate (EVALUATED ONLY; the user ruled it out as the fix): calibrate on the
   first 5 hums of a speaker, reject voiced sounds whose median f0 is outside [min, max] +- margin.
4. Low-f0 hums tagged "talking": share by f0 bin and which speech cues fired.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

CONTOURS = {"rise", "fall", "arch", "dip", "flat"}
RUNS = C.CACHE / "runs"

SCALAR_CUES = ["f0_med_hz", "f0_range_st", "pitch_resid_std_st", "pitch_rough_st", "pitch_jumps_hz", "voiced_frac",
               "strong_voiced_frac", "clarity_med", "centroid_hz", "centroid_spread_oct", "flatness", "zcr", "lf_ratio",
               "hf_ratio", "e1k", "e35f0", "hnr_db", "dur_ms", "energy_iqr_db", "syllable_rate_hz", "flux_mean_db",
               "decay_db", "onset_flux_db", "peak_centroid_hz", "voiced_runs", "syllable_peaks"]


def cue_values(r: dict) -> dict:
    v = {k: r.get(k) for k in SCALAR_CUES}
    if v.get("f0_med_hz"):
        v["f0_med_hz"] = float(np.log2(v["f0_med_hz"]))  # octaves: AUC is rank-based anyway
    for i, x in enumerate(r.get("logmel8") or []):
        v[f"logmel{i}"] = x
    for i, x in enumerate(r.get("mfcc13") or []):
        v[f"mfcc{i}"] = x
    return v


def auc(a: list[float], b: list[float]) -> float | None:
    a = [x for x in a if x is not None and np.isfinite(x)]
    b = [x for x in b if x is not None and np.isfinite(x)]
    if len(a) < 3 or len(b) < 3:
        return None
    allv = np.concatenate([a, b])
    ranks = np.empty(allv.size)
    order = np.argsort(allv, kind="mergesort")
    ranks[order] = np.arange(1, allv.size + 1)
    # average ties
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, ranks)
    ranks = (sums / cnt)[inv]
    ra = ranks[: len(a)].sum()
    return float((ra - len(a) * (len(a) + 1) / 2) / (len(a) * len(b)))


def load(tag: str) -> list[dict]:
    return C.read_jsonl(C.RESULTS / f"real_features_{tag}_clips.jsonl")


def voiced(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["label"] in CONTOURS and r.get("snr", "clean") == "clean" and (r.get("dur_ms") or 0) >= 150]


def src_group(r: dict) -> str:
    g = r["group"]
    if r["dataset"] == "live":
        return "live " + g
    return g


# ------------------------------------------------------------------------------ 1. cue separability

HUM_SETS = {"hum": lambda r: r["group"] == "hum" and r["dataset"] == "mlend",
            "sung": lambda r: r["group"] == "sung"}
NEG_SETS = {"speech": lambda r: r["group"] == "speech",
            "yell": lambda r: r["group"] == "yell" and r["dataset"] != "live",
            "cat": lambda r: r["group"] == "cat",
            "crying": lambda r: r["group"] == "crying",
            "laughing": lambda r: r["group"] in ("laughing",),
            "moaning": lambda r: r["group"] == "moaning",
            "music": lambda r: r["group"] == "music",
            "whistle": lambda r: r["group"] == "whistle" and r["dataset"] == "mlend"}


def per_speaker_medians(rows: list[dict], cue: str) -> list[float]:
    by = defaultdict(list)
    for r in rows:
        v = cue_values(r).get(cue)
        if v is not None and np.isfinite(v):
            by[(r["dataset"], r["speaker"])].append(v)
    return [float(np.median(v)) for v in by.values() if v]


def separability(rows: list[dict]) -> tuple[str, dict]:
    V = voiced(rows)
    hum = [r for r in V if HUM_SETS["hum"](r)]
    cues = list(cue_values(hum[0]).keys()) if hum else []
    table = {}
    L = []
    for name, pred in NEG_SETS.items():
        neg = [r for r in V if pred(r)]
        if not neg:
            continue
        for cue in cues:
            a_ev = auc([cue_values(r).get(cue) for r in hum], [cue_values(r).get(cue) for r in neg])
            a_sp = auc(per_speaker_medians(hum, cue), per_speaker_medians(neg, cue))
            table.setdefault(cue, {})[name] = (a_ev, a_sp, len(neg), len({(r["dataset"], r["speaker"]) for r in neg}))
    # live: the user's own hums vs own meows / yells (one speaker)
    lh = [r for r in V if r["dataset"] == "live" and r["group"] == "hum"]
    for name, g in (("live meow", "meow"), ("live yell", "yell")):
        ln = [r for r in V if r["dataset"] == "live" and r["group"] == g]
        for cue in cues:
            table.setdefault(cue, {})[name] = (auc([cue_values(r).get(cue) for r in lh], [cue_values(r).get(cue) for r in ln]), None, len(ln), 1)
    cols = [c for c in list(NEG_SETS) + ["live meow", "live yell"] if any(c in t for t in table.values())]

    def sep(x):
        return None if x is None else max(x, 1 - x)

    ranked = sorted(cues, key=lambda c: -np.nanmean([sep(table[c][k][1] if table[c][k][1] is not None else table[c][k][0]) or np.nan
                                                     for k in cols if k in table[c] and k != "whistle"]))
    L.append("AUC of each cue, MLEnd hum (voiced events, >= 150 ms, as recorded) vs each voiced negative. "
             "Cell = per-speaker-median AUC (event-level AUC in brackets); live columns are one speaker, events only. "
             "Sorted by mean separation over the negatives (whistle excluded). > 0.5 = the negative has HIGHER values.\n")
    head = ["cue"] + [f"{c} (n ev / spk)" for c in cols] + ["mean sep"]
    hdr_n = {c: next((table[q][c][2:] for q in cues if c in table[q]), (0, 0)) for c in cols}
    head = ["cue"] + [f"{c} ({hdr_n[c][0]}/{hdr_n[c][1]})" for c in cols] + ["mean sep"]
    rowsmd = []
    for c in ranked:
        cells = []
        seps = []
        for k in cols:
            if k not in table[c]:
                cells.append("-")
                continue
            ev, sp = table[c][k][0], table[c][k][1]
            cells.append((f"{sp:.2f} ({ev:.2f})" if sp is not None else f"({ev:.2f})") if ev is not None else "-")
            if k != "whistle":
                s = sep(sp if sp is not None else ev)
                if s is not None:
                    seps.append(s)
        rowsmd.append([c] + cells + [f"{np.mean(seps):.2f}" if seps else "-"])
    L.append(C.md_table(head, rowsmd))
    L.append(f"\nHum reference: {len(hum)} events from {len({r['speaker'] for r in hum})} MLEnd speakers; "
             f"live hums: {len(lh)} events.\n")
    return "\n".join(L), table


# ------------------------------------------------------------------------------ 2. brightness rule

def bright_hit(ev: dict, e1k_thr: float = 0.30, e35_thr: float = 0.85, f0_max: float = 900.0) -> bool:
    r = ev["raw"]
    if ev["label"] not in CONTOURS:
        return False
    f0 = r.get("f0_med_hz") or 0
    if not (0 < f0 < f0_max):
        return False
    return (r.get("e1k") or 0) > e1k_thr or (r.get("e35f0") or 0) > e35_thr


def with_rule(events: list[dict], hit) -> list[str]:
    """Group actions after re-tagging rule hits as talking (so not deliberate)."""
    from vox_extract.policy import DEFAULT_BINDINGS
    groups = C.group([{"t_start_ms": e["t0"], "t_end_ms": e["t1"], **e} for e in events])
    acts = []
    for g in groups:
        if any(e["gate"] is not None or hit(e) for e in g):
            acts.append("none")
        else:
            acts.append(DEFAULT_BINDINGS.get(tuple(e["label"] for e in g), "none"))
    return acts


NEG_DS = {"nonverbal": lambda r: r["role"] in ("neg", "other") and r["snr"] == "clean",
          "musan": lambda r: r["kind"] in ("speech", "music"),
          "nonspeech7k": lambda r: True, "esc50": lambda r: True}


def neg_class(ds: str, r: dict) -> str:
    if ds == "musan":
        return r["kind"]
    return r["cls"]


def rule_eval(tag: str, hit, title: str) -> str:
    L = [f"#### {title}\n"]
    rows = []
    for ds, pred in NEG_DS.items():
        by = defaultdict(lambda: [0.0, 0, 0])
        for split in ("test",):
            p = RUNS / tag / f"{ds}_{split}.jsonl"
            if not p.exists():
                continue
            for r in C.read_jsonl(p):
                if not pred(r):
                    continue
                for k in (neg_class(ds, r), "ALL"):
                    b = by[k]
                    b[0] += r["dur_s"] / 60
                    b[1] += sum(1 for a in r["actions"] if a != "none")
                    b[2] += sum(1 for a in with_rule(r["events"], hit) if a != "none")
        for k, (mins, before, after) in sorted(by.items(), key=lambda kv: -kv[1][1]):
            if k == "ALL" or before >= 3 or k in ("cat", "screaming", "crying", "laugh", "laughing", "moaning", "speech"):
                rows.append([ds, k, f"{mins:.1f}", f"{before / mins:.2f}", f"{after / mins:.2f}",
                             f"{100 * (before - after) / before:.0f} %" if before else "-"])
    L.append("Negatives, TEST split, FA groups per minute before -> after:\n")
    L.append(C.md_table(["dataset", "class", "min", "FA/min before", "FA/min after", "FAs removed"], rows))
    # positives: hums / whistles that fire now and would be silenced
    prow = []
    for ds, pred, name in (("mlend", lambda r: r["interp"] == "hum", "MLEnd hum recordings"),
                           ("mlend", lambda r: r["interp"] == "whistle", "MLEnd whistle recordings"),
                           ("qbsh_contour", lambda r: r["snr"] == "clean", "QBSH contour clips (as recorded)")):
        p = RUNS / tag / f"{ds}_test.jsonl"
        if not p.exists():
            continue
        fire_n = fr = 0
        spk_fire = defaultdict(lambda: [0, 0])
        for r in C.read_jsonl(p):
            if not pred(r):
                continue
            for e, f in zip(r["events"], r["fire"]):
                if f != "none":
                    fire_n += 1
                    h = hit(e)
                    fr += h
                    spk_fire[r["speaker"]][0] += 1
                    spk_fire[r["speaker"]][1] += h
        worst = sorted((b / a for a, b in spk_fire.values() if a >= 5), reverse=True)
        prow.append([name, fire_n, f"{100 * fr / max(1, fire_n):.1f} %",
                     f"{100 * np.median(worst):.0f} % / {100 * worst[len(worst) // 10]:.0f} % / {100 * worst[0]:.0f} %" if worst else "-"])
    L.append("\nPositives, TEST split: voiced events that fire their own action alone today, and the share the rule would silence "
             "(false rejects). Per speaker (>= 5 firing events): median / 90th percentile / worst.\n")
    L.append(C.md_table(["set", "firing events", "false rejects", "per speaker: median / p90 / worst"], prow))
    return "\n".join(L) + "\n"


def live_rule(rows: list[dict], hit) -> str:
    live = [r for r in rows if r["dataset"] == "live"]
    L = []
    for g in ("hum", "whistle", "talk", "meow", "yell"):
        rs = [r for r in live if r["group"] == g and r["label"] in CONTOURS]
        ev = [{"label": r["label"], "raw": r} for r in rs]
        firing = [e for e, r in zip(ev, rs) if r["fire"] != "none"]
        L.append([g, len(rs), sum(hit(e) for e in ev), len(firing), sum(hit(e) for e in firing)])
    return C.md_table(["user's recordings, voiced events", "events", "rule hits", "firing today", "firing and hit"], L)


# ------------------------------------------------------------------------------ 3. pitch-range gate

def pitch_gate(rows: list[dict], margins=(2.0, 4.0, 6.0), n_cal: int = 5) -> str:
    V = [r for r in voiced(rows) if (r.get("f0_med_hz") or 0) > 0]
    L = ["Calibration = the median f0 of a speaker's first 5 voiced events of the same kind (files in name order); "
         "a later voiced sound is rejected if its median f0 is outside [min, max] of those 5, widened by the margin.\n"]
    out = []
    for name, sel in (("MLEnd hum", lambda r: r["dataset"] == "mlend" and r["group"] == "hum"),
                      ("MLEnd whistle", lambda r: r["dataset"] == "mlend" and r["group"] == "whistle"),
                      ("QBSH sung", lambda r: r["dataset"] == "qbsh_contour")):
        by = defaultdict(list)
        for r in V:
            if sel(r):
                by[r["speaker"]].append(r)
        for m in margins:
            rej = tot = 0
            for spk, rs in by.items():
                rs = sorted(rs, key=lambda r: (r["path"], r["t0"]))
                if len(rs) <= n_cal:
                    continue
                cal = [12 * np.log2(r["f0_med_hz"]) for r in rs[:n_cal]]
                lo, hi = min(cal) - m, max(cal) + m
                for r in rs[n_cal:]:
                    s = 12 * np.log2(r["f0_med_hz"])
                    tot += 1
                    rej += not (lo <= s <= hi)
            out.append([name, f"+-{m:g} st", tot, f"{100 * rej / max(1, tot):.1f} %"])
    L.append(C.md_table(["held-out positives", "margin", "events", "false rejects"], out))
    live = [r for r in V if r["dataset"] == "live"]
    hums = sorted([r for r in live if r["group"] == "hum"], key=lambda r: (r["cls"], r["t0"]))
    if len(hums) > n_cal:
        rows2 = []
        for m in margins:
            cal = [12 * np.log2(r["f0_med_hz"]) for r in hums[:n_cal]]
            lo, hi = min(cal) - m, max(cal) + m
            for g in ("hum", "meow", "yell"):
                rs = [r for r in live if r["group"] == g] if g != "hum" else hums[n_cal:]
                rej = sum(not (lo <= 12 * np.log2(r["f0_med_hz"]) <= hi) for r in rs)
                rows2.append([f"+-{m:g} st", g, len(rs), rej])
        L.append(f"\nUser's recordings: calibrated on the first {n_cal} hums (f0 {min(r['f0_med_hz'] for r in hums[:n_cal]):.0f}-"
                 f"{max(r['f0_med_hz'] for r in hums[:n_cal]):.0f} Hz):\n")
        L.append(C.md_table(["margin", "group", "voiced events", "rejected"], rows2))
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------------ 4. low-f0 talking

def low_f0_talking(rows: list[dict]) -> str:
    V = [r for r in voiced(rows) if r["dataset"] in ("mlend", "qbsh_contour", "live") and r["group"] in ("hum", "sung")]
    bins = [0, 100, 130, 160, 200, 250, 400, 600, 5000]
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        rs = [r for r in V if lo <= (r.get("f0_med_hz") or 0) < hi]
        if not rs:
            continue
        talk = [r for r in rs if r["like"] == "talking"]
        cues = Counter(c for r in talk for c in (r.get("speech_cues") or []))
        out.append([f"{lo}-{hi} Hz", len(rs), f"{100 * len(talk) / len(rs):.1f} %",
                    ", ".join(f"{k} {100 * v / max(1, len(talk)):.0f} %" for k, v in cues.most_common())])
    return C.md_table(["median f0", "hum / sung events", "tagged talking", "cues present in those (share)"], out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="frozen")
    a = ap.parse_args()
    rows = load(a.tag)
    L = [f"# REAL audio: cue analysis ({a.tag} code)\n", "```", __doc__.strip(), "```\n"]
    L.append("## 1. Which cues separate hums from voiced negatives across speakers\n")
    md, _ = separability(rows)
    L.append(md)
    L.append("## 2. Brightness rule (hypothesis, not in the extractor)\n")
    L.append(rule_eval(a.tag, bright_hit, "E1k > 0.30 or E3.5 > 0.85, f0 < 900 Hz"))
    L.append(live_rule(rows, bright_hit))
    L.append("\nVariant without the thin E3.5 arm (E1k > 0.30 only):\n")
    L.append(rule_eval(a.tag, lambda e: bright_hit(e, e35_thr=9.9), "E1k > 0.30 only"))
    L.append(live_rule(rows, lambda e: bright_hit(e, e35_thr=9.9)))
    L.append("\n## 3. Per-user pitch-range gate (evaluated only; not the fix)\n")
    L.append(pitch_gate(rows))
    L.append("## 4. Low-f0 hums tagged \"talking\"\n")
    L.append(low_f0_talking(rows))
    out = C.RESULTS / "real_cues.md" if a.tag == "frozen" else C.RESULTS / f"real_cues_{a.tag}.md"
    out.write_text("\n".join(L) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
