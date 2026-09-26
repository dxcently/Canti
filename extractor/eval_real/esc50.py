"""ESC-50 (Piczak 2015, CC BY-NC 3.0): 2000 five-second environmental clips, 50 classes, 44.1 kHz mono, as
NEGATIVES. The class of interest is "cat" (40 clips, mostly meows): a real cat near the phone is the realistic
version of the user-meow false accepts. Every other class is reported too (dog, crying baby, door knock,
mouse click, keyboard typing, clock tick, snoring, breathing ...), because impulsive household sounds are the
obvious threat to pop / click.

One extra meow: MUSAN noise/sound-bible/noise-sound-bible-0013 ("Cat Meow 2") is scored in the cat row as well.
Split: by src_file (the freesound recording a clip was cut from), 30 % tune / 70 % test.
Rate handling: 44.1 kHz -> 16 kHz with scipy resample_poly (resample.to_16k). ESC-50 pads short sounds with
digital silence; leading / trailing silence is trimmed like everywhere else, but silence INSIDE a clip stays and
drops the noise floor to its -85 dB clamp, which makes the gate very sensitive there (a mic never gives exact zeros).
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

NAME = "esc50"
ROOT = C.DATA / "esc50" / "ESC-50-master"
MUSAN_MEOW = C.DATA / "musan" / "musan" / "noise" / "sound-bible" / "noise-sound-bible-0013.wav"


def files() -> list[dict]:
    out = []
    with (ROOT / "meta" / "esc50.csv").open() as fh:
        for row in csv.DictReader(fh):
            src = row["src_file"]
            out.append({"path": str(ROOT / "audio" / row["filename"]), "cls": row["category"], "speaker": src,
                        "split": C.split_of(NAME, src)})
    if MUSAN_MEOW.exists():
        out.append({"path": str(MUSAN_MEOW), "cls": "cat", "speaker": "musan-meow", "split": "test", "source": "musan"})
    return out


def jobs(split: str, cfg_path: str | None) -> list[tuple]:
    return [(f, cfg_path) for f in files() if f["split"] == split]


def run_job(job: tuple) -> dict:
    f, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    x = C.load_16k(f["path"])
    y, off, cut = C.pad_clip(x)
    ev = C.run_extractor(y, cfg)
    shift = int(1000 * (off - cut) / 16000)
    for e in ev:
        e["t_start_ms"] -= shift
        e["t_end_ms"] -= shift
    rec = {"dataset": NAME, **f, "dur_s": len(C.trim_dead(x)[0]) / 16000}
    rec.update(C.analyse(ev, y, shift))
    return rec


def summarise(recs: list[dict]) -> dict:
    s = {}
    classes = sorted({r["cls"] for r in recs})
    for cls in ["cat"] + [c for c in classes if c != "cat"] + ["ALL"]:
        rs = [r for r in recs if cls == "ALL" or r["cls"] == cls]
        if not rs:
            continue
        mins = sum(r["dur_s"] for r in rs) / 60
        s[cls] = {"clips": len(rs), "minutes": mins,
                  "fa_clip_rate": C.rate(sum(1 for r in rs if any(a != "none" for a in r["actions"])), len(rs)),
                  "fa_per_min": sum(1 for r in rs for a in r["actions"] if a != "none") / mins if mins else None,
                  "fireable_per_min": sum(1 for r in rs for a in r["fire"] if a != "none") / mins if mins else None,
                  "actions": dict(Counter(a for r in rs for a in r["actions"] if a != "none")),
                  "likes": dict(Counter(e["like"] for r in rs for e in r["events"])),
                  "labels": dict(Counter(e["label"] for r in rs for e in r["events"]))}
    s["lines"] = sum(len(r["events"]) for r in recs)
    s["line_errors"] = sum(len(r["line_errors"]) for r in recs)
    s["ood"] = sum(len(r["ood"]) for r in recs)
    return s


LIKES = ["hum", "whistle", "talking", "laughing", "coughing", "background music", "background noise", "mouth sound"]


def markdown(s: dict, title: str) -> str:
    L = [f"### {title}\n"]
    cl = [k for k, v in s.items() if isinstance(v, dict)]
    cl_sorted = ["cat", "ALL"] + sorted([k for k in cl if k not in ("cat", "ALL")], key=lambda k: -(s[k]["fa_per_min"] or 0))
    L.append(C.md_table(["class", "clips", "min", "clips with FA %", "FA groups/min", "fireable events/min", "actions"],
                        [[k, s[k]["clips"], C.num(s[k]["minutes"], ".1f"), C.pct(s[k]["fa_clip_rate"]), C.num(s[k]["fa_per_min"]),
                          C.num(s[k]["fireable_per_min"]), ", ".join(f"{a} {n}" for a, n in sorted(s[k]["actions"].items(), key=lambda kv: -kv[1]))]
                         for k in cl_sorted if k in s]))
    L.append("\n'Sounds like' of all events, cat clips:\n")
    if "cat" in s:
        L.append(C.md_table(LIKES, [[s["cat"]["likes"].get(x, 0) for x in LIKES]]))
    L.append(f"\nLines: {s['lines']}; strict-parse/label errors: {s['line_errors']}; outside generate.py's line space: {s['ood']}\n")
    return "\n".join(L)
