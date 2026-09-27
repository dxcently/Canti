#!/usr/bin/env python3
"""Desktop go / no-go: does ONE per-person calibration (the joystick setup) raise gesture-label accuracy?
(wiki/calibration-gestures.md)

The joystick setup (joystick.py) saves recordings/joystick/range.json (home, range, voicing threshold), vowels.json
(vowel centres) and pops.json (lip-pop thresholds). The gesture extractor (vox_extract; the C++ mirror in
firmware/extract, fields in vx_config.h) runs on fixed defaults. This script derives Config overrides ONLY from those
three files (derive()), never from the labelled takes it scores, and replays the user's labelled recordings twice:
DEFAULT and CALIBRATED, each candidate alone, then together.

Scored
  * khoa-guided-1 (one continuous 27 min session.wav, streamed at 48 kHz exactly as it was recorded): the clicks block
    (pop, click, their pairs and runs) and the whistles block (rise / fall / arch / dip, quiet and over a video).
    The unit is one ATTEMPT (segments_auto.jsonl: a take cut at energy pauses >= 0.6 s; cut-off `flub`s left out).
    An attempt is RIGHT when the deliberate gesture labels in its window (policy.not_deliberate is None, as the phone
    acts) are exactly the expected sequence (a click run: 3 or more clicks, nothing else). Segmentation per attempt:
    missed (none), merged (fewer than expected), split (more).
  * vcursor-1 / vcursor-2 (the voice-cursor sessions): NOT gesture prompts. The closest things to hummed gestures the
    user has recorded: sung "ah" range glides LOW -> HIGH (expected: one rise) and held notes (home / range anchors,
    levels, vowels; expected: one flat). Scored on the longest voiced event: its contour label, "sounds like
    talking", and split (more than one voiced event of 100 ms or more).
  * negatives (false triggers per minute): the speech takes of khoa-guided-1 (their windows only), the quiet room
    (aec-desktop-1), media on a simulated desk / phone speaker (aec-desktop-sim-*: room, music with vocals, podcast,
    short video, gesture-like clips), and two live clips of the user meowing / yelling (live_replay.NEG_SESSIONS).
    Counted: deliberate gesture events per minute (the extractor's output, which is what the config changes) and
    app actions per minute (sequencer_sim, default bindings; PhoneGate on for the media clips).

Uncertainty: 2000 paired bootstrap resamples over takes (accuracy) and over windows / 20 s chunks (false triggers).
n is small (87 gesture attempts, 5-13 per kind): a single attempt moves a kind's accuracy by 8-20 points.

Verdict per candidate: GO only if accuracy rises (net gain >= 2 attempts and bootstrap P(delta > 0) >= 0.9), the
pooled false-trigger rate does not rise, no negative set gains more than one event, and the voice-cursor glides /
held notes do not lose. What-ifs (not derivable from the calibration files) are scored for information, never GO.

  ./run python eval_real/calib_gestures.py                          # writes results/calib_gestures.{md,json}
  ./run python eval_real/calib_gestures.py --voice recordings/joystick --boot 2000 --workers 8

Numbers only in the outputs (no audio, no transcripts): the recordings are private.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval_real"))

from common import pmap  # noqa: E402

from vox_extract import Config  # noqa: E402
from vox_extract.extractor import Extractor, load_wav  # noqa: E402
from vox_extract.policy import not_deliberate  # noqa: E402
from vox_extract.sequencer_sim import app_actions  # noqa: E402

REC = ROOT / "recordings"
VOICE = REC / "joystick"
GUIDED = REC / "khoa-guided-1"
VCURSOR = ["vcursor-1", "vcursor-2"]
RESULTS = ROOT / "results"
GESTURES = {"rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss"}
HUMS = {"rise", "fall", "arch", "dip", "flat"}
TICK_MS = 20.0                 # the joystick's analysis tick (prompts/joystick_v1.json tick.tick_ms)
REF_SPAN_ST = 12.0             # the excursion defaults assume about an octave of comfortable range
WIN_PRE_MS, WIN_POST_MS = 200, 300

NEGATIVES = {                  # name -> (wav, PhoneGate on: media plays)
    "room (aec-desktop-1)": (REC / "aec-desktop-1" / "rec" / "room_long_mic.wav", False),
    **{f"sim-{sp} {clip}": (REC / f"aec-desktop-sim-{sp}" / "rec" / f"{clip}_mic.wav", clip != "room")
       for sp in ("desk", "phone") for clip in ("room", "music_vocals", "podcast", "shortvideo", "gesturelike")},
    "live meow (105946)": (REC / "live-20260926-105946" / "session.wav", False),
    "live yell (110107)": (REC / "live-20260926-110107" / "session.wav", False),
}


# ============================================================================== the calibration -> Config overrides

def load_voice(d: Path = VOICE) -> dict:
    """The joystick setup's saved numbers: range.json, vowels.json and pops.json (any may be missing)."""
    out = {}
    for name in ("range", "vowels", "pops"):
        p = Path(d) / f"{name}.json"
        out[name] = json.loads(p.read_text()) if p.exists() else None
    return out


