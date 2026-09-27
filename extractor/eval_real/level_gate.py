#!/usr/bin/env python3
"""Calibration v2's per-mic level gate and the whistle checks (wiki/voice-cursor.md, "Calibration v2"). Report only.

The gate (joystick_core.derive_gate / gate_reason, spec prompts/joystick_v1.json level_gate) drops a discrete sound
(pop / click / hiss, whatever the extractor labelled it) that is quieter than the person's calibrated discrete sounds:
min_snr_db = weakest - margin_snr_db and min_level_dbfs = weakest - margin_level_db over the pops, clicks and hiss
steps' examples (never under the room's transient + room_margin_db, never over weakest - 1). Without the clicks step
(the quietest gesture), and on an uncalibrated mic, level_gate.default.

  1. margins: leave-out on khoa-guided-1 (the clicks block). Simulated setups: 3 pops from distinct `pop` attempts
     (the pops step) and 3 single clicks from distinct `click` attempts (the clicks step; any discrete label,
     dur <= calib_v2.clicks.max_dur_ms). The gate from them is scored on every OTHER discrete event inside a
     clicks-block attempt (real sounds lost) and on the discrete events of the desktop negatives (noise dropped). Grid
     over the two margins, and how far below the weakest calibrated sound a held-out real one falls (the shortfall).
     The per-person click / pop rule (derive_click_pop / relabel) is scored on the same setups: relabels of held-out
     sounds from `pop` attempts (truth pop) and single / double / run click attempts (truth click).
  2. the default gate: the same real events and negatives, and the phone's round-5 event log (the newest
     android/suite/out/zflip/events-r5-*.jsonl, read only): how many of its quiet sounds (snr < 15 dB) it drops, and
     how many of its real pops (snr >= 40 dB) it loses. Also what a gate from the phone's pops step alone would do
     (not used: without a clicks step the default applies).
  3. whistles: the guided whistle rise / fall (and arch / dip) attempts with the extractor's shape thresholds scaled
     by the whistle range (the way calib_gestures.py's "excursion" candidate scales them by the voice range).

  ./run python eval_real/level_gate.py          # writes results/level_gate.{md,json}; numbers only

The recordings and the phone log are private: only aggregates go out.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval_real"))

import calib_gestures as CG  # noqa: E402
import joystick_core as J  # noqa: E402
from common import pmap  # noqa: E402
from vox_extract import Config  # noqa: E402
from vox_extract.extractor import Extractor, load_wav  # noqa: E402
from vox_extract.policy import not_deliberate  # noqa: E402

LOG_DIR = ROOT.parent / "android" / "suite" / "out" / "zflip"
RESULTS = ROOT / "results"
KEYS = ("dur_ms", "snr_db", "level_db", "lf_ratio", "peak_centroid_hz", "net_st", "excursion_st")
DISCRETE = set(J.GATE_LABELS)
QUIET_SNR = 15.0
REAL_POP_SNR = 40.0


# ============================================================================== extractor replay

def _job(j: dict) -> dict:
    x, sr = load_wav(j["wav"])
    ex = Extractor(Config.from_dict({**json.loads(Config().to_json()), **j["over"]}), input_rate=sr)
    ev = []
    for i in range(0, len(x), sr // 10):
        ev += ex.push(x[i:i + sr // 10])
    ev += ex.flush()
    return {"cfg": j["cfg"], "stream": j["stream"], "seconds": len(x) / sr,
            "events": [{"label": e.label, "t": e.t_start_ms, "emit": e.emit,
                        "delib": not not_deliberate(e.label, e.text), **{k: e.raw.get(k) for k in KEYS}} for e in ev]}


def replay(workers: int, scale: float | None) -> dict:
    jobs = [{"cfg": "default", "over": {}, "stream": "guided", "wav": str(CG.GUIDED / "run-01" / "session.wav")}]
    jobs += [{"cfg": "default", "over": {}, "stream": k, "wav": str(p)} for k, (p, _) in CG.NEGATIVES.items() if p.exists()]
    for name, s in (("whistle_range", scale), ("half", 0.5)):
        if s:
            d = Config()
            over = {k: round(getattr(d, k) * s, 3) for k in ("flat_max_range_st", "shape_min_st", "exc_medium_st", "exc_large_st")}
            jobs.append({"cfg": name, "over": over, "stream": "guided", "wav": str(CG.GUIDED / "run-01" / "session.wav")})
    out: dict = {}
    for r in pmap(_job, jobs, workers=workers, chunksize=1):
        out.setdefault(r["cfg"], {})[r["stream"]] = r
    return out


# ============================================================================== the guided sounds

def guided_sounds(ev: list[dict]) -> tuple[list[dict], dict]:
    """Every emitted discrete event inside a clicks-block attempt (the real sounds), each with its attempt's kind and
    id; and per attempt kind the list of attempt ids."""
    pos, _ = CG.guided_takes()
    real, att = [], {}
    for t in pos:
        if t["kind"].startswith("whistle"):
            continue
        att.setdefault(t["kind"], []).append(t["id"])
        for e in ev:
            if e["emit"] and e["label"] in DISCRETE and t["win"][0] <= e["t"] <= t["win"][1]:
                real.append({**e, "kind": t["kind"], "att": t["id"]})
    return real, att


def by_label(exs: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in exs:
        out.setdefault(e["label"], []).append(e)
    return out


def dropped(gate: dict, evs: list[dict], offset: float = 0.0) -> int:
    return sum(J.gate_reason(gate, e["label"], e["snr_db"], e["level_db"], offset) is not None for e in evs)


def setups(real: list[dict], spec: dict, n: int, seed: int = 1) -> list[tuple[list[dict], list[dict]]]:
    """n simulated pops + clicks steps: 3 pops from distinct pop attempts, 3 clicks from distinct single-click
    attempts (one event each, the first discrete one within max_dur_ms)."""
    mx = spec["calib_v2"]["clicks"]["max_dur_ms"]
    first = {}
    for e in real:
        if e["kind"] == "pop" or (e["kind"] == "click" and e["dur_ms"] <= mx):
            first.setdefault((e["kind"], e["att"]), e)
    pops = [e for (k, _), e in first.items() if k == "pop"]
    clicks = [e for (k, _), e in first.items() if k == "click"]
    rng = np.random.default_rng(seed)
    combos = [(list(p), list(c)) for p in itertools.combinations(pops, 3) for c in itertools.combinations(clicks, 3)]
    idx = rng.choice(len(combos), size=min(n, len(combos)), replace=False)
    return [combos[i] for i in idx], len(pops), len(clicks)


def margin_grid(real: list[dict], noise: list[dict], spec: dict, n: int) -> dict:
    sims, n_pop, n_click = setups(real, spec, n)
    grid = {}
    for ms in (0, 2, 4, 6, 8, 10, 12, 15):
        for ml in (0, 2, 4, 6, 8, 10, 12, 15):
            sp = json.loads(json.dumps(spec))
            sp["level_gate"].update(margin_snr_db=float(ms), margin_level_db=float(ml))
            lost = held = nd = 0
            worst = 0
            for p, c in sims:
                g = J.derive_gate({"pops": p, "clicks": c}, None, sp)
                used = {id(e) for e in p + c}
                rest = [e for e in real if id(e) not in used]
                k = dropped(g, rest)
                lost += k; held += len(rest); worst = max(worst, k)
                nd += dropped(g, noise)
            grid[f"{ms}/{ml}"] = {"margin_snr_db": ms, "margin_level_db": ml, "real_lost_pct": round(100 * lost / held, 2),
                                  "real_lost_worst": worst, "noise_dropped_pct": round(100 * nd / (len(sims) * max(1, len(noise))), 1)}
    short_s, short_l = [], []
    rel = {"right": 0, "wrong": 0, "rules": 0, "by": {}}
    truth = {"pop": "pop", "click": "click", "click_click": "click", "click_run": "click"}
    for p, c in sims:
        ws, wl = min(e["snr_db"] for e in p + c), min(e["level_db"] for e in p + c)
        used = {id(e) for e in p + c}
        rest = [e for e in real if id(e) not in used]
        short_s += [ws - e["snr_db"] for e in rest]
        short_l += [wl - e["level_db"] for e in rest]
        rule = J.derive_click_pop(p, c, spec)
        rel["rules"] += rule is not None
        for e in rest:
            r = J.relabel(rule, e["label"], e)
            if r and e["kind"] in truth:
                ok = r["to"] == truth[e["kind"]]
                rel["right" if ok else "wrong"] += 1
                k = f"{e['kind']}: {r['from']}->{r['to']}"
                rel["by"][k] = rel["by"].get(k, 0) + 1
    pct = lambda v: [round(float(x), 1) for x in np.percentile(v, [90, 95, 99, 100])]  # noqa: E731
    return {"setups": len(sims), "pop_attempts": n_pop, "click_attempts": n_click, "grid": grid,
            "shortfall_snr_db_p90_p95_p99_max": pct(short_s), "shortfall_level_db_p90_p95_p99_max": pct(short_l),
            "relabel": rel}


# ============================================================================== the phone log

def phone_log(spec: dict) -> dict:
    logs = sorted(LOG_DIR.glob("events-r5-*.jsonl"))
    if not logs:
        return {"log": None}
    path = logs[-1]
    ms, calib = [], []
    for line in path.read_text().splitlines():
        e = json.loads(line)
        if e.get("ev") == "calib":
            calib.append(e)
        elif e.get("ev") == "mic_sound" and e.get("source") == "phone-mic" and e.get("gate"):
            g = e["gate"]
            ms.append({"t": e["t"], "label": e["label"], "snr_db": g.get("snr_db"), "level_db": g.get("level_db"),
                       "dur_ms": g.get("dur_ms"), "dropped": e.get("dropped")})
    save = next((c["t"] for c in calib if c.get("event") == "save"), None)
    p0 = next((c["t"] for c in calib if c.get("event") == "step" and c.get("step") == "pops"), None)
    p1 = next((c["t"] for c in calib if p0 and c["t"] > p0 and not (c.get("step") == "pops")), save)
    live = [e for e in ms if e["dropped"] != "calibrating" and e["label"] in DISCRETE]
    after = [e for e in live if save and e["t"] > save]
    cal_pops = sorted([e for e in ms if e["dropped"] == "calibrating" and e["label"] == "pop" and p0 and p0 <= e["t"] <= p1],
                      key=lambda e: -e["snr_db"])[:3]
    gates = {"default": J.default_gate(spec),
             "pops_only_not_used": J.derive_gate({"pops": cal_pops, "clicks": cal_pops}, None, spec)}

    def tally(evs: list[dict], g: dict) -> dict:
        quiet = [e for e in evs if e["snr_db"] < QUIET_SNR]
        mid = [e for e in evs if QUIET_SNR <= e["snr_db"] < REAL_POP_SNR]
        real = [e for e in evs if e["label"] == "pop" and e["snr_db"] >= REAL_POP_SNR]
        per = {lab: {"n": sum(e["label"] == lab for e in quiet), "dropped": dropped(g, [e for e in quiet if e["label"] == lab])}
               for lab in J.GATE_LABELS}
        return {"sounds": len(evs), "quiet_n": len(quiet), "quiet_dropped": dropped(g, quiet), "quiet_by_label": per,
                "mid_n": len(mid), "mid_dropped": dropped(g, mid), "real_pops_n": len(real), "real_pops_lost": dropped(g, real),
                "all_dropped": dropped(g, evs)}

    lv = sorted(e["level_db"] for e in live)
    sn = sorted(e["snr_db"] for e in live)
    return {"log": path.name, "calib_pops": [{"snr_db": e["snr_db"], "level_db": e["level_db"]} for e in cal_pops],
            "gates": gates,
            "live_level_dbfs_p10_p50_p90": [round(float(np.percentile(lv, q)), 1) for q in (10, 50, 90)] if lv else None,
            "live_snr_db_p10_p50_p90": [round(float(np.percentile(sn, q)), 1) for q in (10, 50, 90)] if sn else None,
            "whole_log": {k: tally(live, g) for k, g in gates.items()},
            "after_calibration": {k: tally(after, g) for k, g in gates.items()}}


# ============================================================================== whistles

def whistle_range(workers: int) -> dict:
    """The user's quiet guided whistles through the joystick's tick analyser at the whistle ceiling
    (calib_v2.whistle.tick_f0_max_hz): p5 / p50 / p95 of the voiced ticks (st), as the whistle step would take them."""
    from vox_extract.resample import to_16k
    spec = J.load_spec()
    J.V.A["f0_max_hz"] = spec["calib_v2"]["whistle"]["tick_f0_max_hz"]
    x, sr = load_wav(CG.GUIDED / "run-01" / "session.wav")
    pos, _ = CG.guided_takes()
    wins = [t["win"] for t in pos if t["kind"].startswith("whistle_") and t["cond"] == "quiet"]
    st = []
    for w0, w1 in wins:
        seg = to_16k(x[int(w0 * sr / 1000):int(w1 * sr / 1000)], sr).astype(np.float64)
        an = J.Analyzer(spec)
        an.push(np.zeros(16000))                      # a second of silence first: the floor
        for tk in an.push(seg):
            if tk.voiced:
                st.append(float(J.V.st(tk.f0)))
    J.load_spec()                                      # the voice ceiling back
    v = np.array(st)
    return {"ticks": int(v.size), "p5_st": round(float(np.percentile(v, 5)), 2), "p50_st": round(float(np.median(v)), 2),
            "p95_st": round(float(np.percentile(v, 95)), 2),
            "p5_hz": round(55 * 2 ** (np.percentile(v, 5) / 12)), "p95_hz": round(55 * 2 ** (np.percentile(v, 95) / 12)),
            "max_hz": round(55 * 2 ** (v.max() / 12))}


def whistle_scores(run: dict) -> dict:
    pos, _ = CG.guided_takes()
    wh = [t for t in pos if t["kind"].startswith("whistle_")]
    out = {}
    for cfg, streams in run.items():
        ev = streams["guided"]["events"]
        per = {}
        for t in wh:
            got = [e for e in ev if e["emit"] and e["delib"] and t["win"][0] <= e["t"] <= t["win"][1]
                   and e["label"] in CG.GESTURES]
            k = t["kind"] + ("" if t["cond"] == "quiet" else " (video)")
            d = per.setdefault(k, {"n": 0, "right": 0, "missed": 0, "flat": 0, "net_st": []})
            d["n"] += 1
            labs = [e["label"] for e in got]
            d["right"] += labs == t["exp"]
            d["missed"] += not labs
            d["flat"] += "flat" in labs
            d["net_st"] += [round(float(e["net_st"]), 2) for e in got if e.get("net_st") is not None]
        out[cfg] = per
    return out


# ============================================================================== report

def evaluate(workers: int, n_sims: int) -> dict:
    spec = J.load_spec()
    wr = whistle_range(workers)
    scale = float(np.clip((wr["p95_st"] - wr["p5_st"]) / CG.REF_SPAN_ST, 0.5, 1.5))
    run = replay(workers, scale)
    base = run["default"]
    real, att = guided_sounds(base["guided"]["events"])
    noise, minutes = [], 0.0
    for k, r in base.items():
        if k != "guided":
            noise += [e for e in r["events"] if e["emit"] and e["label"] in DISCRETE]
            minutes += r["seconds"] / 60
    g0 = J.default_gate(spec)
    cur = J.derive_gate({}, None, spec)
    grid = margin_grid(real, noise, spec, n_sims)
    chosen = f"{int(spec['level_gate']['margin_snr_db'])}/{int(spec['level_gate']['margin_level_db'])}"
    lost_default = [e for e in real if J.gate_reason(g0, e["label"], e["snr_db"], e["level_db"])]
    return {
        "spec_level_gate": {k: v for k, v in spec["level_gate"].items() if k != "note"},
        "guided": {"real_sounds": len(real), "by_label": {lab: sum(e["label"] == lab for e in real) for lab in J.GATE_LABELS},
                   "attempts": {k: len(v) for k, v in att.items()},
                   "snr_db_min_by_kind": {k: round(float(min(e["snr_db"] for e in real if e["kind"] == k)), 1)
                                          for k in sorted({e["kind"] for e in real})},
                   "level_dbfs_min_by_kind": {k: round(float(min(e["level_db"] for e in real if e["kind"] == k)), 1)
                                              for k in sorted({e["kind"] for e in real})},
                   "default_gate_lost": len(lost_default),
                   "default_gate_lost_detail": [{"kind": e["kind"], "label": e["label"], "snr_db": round(float(e["snr_db"]), 1),
                                                 "level_db": round(e["level_db"], 1), "dur_ms": e["dur_ms"]} for e in lost_default]},
        "negatives": {"discrete_events": len(noise), "minutes": round(minutes, 1),
                      "default_gate_dropped": dropped(cur, noise)},
        "margins": grid, "chosen_margins": chosen, "chosen": grid["grid"].get(chosen),
        "phone": phone_log(spec),
        "whistle": {"range": wr, "scale": round(scale, 3), "scores": whistle_scores(run)},
    }


def report(o: dict) -> str:
    g, p, w = o["guided"], o["phone"], o["whistle"]
    L = ["# Level gate and whistle checks (level_gate.py)", "",
         "Generated by `eval_real/level_gate.py`; aggregates only. See wiki/voice-cursor.md, \"Calibration v2\".", "",
         "## Spec", "", "```", json.dumps(o["spec_level_gate"]), "```", "",
         "## Guided real sounds (khoa-guided-1, clicks block)", "",
         f"{g['real_sounds']} discrete events inside {sum(g['attempts'].values())} attempts; by label {g['by_label']}.",
         f"Weakest SNR by attempt kind: {g['snr_db_min_by_kind']}.",
         f"Weakest level (dBFS) by attempt kind: {g['level_dbfs_min_by_kind']}.", "",
         f"**Default gate (uncalibrated mic): {g['default_gate_lost']} of {g['real_sounds']} real sounds lost.** "
         f"{g['default_gate_lost_detail']}", "",
         f"Desktop negatives: {o['negatives']['discrete_events']} discrete events in {o['negatives']['minutes']} min; "
         f"the default gate drops {o['negatives']['default_gate_dropped']}.", "",
         f"## Margins (leave-out, {o['margins']['setups']} simulated setups from {o['margins']['pop_attempts']} pop and "
         f"{o['margins']['click_attempts']} single-click attempts)", "",
         f"Held-out real sounds below the weakest calibrated one (dB, p90 / p95 / p99 / max): SNR "
         f"{o['margins']['shortfall_snr_db_p90_p95_p99_max']}, level {o['margins']['shortfall_level_db_p90_p95_p99_max']}.",
         f"Click / pop rule on the same setups: {o['margins']['relabel']}.", "",
         "| margin snr / level (dB) | real lost % | worst setup (sounds) | desktop noise dropped % |", "|---|---|---|---|"]
    for k, r in o["margins"]["grid"].items():
        mark = " **(chosen)**" if k == o["chosen_margins"] else ""
        L.append(f"| {k}{mark} | {r['real_lost_pct']} | {r['real_lost_worst']} | {r['noise_dropped_pct']} |")
    L += ["", f"## Phone log ({p.get('log')}, read only)", ""]
    if p.get("log"):
        L += [f"Live discrete sounds: level p10/p50/p90 {p['live_level_dbfs_p10_p50_p90']} dBFS, SNR "
              f"{p['live_snr_db_p10_p50_p90']} dB. The phone's pops step: {p['calib_pops']}.", "",
              "| gate | span | sounds | quiet (< 15 dB) | quiet dropped | 15-40 dB | 15-40 dropped | real pops (>= 40 dB) | real pops lost |",
              "|---|---|---|---|---|---|---|---|---|"]
        for span in ("whole_log", "after_calibration"):
            for k, t in p[span].items():
                L.append(f"| {k} | {span} | {t['sounds']} | {t['quiet_n']} | {t['quiet_dropped']} | {t['mid_n']} | "
                         f"{t['mid_dropped']} | {t['real_pops_n']} | {t['real_pops_lost']} |")
        L += ["", f"Gates: {json.dumps(p['gates'])}", ""]
    L += ["## Whistles", "",
          f"Tick analyser at the whistle ceiling on the quiet guided whistles: {w['range']}. Shape thresholds x "
          f"{w['scale']} (whistle range / 12 st, as calib_gestures' voice-range 'excursion' candidate), and x 0.5.", "",
          "| config | kind | n | right | missed | has flat |", "|---|---|---|---|---|---|"]
    for cfg, per in w["scores"].items():
        for k, d in sorted(per.items()):
            L.append(f"| {cfg} | {k} | {d['n']} | {d['right']} | {d['missed']} | {d['flat']} |")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--sims", type=int, default=400)
    a = ap.parse_args()
    o = evaluate(a.workers, a.sims)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "level_gate.json").write_text(json.dumps(o, indent=1))
    (RESULTS / "level_gate.md").write_text(report(o))
    print(report(o))


if __name__ == "__main__":
    main()
