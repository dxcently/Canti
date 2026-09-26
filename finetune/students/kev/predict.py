"""Kev student: write <split>.<name>.jsonl with {id, probs} aligned with each row's options, plus per-row latency.

    python students/kev/predict.py --run students/kev/runs/smoke --split test_iid --limit 300 --name kev-smoke
    python students/kev/predict.py --run jaredpalmer/kev-0.8b --split test_iid --limit 300 --name kev-zeroshot

Probabilities: softmax(logits / T) with T the temperature stored in the checkpoint (fitted on validation by train.py;
override with --temperature). Bulk probabilities are computed in padded batches on --device; latency is measured
separately at batch size 1, end to end per row (tokenize + encode + forward + softmax + copy to host):
  --latency-gpu N   time the first N rows on the GPU (default: all rows)
  --latency-cpu N   time the first N rows on the CPU in a child process (fp32, torch reference DeltaNet kernels)
Each timed row gets "latency_ms_gpu" / "latency_ms_cpu" in the output; the summary goes to <out>.summary.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if "--device" in sys.argv and sys.argv[sys.argv.index("--device") + 1] == "cpu":
    os.environ["VOX_NO_FLA"] = "1"   # before kevlib/transformers import: fla kernels are GPU-only
import kevlib  # noqa: E402  (sets sys.path)
from common import Timer, load_rows, percentiles, policy_text, score, softmax, split_name, write_preds  # noqa: E402


def load_model(run, device, dtype):
    import torch
    from kev.checkpoint import Checkpoint, LoadOptions
    ck = Checkpoint(run)
    opts = LoadOptions(dtype={"bf16": torch.bfloat16, "fp32": torch.float32}[dtype], merge=True)
    tok, model = ck.load(device, opts)
    return ck, tok, model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run directory from train.py, or a Hub id (jaredpalmer/kev-0.8b)")
    ap.add_argument("--split", required=True, help="split name (data/v0/<split>.jsonl) or a JSONL path")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--name", default="kev", help="student name in the output file name <split>.<name>.jsonl")
    ap.add_argument("--out-dir", default=str(HERE / "preds"))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--dtype", choices=["bf16", "fp32"], default=None, help="default bf16 on GPU, fp32 on CPU")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--latency-gpu", type=int, default=-1, help="rows timed at batch 1 on the GPU (-1 = all, 0 = none)")
    ap.add_argument("--latency-cpu", type=int, default=0, help="rows timed at batch 1 on the CPU (child process)")
    ap.add_argument("--cpu-threads", type=int, default=4, help="CPU threads for the CPU latency run (phone-like)")
    ap.add_argument("--latency-only", action="store_true", help=argparse.SUPPRESS)   # child mode: print latencies as JSON
    a = ap.parse_args()

    import torch
    if a.cpu_threads and a.device == "cpu":
        torch.set_num_threads(a.cpu_threads)
    dtype = a.dtype or ("fp32" if a.device == "cpu" else "bf16")
    rows = load_rows(a.split, a.limit or None)
    policy = policy_text()
    ck, tok, model = load_model(a.run, a.device, dtype)
    T = a.temperature if a.temperature is not None else ck.meta.temperature
    sync = torch.cuda.synchronize if a.device.startswith("cuda") else None

    def one(row):
        with torch.no_grad():
            enc = kevlib.encode_row(model, tok, row, policy)
            z = kevlib.logits_batch(model, [enc])[0]
            return torch.softmax(z / T, -1).cpu()

    if a.latency_only:   # child process: batch-1 latency on this device
        n = a.latency_cpu if a.device == "cpu" else a.latency_gpu
        for r in rows[:2]: one(r)   # warm-up
        lat = {}
        for r in rows[:n]:
            with Timer(sync) as t: one(r)
            lat[r["id"]] = round(t.ms, 2)
        print("LATENCY_JSON " + json.dumps(lat), flush=True)
        return

    # bulk probabilities
    t0 = time.perf_counter()
    raw, probs = {}, {}
    with torch.no_grad():
        for i in range(0, len(rows), a.batch):
            chunk = rows[i:i + a.batch]
            zs = kevlib.logits_batch(model, [kevlib.encode_row(model, tok, r, policy) for r in chunk])
            for r, z in zip(chunk, zs):
                raw[r["id"]] = z.cpu().tolist()
                probs[r["id"]] = softmax(raw[r["id"]], T)
    bulk_s = time.perf_counter() - t0

    extra = {r["id"]: {} for r in rows}
    lat_gpu = {}
    n_gpu = len(rows) if a.latency_gpu < 0 else a.latency_gpu
    if n_gpu and a.device != "cpu":
        for r in rows[:2]: one(r)
        for r in rows[:n_gpu]:
            with Timer(sync) as t: one(r)
            lat_gpu[r["id"]] = round(t.ms, 2)
            extra[r["id"]]["latency_ms_gpu"] = lat_gpu[r["id"]]
    lat_cpu = {}
    if a.latency_cpu:
        del model; torch.cuda.empty_cache()
        cmd = [sys.executable, __file__, "--run", a.run, "--split", a.split, "--limit", str(a.latency_cpu), "--device", "cpu",
               "--latency-only", "--latency-cpu", str(a.latency_cpu), "--temperature", str(T)]
        if a.cpu_threads: cmd += ["--cpu-threads", str(a.cpu_threads)]
        out = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "VOX_NO_FLA": "1"})
        line = [l for l in out.stdout.splitlines() if l.startswith("LATENCY_JSON ")]
        if not line:
            print(out.stdout[-2000:], out.stderr[-4000:], file=sys.stderr)
            raise SystemExit("CPU latency child failed")
        lat_cpu = json.loads(line[0].removeprefix("LATENCY_JSON "))
        for k, v in lat_cpu.items():
            extra[k]["latency_ms_cpu"] = v

    out_path = Path(a.out_dir) / f"{split_name(a.split)}.{a.name}.jsonl"
    write_preds(out_path, rows, probs, extra)
    summary = {"run": a.run, "split": split_name(a.split), "rows": len(rows), "device": a.device, "dtype": dtype, "temperature": T,
               "metrics": score(rows, probs), "metrics_T1": score(rows, {k: softmax(v, 1.0) for k, v in raw.items()}),
               "bulk_rows_per_s": round(len(rows) / bulk_s, 2), "bulk_batch": a.batch,
               "latency_gpu_bs1": percentiles(list(lat_gpu.values())), "latency_cpu_bs1": percentiles(list(lat_cpu.values())),
               "torch_threads": torch.get_num_threads()}
    Path(str(out_path) + ".summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