def derive(voice: dict) -> dict[str, dict]:
    """Candidate -> {"overrides": {vx_config field: value}, "formula": {field: text}}. Only from the setup's files.
    A candidate whose inputs are missing (or were skipped in the setup) is left out."""
    rng, pops = voice.get("range") or {}, voice.get("pops") or {}
    skipped = set(rng.get("skipped", [])) | set(pops.get("skipped", []))
    c: dict[str, dict] = {}
    if rng.get("clarity_on") is not None and "home" not in skipped:
        c["voicing"] = {"overrides": {"voiced_clarity": round(float(rng["clarity_on"]), 3)},
                        "formula": {"voiced_clarity": "range.json clarity_on (the setup hum's own voicing threshold)"}}
    if rng.get("lo_st") is not None and "range" not in skipped:
        c["f0_floor"] = {"overrides": {"f0_min_hz": round(55.0 * 2 ** ((float(rng["lo_st"]) - 3.0) / 12.0), 1)},
                         "formula": {"f0_min_hz": "55 * 2^((lo_st - 3) / 12): 3 st under the range's bottom; creak "
                                                  "further down stays unvoiced"}}
    if rng.get("lo_st") is not None and rng.get("hi_st") is not None and "range" not in skipped:
        s = float(np.clip((float(rng["hi_st"]) - float(rng["lo_st"])) / REF_SPAN_ST, 0.5, 1.5))
        d = Config()
        c["excursion"] = {"overrides": {k: round(getattr(d, k) * s, 2) for k in
                                        ("flat_max_range_st", "shape_min_st", "exc_medium_st", "exc_large_st")},
                          "formula": {k: f"default x clip((hi_st - lo_st) / {REF_SPAN_ST:g}, 0.5, 1.5)" for k in
                                      ("flat_max_range_st", "shape_min_st", "exc_medium_st", "exc_large_st")}}
    p = pops.get("pop") or {}
    if p.get("core_ticks") is not None and "pops" not in skipped:
        c["pop_core"] = {"overrides": {"discrete_core_ms": int(round(TICK_MS * int(p["core_ticks"])))},
                         "formula": {"discrete_core_ms": f"{TICK_MS:g} ms x pops.json pop.core_ticks (the widest setup "
                                                         "pop's ticks within 15 dB of its peak, + 1)"}}
    if p.get("rise_db") is not None and "pops" not in skipped:
        c["pop_rise"] = {"overrides": {"pop_onset_flux_db": round(6.0 * float(p["rise_db"]) / 5.0, 2)},
                         "formula": {"pop_onset_flux_db": "6 x pops.json pop.rise_db / 5 (the extractor's default over "
                                                          "the tick detector's default)"}}
    return c


