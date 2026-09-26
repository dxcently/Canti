"""MIR-QBSH (Roger Jang, NTHU): 4431 sung / hummed queries with MANUALLY labelled pitch.

Audio: 8 kHz, 8-bit unsigned PCM, mono -> upsampled to 16 kHz with scipy resample_poly (resample.to_16k;
not the 48 kHz decimator path). The band above 4 kHz is empty and 8-bit quantisation gives a
~-50 dBFS noise floor, so this is a harder, telephone-like channel than a phone mic.
Manual pitch (.pv): one value per 256 samples (32 ms, no overlap), in semitones (MIDI numbers), 0 =
unvoiced / rest. Frame i covers [32 i, 32 i + 32) ms. The corpus notes the labels were made by the
students who recorded them and are not guaranteed correct.

Speaker = the person's name in personDirInfo.txt (the same person can appear in several years).

(a) PITCH: the extractor's raw per-frame MPM pitch (FrameProcessor, the same frames the classifier
    sees; "voiced" = clarity >= voiced_clarity and energy >= floor + voiced_min_db_over_floor) is compared
    with the manual pitch at the centre of every manual frame (nearest 10 ms extractor frame). On frames the
    manual track calls voiced: voicing recall; and, where both are voiced, gross pitch error (GPE: off by
    more than 20 %), octave errors, and the absolute error in cents (all frames, and without gross errors).

(b) CONTOUR CLIPS cut from the recordings. Cutting rules (on the manual pitch only):
    1. phrase = voiced manual frames, joining runs separated by <= 2 unvoiced frames (<= 64 ms);
    2. at least 5 unvoiced manual frames (>= 160 ms) on both sides inside the recording;
    3. 150 ms <= phrase length <= 1500 ms (5..46 frames);
    4. no jump > 7 semitones between consecutive voiced frames (likely label errors / octave slips);
    5. the voiced pitch track gets a 3-frame median; start / end = median of the first / last 2 frames;
       net = end - start, hump = max - max(start, end), valley = min(start, end) - min;
    6. CLEAR-MARGIN truth (ambiguous phrases are dropped, and counted):
         flat : max(|net|, hump, valley) <= 0.5 st           (extractor boundary is 1.5 st)
         rise : net >= +2 st, hump and valley <= min(1, net/4)
         fall : net <= -2 st, hump and valley <= min(1, |net|/4)
         arch : hump >= 2 st, |net| <= hump/2, valley <= 0.5
         dip  : valley >= 2 st, |net| <= valley/2, hump <= 0.5
    7. truth excursion = the schema bucket (EXCURSION: <2, 2-4, >4 st) of |net| (rise/fall), hump (arch),
       valley (dip), max range (flat); scored only when >= 0.5 st from a bucket edge.
       truth duration = the phrase's voiced span, scored only when >= 20 % away from 150 / 400 / 1000 ms.
    8. the clip = the phrase plus 150 ms of the surrounding recording on each side (unvoiced by rule 2,
       but it can hold breaths / consonants), 10 ms fades at the cut edges, preceded by 1.0 s and followed
       by 0.6 s of the recording's own quietest 200 ms looped (so the noise floor is warm).
    9. at most MAX_PER_CLASS_SPK (8) clips per (speaker, class), 4 for flat, chosen deterministically.
    Sung-melody fragments are NOT deliberate gestures: a "rise" here is usually two or three sung notes
    stepping up, not a glide, and many are sung with lyrics (so "sounds like talking" is not always wrong).
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from vox_extract.vocab import DURATION, EXCURSION  # noqa: E402

NAME = "qbsh"
ROOT = C.DATA / "mir-qbsh" / "MIR-QBSH-corpus" / "waveFile"
PV_MS = 32.0
MAX_PER_CLASS_SPK = 8
MAX_FLAT_PER_SPK = 4       # flats are ~half of all clear phrases: cap them harder
CONTOURS = ["rise", "fall", "arch", "dip", "flat"]


def speakers() -> dict[tuple[str, str], str]:
    out = {}
    for y in sorted(p for p in ROOT.glob("year*") if p.is_dir()):
        info = y / "personDirInfo.txt"
        for line in info.read_bytes().splitlines():
            if b"\t" in line:
                pid, name = line.split(b"\t", 1)
                out[(y.name, pid.decode().strip())] = name.strip().hex()
    return out


def files() -> list[dict]:
    spk = speakers()
    out = []
    for w in sorted(ROOT.glob("year*/person*/*.wav")):
        pv = w.with_suffix(".pv")
        if not pv.exists():
            continue
        s = spk.get((w.parent.parent.name, w.parent.name), w.parent.parent.name + "/" + w.parent.name)
        out.append({"path": str(w), "pv": str(pv), "speaker": s, "split": C.split_of(NAME, s),
                    "song": w.stem})
    return out


def load_pv(path: str) -> np.ndarray:
    return np.loadtxt(path, ndmin=1)


# ------------------------------------------------------------------------------ (a) pitch

def pitch_job(job: tuple) -> dict:
    f, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    x = C.load_16k(f["path"])
    y, off, cut = C.pad_clip(x)
    ex = C.Extractor(cfg, input_rate=16000, keep_frames=True)
    for i in range(0, len(y), 1600):
        ex.push(y[i:i + 1600])
    ex.flush()
    fr = ex.frames
    t = np.array([q.t_ms + 5.0 for q in fr]) - 1000.0 * (off - cut) / 16000   # frame centre, file time
    f0 = np.array([q.f0 for q in fr])
    cl = np.array([q.clarity for q in fr])
    e = np.array([q.e_db for q in fr])
    floor = np.array(ex.floors)
    voiced = (cl >= cfg.voiced_clarity) & (f0 > 0) & (e >= floor + cfg.voiced_min_db_over_floor)
    pv = load_pv(f["pv"])
    res = {}
    for lag in (-32, -16, 0, 16, 32):
        centres = (np.arange(len(pv)) + 0.5) * PV_MS + lag
        j = np.clip(np.searchsorted(t, centres), 0, len(t) - 1)
        j0 = np.clip(j - 1, 0, len(t) - 1)
        j = np.where(np.abs(t[j0] - centres) < np.abs(t[j] - centres), j0, j)
        ref_v = pv > 0
        est_v = voiced[j]
        both = ref_v & est_v
        ref_hz = 440.0 * 2 ** ((pv[both] - 69) / 12)
        cents = 1200 * np.log2(f0[j][both] / ref_hz)
        res[lag] = {"ref_voiced": int(ref_v.sum()), "est_voiced_on_ref": int(both.sum()),
                    "est_voiced_on_unvoiced": int((~ref_v & est_v).sum()), "ref_unvoiced": int((~ref_v).sum()),
                    "cents": np.round(cents, 1).tolist()}
    return {"dataset": NAME, **f, "lags": res}


def pitch_summary(recs: list[dict], lag: int = 0) -> dict:
    rv = sum(r["lags"][lag]["ref_voiced"] if lag in r["lags"] else r["lags"][str(lag)]["ref_voiced"] for r in recs)
    def L(r):
        return r["lags"][lag] if lag in r["lags"] else r["lags"][str(lag)]
    ev = sum(L(r)["est_voiced_on_ref"] for r in recs)
    fv = sum(L(r)["est_voiced_on_unvoiced"] for r in recs)
    ru = sum(L(r)["ref_unvoiced"] for r in recs)
    cents = np.concatenate([np.array(L(r)["cents"], dtype=float) for r in recs]) if recs else np.zeros(0)
    gross = np.abs(cents) > 1200 * np.log2(1.2)          # 20 % (~316 cents)
    octave = np.abs(np.abs(cents) - 1200) < 150
    fine = np.abs(cents[~gross])
    per_file_gpe = [np.mean(np.abs(np.array(L(r)["cents"])) > 316) for r in recs if L(r)["cents"]]
    return {"files": len(recs), "ref_voiced_frames": rv, "voicing_recall": C.rate(ev, rv),
            "false_voicing_on_ref_unvoiced": C.rate(fv, ru), "compared_frames": int(cents.size),
            "gpe_20pct": float(gross.mean()) if cents.size else None,
            "octave_err": float(octave.mean()) if cents.size else None,
            "err_over_1st": float((np.abs(cents) > 100).mean()) if cents.size else None,
            "mean_abs_cents_all": float(np.mean(np.abs(cents))) if cents.size else None,
            "mean_abs_cents_fine": float(np.mean(fine)) if fine.size else None,
            "median_abs_cents_fine": float(np.median(fine)) if fine.size else None,
            "median_signed_cents_fine": float(np.median(cents[~gross])) if fine.size else None,
            "files_gpe_over_20pct": C.rate(sum(1 for g in per_file_gpe if g > 0.2), len(per_file_gpe))}


# ------------------------------------------------------------------------------ (b) contour clips

def _med3(v: np.ndarray) -> np.ndarray:
    if v.size < 3:
        return v
    return np.array([np.median(v[max(0, i - 1): i + 2]) for i in range(v.size)])


def truth_shape(p: np.ndarray) -> dict:
    s = _med3(p)
    start, end = float(np.median(s[:2])), float(np.median(s[-2:]))
    net = end - start
    hump = float(s.max()) - max(start, end)
    valley = min(start, end) - float(s.min())
    rng = max(abs(net), hump, valley)
    lab, exc = None, None
    if rng <= 0.5:
        lab, exc = "flat", rng
    elif net >= 2 and hump <= min(1.0, net / 4) and valley <= min(1.0, net / 4):
        lab, exc = "rise", abs(net)
    elif net <= -2 and hump <= min(1.0, -net / 4) and valley <= min(1.0, -net / 4):
        lab, exc = "fall", abs(net)
    elif hump >= 2 and abs(net) <= hump / 2 and valley <= 0.5:
        lab, exc = "arch", hump
    elif valley >= 2 and abs(net) <= valley / 2 and hump <= 0.5:
        lab, exc = "dip", valley
    return {"label": lab, "exc_st": exc, "net": net, "hump": hump, "valley": valley}


def bucket_or_none(v: float, edges: list[float], names: list[str], margin_abs: float | None = None, margin_rel: float | None = None):
    for e in edges:
        if margin_abs is not None and abs(v - e) < margin_abs:
            return None
        if margin_rel is not None and abs(v - e) < margin_rel * e:
            return None
    for e, n in zip(edges, names):
        if v < e:
            return n
    return names[len(edges)]


def phrases(pv: np.ndarray) -> tuple[list[dict], Counter]:
    """Cutting rules 1-7. Returns (clips, rejection counts)."""
    rej = Counter()
    v = pv > 0
    n = len(pv)
    runs, i = [], 0
    while i < n:
        if v[i]:
            j = i
            while j < n and v[j]:
                j += 1
            runs.append([i, j])
            i = j
        else:
            i += 1
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= 2:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = []
    for k, (a, b) in enumerate(merged):
        gap_before = a - (merged[k - 1][1] if k else 0)
        gap_after = (merged[k + 1][0] if k + 1 < len(merged) else n) - b
        if gap_before < 5 or gap_after < 5:
            rej["no 160 ms rest on both sides"] += 1
            continue
        if not 5 <= b - a <= 46:
            rej["length outside 150-1500 ms"] += 1
            continue
        p = pv[a:b][pv[a:b] > 0]
        if p.size < 4 or np.any(np.abs(np.diff(p)) > 7):
            rej["jump > 7 st or < 4 voiced frames"] += 1
            continue
        t = truth_shape(p)
        if t["label"] is None:
            rej["ambiguous shape"] += 1
            continue
        dur = (b - a) * PV_MS
        t.update({"f0": a, "f1": b, "t0_ms": a * PV_MS, "t1_ms": b * PV_MS, "dur_ms": dur,
                  "exc_bucket": bucket_or_none(t["exc_st"], [2.0, 4.0], EXCURSION, margin_abs=0.5),
                  "dur_bucket": bucket_or_none(dur, [150, 400, 1000], DURATION, margin_rel=0.2),
                  "median_hz": float(440 * 2 ** ((np.median(p) - 69) / 12))})
        out.append(t)
        rej["kept"] += 1
    return out, rej


def contour_clips(split: str) -> tuple[list[dict], Counter]:
    rej = Counter()
    per = defaultdict(list)
    for f in files():
        if f["split"] != split:
            continue
        ps, r = phrases(load_pv(f["pv"]))
        rej.update(r)
        for p in ps:
            per[(f["speaker"], p["label"])].append({**f, **p})
    clips = []
    for key, lst in sorted(per.items()):
        lst.sort(key=lambda c: C.seed_of(c["path"], c["f0"]))
        cap = MAX_FLAT_PER_SPK if key[1] == "flat" else MAX_PER_CLASS_SPK
        clips += lst[:cap]
        rej["capped (per speaker x class)"] += max(0, len(lst) - cap)
    return clips, rej


def clip_audio(c: dict) -> tuple[np.ndarray, float, float]:
    """Returns (audio, truth_t0_ms, truth_t1_ms) in the clip's own time."""
    x = C.load_16k(c["path"])
    a = int(max(0, (c["t0_ms"] - 150) * 16))
    b = int(min(len(x), (c["t1_ms"] + 150) * 16))
    seg = x[a:b].astype(np.float32).copy()
    fade = 160
    if len(seg) > 2 * fade:
        r = np.linspace(0, 1, fade, dtype=np.float32)
        seg[:fade] *= r
        seg[-fade:] *= r[::-1]
    nl, nt = int(C.LEAD_S * 16000), int(C.TAIL_S * 16000)
    bg = C.own_background(C.trim_dead(x)[0], nl + nt)
    y = np.concatenate([bg[:nl], seg, bg[nl:]])
    t0 = 1000 * (nl + (c["t0_ms"] * 16 - a)) / 16000
    return y, t0, t0 + c["dur_ms"]


