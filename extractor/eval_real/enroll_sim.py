#!/usr/bin/env python3
"""Feasibility of phone-side personalization: simulated enrollment + the android Matcher, on real audio.

  ./run python eval_real/enroll_sim.py --tag tuned        # -> results/real_enroll_sim.md

Input: results/real_features_<tag>_clips.jsonl (features.py export + live; rows need fp / pitch16, i.e. a run made
with the fp1 code). Only emitted sounds (the ones a phone would receive) take part, and only the clean
condition (no added noise).

The matcher is vox_extract.personal (a mirror of android Personal.kt), re-implemented here with numpy for speed and
checked against it on a sample at start-up. For every store: standardise by the mean / population std of all its
examples (std raised to a per-feature floor where one is given, as the app does), nearest example picks the class,
reject if the distance > (leave-one-out within-class distance, at every class size) x mult. Five examples are run
four ways: no floor, the extractor's `within` scale as the floor, its published floor (0.25 x population) and the
app's shipped floor table.

Scenarios (every draw enrolls ENROLL examples per class, picked at random from that source; R draws each):
  A. per speaker, datasets (speaker-held-out: enrollment and test sounds come from the same speaker, disjoint):
     - MLEnd: a custom class from the speaker's hums, another from their whistles (both in one store).
       Accept = held-out sounds of the same class matched to it; cross = matched to the speaker's other class.
     - Deeply Nonverbal: the speaker's tongue clicks (gesture click) and lip pops (gesture pop), plus, as a
       custom class, their lip smacks. Own negatives = that speaker's coughs, laughs, sighs ... (other classes).
     - ESC-50 cat: an ignore class from one recording (src_file) with enough meows.
  B. the user's live recordings: custom "meow" (105946), ignore "yell" (110107), gesture click (the click
     sessions), custom "whistle"; the user's hums are NOT enrolled and must stay unmatched (a hum captured by a
     custom class would lose its gesture).
  False accepts of every store on the NEGATIVE sets (other people): MUSAN speech / music / noise, Nonspeech7k,
  ESC-50 (all classes), Deeply Nonverbal negatives: matched sounds per minute of audio (clean, emitted only).
  Also reported: other people's hums / whistles / sung notes (MLEnd, QBSH) captured by a custom class.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from vox_extract import personal as P  # noqa: E402

RUNS = C.CACHE / "runs"
MULTS = (1.3, 1.4, 1.5)
NEG_SETS = ("musan", "nonspeech7k", "esc50", "nonverbal")
NV_POS = {"click", "pop", "smack"}


# ------------------------------------------------------------------------------ vectorised matcher

class Store:
    """numpy version of personal.Matcher for many queries at once (no contour classes: see match_all)."""

    def __init__(self, classes: list[tuple[str, str, np.ndarray, list]], std_floor: np.ndarray | None = None) -> None:
        # classes: (kind, name, fp matrix k x d, pitch16 list)
        self.classes = classes
        allx = np.vstack([c[2] for c in classes])
        self.mean = allx.mean(0)
        sd = allx.std(0)
        if std_floor is not None:
            sd = np.maximum(sd, std_floor)
        self.std = np.where(sd < 1e-9, 1.0, sd)
        self.z = [(c[2] - self.mean) / self.std for c in classes]
        self.base = []
        for c, z in zip(classes, self.z):
            d = np.sqrt(((z[:, None, :] - z[None, :, :]) ** 2).sum(-1))
            np.fill_diagonal(d, np.inf)
            self.base.append(float(d.min(1).max()))     # leave-one-out at every class size (app rule)
        self.contour = [c[0] == "gesture" and c[1] in P.CONTOUR_GESTURES for c in classes]
        if any(self.contour):
            self.dtw_base = [P.within_class(c[3], P.dtw) if ct else None for c, ct in zip(classes, self.contour)]

    def match_all(self, X: np.ndarray, pitch: list, mult: float) -> tuple[np.ndarray, np.ndarray]:
        """Returns (accepted class index or -1, nearest class index) per query row."""
        Q = (X - self.mean) / self.std
        best_d = np.full(len(Q), np.inf)
        best_c = np.full(len(Q), -1)
        pitched = np.array([len(p) == 16 for p in pitch]) if pitch is not None else np.zeros(len(Q), bool)
        for ci, z in enumerate(self.z):
            d = np.sqrt(((Q[:, None, :] - z[None, :, :]) ** 2).sum(-1)).min(1)
            if self.contour[ci]:
                d = np.where(pitched, d, np.inf)
            upd = d < best_d
            best_d[upd], best_c[upd] = d[upd], ci
        thr = np.array([b * mult for b in self.base])
        ok = (best_c >= 0) & (best_d <= thr[np.maximum(best_c, 0)])
        acc = np.where(ok, best_c, -1)
        for i in np.flatnonzero(ok):
            ci = best_c[i]
            if self.contour[ci]:
                dd = min(P.dtw(pitch[i], p) for p in self.classes[ci][3])
                if dd > self.dtw_base[ci] * mult:
                    acc[i] = -1
        return acc, best_c


def self_check(rows: list[dict]) -> None:
    """The numpy Store must agree with personal.Matcher."""
    rng = random.Random(0)
    sample = rng.sample(rows, min(400, len(rows)))
    cls = []
    for k, name in enumerate(("a", "b", "c")):
        ex = sample[k * 5:(k + 1) * 5]
        cls.append(("custom", name, np.array([r["fp"] for r in ex]), [r["pitch16"] for r in ex]))
    st = Store(cls)
    ref = P.Matcher([P.EnrollClass(k, n, [{"fp": list(map(float, x)), "pitch16": p} for x, p in zip(X, Pp)]) for k, n, X, Pp in cls], 1.4)
    fl = [0.5] * len(sample[0]["fp"])
    st_f = Store(cls, np.array(fl))
    ref_f = P.Matcher([P.EnrollClass(k, n, [{"fp": list(map(float, x)), "pitch16": p} for x, p in zip(X, Pp)]) for k, n, X, Pp in cls], 1.4, fl)
    acc_f, _ = st_f.match_all(np.array([r["fp"] for r in sample[15:]]), [r["pitch16"] for r in sample[15:]], 1.4)
    for r, a in zip(sample[15:], acc_f):
        m = ref_f.match(r["fp"], r["pitch16"])
        assert (m.cls or None) == (cls[a][1] if a >= 0 else None), (m, a)
    q = sample[15:]
    acc, _ = st.match_all(np.array([r["fp"] for r in q]), [r["pitch16"] for r in q], 1.4)
    for r, a in zip(q, acc):
        m = ref.match(r["fp"], r["pitch16"])
        assert (m.cls or None) == (cls[a][1] if a >= 0 else None), (m, a)


# ------------------------------------------------------------------------------ data

def load_rows(tag: str) -> list[dict]:
    rows = []
    for l in (C.RESULTS / f"real_features_{tag}_clips.jsonl").open():
        r = json.loads(l)
        if not r.get("fp") or r.get("gate") == "unmatched" or r.get("snr", "clean") != "clean":
            continue
        r["pitch16"] = r.get("pitch16") or []
        rows.append(r)
    return rows


def minutes(tag: str) -> dict[str, float]:
    """Clean audio minutes per negative set (the same dur_s the dataset reports use)."""
    out: dict[str, float] = defaultdict(float)
    for ds in NEG_SETS:
        p = RUNS / tag / f"{ds}_test.jsonl"
        if not p.exists():
            continue
        for rec in C.read_jsonl(p):
            if rec.get("snr", "clean") != "clean":
                continue
            if ds == "nonverbal" and rec.get("role") not in ("neg", "other"):
                continue
            out[ds] += rec["dur_s"] / 60
    return dict(out)


def neg_pool(rows: list[dict]) -> dict[str, list[dict]]:
    pool: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["split"] != "test":
            continue
        ds = r["dataset"]
        if ds == "nonverbal" and r["group"] in NV_POS:
            continue
        if ds in NEG_SETS:
            pool[ds].append(r)
        elif ds in ("mlend", "qbsh_contour"):
            pool["others' " + ("sung" if ds == "qbsh_contour" else r["group"])].append(r)
    return pool


# ------------------------------------------------------------------------------ scenarios

def draw_store(rng, spec: list[tuple[str, str, list[dict]]], n_enroll: int, std_floor=None):
    """spec: (kind, name, candidate rows). Returns (Store, held-out rows per class) or None."""
    classes, held = [], []
    for kind, name, cand in spec:
        if len(cand) < n_enroll + 1:
            return None
        idx = list(range(len(cand)))
        rng.shuffle(idx)
        ex = [cand[i] for i in idx[:n_enroll]]
        classes.append((kind, name, np.array([r["fp"] for r in ex], float), [r["pitch16"] for r in ex]))
        held.append([cand[i] for i in idx[n_enroll:]])
    return Store(classes, std_floor), held


class Tally:
    def __init__(self) -> None:
        self.acc = defaultdict(lambda: [0, 0])      # (class kind/name, mult) -> [accepted, total] held-out
        self.cross = defaultdict(lambda: [0, 0])    # held-out captured by ANOTHER enrolled class
        self.own_neg = defaultdict(lambda: [0, 0])  # the same speaker's non-enrolled sounds captured
        self.neg = defaultdict(float)               # (enrolled class, neg set, mult) -> matched count (summed over stores)
        self.stores = defaultdict(int)              # enrolled class -> number of stores (to average)
        self.store_hit = defaultdict(int)           # (class, set, mult) -> stores with >= 1 negative capture


def run_store(t: Tally, key_of, store: Store, held: list[list[dict]], own_neg: list[dict], pools, mults):
    names = [key_of(c) for c in store.classes]
    for n in names:
        t.stores[n] += 1
    for ci, rows in enumerate(held):
        if not rows:
            continue
        X = np.array([r["fp"] for r in rows], float)
        for m in mults:
            acc, _ = store.match_all(X, [r["pitch16"] for r in rows], m)
            t.acc[(names[ci], m)][0] += int(np.sum(acc == ci))
            t.acc[(names[ci], m)][1] += len(rows)
            t.cross[(names[ci], m)][0] += int(np.sum((acc >= 0) & (acc != ci)))
            t.cross[(names[ci], m)][1] += len(rows)
    if own_neg:
        X = np.array([r["fp"] for r in own_neg], float)
        for m in mults:
            acc, _ = store.match_all(X, [r["pitch16"] for r in own_neg], m)
            for ci in range(len(names)):
                t.own_neg[(names[ci], m)][0] += int(np.sum(acc == ci))
                t.own_neg[(names[ci], m)][1] += len(own_neg)
    for ds, (X, pitch) in pools.items():
        for m in mults:
            acc, _ = store.match_all(X, pitch, m)
            for ci in range(len(names)):
                k = int(np.sum(acc == ci))
                t.neg[(names[ci], ds, m)] += k
                t.store_hit[(names[ci], ds, m)] += int(k > 0)


def by(rows, *keys):
    d = defaultdict(list)
    for r in rows:
        d[tuple(r[k] for k in keys)].append(r)
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="tuned")
    ap.add_argument("--enroll", type=int, nargs="*", default=[5, 3, 10])
    ap.add_argument("--scales", default=str(C.RESULTS / "fp1_scales.json"),
                    help="the extractor's per-feature scales (fp_scales.py); 5 examples are also run with floor = within")
    ap.add_argument("--app-floors", default=str(C.ROOT.parent / "android" / "app" / "src" / "main" / "assets" / "fp_floors.json"),
                    help="the app's floor table (read only); 5 examples are also run with it")
    ap.add_argument("--draws", type=int, default=3)
    ap.add_argument("--max-speakers", type=int, default=60, help="per dataset scenario (random subset of eligible speakers)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = load_rows(a.tag)
    self_check(rows)
    mins = minutes(a.tag)
    pool_rows = neg_pool(rows)
    pools = {ds: (np.array([r["fp"] for r in rs], float), [r["pitch16"] for r in rs]) for ds, rs in pool_rows.items()}
    rng = random.Random(7)
    L = [f"# Enrollment feasibility (fp1 + android Matcher), REAL audio, config `{a.tag}`\n",
         "```", __doc__.strip(), "```\n",
         f"Emitted clean sounds with an fp: {len(rows)}. Negative pools (test split, other people): " +
         ", ".join(f"{k} {len(v)} sounds" + (f" / {mins[k]:.0f} min" if k in mins else "") for k, v in pool_rows.items()) + ".\n"]

    floors = []    # (description, vector)
    if Path(a.scales).exists():
        e = json.loads(Path(a.scales).read_text())["fp1"]
        floors.append(("std floor = the extractor's `within` scale (results/fp1_scales.json `within`)", np.array(e["within"], float)))
        floors.append(("std floor = the extractor's published floor, 0.25 x population (results/fp1_scales.json `floor`)",
                       np.array(e["floor"], float)))
    fl = P.load_floors(a.app_floors, "fp1")
    if fl is not None:
        e = json.loads(Path(a.app_floors).read_text())["fp1"]
        floors.append((f"std floor = the app's table (android assets/fp_floors.json, provisional={e.get('provisional')})",
                       np.array(fl, float)))
    runs = [(n, MULTS if n == 5 else (1.4,), None, None) for n in a.enroll]
    if 5 in a.enroll:
        for i, (desc, fl) in enumerate(floors):
            runs.insert(1 + i, (5, MULTS, fl, desc))
    for n_en, mults, sfl, fdesc in runs:
        t = Tally()
        # ---- MLEnd: hum + whistle custom classes per speaker
        ml = by([r for r in rows if r["dataset"] == "mlend" and r["split"] == "test"], "speaker")
        spk = [s for s, rs in ml.items() if sum(r["group"] == "hum" for r in rs) > n_en + 2 and sum(r["group"] == "whistle" for r in rs) > n_en + 2]
        rng.shuffle(spk)
        for s in spk[:a.max_speakers]:
            rs = ml[s]
            for _ in range(a.draws):
                d = draw_store(rng, [("custom", "mlend:hum", [r for r in rs if r["group"] == "hum"]),
                                     ("custom", "mlend:whistle", [r for r in rs if r["group"] == "whistle"])], n_en, sfl)
                if d:
                    run_store(t, lambda c: c[1], d[0], d[1], [], {k: v for k, v in pools.items() if not k.startswith("others' ")}, mults)
        n_ml = min(len(spk), a.max_speakers)
        # ---- Deeply Nonverbal: click + pop gestures, smack custom; own negatives = the speaker's other classes
        nv = by([r for r in rows if r["dataset"] == "nonverbal" and r["split"] == "test"], "speaker")
        n_nv = 0
        for s, rs in nv.items():
            spec = []
            for g, kind, name in (("click", "gesture", "click"), ("pop", "gesture", "pop"), ("smack", "custom", "nv:smack")):
                c = [r for r in rs if r["group"] == g]
                if len(c) > n_en + 1:
                    spec.append((kind, name, c))
            if not spec:
                continue
            n_nv += 1
            own = [r for r in rs if r["group"] not in NV_POS]
            others = {k: v for k, v in pools.items() if k != "nonverbal"}
            for _ in range(a.draws):
                d = draw_store(rng, spec, n_en, sfl)
                if d:
                    run_store(t, lambda c: "nv:" + c[1] if not c[1].startswith("nv:") else c[1], d[0], d[1], own, others, mults)
        # ---- ESC-50 cat: an ignore class per recording
        cat = by([r for r in rows if r["dataset"] == "esc50" and r["group"] == "cat"], "speaker")
        n_cat = 0
        for s, rs in cat.items():
            if len(rs) <= n_en + 1:
                continue
            n_cat += 1
            others = {k: v for k, v in pools.items() if k != "esc50"}
            for _ in range(a.draws):
                d = draw_store(rng, [("ignore", "esc50:cat", rs)], n_en, sfl)
                if d:
                    run_store(t, lambda c: c[1], d[0], d[1], [], others, mults)
        # ---- live: meow custom, yell ignore, click gesture, whistle custom; hums must stay unmatched
        live = [r for r in rows if r["dataset"] == "live"]
        lg = by(live, "group")
        spec = [(k, n, lg.get((g,), [])) for g, k, n in (("meow", "custom", "live:meow"), ("yell", "ignore", "live:yell"),
                                                         ("click", "gesture", "click"), ("whistle", "custom", "live:whistle"))]
        spec = [s for s in spec if len(s[2]) > n_en]
        hums = lg.get(("hum",), [])
        live_pools = {k: v for k, v in pools.items()}
        for _ in range(a.draws * 10):
            d = draw_store(rng, spec, n_en, sfl)
            if d:
                run_store(t, lambda c: c[1] if c[1] != "click" else "live:click", d[0], d[1], hums, live_pools, mults)

        L.append(f"## {n_en} enrollment examples per class, " + (fdesc if sfl is not None else "no std floor")
                 + ("  (baseline)" if n_en == 5 and sfl is None else "") + "\n")
        L.append(f"Stores: MLEnd {n_ml} speakers, Deeply Nonverbal {n_nv} speakers, ESC-50 cat {n_cat} recordings, "
                 f"live {a.draws * 10} draws; {a.draws} draws per speaker. Live classes: " +
                 ", ".join(f"{n} ({len(c)} sounds)" for _, n, c in spec) + f"; live hums (not enrolled) {len(hums)}.\n")
        hdr = ["enrolled class", "x mult", "accept (held-out, same class)", "captured by another enrolled class",
               "own non-enrolled sounds captured"]
        body = []
        for (name, m), (k, n) in sorted(t.acc.items()):
            cr = t.cross[(name, m)]
            on = t.own_neg.get((name, m))
            body.append([name, m, f"{C.pct(k / n)} % ({k}/{n})", f"{C.pct(cr[0] / cr[1])} %",
                         f"{C.pct(on[0] / on[1])} % ({on[0]}/{on[1]})" if on and on[1] else "-"])
        L.append(C.md_table(hdr, body))
        L.append("\n\"own non-enrolled sounds\": Deeply Nonverbal = the same speaker's coughs, laughs, sighs, ...; live = the "
                 "user's hums (gestures), which must stay unmatched.\n")
        sets = [k for k in pools if not k.startswith("others' ")]
        oth = [k for k in pools if k.startswith("others' ")]
        L.append("### False accepts on other people's sounds, per store (mean over stores)\n")
        L.append("Matched sounds per minute of negative audio; in brackets the share of stores with at least one false "
                 "accept on that set. `others'` columns: sounds per 100 of other people's hums / whistles / sung notes "
                 "captured (MLEnd and QBSH test split; not for the MLEnd stores, whose own speaker is in that pool).\n")
        hdr = ["enrolled class", "x mult"] + [f"{s} /min" for s in sets] + [f"{s} /100" for s in oth]
        body = []
        for name in sorted(t.stores):
            for m in mults:
                ns = t.stores[name]
                row = [name, m]
                for s in sets:
                    if (name, s, m) not in t.neg:
                        row.append("-")
                        continue
                    row.append(f"{t.neg[(name, s, m)] / ns / mins.get(s, np.nan):.3f} ({C.pct(t.store_hit[(name, s, m)] / ns)} %)")
                for s in oth:
                    row.append(f"{100 * t.neg[(name, s, m)] / ns / len(pool_rows[s]):.2f}" if (name, s, m) in t.neg else "-")
                body.append(row)
        L.append(C.md_table(hdr, body))
        L.append("")
    out = Path(a.out) if a.out else C.RESULTS / "real_enroll_sim.md"
    out.write_text("\n".join(L) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
