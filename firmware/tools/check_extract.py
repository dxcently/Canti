#!/usr/bin/env python3
"""Compare the C++ extractor port (firmware/extract, host build) with the Python reference (extractor/vox_extract).

Run through tools/check_extract.sh, which builds the host CLI first. It only READS extractor/ and datasets/.

Checks, in order:
  config     the C defaults (vx_cli --dump-config) equal Config() field for field
  vocab      sha256 of the C vocabulary JSON == vocab.digest()
  decimator  the C Decimator3 on vectors/decimator.in48k.f32 vs decimator.out16k.f32 (abs 1e-5)
  vectors    every case in vectors/manifest.json: events (count, label, text exact; times within one hop; fp1 and
             pitch16 within abs 0.01 + rel 0.01) and frames (manifest tolerances, frames above floor + 6 dB)
  real       the user's live recordings (extractor/recordings/**/session.wav, 48 kHz through the decimator) and a
             fixed sample of the public datasets (datasets/, to_16k like eval_real), Python run live on the same
             input; same event rules, and frame deviations
  glue       the sketch glue (ext.cpp, ext_sim) on every vector: events, and the hold messages it would send
  holds      hold start / pitch / end (vx_cli --holds) and each event's sound / held equal Extractor.push_stream on the
             vectors and the real audio (kind, sound exact; times within one hop; f0 within 0.5 %)

Each check runs the float32 build (what the Pico runs) and the double build (-DVX_REAL_DOUBLE: a porting check,
it should match to rounding). Writes tests/extract_check_report.json. Exit status 1 if any float32 or double
event check fails.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FW = HERE.parent
VOX = FW.parent
EXT = VOX / "extractor"
DATA = VOX / "datasets"
BIN = FW / "build" / "host"
sys.path.insert(0, str(EXT))

from vox_extract import Config, vocab  # noqa: E402
from vox_extract.extractor import Extractor, load_wav  # noqa: E402
from vox_extract.resample import to_16k  # noqa: E402

VARIANTS = {"float32": "vx_cli", "double": "vx_cli_double", "float32_acc": "vx_cli_f32acc"}
FP_ABS, FP_REL = 0.01, 0.01
T_TOL = 10  # ms, one hop
FRAME_TOL = {"e_db": 0.05, "zcr": 1e-5,  # manifest says 0: same crossing count; float32 rounds the ratio (1 crossing = 2e-3)
             "centroid": ("rel", 0.002), "flatness": 0.002, "flux": 0.05,
             "lf_ratio": 0.002, "hf_ratio": 0.002, "f0": ("rel_clear", 0.003), "clarity": 0.01, "floor_db_after": 0.05}
# raw fields: the reference rounds them (2-4 decimals); a float32 port may move the last digit. Same rule as fp1.
RAW_SKIP = {"why", "speech_cues", "contour64", "pitch16", "fp", "fp_version", "gap_ms"}

DATASET_GLOBS = {
    "nonverbal_click": "nonverbal/NonverbalVocalization/tongue-clicking/*.wav",
    "nonverbal_pop": "nonverbal/NonverbalVocalization/lip-popping/*.wav",
    "nonverbal_other": "nonverbal/NonverbalVocalization/*/*.wav",
    "qbsh": "mir-qbsh/MIR-QBSH-corpus/waveFile/*/*/*.wav",
    "mlend": "mlend_hums_whistles/MLEndHWD_audiofiles/*.wav",
    "musan_speech": "musan/musan/speech/*/*.wav",
    "musan_music": "musan/musan/music/*/*.wav",
    "musan_noise": "musan/musan/noise/*/*.wav",
    "nonspeech7k": "nonspeech7k/*/*.wav",
    "esc50": "esc50/ESC-50-master/audio/*.wav",
}
MAX_CLIP_S = 60.0


# ---------------------------------------------------------------- running both sides

def run_c(variant: str, args: list[str], frames: bool = False) -> tuple[list[dict], list[dict] | None, str]:
    exe = BIN / VARIANTS[variant]
    fr = None
    extra = []
    if frames:
        fd, fr = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        extra = ["--frames", fr]
    p = subprocess.run([str(exe)] + args + extra + ["--stats"], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"{exe.name} {' '.join(args)}: {p.stderr}")
    events = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
    rows = None
    if fr:
        with open(fr) as f:
            rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]
        os.unlink(fr)
    return events, rows, p.stderr.strip()


def run_py(x: np.ndarray, rate: int, frames: bool = False) -> tuple[list[dict], list[dict] | None]:
    ex = Extractor(Config(), input_rate=rate, keep_frames=frames)
    events = []
    for i in range(0, x.size, 1600):          # extract_array's chunking
        events += ex.push(x[i:i + 1600])
    events += ex.flush()
    rows = None
    if frames:
        rows = []
        for fr, fl in zip(ex.frames, ex.floors):
            d = dict(zip(["index", "t_ms", "e_db", "zcr", "centroid", "flatness", "flux", "lf_ratio", "hf_ratio", "f0",
                          "clarity"], fr.as_list()))
            d["floor_db_after"] = fl
            rows.append(d)
    return [json.loads(json.dumps(e.to_dict(), default=float)) for e in events], rows


# ---------------------------------------------------------------- comparing

def within(c: float, r: float) -> bool:
    return abs(c - r) <= FP_ABS + FP_REL * abs(r)


def compare_events(ref: list[dict], got: list[dict]) -> dict:
    """Align by start time (within one hop, in order) and compare."""
    out = {"n_ref": len(ref), "n_got": len(got), "matched": 0, "unmatched_ref": [], "unmatched_got": [],
           "label_text_mismatch": [], "dt_start_max": 0, "dt_end_max": 0, "times_exact": 0,
           "fp_violations": 0, "pitch16_violations": 0, "fp_max_dev": 0.0, "pitch16_max_dev": 0.0,
           "raw_violations": {}, "raw_max_dev": {}}
    i = j = 0
    while i < len(ref) or j < len(got):
        if i < len(ref) and j < len(got) and abs(ref[i]["t_start_ms"] - got[j]["t_start_ms"]) <= T_TOL:
            r, g = ref[i], got[j]
            out["matched"] += 1
            if r["label"] != g["label"] or r["text"] != g["text"]:
                out["label_text_mismatch"].append({"t_start_ms": r["t_start_ms"], "ref": [r["label"], r["text"]],
                                                   "got": [g["label"], g["text"]]})
            ds, de = abs(r["t_start_ms"] - g["t_start_ms"]), abs(r["t_end_ms"] - g["t_end_ms"])
            out["dt_start_max"] = max(out["dt_start_max"], ds)
            out["dt_end_max"] = max(out["dt_end_max"], de)
            out["times_exact"] += int(ds == 0 and de == 0)
            rr, gr = r.get("raw", {}), g.get("raw", {})
            for key in ("fp", "pitch16"):
                a, b = rr.get(key) or [], gr.get(key) or []
                if len(a) != len(b):
                    out[f"{key}_violations"] += 1
                    continue
                for va, vb in zip(a, b):
                    out[f"{key}_max_dev"] = max(out[f"{key}_max_dev"], abs(va - vb))
                    if not within(vb, va):
                        out[f"{key}_violations"] += 1
            for k, v in rr.items():
                if k in RAW_SKIP or isinstance(v, (bool, str, list)) or v is None:
                    continue
                gv = gr.get(k)
                if not isinstance(gv, (int, float)) or isinstance(gv, bool):
                    out["raw_violations"][k] = out["raw_violations"].get(k, 0) + 1
                    continue
                dev = abs(gv - v)
                out["raw_max_dev"][k] = max(out["raw_max_dev"].get(k, 0.0), dev)
                if not within(gv, v):
                    out["raw_violations"][k] = out["raw_violations"].get(k, 0) + 1
            i += 1
            j += 1
        elif j >= len(got) or (i < len(ref) and ref[i]["t_start_ms"] < got[j]["t_start_ms"]):
            out["unmatched_ref"].append([ref[i]["t_start_ms"], ref[i]["label"]])
            i += 1
        else:
            out["unmatched_got"].append([got[j]["t_start_ms"], got[j]["label"]])
            j += 1
    out["pass"] = (out["n_ref"] == out["n_got"] == out["matched"] and not out["label_text_mismatch"]
                   and out["dt_start_max"] <= T_TOL and out["dt_end_max"] <= T_TOL
                   and out["fp_violations"] == 0 and out["pitch16_violations"] == 0)
    return out


def compare_frames(ref: list[dict], got: list[dict]) -> dict:
    out = {"n_ref": len(ref), "n_got": len(got), "compared": 0, "max_dev": {}, "violations": {}}
    for r, g in zip(ref, got):
        if not (r["e_db"] > r["floor_db_after"] + 6 and g["e_db"] > g["floor_db_after"] + 6):
            continue
        out["compared"] += 1
        for k, tol in FRAME_TOL.items():
            if k == "f0" and not (r["clarity"] >= 0.8 and g["clarity"] >= 0.8):
                continue
            d = abs(g[k] - r[k])
            if isinstance(tol, tuple):
                d = d / max(abs(r[k]), 1e-9)
                tol = tol[1]
            out["max_dev"][k] = max(out["max_dev"].get(k, 0.0), d)
            if d > tol + 1e-12:
                out["violations"][k] = out["violations"].get(k, 0) + 1
    out["max_dev"] = {k: float(f"{v:.3g}") for k, v in out["max_dev"].items()}
    return out


def merge_frames(acc: dict, fr: dict) -> None:
    acc["compared"] = acc.get("compared", 0) + fr["compared"]
    for k, v in fr["max_dev"].items():
        acc.setdefault("max_dev", {})[k] = max(acc.get("max_dev", {}).get(k, 0.0), v)
    for k, v in fr["violations"].items():
        acc.setdefault("violations", {})[k] = acc.get("violations", {}).get(k, 0) + v


# ---------------------------------------------------------------- the checks

def check_config() -> dict:
    p = subprocess.run([str(BIN / "vx_cli"), "--dump-config"], capture_output=True, text=True, check=True)
    c = json.loads(p.stdout)
    py = json.loads(Config().to_json())
    diff = {k: (py.get(k), c.get(k)) for k in set(py) | set(c) if py.get(k) != c.get(k) or list(py).index(k) != list(c).index(k)
            if k in py and k in c} if set(py) == set(c) else {"keys": [sorted(set(py) - set(c)), sorted(set(c) - set(py))]}
    order_ok = list(py) == list(c)
    return {"pass": not diff and order_ok, "fields": len(py), "diff": {k: list(v) for k, v in diff.items()}, "order_ok": order_ok}


def check_vocab() -> dict:
    p = subprocess.run([str(BIN / "vx_cli"), "--vocab-json"], capture_output=True, check=True)
    d = hashlib.sha256(p.stdout).hexdigest()[:16]
    return {"pass": d == vocab.digest(), "c": d, "python": vocab.digest()}


def check_decimator() -> dict:
    vec = EXT / "vectors"
    fd, out = tempfile.mkstemp(suffix=".f32")
    os.close(fd)
    res = {}
    for v in ("float32", "double"):
        subprocess.run([str(BIN / VARIANTS[v]), "--decim", str(vec / "decimator.in48k.f32"), out], check=True)
        got = np.fromfile(out, dtype="<f4")
        ref = np.fromfile(vec / "decimator.out16k.f32", dtype="<f4")
        dev = float(np.max(np.abs(got - ref))) if got.size == ref.size else float("inf")
        res[v] = {"n": int(got.size), "n_ref": int(ref.size), "max_abs_dev": dev, "pass": got.size == ref.size and dev <= 1e-5}
    os.unlink(out)
    return res


def check_vectors(variants: list[str]) -> dict:
    vec = EXT / "vectors"
    man = json.loads((vec / "manifest.json").read_text())
    res = {}
    for case in man["cases"]:
        name, rate = case["name"], case["rate"]
        ref_ev = json.loads((vec / f"{name}.events.json").read_text())["events"]
        with open(vec / f"{name}.frames.csv") as f:
            ref_fr = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]
        res[name] = {}
        for v in variants:
            ev, fr, _ = run_c(v, ["--pcm", str(vec / f"{name}.pcm"), "--rate", str(rate)], frames=True)
            ce = compare_events(ref_ev, ev)
            cf = compare_frames(ref_fr, fr)
            res[name][v] = {"events": ce, "frames": cf, "labels": [e["label"] for e in ev]}
    return res


def check_glue() -> dict:
    """The sketch's core-0/core-1 glue (arduino/vox_node/ext.cpp) on the host (build/host/ext_sim, two threads):
    every vector through `ext feed` (both rates) and, at 16 kHz, through the mic path (ext_mic_push, then 1 s of
    silence). Checks the ring, the reset and flush handshakes and the event queue against the reference events, and
    the hold messages the glue sends (with each sound's id and held flag, in emission order) against push_stream."""
    vec = EXT / "vectors"
    man = json.loads((vec / "manifest.json").read_text())
    res = {}
    for case in man["cases"]:
        name, rate = case["name"], case["rate"]
        ref = json.loads((vec / f"{name}.events.json").read_text())["events"]
        x = np.fromfile(vec / f"{name}.pcm", dtype="<i2").astype(np.float32) / np.float32(32768.0)
        ref_stream = run_py_stream(x, rate)   # hold messages + numbered events
        for mode in ("feed", "mic"):
            if mode == "mic" and rate != 16000:
                continue
            p = subprocess.run([str(BIN / "ext_sim"), "--pcm", str(vec / f"{name}.pcm"), "--rate", str(rate), "--mode", mode],
                               capture_output=True, text=True)
            got, seq = [], []   # seq: holds and events in the order the glue sent them
            file_ms = (vec / f"{name}.pcm").stat().st_size / 2 / (rate / 1000)
            for line in p.stdout.splitlines():
                e = json.loads(line)
                if "hold" in e:
                    if not (mode == "mic" and e["t_start_ms"] >= file_ms - 30):
                        seq.append(e)
                    continue
                e["raw"] = e.pop("features", None) or {}
                # mic path: the harness pads with digital silence so that sounds end by the hangover (the mic never
                # flushes); the step from the vector's noise to exact zeros is itself a sound. Not the glue's.
                if mode == "mic" and e["t_start_ms"] >= file_ms - 30:
                    continue
                got.append(e)
                seq.append(e)
            c = compare_events(ref, got)
            ch = compare_holds(ref_stream, seq, exact_keys=False)
            c["holds"] = {k: ch[k] for k in ("n_ref", "n_got", "mismatch", "dt_max", "f0_max_rel", "event_ids_mismatch", "order_ok", "pass")}
            c["pass"] = c["pass"] and p.returncode == 0 and ch["pass"] and "overflow 0" in (p.stderr if mode == "mic" else "overflow 0")
            c["stderr"] = p.stderr.strip()[-300:]
            res[f"{name}/{mode}"] = c
    return res


def real_inputs(n_per_dataset: int) -> list[tuple[str, str, int]]:
    """(name, path, rate hint) - live sessions first, then a fixed sample of each dataset."""
    items = []
    for p in sorted(glob.glob(str(EXT / "recordings" / "**" / "session.wav"), recursive=True)):
        items.append(("live/" + str(Path(p).parent.relative_to(EXT / "recordings")), p, 0))
    if n_per_dataset > 0 and DATA.exists():
        for ds, pat in DATASET_GLOBS.items():
            files = sorted(glob.glob(str(DATA / pat)))
            if ds == "nonverbal_other":
                files = [f for f in files if "/tongue-clicking/" not in f and "/lip-popping/" not in f]
            if not files:
                continue
            step = max(1, len(files) // n_per_dataset)
            for f in files[::step][:n_per_dataset]:
                items.append((f"{ds}/{Path(f).name}", f, 0))
    return items


def check_real(variants: list[str], n_per_dataset: int, frames: bool) -> dict:
    res = {"files": {}, "summary": {}}
    tmpdir = tempfile.mkdtemp()
    for name, path, _ in real_inputs(n_per_dataset):
        x, sr = load_wav(path)
        if sr in (16000, 48000):
            x = x[: int(MAX_CLIP_S * sr)]
            rate = sr
        else:
            x = to_16k(x[: int(MAX_CLIP_S * sr)], sr)
            rate = 16000
        x = np.ascontiguousarray(x, dtype=np.float32)
        f32 = os.path.join(tmpdir, "in.f32")
        x.astype("<f4").tofile(f32)
        py_ev, py_fr = run_py(x, rate, frames)
        entry = {"rate_in": sr, "seconds": round(x.size / rate, 2), "n_py": len(py_ev)}
        for v in variants:
            ev, fr, _ = run_c(v, ["--f32", f32, "--rate", str(rate)], frames=frames)
            ce = compare_events(py_ev, ev)
            entry[v] = {"pass": ce["pass"], "events": ce}
            if frames:
                entry[v]["frames"] = compare_frames(py_fr, fr)
        res["files"][name] = entry
    os.unlink(os.path.join(tmpdir, "in.f32")) if os.path.exists(os.path.join(tmpdir, "in.f32")) else None
    os.rmdir(tmpdir)
    for v in variants:
        files = [e for e in res["files"].values() if v in e]
        s = {"files": len(files), "files_pass": sum(e[v]["pass"] for e in files),
             "events_ref": sum(e[v]["events"]["n_ref"] for e in files),
             "events_matched": sum(e[v]["events"]["matched"] for e in files),
             "label_text_mismatch": sum(len(e[v]["events"]["label_text_mismatch"]) for e in files),
             "unmatched": sum(len(e[v]["events"]["unmatched_ref"]) + len(e[v]["events"]["unmatched_got"]) for e in files),
             "dt_start_max": max([e[v]["events"]["dt_start_max"] for e in files] or [0]),
             "dt_end_max": max([e[v]["events"]["dt_end_max"] for e in files] or [0]),
             "fp_max_dev": max([e[v]["events"]["fp_max_dev"] for e in files] or [0]),
             "pitch16_max_dev": max([e[v]["events"]["pitch16_max_dev"] for e in files] or [0]),
             "fp_violations": sum(e[v]["events"]["fp_violations"] for e in files),
             "pitch16_violations": sum(e[v]["events"]["pitch16_violations"] for e in files)}
        fr_acc: dict = {}
        if frames:
            for e in files:
                merge_frames(fr_acc, e[v]["frames"])
            s["frames"] = fr_acc
        res["summary"][v] = s
    return res




# ---------------------------------------------------------------- hold messages (hold.py / vx_hold.cpp)

HOLD_F0_REL = 0.005   # f0_hz: the float32 build's per-frame f0 is within 0.3 % of the reference (FRAME_TOL)


def run_py_stream(x: np.ndarray, rate: int) -> list[dict]:
    """Extractor.push_stream / flush_stream: hold messages and events in emission order, as dicts."""
    ex = Extractor(Config(), input_rate=rate)
    out = []
    step = 1600 * (rate // 16000)
    for i in range(0, x.size, step):
        out += ex.push_stream(x[i:i + step])
    out += ex.flush_stream()
    return [json.loads(json.dumps(o.to_dict(), default=float)) for o in out]


def compare_holds(ref: list[dict], got: list[dict], exact_keys: bool = True) -> dict:
    """Hold messages in order (kind, sound exact; times within one hop; f0 within HOLD_F0_REL), and each event's
    sound / held (the events themselves are compare_events' job). exact_keys: the same keys
    (vx_cli); off, the reference's keys only (ext_sim's mic path prints every field)."""
    rh, gh = [d for d in ref if "hold" in d], [d for d in got if "hold" in d]
    re_, ge = [d for d in ref if "hold" not in d], [d for d in got if "hold" not in d]
    out = {"n_ref": len(rh), "n_got": len(gh), "kinds_ref": {}, "mismatch": [], "dt_max": 0, "f0_max_rel": 0.0,
           "event_ids_mismatch": 0}
    for d in rh:
        out["kinds_ref"][d["hold"]] = out["kinds_ref"].get(d["hold"], 0) + 1
    for i, (r, g) in enumerate(zip(rh, gh)):
        bad = r["hold"] != g["hold"] or r["sound"] != g["sound"] or (set(r) != set(g) if exact_keys else not set(r) <= set(g))
        for k in ("t_ms", "t_start_ms"):
            if k in r and k in g:
                out["dt_max"] = max(out["dt_max"], abs(r[k] - g[k]))
                bad |= abs(r[k] - g[k]) > T_TOL
        if "f0_hz" in r and "f0_hz" in g:
            rel = abs(r["f0_hz"] - g["f0_hz"]) / max(r["f0_hz"], 1e-9)
            out["f0_max_rel"] = max(out["f0_max_rel"], rel)
            bad |= rel > HOLD_F0_REL
        for k in ("flat", "from", "dir"):   # from / dir: glide-and-hold starts
            if k in r and r.get(k) != g.get(k):
                bad = True
        if bad and len(out["mismatch"]) < 5:
            out["mismatch"].append({"i": i, "ref": r, "got": g})
        out["n_bad"] = out.get("n_bad", 0) + int(bad)
    if len(rh) != len(gh):
        out["mismatch"].append({"count": [len(rh), len(gh)], "ref_tail": rh[len(gh):][:2], "got_tail": gh[len(rh):][:2]})
    for r, g in zip(re_, ge):
        if r.get("sound", 0) != g.get("sound", 0) or r.get("held", False) != g.get("held", False):
            out["event_ids_mismatch"] += 1
    out["event_ids_mismatch"] += abs(len(re_) - len(ge))
    # emission order: hold start, pitch..., end, then the event, sound by sound
    tag = lambda d: (d.get("hold", "event"), d.get("sound", 0))
    out["order_ok"] = [tag(d) for d in ref] == [tag(d) for d in got]
    out["pass"] = len(rh) == len(gh) and not out.get("n_bad") and out["event_ids_mismatch"] == 0 and out["order_ok"]
    return out


def check_holds(variants: list[str], n_per_dataset: int) -> dict:
    """Every vector, the live recordings and n_per_dataset clips of each public dataset through --holds."""
    vec = EXT / "vectors"
    man = json.loads((vec / "manifest.json").read_text())
    items = [(f"vec/{c['name']}", vec / f"{c['name']}.pcm", c["rate"]) for c in man["cases"]]
    items += [(n, Path(p), 0) for n, p, _ in real_inputs(n_per_dataset)]
    res = {"files": {}, "summary": {}}
    tmpdir = tempfile.mkdtemp()
    f32 = os.path.join(tmpdir, "in.f32")
    for name, path, rate in items:
        if rate:
            x = np.fromfile(path, dtype="<i2").astype(np.float32) / np.float32(32768.0)
        else:
            x, sr = load_wav(str(path))
            if sr in (16000, 48000):
                x, rate = x[: int(MAX_CLIP_S * sr)], sr
            else:
                x, rate = to_16k(x[: int(MAX_CLIP_S * sr)], sr), 16000
        x = np.ascontiguousarray(x, dtype=np.float32)
        x.astype("<f4").tofile(f32)
        ref = run_py_stream(x, rate)
        entry = {}
        for v in variants:
            got, _, _ = run_c(v, ["--f32", f32, "--rate", str(rate), "--holds"])
            entry[v] = compare_holds(ref, got)
        res["files"][name] = entry
    if os.path.exists(f32):
        os.unlink(f32)
    os.rmdir(tmpdir)
    for v in variants:
        fs = [e[v] for e in res["files"].values()]
        kinds: dict = {}
        for f in fs:
            for k, n in f["kinds_ref"].items():
                kinds[k] = kinds.get(k, 0) + n
        res["summary"][v] = {"files": len(fs), "files_pass": sum(f["pass"] for f in fs), "holds_ref": kinds,
                             "holds_got": sum(f["n_got"] for f in fs), "bad": sum(f.get("n_bad", 0) for f in fs),
                             "dt_max": max([f["dt_max"] for f in fs] or [0]),
                             "f0_max_rel": max([f["f0_max_rel"] for f in fs] or [0.0]),
                             "event_ids_mismatch": sum(f["event_ids_mismatch"] for f in fs)}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", type=int, default=25, help="clips per public dataset (0: live recordings only)")
    ap.add_argument("--no-real", action="store_true", help="skip the real-audio comparison")
    ap.add_argument("--no-frames", action="store_true", help="real audio: events only (faster)")
    ap.add_argument("--acc-float", action="store_true", help="also run the float32-accumulator build")
    ap.add_argument("--report", type=Path, default=FW / "tests" / "extract_check_report.json")
    a = ap.parse_args()
    variants = ["float32", "double"] + (["float32_acc"] if a.acc_float else [])
    t0 = time.time()
    rep = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "variants": variants,
           "rules": {"events": "count, label and text exact; t_start/t_end within 10 ms; fp1 and pitch16 per value "
                               "|c - ref| <= 0.01 + 0.01 |ref|",
                     "frames": "manifest tolerances on frames where both sides are above floor + 6 dB; f0 only where "
                               "both clarities >= 0.8; zcr 1e-5 (same crossing count)"}}
    rep["config"] = check_config()
    rep["vocab"] = check_vocab()
    rep["decimator"] = check_decimator()
    print(f"config: {'ok' if rep['config']['pass'] else 'DIFF ' + json.dumps(rep['config'])} ({rep['config']['fields']} fields)")
    print(f"vocab digest: C {rep['vocab']['c']} Python {rep['vocab']['python']} {'ok' if rep['vocab']['pass'] else 'DIFF'}")
    for v, d in rep["decimator"].items():
        print(f"decimator {v}: {d['n']} samples, max |dev| {d['max_abs_dev']:.2e} {'ok' if d['pass'] else 'FAIL'}")
    rep["vectors"] = check_vectors(variants)
    rep["glue"] = check_glue()
    ok = rep["config"]["pass"] and rep["vocab"]["pass"] and all(d["pass"] for d in rep["decimator"].values())
    print(f"\n{'vector':<22}" + "".join(f"{v:>30}" for v in variants))
    for name, r in rep["vectors"].items():
        cells = []
        for v in variants:
            e = r[v]["events"]
            viol = sum(n for k, n in r[v]["frames"]["violations"].items() if k != "zcr")
            cells.append(f"{'PASS' if e['pass'] else 'FAIL'} {e['n_got']}/{e['n_ref']} ev, dt {e['dt_start_max']}/{e['dt_end_max']}, fr {viol}")
            ok &= e["pass"]
        print(f"{name:<22}" + "".join(f"{c:>30}" for c in cells))
    for v in variants:
        md: dict = {}
        fp = p16 = 0.0
        for r in rep["vectors"].values():
            merge_frames(md, r[v]["frames"])
            fp = max(fp, r[v]["events"]["fp_max_dev"])
            p16 = max(p16, r[v]["events"]["pitch16_max_dev"])
        print(f"  {v}: frame max dev {json.dumps(md.get('max_dev', {}))}; violations {md.get('violations', {})}; "
              f"fp max dev {fp:.4g}, pitch16 max dev {p16:.4g}")
    g = rep["glue"]
    bad = [k for k, v in g.items() if not v["pass"]]
    print(f"\nsketch glue (ext.cpp on two host threads): {len(g) - len(bad)}/{len(g)} runs pass "
          f"(feed: all vectors, mic path: the 16 kHz ones); dt max {max(v['dt_start_max'] for v in g.values())}/"
          f"{max(v['dt_end_max'] for v in g.values())} ms" + (f"; FAIL {bad}" if bad else ""))
    ok &= not bad
    rep["holds"] = check_holds(variants, 0 if a.no_real else a.real)
    print(f"\nhold messages (--holds vs Extractor.push_stream; vectors + real audio):")
    for v, s in rep["holds"]["summary"].items():
        print(f"  {v}: {s['files_pass']}/{s['files']} files pass; ref {s['holds_ref']}, got {s['holds_got']}, {s['bad']} differ, "
              f"dt max {s['dt_max']} ms, f0 max rel dev {s['f0_max_rel']:.2g}, event sound/held mismatches {s['event_ids_mismatch']}")
        if v in ("float32", "double"):
            ok &= s["files_pass"] == s["files"]
    if not a.no_real:
        rep["real"] = check_real(variants, a.real, not a.no_frames)
        print(f"\nreal audio: {len(rep['real']['files'])} files")
        for v, s in rep["real"]["summary"].items():
            print(f"  {v}: {s['files_pass']}/{s['files']} files pass; events {s['events_matched']}/{s['events_ref']} matched, "
                  f"{s['label_text_mismatch']} label/text mismatches, {s['unmatched']} unmatched, "
                  f"dt max {s['dt_start_max']}/{s['dt_end_max']} ms, fp max dev {s['fp_max_dev']:.4g} "
                  f"({s['fp_violations']} over tol), pitch16 max dev {s['pitch16_max_dev']:.4g} ({s['pitch16_violations']})")
            if "frames" in s:
                print(f"      frames compared {s['frames'].get('compared', 0)}, max dev {json.dumps(s['frames'].get('max_dev', {}))}, "
                      f"violations {s['frames'].get('violations', {})}")
            for name, e in rep["real"]["files"].items():
                if v in e and not e[v]["pass"]:
                    ev = e[v]["events"]
                    print(f"      {v} {name}: {ev['n_got']}/{ev['n_ref']} events, mismatches {ev['label_text_mismatch'][:2]}, "
                          f"unmatched ref {ev['unmatched_ref'][:3]} got {ev['unmatched_got'][:3]}, fp viol {ev['fp_violations']}, "
                          f"p16 viol {ev['pitch16_violations']}")
            if v in ("float32", "double"):
                ok &= s["files_pass"] == s["files"]
    rep["pass"] = bool(ok)
    rep["seconds"] = round(time.time() - t0, 1)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(rep, indent=1) + "\n")
    print(f"\n{'PASS' if ok else 'FAIL'} ({rep['seconds']} s); report {a.report}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
