#!/usr/bin/env python3
"""Evaluate the extractor on SYNTHETIC clips (synth.py) across SNRs and backgrounds.

Everything here is synthetic. None of these numbers say anything about real voices or a real mic.

Per clip the extractor runs in streaming mode (1600-sample chunks). Scoring:
  * gesture clips: the emitted event overlapping the truth span most is the prediction
    ("none" if nothing overlaps). Confusion matrix truth x predicted label; label accuracy;
    excursion / duration bucket accuracy; t_end and t_start error vs the synthetic ground truth
    (truth t_end = the sample where the synthetic envelope reaches zero).
  * end to end: the events are grouped like the phone does (gap <= 600 ms) and scored with the
    default profile + the app's not-deliberate gate (vox_extract/policy.py). A gesture clip is
    right when the clip yields exactly its default action and nothing else.
  * negative clips: false accept = any group in the clip maps to an action other than none.
  * every emitted line must parse strictly and agree with its label; lines using field
    combinations generate.py never produces are counted separately ("off-distribution").

Usage
  python tests/synthetic_eval.py                      # full sweep, writes results/synthetic_eval.{json,md}
  python tests/synthetic_eval.py --per-cell 3 --quick # smaller
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import synth  # noqa: E402
from vox_extract import Config  # noqa: E402
from vox_extract.extractor import extract_array  # noqa: E402
from vox_extract.lines import LineError, label_consistent, parse_line  # noqa: E402
from vox_extract.policy import action_for, group  # noqa: E402
from vox_extract.vocab import DEFAULT_BINDINGS, DURATION, EXCURSION  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import finetune_ref  # noqa: E402

SEEN = finetune_ref.seen_lines()   # None if /home/khoa/VOX/finetune is not there
SNRS = [30, 20, 10, 5]
EXPECTED_ACTION = {g: a for (g,), a in ((k, v) for k, v in DEFAULT_BINDINGS.items() if len(k) == 1)}
EXPECTED_ACTION["click_pop"] = DEFAULT_BINDINGS[("click", "pop")]


def truth_label(cls: str) -> str:
    return cls.replace("whistle_", "")


def expected_action(cls: str) -> str:
    if cls in EXPECTED_ACTION:
        return EXPECTED_ACTION[cls]
    if cls.startswith("whistle_"):
        return EXPECTED_ACTION[truth_label(cls)]
    if cls == "click":
        return "none"  # a lone click is unbound by default (it only waits for "click pop")
    return "none"


def off_distribution(p: dict, label: str, text: str | None = None) -> str | None:
    """Lines generate.py never produces (valid vocab, but unseen in training). With finetune/ readable
    the check is exact (the sampled support of generate.py's line builders, tests/finetune_ref.py); the
    reason is then named by the hand rules below."""
    if text is not None and SEEN is not None:
        if text in SEEN:
            return None
        return _off_rules(p, label) or "other unseen combination"
    return _off_rules(p, label)


def _off_rules(p: dict, label: str) -> str | None:
    """Name why a line is outside generate.py's support (deliberate_sound, junk_sound, air_hiss)."""
    if p["kind"] == "hum":
        like, exc, dur = p["sounds_like"], p["pitch_change"], p["duration"]
        if like in ("background noise", "mouth sound"):
            return f"hum line sounds like {like}"
        if label == "flat" and exc != EXCURSION[0]:
            return "flat with non-small pitch change"
        if dur == DURATION[3] and not (label == "flat" and like in ("hum", "whistle")):
            return "hum over 1 s that is not a deliberate flat hum"
        if label != "flat" and exc == EXCURSION[0] and like != "hum":
            return f"non-flat hum with small pitch change that sounds like {like}"
        if dur == DURATION[0] and like != "hum":
            return f"very short hum that sounds like {like}"
    if p["kind"] == "hiss" and p["sounds_like"] not in ("mouth sound", "background noise"):
        return f"hiss sounds like {p['sounds_like']}"
    if p["kind"] == "hiss" and p["duration"] == DURATION[0]:
        return "very short hiss"
    if p["kind"] == "hiss" and p["loudness"] == "loud" and (p["sounds_like"] == "background noise" or p["duration"] == DURATION[3]):
        return "loud background / long hiss (generate.py makes those quiet or normal)"
    return None


CFG_PATH: str | None = None   # --config (set in each worker by _init)


def _init(path: str | None) -> None:
    global CFG_PATH
    CFG_PATH = path


def run_clip(args: tuple) -> dict:
    cls, seed, snr, bg, sr = args
    rng = np.random.default_rng(seed)
    clip = synth.make_clip(cls, rng, sr=sr, snr_db=snr, bg=bg)
    t = time.perf_counter()
    events = [e.to_dict() for e in extract_array(clip.audio, clip.sr, Config.load(CFG_PATH) if CFG_PATH else Config())]
    proc_s = time.perf_counter() - t
    line_errors, off = [], []
    for e in events:
        try:
            p = parse_line(e["text"])
            if not label_consistent(e["label"], p):
                line_errors.append(f"label {e['label']} vs line {e['text']}")
            o = off_distribution(p, e["label"], e["text"])
            if o:
                off.append(o)
        except LineError as err:
            line_errors.append(str(err))
    groups = group(events)
    actions = [action_for([(e["label"], e["text"]) for e in g]) for g in groups]
    rec = {"cls": cls, "kind": clip.kind, "snr": snr, "bg": bg, "sr": sr, "seed": seed,
           "n_events": len(events), "labels": [e["label"] for e in events],
           "likes": [e["sounds_like"] for e in events], "actions": actions,
           "line_errors": line_errors, "off_distribution": off, "audio_s": len(clip.audio) / clip.sr,
           "proc_s": proc_s, "truth": clip.events, "span": clip.span}
    if clip.kind in ("gesture", "sequence"):
        preds = []
        for tr in clip.events:
            best, best_ov = None, 0.0
            for e in events:
                ov = min(e["t_end_ms"], tr["t_end_ms"]) - max(e["t_start_ms"], tr["t_start_ms"])
                if ov > best_ov:
                    best, best_ov = e, ov
            preds.append(best)
        rec["pred"] = [p["label"] if p else "none" for p in preds]
        rec["pred_like"] = [p["sounds_like"] if p else None for p in preds]
        rec["t_end_err"] = [(p["t_end_ms"] - tr["t_end_ms"]) if p else None for p, tr in zip(preds, clip.events)]
        rec["t_start_err"] = [(p["t_start_ms"] - tr["t_start_ms"]) if p else None for p, tr in zip(preds, clip.events)]
        rec["exc_ok"], rec["dur_ok"] = [], []
        for p, tr in zip(preds, clip.events):
            if p and "expected_excursion" in tr and p["label"] in synth.CONTOUR_CLASSES:
                pp = parse_line(p["text"])
                rec["exc_ok"].append(pp["pitch_change"] == tr["expected_excursion"])
                rec["dur_ok"].append(pp["duration"] == tr["expected_duration"])
            elif p and tr.get("expected_duration") not in (None, "instant") and p["label"] == "hiss":
                rec["dur_ok"].append(parse_line(p["text"])["duration"] == tr["expected_duration"])
        exp = expected_action(cls)
        acted = [a for a in actions if a != "none"]
        rec["action_ok"] = (acted == [exp]) if exp != "none" else (acted == [])
        rec["expected_action"] = exp
    else:
        rec["false_accept"] = any(a != "none" for a in actions)
    return rec


def jobs(per_cell: int, snrs: list[int], bgs: list[str], classes: list[str], sr: int, seed0: int) -> list[tuple]:
    out = []
    for ci, cls in enumerate(classes):
        for snr in snrs:
            for i in range(per_cell):
                bg = bgs[i % len(bgs)]
                out.append((cls, seed0 + 1_000_003 * ci + 7919 * snr + i, snr, bg, sr))
    return out


def summarise(recs: list[dict]) -> dict:
    out: dict = {"n_clips": len(recs)}
    ges = [r for r in recs if r["kind"] == "gesture"]
    labels = ["rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss"]
    cols = labels + ["none"]
    # confusion per SNR and overall (truth label x predicted label)
    def confusion(rs):
        m = {t: Counter() for t in labels}
        for r in rs:
            m[truth_label(r["cls"])][r["pred"][0]] += 1
        return {t: dict(c) for t, c in m.items()}
    out["confusion_all"] = confusion(ges)
    out["confusion_by_snr"] = {snr: confusion([r for r in ges if r["snr"] == snr]) for snr in sorted({r["snr"] for r in ges})}
    out["columns"] = cols

    def acc(rs, key=lambda r: r["pred"][0] == truth_label(r["cls"])):
        return (sum(1 for r in rs if key(r)) / len(rs)) if rs else None
    contour = [r for r in ges if truth_label(r["cls"]) in synth.CONTOUR_CLASSES]
    discrete = [r for r in ges if r["cls"] in ("pop", "click", "hiss")]
    snrs = sorted({r["snr"] for r in recs})
    out["contour_acc"] = {s: acc([r for r in contour if r["snr"] == s]) for s in snrs} | {"all": acc(contour)}
    out["contour_acc_hum_only"] = {s: acc([r for r in contour if r["snr"] == s and not r["cls"].startswith("whistle")]) for s in snrs}
    out["contour_acc_whistle_only"] = {s: acc([r for r in contour if r["snr"] == s and r["cls"].startswith("whistle")]) for s in snrs}
    out["discrete_acc"] = {s: acc([r for r in discrete if r["snr"] == s]) for s in snrs} | {"all": acc(discrete)}
    out["per_class_label_acc"] = {c: {s: acc([r for r in ges if r["cls"] == c and r["snr"] == s]) for s in snrs}
                                  for c in sorted({r["cls"] for r in ges})}
    out["end_to_end_action_acc"] = {c: {s: acc([r for r in recs if r["cls"] == c and r["snr"] == s], lambda r: r["action_ok"]) for s in snrs}
                                    for c in sorted({r["cls"] for r in recs if r["kind"] != "negative"})}
    out["whistle_called_whistle"] = acc([r for r in contour if r["cls"].startswith("whistle")], lambda r: r["pred_like"][0] == "whistle")
    out["hum_called_hum"] = acc([r for r in contour if not r["cls"].startswith("whistle")], lambda r: r["pred_like"][0] == "hum")
    exc = [x for r in contour for x in r["exc_ok"]]
    dur = [x for r in ges for x in r["dur_ok"]]
    out["excursion_bucket_acc"] = float(np.mean(exc)) if exc else None
    out["duration_bucket_acc"] = float(np.mean(dur)) if dur else None
    # timing
    errs = defaultdict(list)
    serrs = defaultdict(list)
    for r in ges + [r for r in recs if r["kind"] == "sequence"]:
        for tr, e, se in zip(r["truth"], r["t_end_err"], r["t_start_err"]):
            if e is not None:
                errs[(tr["label"], r["snr"])].append(e)
                serrs[(tr["label"], r["snr"])].append(se)
    out["t_end_err_ms"] = {f"{k[0]}@{k[1]}": {"n": len(v), "median": float(np.median(v)), "mean_abs": float(np.mean(np.abs(v))),
                                              "p90_abs": float(np.percentile(np.abs(v), 90))} for k, v in sorted(errs.items())}
    all_e = [x for v in errs.values() for x in v]
    all_s = [x for v in serrs.values() for x in v]
    out["t_end_err_all"] = {"median": float(np.median(all_e)), "mean_abs": float(np.mean(np.abs(all_e))),
                            "p90_abs": float(np.percentile(np.abs(all_e), 90))} if all_e else None
    out["t_start_err_all"] = {"median": float(np.median(all_s)), "mean_abs": float(np.mean(np.abs(all_s))),
                              "p90_abs": float(np.percentile(np.abs(all_s), 90))} if all_s else None
    # negatives
    neg = [r for r in recs if r["kind"] == "negative"]
    out["false_accept"] = {c: {s: acc([r for r in neg if r["cls"] == c and r["snr"] == s], lambda r: r["false_accept"]) for s in snrs}
                           for c in sorted({r["cls"] for r in neg})}
    out["false_accept_all"] = acc(neg, lambda r: r["false_accept"])
    out["false_accept_actions"] = {c: dict(Counter(a for r in neg if r["cls"] == c for a in r["actions"] if a != "none"))
                                   for c in sorted({r["cls"] for r in neg})}
    out["negative_sounds_like"] = {c: dict(Counter(l for r in neg if r["cls"] == c for l in r["likes"]))
                                   for c in sorted({r["cls"] for r in neg})}
    out["insertions_on_gestures"] = sum(max(0, r["n_events"] - len(r["truth"])) for r in ges)
    out["line_errors"] = sum(len(r["line_errors"]) for r in recs)
    out["lines_total"] = sum(r["n_events"] for r in recs)
    out["off_distribution"] = dict(Counter(o for r in recs for o in r["off_distribution"]))
    out["realtime_factor"] = sum(r["proc_s"] for r in recs) / sum(r["audio_s"] for r in recs)
    return out


def fmt_pct(v) -> str:
    return "  -  " if v is None else f"{100 * v:5.1f}"


def markdown(s: dict, meta: dict) -> str:
    L = []
    L.append("# Synthetic evaluation (SYNTHETIC AUDIO ONLY: not evidence about real voices or mics)\n")
    L.append(f"clips: {s['n_clips']}; per cell: {meta['per_cell']}; SNRs: {meta['snrs']}; backgrounds: {meta['bgs']}; "
             f"sample rate: {meta['sr']}; seed: {meta['seed']}\n")
    snrs = meta["snrs"]
    head = "| | " + " | ".join(f"{x} dB" for x in snrs) + " |\n|---|" + "---|" * len(snrs)
    L.append("## Label accuracy (gesture clips)\n")
    L.append(head)
    for name, key in (("contour (hum + whistle)", "contour_acc"), ("contour, hum only", "contour_acc_hum_only"),
                      ("contour, whistle only", "contour_acc_whistle_only"), ("discrete (pop/click/hiss)", "discrete_acc")):
        L.append(f"| {name} | " + " | ".join(fmt_pct(s[key].get(x)) for x in snrs) + " |")
    L.append("\n### Per class\n")
    L.append(head)
    for c, d in s["per_class_label_acc"].items():
        L.append(f"| {c} | " + " | ".join(fmt_pct(d.get(x)) for x in snrs) + " |")
    L.append("\n## End-to-end default action (grouped like the phone, not-deliberate gate applied)\n")
    L.append("A clip is right only if it yields exactly its default action and no other action "
             "(a lone click correctly yields none: it is unbound).\n")
    L.append(head)
    for c, d in s["end_to_end_action_acc"].items():
        L.append(f"| {c} | " + " | ".join(fmt_pct(d.get(x)) for x in snrs) + " |")
    L.append("\n## False accepts on negatives (any action other than none)\n")
    L.append(head)
    for c, d in s["false_accept"].items():
        L.append(f"| {c} | " + " | ".join(fmt_pct(d.get(x)) for x in snrs) + " |")
    L.append(f"\nOverall false-accept rate: {fmt_pct(s['false_accept_all'])} %\n")
    L.append("Actions triggered by negatives: " + json.dumps({k: v for k, v in s["false_accept_actions"].items() if v}) + "\n")
    L.append("'Sounds like' emitted for negatives: \n")
    for c, d in s["negative_sounds_like"].items():
        L.append(f"- {c}: {json.dumps(d)}")
    L.append("\n## Confusion matrix, all SNRs (rows = truth, columns = predicted label)\n")
    cols = s["columns"]
    L.append("| truth | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols))
    for t, row in s["confusion_all"].items():
        L.append(f"| {t} | " + " | ".join(str(row.get(c, 0)) for c in cols) + " |")
    for snr, cm in s["confusion_by_snr"].items():
        L.append(f"\n### Confusion at {snr} dB\n")
        L.append("| truth | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols))
        for t, row in cm.items():
            L.append(f"| {t} | " + " | ".join(str(row.get(c, 0)) for c in cols) + " |")
    L.append("\n## Buckets and timing\n")
    L.append(f"- excursion bucket accuracy (hums/whistles with a correct contour label): {fmt_pct(s['excursion_bucket_acc'])} %")
    L.append(f"- duration bucket accuracy: {fmt_pct(s['duration_bucket_acc'])} %")
    L.append(f"- hum clips called 'hum': {fmt_pct(s['hum_called_hum'])} %; whistle clips called 'whistle': {fmt_pct(s['whistle_called_whistle'])} %")
    L.append(f"- t_end error, all matched events: {json.dumps(s['t_end_err_all'])} (ms; negative = reported early)")
    L.append(f"- t_start error, all matched events: {json.dumps(s['t_start_err_all'])} (ms)")
    L.append("\n| sound@SNR | n | median t_end err | mean abs | p90 abs |\n|---|---|---|---|---|")
    for k, v in s["t_end_err_ms"].items():
        L.append(f"| {k} | {v['n']} | {v['median']:.0f} | {v['mean_abs']:.0f} | {v['p90_abs']:.0f} |")
    L.append("\n## Line validity\n")
    L.append(f"- lines emitted: {s['lines_total']}; strict-parser or label errors: {s['line_errors']}")
    L.append(f"- valid but off the training distribution: {json.dumps(s['off_distribution'])}")
    L.append(f"- extra events on single-gesture clips: {s['insertions_on_gestures']}")
    L.append(f"- Python real-time factor (processing time / audio time, this workstation): {s['realtime_factor']:.3f}")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cell", type=int, default=12, help="clips per class per SNR")
    ap.add_argument("--snrs", type=int, nargs="*", default=SNRS)
    ap.add_argument("--bgs", nargs="*", default=synth.BACKGROUNDS)
    ap.add_argument("--classes", nargs="*", default=synth.ALL_CLASSES)
    ap.add_argument("--sr", type=int, default=16000, choices=[16000, 48000])
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--config", default=None, help="Config JSON (partial is fine); default Config()")
    ap.add_argument("--out", type=Path, default=ROOT / "results")
    ap.add_argument("--name", default="synthetic_eval")
    ap.add_argument("--dump", action="store_true", help="also write per-clip records")
    a = ap.parse_args()
    js = jobs(a.per_cell, a.snrs, a.bgs, a.classes, a.sr, a.seed)
    t = time.time()
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.config,)) as ex:
        recs = list(ex.map(run_clip, js, chunksize=4))
    s = summarise(recs)
    meta = {"config": a.config or "default", "per_cell": a.per_cell, "snrs": a.snrs, "bgs": a.bgs, "sr": a.sr, "seed": a.seed, "synthetic": True}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"{a.name}.json").write_text(json.dumps({"meta": meta, "summary": s}, indent=1, default=str) + "\n")
    (a.out / f"{a.name}.md").write_text(markdown(s, meta))
    if a.dump:
        with (a.out / f"{a.name}_clips.jsonl").open("w") as f:
            for r in recs:
                f.write(json.dumps(r, default=str) + "\n")
    print(markdown(s, meta))
    print(f"[{len(recs)} clips in {time.time() - t:.0f} s]")


if __name__ == "__main__":
    main()
