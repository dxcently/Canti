"""MUSAN (OpenSLR 17) as NEGATIVES: speech/, music/ and noise/ must yield no gesture.

  * speech: librivox read speech (several languages) and US-government hearings (English). One file is one
    recording session; no speaker IDs are given, so the split is by file.
  * music: fma, fma-western-art, hd-classical, jamendo, rfm; split BY ARTIST (ANNOTATIONS column 4);
    vocals Y/N from ANNOTATIONS column 3.
  * noise: free-sound and sound-bible technical / ambient noises (DTMF, dial tones, rain, traffic, clapping,
    animals ...); split by file. The same split's noise files are what the other scripts mix into positives.
Each file contributes one excerpt of at most EXCERPT_S seconds (from OFFSET_S in, or the whole file if it is
short). All MUSAN audio is 16 kHz mono.

A negative "false accept" = a phone-style group (gap <= 600 ms) whose default-profile action is not none.
We also report fireable events per minute (each event judged alone) and the "sounds like" distribution: speech
should say "talking", music "background music", but the requirement is only "no gesture".
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

NAME = "musan"
ROOT = C.DATA / "musan" / "musan"
EXCERPT_S = 60.0
OFFSET_S = 20.0


def _annotations(d: Path) -> dict[str, list[str]]:
    out = {}
    a = d / "ANNOTATIONS"
    if a.exists():
        for line in a.read_text(errors="replace").splitlines():
            parts = line.split()
            if parts and parts[0].startswith(("music-", "speech-", "noise-")):
                out[parts[0]] = parts[1:]
    return out


def files() -> list[dict]:
    out = []
    for kind in ("speech", "music", "noise"):
        for sub in sorted(p for p in (ROOT / kind).iterdir() if p.is_dir()):
            ann = _annotations(sub)
            for w in sorted(sub.glob("*.wav")):
                meta = ann.get(w.stem, [])
                if kind == "music":
                    spk = meta[2] if len(meta) >= 3 else w.stem
                    vocals = (meta[1] == "Y") if len(meta) >= 2 else None
                else:
                    spk, vocals = w.stem, None
                split = C.split_of(f"musan-{kind}", spk) if kind != "noise" else C.split_of("musan-noise", w.stem)
                out.append({"path": str(w), "kind": kind, "source": sub.name, "speaker": spk, "split": split,
                            "vocals": vocals})
    return out


def jobs(split: str, cfg_path: str | None) -> list[tuple]:
    return [(f, cfg_path) for f in files() if f["split"] == split]


def run_job(job: tuple) -> dict:
    f, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    import soundfile as sf
    info = sf.info(f["path"])
    total = info.frames / info.samplerate
    start = OFFSET_S if total > OFFSET_S + EXCERPT_S else max(0.0, total - EXCERPT_S)
    x, sr = sf.read(f["path"], start=int(start * info.samplerate), frames=int(EXCERPT_S * info.samplerate), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != 16000:
        x = C.to_16k(x, sr)
    y, off, cut = C.pad_clip(x)
    ev = C.run_extractor(y, cfg)
    rec = {"dataset": NAME, **f, "dur_s": len(C.trim_dead(x)[0]) / 16000, "excerpt_start_s": start}
    rec.update(C.analyse(ev, y))
    return rec


def summarise(recs: list[dict]) -> dict:
    s = {}
    groups = {"speech (all)": lambda r: r["kind"] == "speech",
              "speech/librivox": lambda r: r["source"] == "librivox",
              "speech/us-gov": lambda r: r["source"] == "us-gov",
              "music (all)": lambda r: r["kind"] == "music",
              "music with vocals": lambda r: r["kind"] == "music" and r["vocals"] is True,
              "music without vocals": lambda r: r["kind"] == "music" and r["vocals"] is False,
              "noise (all)": lambda r: r["kind"] == "noise"}
    for g, fn in groups.items():
        rs = [r for r in recs if fn(r)]
        mins = sum(r["dur_s"] for r in rs) / 60
        fa = sum(1 for r in rs for a in r["actions"] if a != "none")
        fire = sum(1 for r in rs for a in r["fire"] if a != "none")
        evs = [e for r in rs for e in r["events"]]
        s[g] = {"files": len(rs), "minutes": mins, "fa_per_min": fa / mins if mins else None,
                "fireable_per_min": fire / mins if mins else None,
                "files_with_fa": C.rate(sum(1 for r in rs if any(a != "none" for a in r["actions"])), len(rs)),
                "events_per_min": len(evs) / mins if mins else None,
                "actions": dict(Counter(a for r in rs for a in r["actions"] if a != "none")),
                "likes": dict(Counter(e["like"] for e in evs)), "labels": dict(Counter(e["label"] for e in evs)),
                "fa_labels": dict(Counter(e["label"] for r in rs for e, a in zip(r["events"], r["fire"]) if a != "none"))}
    s["lines"] = sum(len(r["events"]) for r in recs)
    s["line_errors"] = sum(len(r["line_errors"]) for r in recs)
    s["ood"] = sum(len(r["ood"]) for r in recs)
    return s


LIKES = ["hum", "whistle", "talking", "laughing", "coughing", "background music", "background noise", "mouth sound"]


def markdown(s: dict, title: str) -> str:
    L = [f"### {title}\n"]
    rows = []
    for g, d in s.items():
        if not isinstance(d, dict):
            continue
        rows.append([g, d["files"], C.num(d['minutes'], ".0f"), C.num(d['events_per_min'], ".1f"), C.num(d['fa_per_min'], ".2f"), C.num(d['fireable_per_min'], ".2f"),
                     C.pct(d["files_with_fa"]), ", ".join(f"{k} {v}" for k, v in sorted(d["actions"].items(), key=lambda kv: -kv[1]))])
    L.append(C.md_table(["subset", "files", "min", "events/min", "FA groups/min", "fireable events/min", "files with FA %", "actions"], rows))
    L.append("\n'Sounds like' of all events (counts):\n")
    L.append(C.md_table(["subset"] + LIKES, [[g] + [d["likes"].get(k, 0) for k in LIKES] for g, d in s.items() if isinstance(d, dict)]))
    L.append("\nLabels of events that would fire alone:\n")
    L.append(C.md_table(["subset", "labels"], [[g, ", ".join(f"{k} {v}" for k, v in sorted(d["fa_labels"].items(), key=lambda kv: -kv[1]))]
                                                for g, d in s.items() if isinstance(d, dict)]))
    L.append(f"\nLines: {s['lines']}; strict-parse/label errors: {s['line_errors']}; outside generate.py's line space: {s['ood']}\n")
    return "\n".join(L)
