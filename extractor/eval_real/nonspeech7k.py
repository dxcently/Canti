"""Nonspeech7k (Rashid et al., IET Signal Processing 2023; Zenodo 10.5281/zenodo.6967442) as NEGATIVES.

Seven classes of human non-speech sound: breath, cough, crying, laugh, screaming, sneeze, yawn. Clips are
0.5-4 s, 32 kHz mono, cut from freesound / YouTube / Aigei recordings. Only "Original" rows are used (the
metadata also lists augmented copies). There are no speaker IDs; File_ID (the source recording) stands in for
the speaker, so segments of one source recording never land in both splits. Train and test folders of the
corpus are pooled and re-split by File_ID (30 % tune / 70 % test).
Rate handling: 32 kHz -> 16 kHz with scipy resample_poly (resample.to_16k), not the 48 kHz decimator.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

NAME = "nonspeech7k"
ROOT = C.DATA / "nonspeech7k"


def files() -> list[dict]:
    out = []
    for meta, folder in (("metadata of train set .csv", "train"), ("metadata of test set.csv", "test")):
        with (ROOT / meta).open(newline="", errors="replace") as fh:
            for raw in csv.DictReader(fh):
                # the two CSVs spell their headers differently ("File ID" / "File_ID", "Augmentation  type" /
                # "Augmentation type") and the train CSV says "Orignal": normalise keys, match on a prefix
                row = {"".join(ch for ch in (k or "").lower() if ch.isalnum()): (v or "").strip() for k, v in raw.items()}
                if not row.get("augmentationtype", "original").lower().startswith("orig"):
                    continue
                p = ROOT / folder / row["filename"]
                if not p.exists():
                    continue
                fid = row["fileid"]
                out.append({"path": str(p), "cls": {"yawm": "yawn"}.get(row["classname"], row["classname"]), "speaker": fid,
                            "split": C.split_of(NAME, fid), "orig_split": folder, "source": row.get("source", "")})
    return out


def jobs(split: str, cfg_path: str | None) -> list[tuple]:
    return [(f, cfg_path) for f in files() if f["split"] == split]


def run_job(job: tuple) -> dict:
    f, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    x = C.load_16k(f["path"])
    y, off, cut = C.pad_clip(x)
    ev = C.run_extractor(y, cfg)
    rec = {"dataset": NAME, **f, "dur_s": len(C.trim_dead(x)[0]) / 16000}
    rec.update(C.analyse(ev, y))
    return rec


def summarise(recs: list[dict]) -> dict:
    s = {}
    for cls in sorted({r["cls"] for r in recs}) + ["ALL"]:
        rs = [r for r in recs if cls == "ALL" or r["cls"] == cls]
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
    L.append(C.md_table(["class", "clips", "min", "clips with FA %", "FA groups/min", "fireable events/min", "actions"],
                        [[k, s[k]["clips"], C.num(s[k]['minutes'], ".1f"), C.pct(s[k]["fa_clip_rate"]), C.num(s[k]['fa_per_min'], ".2f"),
                          C.num(s[k]['fireable_per_min'], ".2f"), ", ".join(f"{a} {n}" for a, n in sorted(s[k]["actions"].items(), key=lambda kv: -kv[1]))]
                         for k in cl]))
    L.append("\n'Sounds like' of all events (counts):\n")
    L.append(C.md_table(["class"] + LIKES, [[k] + [s[k]["likes"].get(x, 0) for x in LIKES] for k in cl]))
    L.append(f"\nLines: {s['lines']}; strict-parse/label errors: {s['line_errors']}; outside generate.py's line space: {s['ood']}\n")
    return "\n".join(L)
