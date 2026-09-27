"""Phone-mic over media, offline: how well hums and pops survive a video playing on the phone, and how often the
video alone would make Canti act. The extractor is the Python reference (vox_extract, what the C port reproduces).

    ./run python ../android/tools/phone_media_eval.py run  --out R.jsonl [--cfg cfg.json] [--limit N]
    ./run python ../android/tools/phone_media_eval.py score R.jsonl [R2.jsonl ...]      (from extractor/)

run: every job is [6 s of media alone] + [a test clip mixed into the media at SNR dB] + [1.5 s of media]:
- media: a MUSAN speech or music excerpt (test split), level-normalised; the lead-in lets the noise floor settle on
  the media as it does while a video plays;
- clips: the user's own gestures (extractor/recordings/live-20260926-*, CMEDIA Q9, private: read, never copied):
  every sound whose group acts in the clean recording, cut with 400 ms around it (the negative sessions, meowing
  and yelling, are skipped); MIR-QBSH hum contours (eval_real/qbsh.py's cuts, test split); nonverbal lip pops and
  tongue clicks (eval_real/nonverbal.py's positives, test split; the extractor mostly reads these as hiss, so they
  mainly check that clicks stay idle); synthetic pops, click-pops, hisses, hums and whistles (synth.py, --n-syn per
  class), the only clean pop and whistle positives there are;
- SNR: the clip's active RMS over the media's RMS, in {10, 5, 0, -5} dB (a phone speaker a few cm from its own mic
  is loud: 0 dB and below is the realistic range without an echo canceller), plus "clean" (the clip alone);
- media-alone runs (60 s excerpts) give the false triggers per minute.
Records keep the events (label, text, raw gate numbers), never audio.

score: survival (of the clips whose expected action comes out clean, the share that still gets it over media: the
dataset's own misses, e.g. QBSH's sung phrases read as talking, are factored out), wrong actions on the clip, false
triggers per minute on media alone, for the app-side gate variants in GATES (a gate sees one event's raw numbers and
passes it or not; a gated event stays in the grouping as "unknown", i.e. not deliberate, so it still blocks its
group, as the app does). Uses vox_extract.policy (the Python mirror
of RuleDecider's not-deliberate rules and the default bindings).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

EXTRACTOR = Path(__file__).resolve().parents[2] / "extractor"
sys.path.insert(0, str(EXTRACTOR))
sys.path.insert(0, str(EXTRACTOR / "eval_real"))

import common as C  # noqa: E402
import musan  # noqa: E402
import nonverbal  # noqa: E402
import qbsh  # noqa: E402
from vox_extract.policy import action_for, group  # noqa: E402

SNRS = ["clean", 10, 5, 0, -5]
REC = EXTRACTOR / "recordings"
NEG_SESSIONS = {"105946", "110107"}      # eval_real/live_replay.py: the user meowing, yelling
LEAD_S, TAIL_S = 6.0, 1.5
KEEP_RAW = ("dur_ms", "snr_db", "level_db", "floor_db", "voiced_frac", "strong_voiced_frac", "clarity_med",
            "f0_med_hz", "onset_flux_db", "energy_iqr_db", "excursion_st", "net_st", "pitch_jumps_hz",
            "pitch_resid_std_st", "centroid_spread_oct", "voiced_runs", "syllable_peaks", "impulsive", "tonal",
            "flatness", "decay_db", "core_ms", "speech_cues", "why")
EXPECTED = {"rise": "swipe_up", "fall": "swipe_down", "arch": "swipe_right", "dip": "swipe_left", "flat": "long_press",
            "pop": "tap", "click": None,   # a single click is bound to nothing: it must just not do anything else
            "hiss": "back", "click_pop": "listen_for_phrase", "whistle_rise": "swipe_up", "whistle_fall": "swipe_down"}
SYN_CLASSES = ["pop", "click_pop", "hiss", "rise", "fall", "whistle_rise", "whistle_fall"]   # synth.py, per class
KINDS = ["user", "hum", "pop", "syn", "media"]


def user_items() -> list[dict]:
    """The user's sounds that act in the clean recording: {session, wav, t0, t1, label, action}."""
    from vox_extract import Config
    out = []
    cfg = Config()
    for d in sorted(REC.glob("live-20260926-*")):
        sid = d.name.split("-")[-1]
        if sid in NEG_SESSIONS or not (d / "session.wav").exists() or (d / "session.wav").stat().st_size > 20e6:
            # (the two long unlabelled sessions, 171632 and 184251, have no notes: not usable as positives)
            continue
        x = C.load_16k(d / "session.wav")
        ev = C.run_extractor(x, cfg)
        for g in group(ev):
            a = action_for([(e["label"], e["text"]) for e in g])
            if a != "none":
                out.append({"path": str(d / "session.wav"), "session": sid, "t0_ms": g[0]["t_start_ms"],
                            "t1_ms": g[-1]["t_end_ms"], "label": "+".join(e["label"] for e in g), "action": a})
    return out


