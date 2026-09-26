"""Deeply Nonverbal Vocalization Dataset (OpenSLR 99): real tongue clicks / lip pops vs other mouth noises.

Positives: tongue-clicking -> click, lip-popping -> pop. Borderline (reported separately): lip-smacking.
Negatives (user list): coughing, sighing, laughing, throat-clearing, sneezing, yawning, teeth-chattering,
teeth-grinding. Other classes (panting, crying, moaning, screaming, nose-blowing) are scored as "other
negatives" and kept out of the headline negative numbers.

Each file is ONE speaker performing the sound usually SEVERAL times (e.g. a train of 5-15 clicks), with
no per-event timestamps. So scoring is per clip and per event, never "exactly one event":
  * detect:  the clip yields at least one event with the target label;
  * major:   the clip's most frequent emitted label (ties -> the target if tied; "none" if no events);
  * purity:  of all events emitted in positive clips, the share with the target label;
  * fire:    of all events, the share that would trigger their own default action ALONE (pop -> tap;
             a lone click is unbound, so for clicks "fire" means "correct label and passes the gate").
Negatives: false accepts per minute = groups (phone-style, gap <= 600 ms) mapping to an action other than
none, per minute of original audio; and fireable events per minute (each event judged alone, pessimistic).

Filename: {speaker}_{class}_{trial}_{sex}_{age}_{location}_{quality}_{noise}.wav, 16 kHz mono PCM16.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

NAME = "nonverbal"
ROOT = C.DATA / "nonverbal" / "NonverbalVocalization"
POS = {"tongue-clicking": "click", "lip-popping": "pop"}
BORDER = {"lip-smacking": "pop"}
NEG = ["coughing", "sighing", "laughing", "throat-clearing", "sneezing", "yawning", "teeth-chattering", "teeth-grinding"]
OTHER = ["panting", "crying", "moaning", "screaming", "nose-blowing"]


def role(cls: str) -> str:
    return "pos" if cls in POS else "border" if cls in BORDER else "neg" if cls in NEG else "other"


def files() -> list[dict]:
    out = []
    for p in sorted(ROOT.glob("*/*.wav")):
        spk = p.stem.split("_")[0]
        parts = p.stem.split("_")
        out.append({"path": str(p), "cls": p.parent.name, "speaker": spk, "split": C.split_of(NAME, spk),
                    "quality": "low" if parts[6] == "1" else "high", "noisy": parts[7] == "1"})
    return out


def jobs(split: str, cfg_path: str | None) -> list[tuple]:
    js = []
    for f in files():
        if f["split"] != split:
            continue
        snrs = C.SNRS if role(f["cls"]) in ("pos", "border") else ["clean"]
        for snr in snrs:
            js.append((f, snr, cfg_path))
    return js


def run_job(job: tuple) -> dict:
    f, snr, cfg_path = job
    cfg = C.cfg_from(cfg_path)
    x = C.load_16k(f["path"])
    y, off, cut = C.pad_clip(x)
    rng = np.random.default_rng(C.seed_of(NAME, f["path"], snr))
    ref = C.active_rms(C.trim_dead(x)[0])
    y, noise = C.mix_at(y, snr, rng, f["split"], ref_rms=ref)
    ev = C.run_extractor(y, cfg)
    shift = int(1000 * (off - cut) / 16000)
    for e in ev:  # times relative to the original file
        e["t_start_ms"] -= shift
        e["t_end_ms"] -= shift
    rec = {"dataset": NAME, **f, "role": role(f["cls"]), "snr": snr, "dur_s": len(x) / 16000, **noise}
    rec.update(C.analyse(ev, y, shift))
    return rec


def target(cls: str) -> str | None:
    return POS.get(cls) or BORDER.get(cls)


def summarise(recs: list[dict]) -> dict:
    s: dict = {"n_clips": len(recs)}
    labs = C.LABELS + ["none"]
    for grp_name, clsset in (("pos", list(POS)), ("border", list(BORDER))):
        by = {}
        for snr in C.SNRS:
            rs = [r for r in recs if r["cls"] in clsset and r["snr"] == snr]
            d = {}
            for cls in clsset:
                t = target(cls)
                cr = [r for r in rs if r["cls"] == cls]
                evs = [e for r in cr for e in r["events"]]
                detect = sum(1 for r in cr if any(e["label"] == t for e in r["events"]))
                maj = Counter()
                for r in cr:
                    c = Counter(e["label"] for e in r["events"])
                    if not c:
                        maj["none"] += 1
                    else:
                        top = max(c.values())
                        maj[t if c.get(t) == top else c.most_common(1)[0][0]] += 1
                ok_evs = sum(1 for e in evs if e["label"] == t)
                fire_ok = sum(1 for r in cr for e, a in zip(r["events"], r["fire"])
                              if e["label"] == t and (a == "tap" if t == "pop" else e["gate"] is None))
                d[cls] = {"clips": len(cr), "detect": C.rate(detect, len(cr)), "major": dict(maj),
                          "major_acc": C.rate(maj.get(t, 0), len(cr)),
                          "events": len(evs), "events_per_clip": C.rate(len(evs), len(cr)),
                          "purity": C.rate(ok_evs, len(evs)), "fire": C.rate(fire_ok, len(evs)),
                          "event_labels": dict(Counter(e["label"] for e in evs)),
                          "event_likes": dict(Counter(e["like"] for e in evs))}
            by[snr] = d
        s[grp_name] = by
    # confusion (clip majority label) per SNR for positives + borderline
    s["confusion"] = {snr: {cls: s[g][snr][cls]["major"] for g, cl in (("pos", POS), ("border", BORDER)) for cls in cl}
                      for snr in C.SNRS}
    s["columns"] = labs
    # negatives
    for grp_name, clsset in (("neg", NEG), ("other", OTHER)):
        d = {}
        for cls in clsset + ["ALL"]:
            cr = [r for r in recs if (r["cls"] == cls if cls != "ALL" else r["cls"] in clsset) and r["snr"] == "clean"]
            mins = sum(r["dur_s"] for r in cr) / 60
            fa_groups = sum(1 for r in cr for a in r["actions"] if a != "none")
            fire = sum(1 for r in cr for a in r["fire"] if a != "none")
            d[cls] = {"clips": len(cr), "minutes": mins, "fa_clip_rate": C.rate(sum(1 for r in cr if any(a != "none" for a in r["actions"])), len(cr)),
                      "fa_per_min": fa_groups / mins if mins else None, "fireable_per_min": fire / mins if mins else None,
                      "actions": dict(Counter(a for r in cr for a in r["actions"] if a != "none")),
                      "likes": dict(Counter(e["like"] for r in cr for e in r["events"])),
                      "labels": dict(Counter(e["label"] for r in cr for e in r["events"]))}
        s[grp_name] = d
    s["line_errors"] = sum(len(r["line_errors"]) for r in recs)
    s["lines"] = sum(len(r["events"]) for r in recs)
    s["ood"] = sum(len(r["ood"]) for r in recs)
    return s


def markdown(s: dict, title: str) -> str:
    L = [f"### {title}\n"]
    rows = []
    for g in ("pos", "border"):
        for cls in (POS if g == "pos" else BORDER):
            for snr in C.SNRS:
                d = s[g][snr][cls]
                rows.append([cls + (" (borderline)" if g == "border" else ""), snr, d["clips"], C.pct(d["detect"]), C.pct(d["major_acc"]),
                             C.num(d['events_per_clip'], ".1f") if d["events_per_clip"] is not None else "-", C.pct(d["purity"]), C.pct(d["fire"])])
    L.append(C.md_table(["class", "SNR", "clips", "detect %", "majority = target %", "events/clip", "event purity %", "event fires own action %"], rows))
    L.append("\nClip-majority confusion (rows = class, columns = most frequent emitted label):\n")
    for snr in C.SNRS:
        conf = {cls: Counter(v) for cls, v in s["confusion"][snr].items()}
        L.append(f"\n{snr}:\n")
        L.append(C.confusion_md(conf, s["columns"]))
    for g, name in (("neg", "negatives (user list)"), ("other", "other nonverbal classes")):
        L.append(f"\nFalse accepts, {name}, as recorded:\n")
        rows = []
        for cls, d in s[g].items():
            rows.append([cls, d["clips"], C.num(d['minutes'], ".1f"), C.pct(d["fa_clip_rate"]), C.num(d['fa_per_min'], ".2f"), C.num(d['fireable_per_min'], ".2f"),
                         ", ".join(f"{k} {v}" for k, v in sorted(d["actions"].items(), key=lambda kv: -kv[1]))])
        L.append(C.md_table(["class", "clips", "min", "clips with FA %", "FA groups / min", "fireable events / min", "actions"], rows))
    L.append(f"\nLines: {s['lines']}; strict-parse/label errors: {s['line_errors']}; outside generate.py's line space: {s['ood']}\n")
    return "\n".join(L)
