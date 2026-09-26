"""MLEnd Hums and Whistles (Queen Mary University of London): ~15-20 s hummed / whistled song excerpts
recorded by 226 interpreters on their own devices (mostly phones / laptops), 44.1 kHz, mono or stereo.

These are MELODIES, not gestures: a hummed song breaks into many notes and phrases, and anything longer than
3 s is "background music" by design (max_gesture_ms). So nothing here is scored as a gesture. Two questions:
  1. Does the extractor recognise the source? Of the voiced (contour) events, how many say "hum" for hum
     recordings and "whistle" for whistle recordings, time-weighted and by count; which other "sounds like"
     values appear (talking, background music ...). Also by the event's median f0 (low-f0 hums vs talking cue).
  2. Is pitch tracked? No manual pitch exists, so the reference is Praat's autocorrelation tracker
     (parselmouth, to_pitch_ac, 10 ms step; floor/ceiling 60/900 Hz for hums, 300/3000 Hz for whistles):
     voicing agreement and, on frames both call voiced, gross error (> 20 %), octave errors and cents error.
     This measures agreement with another tracker, NOT accuracy against the truth.
Rate handling: stereo -> mean, 44.1 kHz -> 16 kHz with scipy resample_poly (resample.to_16k), not the 48 kHz
decimator. Speaker = Interpreter.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

NAME = "mlend"
ROOT = C.DATA / "mlend_hums_whistles"
CONTOURS = ["rise", "fall", "arch", "dip", "flat"]
F0_BINS = [0, 110, 160, 250, 400, 600, 1000, 5000]


def files() -> list[dict]:
    out = []
    with (ROOT / "MLEndHWD_audio_attributes_benchmark.csv").open() as fh:
        for row in csv.DictReader(fh):
            p = ROOT / "MLEndHWD_audiofiles" / row["filename"]
            if not p.exists() or p.stat().st_size < 1000:
                continue
            spk = row["Interpreter"]
            out.append({"path": str(p), "speaker": spk, "split": C.split_of(NAME, spk), "song": row["Song"],
                        "interp": row["Interpretation"].lower()})
    return out


def jobs(split: str, cfg_path: str | None) -> list[tuple]:
    return [(f, cfg_path) for f in files() if f["split"] == split]


def praat_pitch(x: np.ndarray, interp: str) -> tuple[np.ndarray, np.ndarray]:
    import parselmouth
    lo, hi = (60.0, 900.0) if interp == "hum" else (300.0, 3000.0)
    snd = parselmouth.Sound(x.astype(np.float64), sampling_frequency=16000.0)
    p = snd.to_pitch_ac(time_step=0.01, pitch_floor=lo, pitch_ceiling=hi)
    return p.xs() * 1000.0, p.selected_array["frequency"]


def run_job(job: tuple) -> dict:
    f, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    try:
        x = C.load_16k(f["path"])
    except Exception as err:  # noqa: BLE001 - a broken download must not kill the run
        return {"dataset": NAME, **f, "error": str(err)}
    x_t, cut = C.trim_dead(x)
    y, off, _ = C.pad_clip(x)
    ex = C.Extractor(cfg, input_rate=16000, keep_frames=True)
    ev = []
    for i in range(0, len(y), 1600):
        ev += ex.push(y[i:i + 1600])
    ev += ex.flush()
    ev = [e.to_dict() for e in ev]
    shift = 1000.0 * off / 16000                                     # padded time -> trimmed-clip time
    fr = ex.frames
    t = np.array([q.t_ms + 5.0 for q in fr]) - shift
    f0 = np.array([q.f0 for q in fr])
    cl = np.array([q.clarity for q in fr])
    e = np.array([q.e_db for q in fr])
    fl = np.array(ex.floors)
    vo = (cl >= cfg.voiced_clarity) & (f0 > 0) & (e >= fl + cfg.voiced_min_db_over_floor)
    pt, pf = praat_pitch(x_t, f["interp"])
    j = np.clip(np.searchsorted(t, pt), 0, len(t) - 1)
    ref_v = pf > 0
    both = ref_v & vo[j]
    cents = 1200 * np.log2(f0[j][both] / pf[both]) if both.any() else np.zeros(0)
    rec = {"dataset": NAME, **f, "dur_s": len(x_t) / 16000,
           "pitch": {"ref_voiced": int(ref_v.sum()), "both": int(both.sum()), "est_on_ref_unvoiced": int((~ref_v & vo[j]).sum()),
                     "ref_unvoiced": int((~ref_v).sum()), "cents": np.round(cents, 1).tolist()}}
    for q in ev:
        q["t_start_ms"] -= int(shift)
        q["t_end_ms"] -= int(shift)
    rec.update(C.analyse(ev, y, int(shift)))
    return rec


def summarise(recs: list[dict]) -> dict:
    recs = [r for r in recs if "error" not in r]
    s = {"files": len(recs), "errors": 0}
    for interp in ("hum", "whistle"):
        rs = [r for r in recs if r["interp"] == interp]
        evs = [e for r in rs for e in r["events"]]
        voiced = [e for e in evs if e["label"] in CONTOURS]
        want = interp
        dur = lambda es: sum(max(0, e["t1"] - e["t0"]) for e in es)  # noqa: E731
        like_n = Counter(e["like"] for e in voiced)
        like_t = defaultdict(float)
        for e in voiced:
            like_t[e["like"]] += max(0, e["t1"] - e["t0"])
        tot_t = sum(like_t.values())
        # by f0 of the event
        f0tab = defaultdict(Counter)
        for e in voiced:
            f0 = e["raw"].get("f0_med_hz") or 0
            b = next(i for i in range(len(F0_BINS) - 1) if F0_BINS[i] <= f0 < F0_BINS[i + 1]) if f0 < F0_BINS[-1] else len(F0_BINS) - 2
            f0tab[f"{F0_BINS[b]}-{F0_BINS[b + 1]} Hz"][e["like"]] += 1
        cents = np.concatenate([np.array(r["pitch"]["cents"], dtype=float) for r in rs]) if rs else np.zeros(0)
        gross = np.abs(cents) > 316
        rv = sum(r["pitch"]["ref_voiced"] for r in rs)
        s[interp] = {
            "files": len(rs), "minutes": sum(r["dur_s"] for r in rs) / 60,
            "events": len(evs), "events_per_min": len(evs) / max(1e-9, sum(r["dur_s"] for r in rs) / 60),
            "event_labels": dict(Counter(e["label"] for e in evs)),
            "voiced_events": len(voiced), "voiced_likes": dict(like_n),
            "called_right_n": C.rate(like_n.get(want, 0), len(voiced)),
            "called_right_time": (like_t.get(want, 0) / tot_t) if tot_t else None,
            "called_hum_or_whistle_n": C.rate(like_n.get("hum", 0) + like_n.get("whistle", 0), len(voiced)),
            "talking_n": C.rate(like_n.get("talking", 0), len(voiced)),
            "files_with_any_right": C.rate(sum(1 for r in rs if any(e["like"] == want for e in r["events"])), len(rs)),
            "likes_by_f0": {k: dict(v) for k, v in sorted(f0tab.items(), key=lambda kv: float(kv[0].split("-")[0]))},
            "fireable_per_min": sum(1 for r in rs for a in r["fire"] if a != "none") / max(1e-9, sum(r["dur_s"] for r in rs) / 60),
            "pitch": {"ref_voiced_frames": rv, "voicing_recall": C.rate(sum(r["pitch"]["both"] for r in rs), rv),
                      "false_voicing": C.rate(sum(r["pitch"]["est_on_ref_unvoiced"] for r in rs), sum(r["pitch"]["ref_unvoiced"] for r in rs)),
                      "gpe_20pct": float(gross.mean()) if cents.size else None,
                      "octave_err": float((np.abs(np.abs(cents) - 1200) < 150).mean()) if cents.size else None,
                      "median_abs_cents_fine": float(np.median(np.abs(cents[~gross]))) if cents.size else None,
                      "mean_abs_cents_fine": float(np.mean(np.abs(cents[~gross]))) if cents.size else None},
        }
    s["line_errors"] = sum(len(r["line_errors"]) for r in recs)
    s["lines"] = sum(len(r["events"]) for r in recs)
    s["ood"] = sum(len(r["ood"]) for r in recs)
    return s


LIKES = ["hum", "whistle", "talking", "laughing", "coughing", "background music", "background noise", "mouth sound"]


def markdown(s: dict, title: str) -> str:
    L = [f"### {title}\n"]
    rows = []
    for interp in ("hum", "whistle"):
        d = s[interp]
        p = d["pitch"]
        rows.append([interp, d["files"], C.num(d['minutes'], ".0f"), C.num(d['events_per_min'], ".1f"), d["voiced_events"],
                     C.pct(d["called_right_n"]), C.pct(d["called_right_time"]), C.pct(d["called_hum_or_whistle_n"]), C.pct(d["talking_n"]),
                     C.pct(d["files_with_any_right"]), C.pct(p["voicing_recall"]), C.pct(p["gpe_20pct"]), C.pct(p["octave_err"]),
                     C.num(p['median_abs_cents_fine'], ".0f") if p["median_abs_cents_fine"] is not None else "-"])
    L.append(C.md_table(["recordings", "files", "min", "events/min", "voiced events", f"called right % (n)", "called right % (time)",
                         "hum or whistle %", "talking %", "files with >= 1 right", "voicing recall vs Praat %", "GPE vs Praat %",
                         "octave err %", "median |cents| (no gross)"], rows))
    for interp in ("hum", "whistle"):
        d = s[interp]
        L.append(f"\n'Sounds like' of voiced events in {interp} recordings, by event median f0:\n")
        L.append(C.md_table(["f0"] + LIKES + ["n"], [[k] + [v.get(x, 0) for x in LIKES] + [sum(v.values())] for k, v in d["likes_by_f0"].items()]))
    L.append(f"\nLines: {s['lines']}; strict-parse/label errors: {s['line_errors']}; outside generate.py's line space: {s['ood']}\n")
    return "\n".join(L)