def user_clip(c: dict) -> tuple[np.ndarray, float, float]:
    x = C.load_16k(c["path"])
    a = int(max(0, (c["t0_ms"] - 400) * 16))
    b = int(min(len(x), (c["t1_ms"] + 400) * 16))
    seg = x[a:b].astype(np.float32).copy()
    fade = 160
    r = np.linspace(0, 1, fade, dtype=np.float32)
    seg[:fade] *= r
    seg[-fade:] *= r[::-1]
    nl, nt = int(C.LEAD_S * 16000), int(C.TAIL_S * 16000)
    bg = C.own_background(C.trim_dead(x)[0], nl + nt)
    y = np.concatenate([bg[:nl], seg, bg[nl:]])
    t0 = 1000 * (nl + (c["t0_ms"] * 16 - a)) / 16000
    return y, t0, t0 + (c["t1_ms"] - c["t0_ms"])


def media_files() -> list[dict]:
    return [f for f in musan.files() if f["kind"] in ("speech", "music") and f["split"] == "test"]


def media_excerpt(f: dict, n: int, rng: np.random.Generator) -> np.ndarray:
    import soundfile as sf
    info = sf.info(f["path"])
    need = n / 16000 * info.samplerate
    start = int(rng.uniform(0, max(1.0, info.frames - need)))
    x, sr = sf.read(f["path"], start=start, frames=int(min(info.frames, need + 16000)), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != 16000:
        x = C.to_16k(x, sr)
    x = C.trim_dead(x)[0]
    if len(x) < n:
        x = np.tile(x, int(np.ceil(n / max(1, len(x)))))
    x = x[:n].astype(np.float32)
    r = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) or 1.0
    return x * (0.05 / r)            # -26 dBFS rms: a video at a normal volume, before the clip's SNR scaling


def slim(e: dict) -> dict:
    r = e.get("raw", {})
    return {"t0": e["t_start_ms"], "t1": e["t_end_ms"], "label": e["label"], "like": e.get("sounds_like"),
            "text": e["text"], "raw": {k: r[k] for k in KEEP_RAW if k in r}}


def job_clip(job: tuple) -> dict:
    kind, c, snr, mf, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    rng = np.random.default_rng(C.seed_of("phone_media", kind, c["path"], c.get("f0", ""), snr, mf["path"]))
    if kind == "hum":
        y, t0, t1 = qbsh.clip_audio(c)
        truth = c["label"]
    elif kind == "user":
        y, t0, t1 = user_clip(c)
        truth = c["action"]
    elif kind == "syn":
        import synth
        clip = synth.make_clip(c["cls"], np.random.default_rng(c["seed"]), snr_db=35.0, bg="pink")
        y, (t0, t1) = clip.audio, clip.span
        truth = c["cls"]
    else:
        x = C.load_16k(c["path"])
        y, off, cut = C.pad_clip(x)
        a = C.trim_dead(x)[0]
        t0, t1 = 1000 * off / 16000, 1000 * (off + len(a)) / 16000
        truth = nonverbal.POS[c["cls"]]
    seg = y[int(t0 * 16): int(t1 * 16)]
    ref = C.active_rms(seg) if len(seg) > 320 else C.active_rms(y)
    if snr == "clean":
        ev = [slim(e) for e in C.run_extractor(y, cfg)]
        return {"kind": kind, "truth": truth, "snr": snr, "media": None, "clip": c["path"], "item": _item(kind, c),
                "span": [t0, t1], "dur_ms": t1 - t0, "events": ev, "total_ms": 1000 * len(y) / 16000}
    lead, tail = int(LEAD_S * 16000), int(TAIL_S * 16000)
    m = media_excerpt(mf, lead + len(y) + tail, rng)
    mr = float(np.sqrt(np.mean(m.astype(np.float64) ** 2))) or 1.0
    g = ref / (mr * 10 ** (snr / 20))
    z = m * g                                      # keep the clip's level, scale the media to ref / 10^(snr/20)
    out = z.copy()
    out[lead: lead + len(y)] += y
    peak = float(np.max(np.abs(out)))
    if peak > 0.99:
        out *= 0.99 / peak
    ev = [slim(e) for e in C.run_extractor(out, cfg)]
    span = [LEAD_S * 1000 + t0, LEAD_S * 1000 + t1]
    return {"kind": kind, "truth": truth, "snr": snr, "media": mf["kind"], "media_path": mf["path"],
            "clip": c["path"], "item": _item(kind, c), "span": span, "dur_ms": t1 - t0, "events": ev,
            "total_ms": 1000 * len(out) / 16000}