# not derivable from the calibration files as saved: scored for information, never GO
WHATIFS = {
    "whatif_hangover200": {"hangover_frames": 20},        # the joystick's end_gap_ms (200 ms), a global number
    "whatif_discrete300": {"discrete_max_ms": 300},       # the tick pop detector's max_ticks (15 x 20 ms), global
}
NOT_DERIVABLE = {
    "pop-vs-click (click_centroid_hz)": "pops.json has no spectral number and the setup has no click step",
    "creak gap-bridging": "no vx_config field bridges voiced gaps inside a sound (the segmenter is energy-gated; "
                          "hangover_frames is energy, not voicing) and the setup does not measure creak",
    "discrete_max_ms (long-tailed pops)": "the setup saves no burst length (the tick detector's `ticks`)",
    "vowel centres": "the gesture extractor has no formant field",
}


# ============================================================================== the labelled data

def _last_per_pid(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        out[r["pid"]] = r               # the last line per prompt id wins (guided_session.py)
    return out


def expected(kind: str, pid: str) -> list[str]:
    if kind.startswith("whistle_"):
        return [kind.split("_")[1]]
    if kind == "click_run":
        m = re.search(r"run(\d+)", pid)
        return ["click"] * (int(m.group(1)) if m else 3)
    return kind.split("_")


def guided_takes() -> tuple[list[dict], list[dict]]:
    """(gesture attempts, speech windows) of khoa-guided-1, times on run-01/session.wav.

    A gesture take often holds two or three attempts (the user repeated it). The unit is one ATTEMPT: a segment of
    segments_auto.jsonl (segment_takes.py --sounds cuts a take at energy pauses >= 0.6 s, independent of the
    extractor config), except those flagged `flub` (cut off by the take's end). Speech: the whole take window."""
    labels = _last_per_pid(GUIDED / "labels.jsonl")
    pos, neg = [], []
    for line in (GUIDED / "segments_auto.jsonl").read_text().splitlines():
        s = json.loads(line)
        r = labels.get(s["pid"])
        if s["block"] not in ("clicks", "whistles") or s["flag"] == "flub" or not r or r["take"] != s["take"] \
                or r.get("status") != "kept" or r.get("run") != "run-01":
            continue
        off = r["clip_offset_ms"]
        pos.append({"id": s["seg"], "kind": s["kind"], "cond": s.get("cond"), "exp": expected(s["kind"], s["pid"]),
                    "win": (off + s["start_ms"] - 150, off + s["end_ms"] + 250)})
    for pid, r in sorted(labels.items()):
        if r["block"] == "phrases" and r.get("status") == "kept" and r.get("run") == "run-01" and r.get("window_ms"):
            neg.append({"id": pid, "kind": "speech", "win": (r["window_ms"][0] - WIN_PRE_MS, r["end_ms"] + WIN_POST_MS)})
    return pos, neg


def label_ok(got: list[str], exp: list[str], kind: str) -> bool:
    if kind == "click_run":                  # a run: at least 3 clicks and nothing else (aec_desktop.label_ok)
        return len(got) >= 3 and all(g == "click" for g in got)
    return got == exp


def vcursor_takes(sess: str) -> list[dict]:
    """Sung range glides (expected rise) and held notes (expected flat) of a voice-cursor session. Every kept, heard
    row counts (a redone range repeats a prompt id with a new take)."""
    out = []
    for i, line in enumerate((REC / sess / "labels.jsonl").read_text().splitlines()):
        r = json.loads(line)
        if r.get("status") != "kept" or not r.get("heard") or r.get("go_ms") is None or r.get("kind") not in (
                "glide", "anchor", "level", "vowel"):
            continue
        out.append({"id": f"{sess}:{i}", "sess": sess, "kind": "glide" if r["kind"] == "glide" else "held",
                    "win": (r["go_ms"] - WIN_PRE_MS, r["end_ms"] + WIN_POST_MS),
                    "exp": "rise" if r["kind"] == "glide" else "flat"})
    return out


# ============================================================================== replay

def _slim(e) -> dict:
    r = e.raw
    return {"label": e.label, "text": e.text, "sounds_like": e.sounds_like, "t_start_ms": e.t_start_ms,
            "t_end_ms": e.t_end_ms, "emit": e.emit,
            "raw": {k: r.get(k) for k in ("dur_ms", "snr_db", "clarity_med", "centroid_hz", "peak_centroid_hz")}}


def _job(j: dict) -> dict:
    x, sr = load_wav(j["wav"])
    ex = Extractor(Config.from_dict({**json.loads(Config().to_json()), **j["over"]}), input_rate=sr)
    ev = []
    step = sr // 10
    for i in range(0, len(x), step):
        ev += ex.push(x[i:i + step])
    ev += ex.flush()
    return {"cfg": j["cfg"], "stream": j["stream"], "seconds": len(x) / sr, "events": [_slim(e) for e in ev]}


def streams() -> dict[str, tuple[Path, bool]]:
    s = {"guided": (GUIDED / "run-01" / "session.wav", False)}
    s.update({v: (REC / v / "run-01" / "session.wav", False) for v in VCURSOR})
    s.update({k: v for k, v in NEGATIVES.items() if v[0].exists()})
    return s


def replay(configs: dict[str, dict], workers: int) -> dict[str, dict[str, dict]]:
    st = streams()
    jobs = [{"cfg": c, "over": o, "stream": s, "wav": str(p)} for c, o in configs.items() for s, (p, _) in st.items()]
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in pmap(_job, jobs, workers=workers, chunksize=1):
        out[r["cfg"]][r["stream"]] = r
    return out


# ============================================================================== scoring

def inside(events: list[dict], w: tuple[float, float]) -> list[dict]:
    return [e for e in events if e["emit"] and w[0] <= e["t_start_ms"] <= w[1]]


def deliberate(events: list[dict]) -> list[str]:
    return [e["label"] for e in events if e["label"] in GESTURES and not not_deliberate(e["label"], e["text"])]


def seg_error(got: list[str], exp: list[str]) -> str:
    return "missed" if not got else "merged" if len(got) < len(exp) else "split" if len(got) > len(exp) else "count ok"


def score_gestures(ev: list[dict], takes: list[dict]) -> list[dict]:
    out = []
    for t in takes:
        got = deliberate(inside(ev, t["win"]))
        out.append({"id": t["id"], "kind": t["kind"], "cond": t["cond"], "got": got, "ok": label_ok(got, t["exp"], t["kind"]),
                    "seg": seg_error(got, t["exp"])})
    return out


def score_voiced(ev: list[dict], takes: list[dict]) -> list[dict]:
    out = []
    for t in takes:
        v = [e for e in inside(ev, t["win"]) if e["label"] in HUMS and (e["raw"]["dur_ms"] or 0) >= 100]
        main = max(v, key=lambda e: e["raw"]["dur_ms"]) if v else None
        out.append({"id": t["id"], "kind": t["kind"], "label": main["label"] if main else None,
                    "ok": bool(main and main["label"] == t["exp"]), "talking": bool(main and main["sounds_like"] == "talking"),
                    "split": len(v) > 1, "missed": main is None})
    return out


def _chunks(ev: list[dict], seconds: float, gate: bool, chunk_s: float = 20.0) -> list[dict]:
    n = max(1, int(math.ceil(seconds / chunk_s)))
    units = []
    for k in range(n):
        a, b = k * chunk_s * 1000, min(seconds, (k + 1) * chunk_s) * 1000
        units.append(_unit(ev, (a, b - 1e-6), gate))
    return units


def _unit(ev: list[dict], w: tuple[float, float], gate: bool) -> dict:
    sub = inside(ev, w)
    acts = [a for _, a in app_actions(sub, gate={} if gate else None)] if sub else []
    return {"min": (w[1] - w[0]) / 60000.0, "fa": len(deliberate(sub)), "act": sum(a != "none" for a in acts)}


def score_negatives(run: dict[str, dict], speech: list[dict]) -> dict[str, list[dict]]:
    out = {"guided speech takes": [_unit(run["guided"]["events"], t["win"], False) for t in speech]}
    for name, (_, gate) in NEGATIVES.items():
        if name in run:
            out[name] = _chunks(run[name]["events"], run[name]["seconds"], gate)
    return out


def score_all(run: dict[str, dict]) -> dict:
    pos, speech = guided_takes()
    vc = []
    for s in VCURSOR:
        if s in run:
            vc += score_voiced(run[s]["events"], vcursor_takes(s))
    return {"gest": score_gestures(run["guided"]["events"], pos), "voiced": vc,
            "neg": score_negatives(run, speech)}


# ============================================================================== bootstrap and verdict

def boot_ci(a: np.ndarray, b: np.ndarray | None = None, n: int = 2000, seed: int = 1) -> dict:
    """Mean of a (or of b - a, paired), with a 95 % percentile CI and P(> 0) over n resamples of the units."""
    rng = np.random.default_rng(seed)
    x = a if b is None else b - a
    if x.size == 0:
        return {"mean": None, "lo": None, "hi": None, "p_pos": None}
    idx = rng.integers(0, x.size, (n, x.size))
    m = x[idx].mean(axis=1)
    return {"mean": float(x.mean()), "lo": float(np.percentile(m, 2.5)), "hi": float(np.percentile(m, 97.5)),
            "p_pos": float(np.mean(m > 0))}


def rate_ci(units: list[dict], key: str, other: list[dict] | None = None, n: int = 2000, seed: int = 1) -> dict:
    """Events per minute (sum / sum), CI over resampled units; paired delta when `other` (same units) is given."""
    rng = np.random.default_rng(seed)
    mins = np.array([u["min"] for u in units])
    a = np.array([u[key] for u in units], float)
    b = np.array([u[key] for u in other], float) if other is not None else None
    tot = mins.sum() or 1e-9
    val = (a.sum() if b is None else b.sum() - a.sum()) / tot
    idx = rng.integers(0, len(units), (n, len(units)))
    m = mins[idx].sum(axis=1) + 1e-9
    r = ((a[idx].sum(axis=1)) if b is None else (b[idx].sum(axis=1) - a[idx].sum(axis=1))) / m
    return {"per_min": float(val), "lo": float(np.percentile(r, 2.5)), "hi": float(np.percentile(r, 97.5)),
            "events": int(a.sum() if b is None else b.sum() - a.sum()), "minutes": float(tot)}


def compare(base: dict, cand: dict, n_boot: int) -> dict:
    ok0 = np.array([t["ok"] for t in base["gest"]], float)
    ok1 = np.array([t["ok"] for t in cand["gest"]], float)
    gained = int(np.sum((ok1 == 1) & (ok0 == 0)))
    lost = int(np.sum((ok1 == 0) & (ok0 == 1)))
    v0 = np.array([t["ok"] and not t["talking"] and not t["split"] for t in base["voiced"]], float)
    v1 = np.array([t["ok"] and not t["talking"] and not t["split"] for t in cand["voiced"]], float)
    pooled0 = [u for k in base["neg"] for u in base["neg"][k]]
    pooled1 = [u for k in cand["neg"] for u in cand["neg"][k]]
    per_set = {k: int(sum(u["fa"] for u in cand["neg"][k]) - sum(u["fa"] for u in base["neg"][k])) for k in base["neg"]}
    return {"acc": float(ok1.mean()), "acc_base": float(ok0.mean()), "gained": gained, "lost": lost,
            "d_acc": boot_ci(ok0, ok1, n_boot), "voiced_gained": int(np.sum((v1 == 1) & (v0 == 0))),
            "voiced_lost": int(np.sum((v1 == 0) & (v0 == 1))),
            "d_fa": rate_ci(pooled0, "fa", pooled1, n_boot), "d_act": rate_ci(pooled0, "act", pooled1, n_boot),
            "fa_by_set": per_set}


def verdict(c: dict) -> tuple[str, str]:
    why = []
    if not (c["gained"] - c["lost"] >= 2 and (c["d_acc"]["p_pos"] or 0) >= 0.9):
        why.append(f"accuracy {c['gained']} gained / {c['lost']} lost, P(delta>0) {c['d_acc']['p_pos']:.2f}")
    if c["d_fa"]["events"] > 0:
        why.append(f"false triggers +{c['d_fa']['events']} pooled")
    worst = max(c["fa_by_set"].items(), key=lambda kv: kv[1])
    if worst[1] > 1:
        why.append(f"{worst[0]} +{worst[1]}")
    if c["voiced_lost"] > c["voiced_gained"]:
        why.append(f"voice-cursor glides / held notes {c['voiced_gained']} gained / {c['voiced_lost']} lost")
    return ("GO", "all conditions hold") if not why else ("NO-GO", "; ".join(why))


# ============================================================================== report

def per_kind(res: dict) -> dict[str, dict]:
    by = defaultdict(list)
    for t in res["gest"]:
        by[t["kind"] + (" (video)" if t["cond"] == "video" else "")].append(t)
    return {k: {"n": len(v), "ok": sum(t["ok"] for t in v), "seg": dict(Counter(t["seg"] for t in v)),
                "got": dict(Counter(" ".join(t["got"]) or "-" for t in v).most_common())} for k, v in sorted(by.items())}


def neg_table(res: dict) -> dict[str, dict]:
    return {k: {"minutes": round(sum(u["min"] for u in v), 2), "fa": sum(u["fa"] for u in v),
                "act": sum(u["act"] for u in v)} for k, v in res["neg"].items()}


def voiced_table(res: dict) -> dict[str, dict]:
    by = defaultdict(list)
    for t in res["voiced"]:
        by[t["kind"]].append(t)
    return {k: {"n": len(v), "label_ok": sum(t["ok"] for t in v), "talking": sum(t["talking"] for t in v),
                "split": sum(t["split"] for t in v), "missed": sum(t["missed"] for t in v),
                "labels": dict(Counter(t["label"] or "-" for t in v))} for k, v in sorted(by.items())}


def f1(x) -> str:
    return "-" if x is None else f"{x:+.1f}" if isinstance(x, float) else str(x)


def report(out: dict) -> str:
    L = ["# Per-person calibration vs gesture labels (calib_gestures.py)", "",
         "Generated by `eval_real/calib_gestures.py`; numbers only. See wiki/calibration-gestures.md for the reading.", ""]
    L += ["## Candidates (derived from recordings/joystick only)", "", "| candidate | overrides | formula |", "|---|---|---|"]
    for name, c in out["candidates"].items():
        L.append(f"| {name} | {', '.join(f'`{k}` = {v}' for k, v in c['overrides'].items())} | "
                 f"{'; '.join(c.get('formula', {}).values()) or 'what-if (not derivable)'} |")
    L += ["", "## Verdicts", "",
          "| config | accuracy | gained / lost | delta acc (95 % CI) | P(delta>0) | delta FA/min pooled (95 % CI) "
          "| delta acts/min | worst set | glides+held gained / lost | verdict |", "|---|---|---|---|---|---|---|---|---|---|"]
    base = out["results"]["default"]
    L.append(f"| default | {100 * base['acc']:.1f} % | | | | | | | | |")
    for name, c in out["compare"].items():
        d, fa, ac = c["d_acc"], c["d_fa"], c["d_act"]
        worst = max(c["fa_by_set"].items(), key=lambda kv: kv[1])
        L.append(f"| {name} | {100 * c['acc']:.1f} % | {c['gained']} / {c['lost']} | {100 * d['mean']:+.1f} "
                 f"({100 * d['lo']:+.1f}, {100 * d['hi']:+.1f}) | {d['p_pos']:.2f} | {fa['per_min']:+.2f} "
                 f"({fa['lo']:+.2f}, {fa['hi']:+.2f}) | {ac['per_min']:+.2f} | {worst[0]} {worst[1]:+d} | "
                 f"{c['voiced_gained']} / {c['voiced_lost']} | **{out['verdicts'][name][0]}** {out['verdicts'][name][1]} |")
    for name in ["default"] + list(out["compare"]):
        r = out["results"][name]
        L += ["", f"## {name}: per kind", "", "| kind | n | right | missed | merged | split | count ok | got (top) |",
              "|---|---|---|---|---|---|---|---|"]
        for k, v in r["per_kind"].items():
            s = v["seg"]
            top = "; ".join(f"{g} x{n}" for g, n in list(v["got"].items())[:4])
            L.append(f"| {k} | {v['n']} | {v['ok']} | {s.get('missed', 0)} | {s.get('merged', 0)} | {s.get('split', 0)} "
                     f"| {s.get('count ok', 0)} | {top} |")
        L += ["", "| voice-cursor | n | label ok | talking | split | missed | labels |", "|---|---|---|---|---|---|---|"]
        for k, v in r["voiced"].items():
            L.append(f"| {k} | {v['n']} | {v['label_ok']} | {v['talking']} | {v['split']} | {v['missed']} | "
                     f"{', '.join(f'{a} {b}' for a, b in v['labels'].items())} |")
        L += ["", "| negatives | minutes | deliberate gesture events | per min | app actions | per min |",
              "|---|---|---|---|---|---|"]
        for k, v in r["neg"].items():
            L.append(f"| {k} | {v['minutes']:.1f} | {v['fa']} | {v['fa'] / v['minutes']:.2f} | {v['act']} | "
                     f"{v['act'] / v['minutes']:.2f} |")
    L += ["", "## Not derivable from the calibration files", ""]
    L += [f"- {k}: {v}" for k, v in NOT_DERIVABLE.items()]
    return "\n".join(L) + "\n"


def evaluate(voice_dir: Path, workers: int, n_boot: int) -> dict:
    cand = derive(load_voice(voice_dir))
    configs = {"default": {}, **{k: v["overrides"] for k, v in cand.items()}, **WHATIFS}
    configs["all_person"] = {k: v for c in cand.values() for k, v in c["overrides"].items()}
    runs = replay(configs, workers)
    scored = {k: score_all(v) for k, v in runs.items()}
    cmp = {k: compare(scored["default"], scored[k], n_boot) for k in configs if k != "default"}
    verd = {k: verdict(c) if not k.startswith("whatif") else ("what-if", "not derivable: never GO") for k, c in cmp.items()}
    go = {f: v for k, c in cand.items() if verd[k][0] == "GO" for f, v in c["overrides"].items()}
    if go and set(go) != set(configs["all_person"]) and len([k for k in cand if verd[k][0] == "GO"]) > 1:
        runs.update(replay({"all_go": go}, workers))
        scored["all_go"] = score_all(runs["all_go"])
        cmp["all_go"] = compare(scored["default"], scored["all_go"], n_boot)
        verd["all_go"] = verdict(cmp["all_go"])
    results = {k: {"acc": float(np.mean([t["ok"] for t in s["gest"]])), "per_kind": per_kind(s),
                   "voiced": voiced_table(s), "neg": neg_table(s)} for k, s in scored.items()}
    return {"voice_dir": str(voice_dir), "candidates": {**cand, **{k: {"overrides": v} for k, v in WHATIFS.items()}},
            "results": results, "compare": cmp, "verdicts": verd,
            "go_fields": {f: {"value": v, "formula": next(c["formula"][f] for c in cand.values() if f in c["overrides"])}
                          for f, v in go.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice", type=Path, default=VOICE, help="the joystick setup's folder (range / vowels / pops.json)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--out", type=Path, default=RESULTS / "calib_gestures")
    a = ap.parse_args()
    out = evaluate(a.voice, min(8, a.workers), a.boot)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".json").write_text(json.dumps(out, indent=1, default=float))
    a.out.with_suffix(".md").write_text(report(out))
    for k, (v, why) in out["verdicts"].items():
        c = out["compare"][k]
        print(f"{k:22s} acc {100 * c['acc']:5.1f} % (default {100 * c['acc_base']:.1f})  +{c['gained']}/-{c['lost']}  "
              f"dFA {c['d_fa']['per_min']:+.2f}/min  {v}: {why}")
    print("GO fields:", json.dumps(out["go_fields"]))
    print(f"wrote {a.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
