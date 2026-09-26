"""Verdict student: write <split>.<name>.jsonl with {id, probs} aligned with each row's options, plus per-row latency.

    python students/verdict/predict.py --run students/verdict/runs/verdict-bi-smoke --split test_iid --limit 300 --name verdict-bi-smoke
    python students/verdict/predict.py --run Manav2op/verdict-small --arch bi --split test_iid --limit 300 --name verdict-zeroshot

Probabilities (bulk, torch on --device): softmax(logits / T), T from the run's student.json (fitted on validation).
Latency, batch size 1, end to end per row (tokenize + encode + score + softmax), each on the first N rows:
  --latency-gpu N    torch on the GPU (bf16 autocast)                  -> "latency_ms_gpu"
  --latency-cpu N    torch fp32 on the CPU, --cpu-threads threads       -> "latency_ms_cpu"
  --latency-onnx N   onnxruntime int8 on the CPU (needs export_onnx.py) -> "latency_ms_onnx_int8"; also scored
bi-encoder: option embeddings are precomputed once for every option text in the split (VOX has a fixed 49-text option
vocabulary), so a decision costs one encoder pass over the context. cross-encoder: one batch of K (context, option) pairs.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import vlib  # noqa: F401  (sets sys.path, env)
import numpy as np
import torch
from common import Timer, load_rows, percentiles, score, softmax, split_name, write_preds

HERE = Path(__file__).resolve().parent


def run_arch(run, arch):
    p = Path(run) / "student.json"
    if p.exists():
        return json.loads(p.read_text())["arch"]
    if not arch:
        raise SystemExit("--arch is required for a checkpoint without student.json")
    return arch


class OnnxScorer:
    def __init__(self, run, arch, threads, int8=True):
        self.int8 = int8
        import onnxruntime as ort
        from transformers import AutoTokenizer
        name = {"bi": "encoder", "cross": "cross", "cross_cos": "cross_cos"}[arch] + ("_int8" if int8 else "")
        so = ort.SessionOptions(); so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(Path(run) / "onnx" / f"{name}.onnx"), so, providers=["CPUExecutionProvider"])
        self.tok = AutoTokenizer.from_pretrained(run)
        self.arch = arch
        self.meta = json.loads((Path(run) / "student.json").read_text())
        self.T = self.meta.get("temperature", 1.0)
        self.q, self.p = self.meta.get("q_prefix", "query: "), self.meta.get("p_prefix", "passage: ")
        self.opt = {}

    def _run(self, texts, pairs=None, max_len=512):
        b = self.tok(texts, pairs, padding=True, truncation="only_first" if pairs else True, max_length=max_len, return_tensors="np")
        feeds = {"input_ids": b["input_ids"].astype(np.int64), "attention_mask": b["attention_mask"].astype(np.int64)}
        if self.arch == "cross_cos":
            feeds["opt_mask"] = np.array([[int(s == 1) for s in b.sequence_ids(i)] for i in range(len(texts))], dtype=np.int64)
        return self.sess.run(None, feeds)[0]

    def warm_options(self, options):
        miss = [o for o in dict.fromkeys(options) if o not in self.opt]
        if miss and self.arch == "bi":
            for o, v in zip(miss, self._run([self.p + o for o in miss], max_len=64)): self.opt[o] = v

    def probs(self, row):
        if self.arch == "bi":
            x = self._run([self.q + row["context"]])[0]
            z = [float(self.opt[o] @ x) * vlib.SCALE for o in row["options"]]
        else:
            z = self._run([self.q + row["context"]] * len(row["options"]), [self.p + o for o in row["options"]]).tolist()
        return softmax(z, self.T)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run directory from train.py, or a Hub id / directory (needs --arch)")
    ap.add_argument("--arch", choices=["bi", "cross", "cross_cos"], default=None)
    ap.add_argument("--split", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--name", default=None, help="default verdict-<arch>")
    ap.add_argument("--out-dir", default=str(HERE / "preds"))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--latency-gpu", type=int, default=-1, help="-1 = all rows")
    ap.add_argument("--latency-cpu", type=int, default=100)
    ap.add_argument("--latency-onnx", type=int, default=-1, help="-1 = all rows if <run>/onnx exists, 0 = skip")
    ap.add_argument("--cpu-threads", type=int, default=4, help="CPU threads for torch-CPU and onnxruntime latency (phone-like)")
    ap.add_argument("--onnx-fp32", action="store_true", help="score/time the fp32 ONNX model instead of int8")
    a = ap.parse_args()

    arch = run_arch(a.run, a.arch)
    name = a.name or f"verdict-{arch}"
    rows = load_rows(a.split, a.limit or None)
    all_opts = list(dict.fromkeys(o for r in rows for o in r["options"]))
    m = vlib.Student(a.run, arch, device=a.device).eval()
    T = a.temperature if a.temperature is not None else m.temperature
    cuda = a.device.startswith("cuda")
    autocast = torch.autocast("cuda", dtype=torch.bfloat16, enabled=cuda)
    sync = torch.cuda.synchronize if cuda else None

    raw = {}
    t0 = time.perf_counter()
    bs = a.batch if arch == "bi" else max(1, a.batch // 8)
    with torch.no_grad(), autocast:
        for i in range(0, len(rows), bs):
            chunk = rows[i:i + bs]
            for r, z in zip(chunk, m.logits(chunk)):
                raw[r["id"]] = z.float().cpu().tolist()
    if sync: sync()
    bulk_s = time.perf_counter() - t0
    probs = {k: softmax(v, T) for k, v in raw.items()}
    extra = {r["id"]: {} for r in rows}

    def timed(model, rows_n, key, ctx):
        with torch.no_grad(), ctx:
            model.option_embeddings(all_opts, cache=True) if arch == "bi" else None
            for r in rows_n[:2]: model.logits([r], cache_options=True)
            lat = {}
            for r in rows_n:
                s = sync if model.device != "cpu" else None
                with Timer(s) as t:
                    z = model.logits([r], cache_options=True)[0]
                    torch.softmax(z.float() / T, -1).cpu()
                lat[r["id"]] = round(t.ms, 3); extra[r["id"]][key] = lat[r["id"]]
        return lat

    lat_gpu = timed(m, rows if a.latency_gpu < 0 else rows[:a.latency_gpu], "latency_ms_gpu", autocast) if cuda and a.latency_gpu else {}
    lat_cpu = {}
    if a.latency_cpu:
        torch.set_num_threads(a.cpu_threads)
        mc = vlib.Student(a.run, arch, device="cpu").eval()
        import contextlib
        lat_cpu = timed(mc, rows[:a.latency_cpu], "latency_ms_cpu", contextlib.nullcontext())
        del mc

    onnx = {}
    lat_onnx = {}
    onnx_dir = Path(a.run) / "onnx"
    okey = "onnx_fp32" if a.onnx_fp32 else "onnx_int8"
    if a.latency_onnx and onnx_dir.exists():
        sc = OnnxScorer(a.run, arch, a.cpu_threads, int8=not a.onnx_fp32)
        if a.temperature is not None: sc.T = a.temperature
        sc.warm_options(all_opts)
        for r in rows[:2]: sc.probs(r)
        for r in (rows if a.latency_onnx < 0 else rows[:a.latency_onnx]):
            with Timer() as t:
                onnx[r["id"]] = sc.probs(r)
            lat_onnx[r["id"]] = round(t.ms, 3); extra[r["id"]]["latency_ms_" + okey] = lat_onnx[r["id"]]

    out_path = Path(a.out_dir) / f"{split_name(a.split)}.{name}.jsonl"
    write_preds(out_path, rows, probs, extra)
    summary = {"run": a.run, "arch": arch, "split": split_name(a.split), "rows": len(rows), "temperature": T,
               "metrics": score(rows, probs), "metrics_T1": score(rows, {k: softmax(v, 1.0) for k, v in raw.items()}),
               "metrics_" + okey: score(rows, onnx) if onnx else None,
               "bulk_rows_per_s": round(len(rows) / bulk_s, 1), "latency_gpu_bs1": percentiles(list(lat_gpu.values())),
               "latency_cpu_bs1": percentiles(list(lat_cpu.values())), "latency_" + okey + "_bs1": percentiles(list(lat_onnx.values())),
               "cpu_threads": a.cpu_threads, "mean_options": round(sum(len(r["options"]) for r in rows) / len(rows), 2)}
    Path(str(out_path) + ".summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("metrics_T1",)}, indent=1))


if __name__ == "__main__":
    main()
