#!/usr/bin/env python3
"""Before / after on the user's own live recordings (recordings/live-20260926-*, 48 kHz USB mic, ~11.5 s each).

"before" = the events.jsonl written at recording time (the frozen code + config; replaying the frozen code
reproduces it exactly). "after" = the current code with the given config (default: the session's own config).
The 48 kHz path (Decimator3) is exercised here, unlike the datasets (all <= 44.1 kHz, resampled offline).

Ground truth is what the user / coordinator reported by ear and spectrogram; sessions without notes are free,
unlabelled takes.

  ./run python eval_real/live_replay.py                       # current code, session configs
  ./run python eval_real/live_replay.py --config my.json      # current code, another config
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vox_extract import Config  # noqa: E402
from vox_extract.extractor import Extractor, load_wav  # noqa: E402
from vox_extract.policy import action_for, group  # noqa: E402

REC = ROOT / "recordings"

# session -> (what it contains, [(t_ms, expectation, predicate on the matched event or None)])
NOTES = {
    "104838": ("free: hums, whistles, talking", [(1039, "steady ~86 Hz hum (1.16 s): should NOT say talking",
                                                  lambda e: e is not None and e["sounds_like"] != "talking")]),
    "104919": ("free (unlabelled)", []),
    "105004": ("free: hums, whistles, talking", [(3759, "short spoken syllable: talking is right",
                                                  lambda e: e is None or e["sounds_like"] == "talking" or action_for([(e["label"], e["text"])]) == "none")]),
    "105021": ("free (unlabelled)", []),
    "105053": ("free: whistles, hums", [(989, "top of a rising whistle that starts ~600 ms: must not be a pop/click",
                                         lambda e: e is None or e["label"] not in ("pop", "click"))]),
    "105133": ("free: hums, talking", [(5129, "spoken syllable: talking is right", lambda e: e is None or e["sounds_like"] == "talking"),
                                        (6139, "spoken syllable: talking is right", lambda e: e is None or e["sounds_like"] == "talking")]),
    "105534": ("tongue + cheek clicks (no pops) + whistles", []),
    "105559": ("tongue + cheek clicks (no pops) + whistles", []),
    "105615": ("tongue + cheek clicks (no pops) + whistles", []),
    "105910": ("6 lip pops, 2 whistles, 1 hum, 2 hisses", [(669, "lip pop (70 ms): pop wanted; a non-action is a safe miss",
                                                            lambda e: e is not None and e["label"] == "pop"),
                                                           (8559, "hiss", lambda e: e is not None and e["label"] == "hiss"),
                                                           (9949, "hiss", lambda e: e is not None and e["label"] == "hiss")]),
    "105946": ("NEGATIVE: the user meowing 8 times", []),
    "110107": ("NEGATIVE: the user yelling / screaming", []),
}
CLICK_SESSIONS = {"105534", "105559", "105615"}
NEG_SESSIONS = {"105946", "110107"}


def run(d: Path, cfg: Config) -> list[dict]:
    x, sr = load_wav(d / "session.wav")
    ex = Extractor(cfg, input_rate=sr)
    out = []
    blk = sr // 20
    for i in range(0, x.size, blk):
        out += ex.push(x[i:i + blk])
    return [e.to_dict() for e in out + ex.flush()]


def near(evs: list[dict], t: int, tol: int = 150) -> dict | None:
    c = [e for e in evs if e["t_start_ms"] - tol <= t <= e["t_end_ms"] + tol]
    return min(c, key=lambda e: abs(e["t_start_ms"] - t)) if c else None


def tonal_discrete(evs: list[dict]) -> int:
    return sum(1 for e in evs if e["label"] in ("pop", "click", "hiss")
               and e["raw"].get("voiced_frac", 0) > 0.5 and e["raw"].get("clarity_med", 0) > 0.8)


def summary(sid: str, evs: list[dict]) -> dict:
    acts = [action_for([(e["label"], e["text"]) for e in g]) for g in group(evs)]
    checks = []
    for t, what, ok in NOTES.get(sid, ("", []))[1]:
        e = near(evs, t)
        checks.append({"t": t, "what": what, "event": (f"{e['t_start_ms']} {e['label']} / {e['sounds_like']}" if e else "none"),
                       "ok": bool(ok(e))})
    return {"n": len(evs), "labels": dict(Counter(e["label"] for e in evs)), "actions": [a for a in acts if a != "none"],
            "tonal_discrete": tonal_discrete(evs), "checks": checks,
            "events": [(e["t_start_ms"], e["t_end_ms"], e["label"], e["sounds_like"], round(e["raw"].get("f0_med_hz", 0)),
                        e["raw"].get("voiced_frac")) for e in evs]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=str(ROOT / "results" / "real_live_replay.json"))
    ap.add_argument("--tag", default="after")
    a = ap.parse_args()
    res = {}
    for d in sorted(REC.glob("live-20260926-*")):
        sid = d.name.split("-")[-1]
        meta = json.loads((d / "session.json").read_text())
        cfg = Config.load(a.config) if a.config else Config.from_dict(meta["config"])
        before = [json.loads(l) for l in (d / "events.jsonl").read_text().splitlines() if l.strip()]
        after = run(d, cfg)
        res[sid] = {"note": NOTES.get(sid, ("", []))[0], "before": summary(sid, before), a.tag: summary(sid, after)}
    outp = Path(a.out)
    old = json.loads(outp.read_text()) if outp.exists() else {}
    for sid, v in res.items():
        old.setdefault(sid, {}).update(v)
    outp.write_text(json.dumps(old, indent=1))
    for sid, v in res.items():
        b, f = v["before"], v[a.tag]
        print(f"{sid} [{v['note']}]  events {b['n']} -> {f['n']}  actions {b['actions']} -> {f['actions']}  "
              f"tonal pop/click/hiss {b['tonal_discrete']} -> {f['tonal_discrete']}  labels {b['labels']} -> {f['labels']}")
        for cb, cf in zip(b["checks"], f["checks"]):
            print(f"    @{cb['t']} {cb['what']}: {cb['event']} ({'ok' if cb['ok'] else 'WRONG'}) -> {cf['event']} ({'ok' if cf['ok'] else 'WRONG'})")
    print(f"wrote {outp}")


if __name__ == "__main__":
    main()