def contour_job(job: tuple) -> dict:
    c, snr, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    y, t0, t1 = clip_audio(c)
    x_seg = y[int(t0 * 16): int(t1 * 16)]
    rng = np.random.default_rng(C.seed_of(NAME, c["path"], c["f0"], snr))
    y, noise = C.mix_at(y, snr, rng, c["split"], ref_rms=C.active_rms(x_seg))
    ev = C.run_extractor(y, cfg)
    best, best_ov = None, 0.0
    for e in ev:
        ov = min(e["t_end_ms"], t1) - max(e["t_start_ms"], t0)
        if ov > best_ov:
            best, best_ov = e, ov
    rec = {"dataset": NAME, "path": c["path"], "speaker": c["speaker"], "split": c["split"], "snr": snr,
           "truth": c["label"], "truth_exc": c["exc_bucket"], "truth_dur": c["dur_bucket"], "truth_exc_st": c["exc_st"],
           "dur_ms": c["dur_ms"], "t0_ms": c["t0_ms"], "median_hz": c["median_hz"], **noise,
           "truth_span": [t0, t1]}
    rec.update(C.analyse(ev, y))
    rec["pred"] = best["label"] if best else "none"
    rec["pred_like"] = best["sounds_like"] if best else None
    if best is not None and best["label"] in CONTOURS:
        p = C.parse_line(best["text"])
        rec["pred_exc"], rec["pred_dur"] = p["pitch_change"], p["duration"]
    exp = {"rise": "swipe_up", "fall": "swipe_down", "arch": "swipe_right", "dip": "swipe_left", "flat": "long_press"}[c["label"]]
    acted = [a for a in rec["actions"] if a != "none"]
    rec["expected_action"] = exp
    rec["action_ok"] = acted == [exp]
    rec["extra_events"] = max(0, len(ev) - 1)
    return rec


