"""Label a VOX JSONL split with local teacher models (in-process, batched on the GPU).

For every row each teacher answers one `choice` question: state = context, criteria = options, instructions = policy.txt.
Output, one file per split and teacher: <out>/<split>.<teacher>.jsonl with
    {"id", "probs": [... aligned with options ...], "top": index of the most likely option,
     "confidence": probs[top] (calibrated top-option probability, what ECE is measured on),
     "jev_confidence": TypeSafe's (N * p_max - 1) / (N - 1)}
and <out>/<split>.<teacher>.meta.json with the settings and throughput of the last run.

Resumable: ids already in the output file are skipped, and rows are appended and flushed chunk by chunk.

Usage (from /home/khoa/VOX/finetune, inside the venv):
    python -m teachers.label test_iid test_unseen_phrasing --limit 300
    python -m teachers.label train --teachers jevk5
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from teachers.scorer import REPOS, REVISIONS, TEACHERS, check_kernels, jev_confidence, load, question

ROOT = Path(__file__).resolve().parents[1]


def resolve_split(split: str, data_dir: Path) -> Path:
    p = Path(split)
    return p if p.suffix == ".jsonl" and p.exists() else data_dir / f"{split}.jsonl"


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text().splitlines():
        try:
            ids.add(json.loads(line)["id"])
        except (json.JSONDecodeError, KeyError):
            pass  # a torn last line from an interrupted run; the row is simply redone
    return ids


def plan(lengths: list[int], token_budget: int, max_batch: int) -> list[list[int]]:
    """Length-sorted batches whose padded size (rows x longest) stays under token_budget."""
    order = sorted(range(len(lengths)), key=lengths.__getitem__)
    out, cur = [], []
    for i in order:
        if cur and (len(cur) == max_batch or (len(cur) + 1) * lengths[i] > token_budget):
            out.append(cur)
            cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return out


def probs_backoff(teacher, batch):
    """teacher.probs, halving the batch on out-of-memory (the GPU is shared, so free memory moves)."""
    try:
        return teacher.probs(batch)
    except torch.OutOfMemoryError:
        torch.cuda.empty_cache()
        if len(batch) == 1:
            time.sleep(30)  # another job holds the memory; wait and retry the single row
            return probs_backoff(teacher, batch)
        half = len(batch) // 2
        return probs_backoff(teacher, batch[:half]) + probs_backoff(teacher, batch[half:])


def score(teacher, encs, token_budget: int, max_batch: int) -> list[list[float]]:
    probs: list[list[float] | None] = [None] * len(encs)
    for b in plan([len(e.ids) for e in encs], token_budget, max_batch):
        for i, p in zip(b, probs_backoff(teacher, [encs[i] for i in b])):
            probs[i] = p
    return probs  # type: ignore[return-value]


def run(teacher, rows: list[dict], policy: str, out_path: Path, criteria: str, token_budget: int, max_batch: int,
        chunk: int) -> dict:
    todo = [r for r in rows if r["id"] not in done_ids(out_path)]
    n_tokens, t_score = 0, 0.0
    with out_path.open("a") as f:
        for s in range(0, len(todo), chunk):
            part = todo[s:s + chunk]
            encs = [teacher.encode(r["context"], question(policy, r["options"], r["option_keys"] if criteria == "keyed" else None))
                    for r in part]
            n_tokens += sum(len(e.ids) for e in encs)
            torch.cuda.synchronize()
            t0 = time.perf_counter()
            probs = score(teacher, encs, token_budget, max_batch)
            torch.cuda.synchronize()
            t_score += time.perf_counter() - t0
            for r, p in zip(part, probs):
                top = max(range(len(p)), key=p.__getitem__)
                f.write(json.dumps({"id": r["id"], "probs": [round(x, 6) for x in p], "top": top,
                                    "confidence": round(p[top], 6), "jev_confidence": round(jev_confidence(p), 6)}) + "\n")
            f.flush()
            done = s + len(part)
            print(f"  {teacher.name}: {done}/{len(todo)} rows, {done / max(t_score, 1e-9):.1f} rows/s", flush=True)
    return {"rows_scored": len(todo), "input_tokens": n_tokens, "gpu_seconds": round(t_score, 2),
            "rows_per_s": round(len(todo) / t_score, 2) if t_score else None,
            "tokens_per_s": round(n_tokens / t_score) if t_score else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("splits", nargs="+", help="split names (test_iid, train, ...) or paths to .jsonl files")
    ap.add_argument("--teachers", default=",".join(TEACHERS), help=f"comma list from {TEACHERS}")
    ap.add_argument("--limit", type=int, help="only the first N rows of the split")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data/v0")
    ap.add_argument("--policy", type=Path, help="default: <data-dir>/policy.txt")
    ap.add_argument("--out", type=Path, default=ROOT / "teachers/labels")
    ap.add_argument("--criteria", choices=["text", "keyed"], default="text",
                    help="text: criteria are the option texts (default); keyed: {option_key: option text}")
    ap.add_argument("--token-budget", type=int, default=16384, help="max padded tokens per forward pass")
    ap.add_argument("--max-batch", type=int, default=64)
    ap.add_argument("--chunk", type=int, default=512, help="rows encoded, scored and flushed together")
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()

    policy = (a.policy or a.data_dir / "policy.txt").read_text().strip()
    a.out.mkdir(parents=True, exist_ok=True)
    suffix = "" if a.criteria == "text" else f".{a.criteria}"
    jobs = []  # (split name, rows, output path)
    for sp in a.splits:
        path = resolve_split(sp, a.data_dir)
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()][: a.limit]
        jobs.append((path.stem, rows))

    for name in a.teachers.split(","):  # each teacher is loaded once for all splits
        todo = [(split, rows, a.out / f"{split}.{name}{suffix}.jsonl") for split, rows in jobs]
        todo = [(split, rows, out) for split, rows, out in todo if any(r["id"] not in done_ids(out) for r in rows)]
        if not todo:
            print(f"{name}: every requested row is already labelled")
            continue
        t0 = time.perf_counter()
        teacher = load(name, a.device)
        load_s = time.perf_counter() - t0
        print(f"{name}: loaded in {load_s:.0f}s, kernels={check_kernels()}, T={teacher.temperature}", flush=True)
        for split, rows, out_path in todo:
            stats = run(teacher, rows, policy, out_path, a.criteria, a.token_budget, a.max_batch, a.chunk)
            meta = {"split": split, "teacher": name, "repo": REPOS[name], "revision": REVISIONS[name],
                    "temperature": teacher.temperature, "criteria": a.criteria, "kernels": check_kernels(),
                    "limit": a.limit, "token_budget": a.token_budget, "max_batch": a.max_batch,
                    "load_seconds": round(load_s, 1), "device": torch.cuda.get_device_name(0), "torch": torch.__version__,
                    **stats}
            (a.out / f"{split}.{name}{suffix}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
            print(json.dumps(meta), flush=True)
        del teacher
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