def _item(kind: str, c: dict) -> str:
    return f"{kind}:{c['path']}:{c.get('t0_ms', '')}:{c.get('f0', '')}"


def job_media(job: tuple) -> dict:
    mf, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    rng = np.random.default_rng(C.seed_of("phone_media_alone", mf["path"]))
    m = media_excerpt(mf, 60 * 16000, rng)
    ev = [slim(e) for e in C.run_extractor(m, cfg)]
    return {"kind": "media", "media": mf["kind"], "media_path": mf["path"], "events": ev, "total_ms": 60000.0}


def build_jobs(cfg_path: str | None, limit: int | None, seed: int = 7, kinds=tuple(KINDS),
               n_syn: int = 40) -> list[tuple]:
    rng = np.random.default_rng(seed)
    media = media_files()
    clips, _ = qbsh.contour_clips("test")
    rng.shuffle(clips)
    pops = [f for f in nonverbal.files() if f["split"] == "test" and nonverbal.role(f["cls"]) == "pos"]
    rng.shuffle(pops)
    if limit:
        clips, pops = clips[:limit], pops[:max(1, limit // 2)]
    syn = [{"path": f"syn:{cls}:{i}", "cls": cls, "seed": 1000 * j + i}
           for j, cls in enumerate(SYN_CLASSES) for i in range(n_syn)]
    jobs: list[tuple] = []
    # every kind draws its media from rng in the same order whether it runs or not, so a partial run pairs the
    # same clip with the same media as a full one
    for kind, items in (("user", user_items() if "user" in kinds else []), ("hum", clips), ("pop", pops),
                        ("syn", syn)):
        for c in items:
            for snr in SNRS:
                mf = media[int(rng.integers(len(media)))]
                if kind in kinds:
                    jobs.append((kind, c, snr, mf, cfg_path))
    alone = list(media)
    rng.shuffle(alone)
    return jobs + ([("media", m, cfg_path) for m in alone[: (limit * 2 if limit else 400)]] if "media" in kinds else [])


def run_job(job: tuple) -> dict:
    return job_media(job[1:]) if job[0] == "media" else job_clip(job)


# --------------------------------------------------------------------------------------------------- gates

def g_none(e: dict) -> bool:
    return True


def _hum(e):
    return e["label"] in ("rise", "fall", "arch", "dip", "flat")


def g_strict_hum(e: dict) -> bool:
    """Hums: a steadily voiced, clear tone well over the floor (media is choppy: speech breaks, music has jumps)."""
    r = e["raw"]
    if _hum(e):
        return (r.get("strong_voiced_frac", 0) >= 0.8 and r.get("clarity_med", 0) >= 0.8 and r.get("snr_db", 0) >= 12
                and r.get("pitch_jumps_hz", 0) < 0.8)
    return True


def g_strict_pop(e: dict) -> bool:
    """(Rejected: onset flux >= 9 also drops 87 % of clean synthetic pops.)"""
    r = e["raw"]
    if e["label"] in ("pop", "click"):
        return r.get("snr_db", 0) >= 20 and r.get("onset_flux_db", 0) >= 9
    return True


def g_strict(e: dict) -> bool:
    return g_strict_hum(e) and g_strict_pop(e)


def g_app(e: dict) -> bool:
    """The app's PhoneGate (android .../audio/PhoneGate.kt), applied while media plays on the phone's speaker."""
    r = e["raw"]
    if e["label"] in ("pop", "click"):
        return r.get("snr_db", 0) >= 14
    if _hum(e):
        return r.get("snr_db", 0) >= 14 and r.get("clarity_med", 0) >= 0.8
    return True


GATES = {"none": g_none, "app": g_app, "strict_hum": g_strict_hum, "strict_pop": g_strict_pop, "strict": g_strict}


def score(recs: list[dict], gate) -> dict:
    out: dict = {}
    rows: dict = {}
    per_item: dict = {}
    for r in recs:
        # a gated sound is kept as "unknown" (not deliberate), so it still blocks its group like the app will;
        # deleting it instead would let a neighbour act on its own
        evs = [e if gate(e) else {**e, "label": "unknown"} for e in r["events"]]
        seq = [{"t_start_ms": e["t0"], "t_end_ms": e["t1"], **e} for e in evs]
        groups = group(seq)
        acts = [(g, action_for([(e["label"], e["text"]) for e in g])) for g in groups]
        if r["kind"] == "media":
            k = ("media alone", r["media"])
            d = rows.setdefault(k, {"minutes": 0.0, "fires": 0})
            d["minutes"] += r["total_ms"] / 60000
            d["fires"] += sum(1 for _, a in acts if a != "none")
            continue
        s0, s1 = r["span"]
        over = [(g, a) for g, a in acts if min(g[-1]["t1"], s1 + 300) - max(g[0]["t0"], s0 - 300) > 0]
        outside = [(g, a) for g, a in acts if (g, a) not in over and g[0]["t0"] >= LEAD_S * 1000 - 1]
        exp = r["truth"] if r["kind"] == "user" else EXPECTED[r["truth"]]
        fired = [a for _, a in over if a != "none"]
        ok = (fired == [exp]) if exp else not fired
        cls = {"pop": "pop", "user": "user/" + str(exp), "syn": "syn/" + r["truth"]}.get(r["kind"], "qbsh/" + r["truth"])
        per_item[(r["item"], r["snr"])] = (cls, ok, any(a != exp for a in fired))
    clean_ok = {it for (it, snr), (_, ok, _) in per_item.items() if snr == "clean" and ok}
    for (it, snr), (cls, ok, wrong) in per_item.items():
        for c in (cls, cls.split("/")[0] + "/ALL") if "/" in cls else (cls,):
            d = rows.setdefault((c, snr), {"n": 0, "ok": 0, "wrong": 0, "n_clean_ok": 0, "survive": 0})
            d["n"] += 1
            d["ok"] += int(ok)
            d["wrong"] += int(wrong)
            if it in clean_ok:
                d["n_clean_ok"] += 1
                d["survive"] += int(ok)
    order = {s: i for i, s in enumerate(SNRS)}
    for k, d in sorted(rows.items(), key=lambda kv: (str(kv[0][0]), order.get(kv[0][1], -1))):
        if "minutes" in d:
            out[f"{k[0]}/{k[1]}"] = {"fa_per_min": round(d["fires"] / max(d["minutes"], 1e-9), 2),
                                     "minutes": round(d["minutes"], 1)}
        else:
            out[f"{k[0]}@{k[1]}"] = {"n": d["n"], "acts": round(d["ok"] / d["n"], 3),
                                     "survival": round(d["survive"] / d["n_clean_ok"], 3) if d["n_clean_ok"] else None,
                                     "of": d["n_clean_ok"], "wrong": round(d["wrong"] / d["n"], 3)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--cfg", default=None)
    r.add_argument("--limit", type=int, default=None, help="hum clips (pops: half)")
    r.add_argument("--workers", type=int, default=C.WORKERS)
    r.add_argument("--kinds", nargs="*", default=KINDS, choices=KINDS)
    r.add_argument("--n-syn", type=int, default=40, help="synthetic clips per class")
    s = sub.add_parser("score")
    s.add_argument("runs", nargs="+", type=Path)
    s.add_argument("--gates", nargs="*", default=["none", "app"], choices=list(GATES))
    s.add_argument("--merge", action="store_true", help="score the runs as one set (e.g. a base run + a syn run)")
    a = ap.parse_args()
    if a.cmd == "run":
        jobs = build_jobs(a.cfg, a.limit, kinds=tuple(a.kinds), n_syn=a.n_syn)
        recs = C.pmap(run_job, jobs, workers=a.workers)
        with a.out.open("w") as f:
            for rec in recs:
                f.write(json.dumps(rec) + "\n")
        print(f"{len(recs)} records -> {a.out}")
        return 0
    sets = [(" + ".join(p.name for p in a.runs), [json.loads(line) for p in a.runs for line in p.open()])] if a.merge \
        else [(p.name, [json.loads(line) for line in p.open()]) for p in a.runs]
    for name, recs in sets:
        print(f"== {name}")
        for gname in a.gates:
            print(f"-- gate {gname}")
            for k, v in score(recs, GATES[gname]).items():
                print(f"   {k:28s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