def contour_jobs(split: str, cfg_path: str | None) -> tuple[list[tuple], Counter]:
    clips, rej = contour_clips(split)
    return [(c, snr, cfg_path) for c in clips for snr in C.SNRS], rej


def contour_summary(recs: list[dict]) -> dict:
    s = {"n": len(recs)}
    cols = C.LABELS + ["none"]
    s["columns"] = cols
    for snr in C.SNRS:
        rs = [r for r in recs if r["snr"] == snr]
        conf = {t: Counter() for t in CONTOURS}
        for r in rs:
            conf[r["truth"]][r["pred"]] += 1
        per = {t: C.rate(conf[t].get(t, 0), sum(conf[t].values())) for t in CONTOURS}
        ok = [r for r in rs if r["pred"] == r["truth"]]
        exc = [r["pred_exc"] == r["truth_exc"] for r in ok if r.get("truth_exc") and r.get("pred_exc")]
        dur = [r["pred_dur"] == r["truth_dur"] for r in rs if r.get("truth_dur") and r.get("pred_dur")]
        s[snr] = {"n": len(rs), "acc": C.rate(len(ok), len(rs)), "per_class": per,
                  "balanced_acc": float(np.mean([v for v in per.values() if v is not None])) if rs else None,
                  "confusion": {t: dict(c) for t, c in conf.items()},
                  "exc_acc": C.rate(sum(exc), len(exc)), "exc_n": len(exc),
                  "dur_acc": C.rate(sum(dur), len(dur)), "dur_n": len(dur),
                  "action_ok": C.rate(sum(r["action_ok"] for r in rs), len(rs)),
                  "likes": dict(Counter(r["pred_like"] for r in rs)),
                  "extra_events_per_clip": C.rate(sum(r["extra_events"] for r in rs), len(rs))}
    s["line_errors"] = sum(len(r["line_errors"]) for r in recs)
    s["lines"] = sum(len(r["events"]) for r in recs)
    s["ood"] = sum(len(r["ood"]) for r in recs)
    return s


