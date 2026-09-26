#!/usr/bin/env python3
"""Runner for the REAL-audio evaluation.

  VOX_CODE=frozen ./run python eval_real/run_all.py run --tag frozen     # every dataset, both splits, Config(), frozen code snapshot
  ./run python eval_real/run_all.py run --tag tuned --cfg results/real_tuned_config.json --splits test
  ./run python eval_real/run_all.py report                               # rewrite results/real_*.md from the runs

Per-clip records (JSONL) go to /home/khoa/VOX/datasets/_eval_cache/runs/<tag>/<dataset>_<split>.jsonl, next to the
audio and out of the extractor tree. Reports go to extractor/results/real_*.md.
Workers default to 8 (VOX_EVAL_WORKERS); every worker is single-threaded. CPU only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import esc50  # noqa: E402
import mlend  # noqa: E402
import musan  # noqa: E402
import nonspeech7k  # noqa: E402
import nonverbal  # noqa: E402
import qbsh  # noqa: E402

RUNS = C.CACHE / "runs"
DATASETS = ["nonverbal", "qbsh_pitch", "qbsh_contour", "musan", "mlend", "nonspeech7k", "esc50"]


def job_list(ds: str, split: str, cfg: str | None) -> tuple[list, callable, dict]:
    if ds == "nonverbal":
        return nonverbal.jobs(split, cfg), nonverbal.run_job, {}
    if ds == "qbsh_pitch":
        return [(f, cfg) for f in qbsh.files() if f["split"] == split], qbsh.pitch_job, {}
    if ds == "qbsh_contour":
        js, rej = qbsh.contour_jobs(split, cfg)
        return js, qbsh.contour_job, {"cutting": dict(rej)}
    if ds == "musan":
        return musan.jobs(split, cfg), musan.run_job, {}
    if ds == "mlend":
        return mlend.jobs(split, cfg), mlend.run_job, {}
    if ds == "nonspeech7k":
        return nonspeech7k.jobs(split, cfg), nonspeech7k.run_job, {}
    if ds == "esc50":
        return esc50.jobs(split, cfg), esc50.run_job, {}
    raise ValueError(ds)


def cmd_run(a) -> None:
    for ds in a.datasets:
        for split in a.splits:
            js, fn, meta = job_list(ds, split, a.cfg)
            if a.limit:
                js = js[: a.limit]
            t = time.time()
            recs = C.pmap(fn, js, workers=a.workers, chunksize=2)
            out = RUNS / a.tag / f"{ds}_{split}.jsonl"
            C.write_jsonl(out, recs)
            (RUNS / a.tag / f"{ds}_{split}.meta.json").write_text(json.dumps(
                {"cfg": a.cfg or "frozen", "code": C.CODE, "jobs": len(js), "seconds": round(time.time() - t, 1), **meta}, indent=1))
            print(f"[{a.tag}] {ds}/{split}: {len(recs)} records in {time.time() - t:.0f} s -> {out}", flush=True)


# ------------------------------------------------------------------------------ reporting

def load(tag: str, ds: str, split: str):
    p = RUNS / tag / f"{ds}_{split}.jsonl"
    if not p.exists():
        return None
    return C.read_jsonl(p)


def meta(tag: str, ds: str, split: str) -> dict:
    p = RUNS / tag / f"{ds}_{split}.meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


SUMMARISE = {"nonverbal": (nonverbal.summarise, nonverbal.markdown), "musan": (musan.summarise, musan.markdown),
             "mlend": (mlend.summarise, mlend.markdown), "nonspeech7k": (nonspeech7k.summarise, nonspeech7k.markdown),
             "qbsh_contour": (qbsh.contour_summary, qbsh.contour_markdown), "esc50": (esc50.summarise, esc50.markdown)}


def summaries(tags: list[str]) -> dict:
    out: dict = defaultdict(dict)
    for tag in tags:
        for ds in DATASETS:
            for split in ("tune", "test"):
                recs = load(tag, ds, split)
                if recs is None:
                    continue
                if ds == "qbsh_pitch":
                    out[(tag, split)][ds] = {lag: qbsh.pitch_summary(recs, lag) for lag in (0, -16, 16)}
                else:
                    out[(tag, split)][ds] = SUMMARISE[ds][0](recs)
    return out


def ood_report(tags: list[str]) -> str:
    L = ["# Lines outside the generator's line space, REAL audio\n",
         "Check: `tests/synthetic_eval.off_distribution` (exact membership in the sampled support of generate.py's "
         "`deliberate_sound`, `air_hiss` and `junk_sound` via `tests/finetune_ref.py`; the reason is named by the same "
         "hand rules as in README \"Schema / line-format issues\"). This is the check behind the synthetic "
         "\"193 of 1181 lines\" figure. Every line counted here parsed strictly; it is valid vocabulary in a combination "
         "the training data never contains. Counts are over all conditions a dataset was run in (as recorded and "
         "20/10/5 dB for positives), both splits.\n"]
    for tag in tags:
        tot = 0
        lines = 0
        by_reason: Counter = Counter()
        by_text: Counter = Counter()
        by_ds: dict = defaultdict(Counter)
        text_reason = {}
        text_ds: dict = defaultdict(Counter)
        for ds in DATASETS:
            if ds == "qbsh_pitch":
                continue
            for split in ("tune", "test"):
                recs = load(tag, ds, split)
                if recs is None:
                    continue
                for r in recs:
                    lines += len(r["events"])
                    for reason, text in r["ood"]:
                        tot += 1
                        by_reason[reason] += 1
                        by_text[text] += 1
                        by_ds[ds][reason] += 1
                        text_reason[text] = reason
                        text_ds[text][ds] += 1
        if not lines:
            continue
        L.append(f"## Config: {tag}\n")
        L.append(f"{tot} of {lines} emitted lines ({100 * tot / lines:.1f} %) are outside generate.py's line space "
                 f"(synthetic run: 193 of 1181, 16.3 %). {len(by_text)} distinct lines.\n")
        L.append("### By reason\n")
        L.append(C.md_table(["reason", "count", "share of OOD"], [[k, v, f"{100 * v / tot:.1f} %"] for k, v in by_reason.most_common()]))
        L.append("\n### By dataset\n")
        dss = list(by_ds)
        reasons = [k for k, _ in by_reason.most_common()]
        L.append(C.md_table(["reason"] + dss, [[k] + [by_ds[d].get(k, 0) for d in dss] for k in reasons]))
        L.append("\n### Every distinct line, with counts (for training-data v6)\n")
        L.append(C.md_table(["count", "line", "reason", "datasets"],
                            [[v, f"`{t}`", text_reason[t], ", ".join(f"{d} {n}" for d, n in text_ds[t].most_common())] for t, v in by_text.most_common()]))
        L.append("")
    return "\n".join(L) + "\n"


def cmd_report(a) -> None:
    tags = [t for t in ("frozen", "fixed", "tuned") if (RUNS / t).exists()] if not a.tags else a.tags
    S = summaries(tags)
    (C.RESULTS / "real_summaries.json").write_text(json.dumps({f"{k[0]}/{k[1]}": v for k, v in S.items()}, indent=1, default=str))
    names = {"nonverbal": "real_nonverbal.md", "qbsh_contour": "real_qbsh_contour.md", "musan": "real_musan.md",
             "mlend": "real_mlend.md", "nonspeech7k": "real_nonspeech7k.md", "esc50": "real_esc50.md"}
    docs = {"nonverbal": nonverbal.__doc__, "qbsh_contour": qbsh.__doc__, "musan": musan.__doc__, "mlend": mlend.__doc__,
            "nonspeech7k": nonspeech7k.__doc__, "esc50": esc50.__doc__}
    for ds, fname in names.items():
        L = [f"# REAL audio: {ds}\n", "```", docs[ds].strip(), "```\n"]
        if ds == "qbsh_contour":
            for tag in tags:
                for split in ("test", "tune"):
                    m = meta(tag, ds, split)
                    if m.get("cutting"):
                        L.append(f"Cutting outcome ({split} split): " + json.dumps(m["cutting"]) + "\n")
                break
        for tag in tags:
            for split in ("test", "tune"):
                s = S.get((tag, split), {}).get(ds)
                if s is None:
                    continue
                label = f"{tag.upper()} config, {split.upper()} split" + ("  <- headline" if (tag, split) == ("frozen", "test") else "")
                L.append(SUMMARISE[ds][1](s, label))
        if ds == "qbsh_contour":
            for tag in tags:
                for split in ("test", "tune"):
                    p = S.get((tag, split), {}).get("qbsh_pitch")
                    if p:
                        L.append(qbsh.pitch_markdown(p[0], f"Pitch tracker vs manual pitch, {tag.upper()} config, {split.upper()} split (lag 0)"))
                        L.append("Alignment check, GPE at lag -16 / 0 / +16 ms: " +
                                 " / ".join(C.pct(p[l]["gpe_20pct"]) for l in (-16, 0, 16)) + " %\n")
        (C.RESULTS / fname).write_text("\n".join(L) + "\n")
    (C.RESULTS / "real_ood_lines.md").write_text(ood_report(tags))
    print("wrote", ", ".join(names.values()), "real_ood_lines.md, real_summaries.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tag", default="frozen")
    r.add_argument("--cfg", default=None, help="Config JSON (default: Config() as shipped)")
    r.add_argument("--datasets", nargs="*", default=DATASETS)
    r.add_argument("--splits", nargs="*", default=["tune", "test"])
    r.add_argument("--workers", type=int, default=C.WORKERS)
    r.add_argument("--limit", type=int, default=0)
    p = sub.add_parser("report")
    p.add_argument("--tags", nargs="*", default=None)
    a = ap.parse_args()
    {"run": cmd_run, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
