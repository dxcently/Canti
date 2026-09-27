"""Cloud (Ollama) vs Verdict on real-targets-v2 emulator sets: paired screen-bootstrap differences overall, by kind, by
app and on novel phrases, plus the cascade "Verdict if its confidence >= tau, else the cloud answer".

    python sweeps/cloud_cascade.py [--tag dsv41flash] [--student verdict-bi-real-v1d] [--out sweeps/eval/cloud_cascade.json]

Reads only preds/ollama/real2-*.<tag>.jsonl, the student's preds/real-targets-v2/<set>.<student>.jsonl and the three
emulator gold files. A cloud error (invalid answer / timeout) counts as the student's answer (what the phone would do).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

FT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FT / "students" / "verdict"))
import vstats  # noqa: E402

SETS = {"real2-test": "test_real", "real2-test-old": "test_real_old", "real2-val": "val_real"}


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="dsv41flash")
    ap.add_argument("--student", default="verdict-bi-real-v1d")
    ap.add_argument("--train", default="data/real-targets-v2/zflip/train_real_all.jsonl", help="novel-phrase reference")
    ap.add_argument("--B", type=int, default=2000)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    trp = {vstats.phrase_key(r["phrase"]) for r in jl(FT / a.train) if r.get("phrase")}
    res = {}
    md = []
    for cs, fs in SETS.items():
        gold = jl(FT / f"data/real-targets-v2/{fs}.jsonl")
        st = {r["id"]: r["probs"] for r in jl(FT / f"preds/real-targets-v2/{fs}.{a.student}.jsonl")}
        cl = {r["id"]: r for r in jl(FT / f"preds/ollama/{cs}.{a.tag}.jsonl")}
        gold = [g for g in gold if g["id"] in st and g["id"] in cl]
        cloud = {g["id"]: (cl[g["id"]]["probs"] if "probs" in cl[g["id"]] else st[g["id"]]) for g in gold}
        n_err = sum("probs" not in cl[g["id"]] for g in gold)
        rs, rc = vstats.records(gold, st, trp), vstats.records(gold, cloud, trp)
        out = {"n": len(gold), "cloud_errors_fell_back": n_err, "student": vstats.bootstrap(rs, a.B), "cloud": vstats.bootstrap(rc, a.B),
               "paired_cloud_minus_student": vstats.paired(rc, rs, a.B), "by": {}}
        groups = defaultdict(list)
        for i, g in enumerate(gold):
            groups["kind:" + g["kind"]].append(i)
            groups["app:" + g["app"]].append(i)
            groups["novel" if rs[i]["novel"] else "in-train phrase"].append(i)
        for k, idx in sorted(groups.items()):
            if len(idx) < 20:
                continue
            p = vstats.paired([rc[i] for i in idx], [rs[i] for i in idx], a.B)
            out["by"][k] = {"n": len(idx), "student_acc": vstats.metrics([rs[i] for i in idx])["acc"],
                            "cloud_acc": vstats.metrics([rc[i] for i in idx])["acc"], "diff": p["acc"]}
        casc = {}
        for tau in (0.7, 0.8, 0.9):
            sent = {g["id"] for g in gold if max(st[g["id"]]) < tau}
            mix = {g["id"]: (cloud[g["id"]] if g["id"] in sent else st[g["id"]]) for g in gold}
            rm = vstats.records(gold, mix, trp)
            b = vstats.bootstrap(rm, a.B)
            casc[str(tau)] = {"sent_to_cloud": len(sent) / len(gold), "acc": b["acc"], "none_recall": b["none_recall"],
                              "false_none": b["false_none"][0], "novel_acc": b["novel_acc"][0],
                              "vs_cloud_only": vstats.paired(rm, rc, a.B)["acc"], "vs_student": vstats.paired(rm, rs, a.B)["acc"]}
        out["cascade"] = casc
        res[cs] = out
        f = lambda t: f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"  # noqa: E731
        d = lambda t: f"{t[0]:+.3f} [{t[1]:+.3f}, {t[2]:+.3f}] p={t[3]:.3f}"  # noqa: E731
        md += [f"#### {cs} ({fs}, n={len(gold)}; {n_err} cloud errors fell back to {a.student})", "",
               "| model | acc | none recall | false none | novel-phrase acc |", "|---|---|---|---|---|",
               f"| {a.student} | {f(out['student']['acc'])} | {f(out['student']['none_recall'])} | {out['student']['false_none'][0]:.3f} | {f(out['student']['novel_acc'])} |",
               f"| cloud {a.tag} | {f(out['cloud']['acc'])} | {f(out['cloud']['none_recall'])} | {out['cloud']['false_none'][0]:.3f} | {f(out['cloud']['novel_acc'])} |",
               "", f"Cloud minus {a.student} (paired screen bootstrap): acc {d(out['paired_cloud_minus_student']['acc'])}; none recall "
               f"{d(out['paired_cloud_minus_student']['none_recall'])}; novel {d(out['paired_cloud_minus_student']['novel_acc'])}", "",
               "| group | n | student acc | cloud acc | cloud - student |", "|---|---|---|---|---|"]
        md += [f"| {k} | {v['n']} | {v['student_acc']:.3f} | {v['cloud_acc']:.3f} | {d(v['diff'])} |" for k, v in out["by"].items()]
        md += ["", "| cascade tau | sent to cloud | acc | none recall | false none | vs cloud only | vs student only |", "|---|---|---|---|---|---|---|"]
        md += [f"| {t} | {c['sent_to_cloud']:.1%} | {f(c['acc'])} | {f(c['none_recall'])} | {c['false_none']:.3f} | {d(c['vs_cloud_only'])} | {d(c['vs_student'])} |"
               for t, c in casc.items()]
        md.append("")
    text = "\n".join(md)
    print(text)
    Path(a.out or FT / f"sweeps/eval/cloud_cascade.{a.tag}.{a.student}.json").write_text(json.dumps(res, indent=1, default=float))
    (FT / f"sweeps/eval/cloud_cascade.{a.tag}.{a.student}.md").write_text(text)


if __name__ == "__main__":
    main()