def contour_markdown(s: dict, title: str) -> str:
    L = [f"### {title}\n"]
    rows = []
    for snr in C.SNRS:
        d = s[snr]
        rows.append([snr, d["n"], C.pct(d["acc"]), C.pct(d["balanced_acc"])] + [C.pct(d["per_class"][t]) for t in CONTOURS] +
                    [f"{C.pct(d['exc_acc'])} (n={d['exc_n']})", f"{C.pct(d['dur_acc'])} (n={d['dur_n']})", C.pct(d["action_ok"]),
                     C.num(d['extra_events_per_clip'], ".2f") if d["extra_events_per_clip"] is not None else "-"])
    L.append(C.md_table(["SNR", "clips", "contour acc %", "balanced %"] + CONTOURS +
                        ["excursion ok % (given contour ok)", "duration ok %", "end-to-end action ok %", "extra events/clip"], rows))
    L.append("\n'Sounds like' on the matched event:\n")
    L.append(C.md_table(["SNR"] + ["hum", "whistle", "talking", "laughing", "coughing", "background music", "background noise", "mouth sound", "None"],
                        [[snr] + [s[snr]["likes"].get(k, 0) for k in ["hum", "whistle", "talking", "laughing", "coughing", "background music",
                                                                     "background noise", "mouth sound", None]] for snr in C.SNRS]))
    for snr in C.SNRS:
        L.append(f"\nConfusion at {snr} (rows = manual-pitch truth, columns = matched event label):\n")
        L.append(C.confusion_md({t: Counter(v) for t, v in s[snr]["confusion"].items()}, s["columns"]))
    L.append(f"\nLines: {s['lines']}; strict-parse/label errors: {s['line_errors']}; outside generate.py's line space: {s['ood']}\n")
    return "\n".join(L)


def pitch_markdown(p: dict, title: str) -> str:
    rows = [[k, (C.pct(v) if isinstance(v, float) and v <= 1 and "cents" not in k else (f"{v:.1f}" if isinstance(v, float) else v))]
            for k, v in p.items()]
    return f"### {title}\n\n" + C.md_table(["metric", "value (%, or cents)"], rows) + "\n"
