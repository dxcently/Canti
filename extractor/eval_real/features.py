#!/usr/bin/env python3
"""Per-event feature export: every event on every dataset run, plus the user's live recordings.

  ./run python eval_real/features.py export --tag frozen      # -> results/real_features_<tag>_clips.jsonl
  ./run python eval_real/features.py live --tag fixed          # appends the live-recording events (current code)

One JSON row per emitted-or-dropped event. The rows feed the cross-speaker cue analysis (cues.py), the
v6 personalization work (fp1 / enrollment matching) and the "sounds like" categories planned for v6.
Fields:
  dataset, split, speaker, group (what the SOURCE is, see group_of), cls (the dataset's own class), snr, path
  t0, t1, label, like, gate (policy not-deliberate reason or null), fire (action if judged alone)
  f0_med_hz, f0_range_st (max - min of the smoothed contour), pitch_resid_std_st, pitch_rough_st,
  pitch_jumps_hz, excursion_st, net_st  - f0 statistics (0 / null when unpitched)
  e1k, e35f0, hnr_db, logmel8[8], mfcc13[13]  - offline spectral features (common.brightness)
  every classify() raw feature kept by common.slim (voiced_frac, clarity_med, centroid, flatness, ...)
  contour64 (semitones re start) when pitched
The file matches /extractor/results/*_clips.jsonl in the repo .gitignore (it is regenerable).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

RUNS = C.CACHE / "runs"
LIVE_GROUPS = {"105946": "meow", "110107": "yell"}
CLICK_SESSIONS = {"105534", "105559", "105615"}
LIVE_TALK = {("105133", 5129), ("105133", 6139), ("105004", 3759)}
NV_GROUP = {"tongue-clicking": "click", "lip-popping": "pop", "lip-smacking": "smack", "screaming": "yell"}
N7_GROUP = {"screaming": "yell", "laugh": "laughing", "cough": "coughing"}


def group_of(ds: str, rec: dict, ev: dict) -> str:
    if ds == "nonverbal":
        return NV_GROUP.get(rec["cls"], rec["cls"])
    if ds == "qbsh_contour":
        return "sung"          # QBSH: people humming / singing a melody ("da da"), clipped to one note run
    if ds == "musan":
        return {"speech": "speech", "music": "music", "noise": "noise"}[rec["kind"]] if "kind" in rec else rec.get("cls", "musan")
    if ds == "mlend":
        return rec["interp"]   # hum / whistle
    if ds == "nonspeech7k":
        return N7_GROUP.get(rec["cls"], rec["cls"])
    if ds == "esc50":
        return "cat" if rec["cls"] == "cat" else "env:" + rec["cls"]
    return "?"


def row(ds: str, rec: dict, ev: dict, fire: str) -> dict:
    r = ev["raw"]
    out = {"dataset": ds, "split": rec.get("split"), "speaker": rec.get("speaker"), "group": group_of(ds, rec, ev),
           "cls": rec.get("cls", rec.get("interp", rec.get("kind"))), "snr": rec.get("snr", "clean"), "path": rec.get("path"),
           "t0": ev["t0"], "t1": ev["t1"], "label": ev["label"], "like": ev["like"], "gate": ev["gate"], "fire": fire}
    out.update(features_from_raw(r))
    return out


def features_from_raw(r: dict) -> dict:
    out = {k: v for k, v in r.items() if k != "contour64"}
    mx, mn = r.get("max_st"), r.get("min_st")
    out["f0_range_st"] = round(mx - mn, 2) if mx is not None and mn is not None else None
    if r.get("contour64"):
        out["contour64"] = r["contour64"]
    return out


def cmd_export(a) -> None:
    out = C.RESULTS / f"real_features_{a.tag}_clips.jsonl"
    n = 0
    with out.open("w") as fh:
        for p in sorted((RUNS / a.tag).glob("*.jsonl")):
            ds, split = p.stem.rsplit("_", 1)
            if ds == "qbsh_pitch":
                continue
            for rec in C.read_jsonl(p):
                for ev, fire in zip(rec.get("events", []), rec.get("fire", [])):
                    fh.write(json.dumps(row(ds, rec, ev, fire)) + "\n")
                    n += 1
    print(f"wrote {n} event rows -> {out}")


def live_rows(cfg_path: str | None = None) -> list[dict]:
    """Current code on the user's live recordings (48 kHz path), each event with the same features."""
    from vox_extract import Config
    from vox_extract.extractor import Extractor, load_wav
    from vox_extract.resample import Decimator3
    rows = []
    for d in sorted((C.ROOT / "recordings").glob("live-20260926-*")):
        sid = d.name.split("-")[-1]
        meta = json.loads((d / "session.json").read_text())
        cfg = Config.load(cfg_path) if cfg_path else Config.from_dict(meta["config"])
        x, sr = load_wav(d / "session.wav")
        ex = Extractor(cfg, input_rate=sr)
        evs = []
        blk = sr // 20
        for i in range(0, x.size, blk):
            evs += ex.push(x[i:i + blk])
        evs = [e.to_dict() for e in evs + ex.flush()]
        y = Decimator3().push(x) if sr == 48000 else C.to_16k(x, sr)
        res = C.analyse(evs, np.asarray(y, dtype=np.float64))
        for ev, fire in zip(res["events"], res["fire"]):
            f0 = ev["raw"].get("f0_med_hz") or 0
            if sid in LIVE_GROUPS:
                g = LIVE_GROUPS[sid]
            elif any(sid == s and abs(ev["t0"] - t) <= 150 for s, t in LIVE_TALK):
                g = "talk"
            elif ev["label"] in ("pop", "click", "hiss"):
                g = ev["label"] if sid not in CLICK_SESSIONS else "click"
            elif ev["label"] == "unknown":
                g = "blip"
            else:
                g = "whistle" if f0 >= 600 else "hum"
            rows.append({"dataset": "live", "split": "live", "speaker": "user", "group": g, "cls": sid, "snr": "clean",
                         "path": str(d / "session.wav"), "t0": ev["t0"], "t1": ev["t1"], "label": ev["label"], "like": ev["like"],
                         "gate": ev["gate"], "fire": fire, **features_from_raw(ev["raw"])})
    return rows


def cmd_live(a) -> None:
    out = C.RESULTS / f"real_features_{a.tag}_clips.jsonl"
    rows = live_rows(a.cfg)
    keep = [json.loads(l) for l in out.read_text().splitlines() if l.strip() and '"dataset": "live"' not in l] if out.exists() else []
    with out.open("w") as fh:
        for r in keep + rows:
            fh.write(json.dumps(r) + "\n")
    print(f"{len(rows)} live event rows (+{len(keep)} dataset rows) -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--tag", default="frozen")
    lv = sub.add_parser("live")
    lv.add_argument("--tag", default="frozen")
    lv.add_argument("--cfg", default=None)
    a = ap.parse_args()
    {"export": cmd_export, "live": cmd_live}[a.cmd](a)


if __name__ == "__main__":
    main()
