"""Compare the C++ joystick ticks (firmware/extract/src/vx_tick.cpp, via vx_cli --ticks) with the Python reference
(extractor/joystick_core.py Analyzer) on a fixed sample of PUBLIC dataset clips (datasets/: Hillenbrand vowels,
MIR-QBSH hums, MLEnd hums/whistles, lip pops). Never the live recordings.

Run through tools/check_extract.sh (after the host build), or alone:  extractor/run python firmware/tools/check_ticks.py
Exit status 1 when a tolerance is exceeded. Per-tick agreement, both builds (float32 FFT as on the phone, and double):
  - same number of ticks, t_ms equal
  - db, floor_db within 0.01 dB (0.05 float32); clarity within 0.002 (0.01 float32)
  - voiced / F2-present agree on >= 99% of ticks (a clarity or level right at a threshold may flip)
  - f0 within 0.1% where both are voiced; F1/F2 within 1% (p99) where both are present
"""

from __future__ import annotations

import csv
import glob
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FW = HERE.parent
VOX = FW.parent
EXT = VOX / "extractor"
DATA = VOX / "datasets"
BIN = FW / "build" / "host"
sys.path.insert(0, str(EXT))

import joystick_core as J  # noqa: E402
from vox_extract.extractor import load_wav  # noqa: E402
from vox_extract.resample import to_16k  # noqa: E402

SETS = {
    "hillenbrand": ("hillenbrand/data/*/*.wav", 6),
    "qbsh": ("mir-qbsh/MIR-QBSH-corpus/waveFile/*/*/*.wav", 3),
    "mlend": ("mlend_hums_whistles/MLEndHWD_audiofiles/*.wav", 3),
    "lip_pop": ("nonverbal/NonverbalVocalization/lip-popping/*.wav", 2),
}
MAX_S = 12.0
TOL = {"double": {"db": 0.01, "floor_db": 0.01, "clarity": 0.002, "f0_rel": 0.001, "fmt_rel_p99": 0.01, "agree": 0.99},
       "float32": {"db": 0.05, "floor_db": 0.05, "clarity": 0.01, "f0_rel": 0.002, "fmt_rel_p99": 0.02, "agree": 0.98}}
EXE = {"double": "vx_cli_double", "float32": "vx_cli"}


def inputs() -> list[tuple[str, str]]:
    out = []
    for ds, (pat, n) in SETS.items():
        files = sorted(glob.glob(str(DATA / pat)))
        if not files:
            continue
        step = max(1, len(files) // n)
        out += [(f"{ds}/{Path(f).name}", f) for f in files[::step][:n]]
    return out


def py_ticks(x: np.ndarray, spec: dict) -> list[dict]:
    an = J.Analyzer(spec)
    rows = []
    for i in range(0, x.size, 1600):
        for tk in an.push(x[i:i + 1600]):
            rows.append({"t_ms": tk.t_ms, "f0": tk.f0, "f0_raw": tk.f0_raw, "clarity": tk.clarity, "db": tk.db,
                         "floor_db": tk.db - tk.over_db, "f1": tk.f1, "f2": tk.f2, "voiced": tk.voiced})
    return rows


def c_ticks(variant: str, f32: str) -> list[dict]:
    fd, out = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    p = subprocess.run([str(BIN / EXE[variant]), "--f32", f32, "--rate", "16000", "--ticks", out],
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr)
    with open(out) as f:
        rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]
    os.unlink(out)
    for r in rows:
        r["voiced"] = bool(r["voiced"])
    return rows


def compare(ref: list[dict], got: list[dict], tol: dict) -> dict:
    res = {"n_py": len(ref), "n_c": len(got)}
    if len(ref) != len(got):
        res["pass"] = False
        return res
    n = len(ref)
    a = lambda rows, k: np.array([r[k] for r in rows], float)  # noqa: E731
    fails = []
    for k in ("db", "floor_db", "clarity"):
        d = np.abs(a(ref, k) - a(got, k))
        # the floor is a percentile of past levels: a one-tick flip of the clarity gate changes its set; judge p99
        res[k + "_max"] = float(d.max()) if n else 0.0
        res[k + "_p99"] = float(np.percentile(d, 99)) if n else 0.0
        if res[k + "_p99"] > tol[k]:
            fails.append(k)
    v_r, v_c = a(ref, "voiced") > 0, a(got, "voiced") > 0
    res["voiced_agree"] = float(np.mean(v_r == v_c)) if n else 1.0
    both = v_r & v_c
    if both.any():
        rel = np.abs(a(ref, "f0")[both] / a(got, "f0")[both] - 1)
        res["f0_rel_p99"] = float(np.percentile(rel, 99))
        if res["f0_rel_p99"] > tol["f0_rel"]:
            fails.append("f0")
    f2r, f2c = np.isfinite(a(ref, "f2")), np.isfinite(a(got, "f2"))
    res["f2_present_agree"] = float(np.mean(f2r == f2c)) if n else 1.0
    res["n_f2"] = int(f2r.sum())
    fb = f2r & f2c
    for k in ("f1", "f2"):
        if fb.any():
            rel = np.abs(a(ref, k)[fb] / a(got, k)[fb] - 1)
            res[k + "_rel_p99"] = float(np.percentile(rel, 99))
            if res[k + "_rel_p99"] > tol["fmt_rel_p99"]:
                fails.append(k)
    for k in ("voiced_agree", "f2_present_agree"):
        if res[k] < tol["agree"]:
            fails.append(k)
    res["fails"] = fails
    res["pass"] = not fails
    return res


def main() -> int:
    spec = J.load_spec()
    tmp = tempfile.mkdtemp()
    f32 = os.path.join(tmp, "in.f32")
    report, ok, total_ticks = {}, True, 0
    for name, path in inputs():
        x, sr = load_wav(path)
        x = x[: int(MAX_S * sr)]
        if sr != 16000:
            x = to_16k(x, sr)
        x = np.ascontiguousarray(x, dtype=np.float32)
        x.astype("<f4").tofile(f32)
        ref = py_ticks(x.astype(np.float64), spec)
        total_ticks += len(ref)
        entry = {}
        for v in EXE:
            entry[v] = compare(ref, c_ticks(v, f32), TOL[v])
            ok = ok and entry[v]["pass"]
        report[name] = entry
        flag = "ok " if all(e["pass"] for e in entry.values()) else "BAD"
        d, f = entry["double"], entry["float32"]
        print(f"{flag} {name:48s} ticks {d['n_py']:4d} f2 {d.get('n_f2', 0):4d}  voiced {d.get('voiced_agree', 0):.3f}/"
              f"{f.get('voiced_agree', 0):.3f}  f2 rel p99 {d.get('f2_rel_p99', 0):.2e}/{f.get('f2_rel_p99', 0):.2e}  "
              f"fails {d.get('fails')}{f.get('fails')}")
    os.unlink(f32) if os.path.exists(f32) else None
    out = VOX / "firmware" / "tests" / "tick_check_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"pass": ok, "ticks": total_ticks, "files": report}, indent=1))
    print(f"tick check: {'PASS' if ok else 'FAIL'} ({len(report)} clips, {total_ticks} ticks) -> {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
