#!/usr/bin/env python3
"""Run audio through the ON-DEVICE extractor over USB serial (`ext feed`) and compare with the reference.

The device takes the samples instead of the mic, runs them through the same core-1 extractor, and prints each sound
as `ext event {...}` + `ext features {...}` lines, then `ext feed: done` and its `ext stats` (cycles per hop etc.).

  PY="nix shell --impure --expr 'with import <nixpkgs> {}; python313.withPackages (p: [p.pyserial])' -c python"
  $PY tools/ext_feed.py --vectors                  # every case in extractor/vectors, checked against its events.json
  $PY tools/ext_feed.py --vectors rise_20db talk_20db
  $PY tools/ext_feed.py --wav some.wav [--ref ref.jsonl]   # PCM16 mono 16/48 kHz; --ref: one event JSON per line
                                                           # (vx_cli or the Python extractor), else just printed

Pass rules (as tools/check_extract.py): same count, labels and texts; t_start/t_end within 10 ms; fp1 and pitch16
|dev| <= 0.01 + 0.01 |ref|. The device computes in float32 with the RP2350's own libm, so a value can differ in
the last rounded digit; that is inside the tolerance.
Needs pyserial only. Writes nothing (stdout; --json FILE for a machine-readable report).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import wave
from pathlib import Path

import serial

HERE = Path(__file__).resolve().parent
VEC = HERE.parent.parent / "extractor" / "vectors"
T_TOL = 10


def within(c: float, r: float) -> bool:
    return abs(c - r) <= 0.01 + 0.01 * abs(r)


_pending = b""   # bytes read after the line that ended the previous read_until (the next lines of the same burst)


def read_until(port: serial.Serial, pred, timeout: float) -> list[str]:
    """Collect text lines until pred(line) or the timeout. Bytes already read past the matching line are kept for the
    next call (`ext feed: done` and the stats lines after it usually arrive in one USB packet)."""
    global _pending
    lines, buf, t0 = [], _pending, time.time()
    _pending = b""
    while True:
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            s = raw.decode(errors="replace").rstrip("\r")
            lines.append(s)
            if pred(s):
                _pending = buf
                return lines
        if time.time() - t0 >= timeout:
            break
        buf += port.read(port.in_waiting or 1)
    raise TimeoutError(f"no answer within {timeout} s; last lines: {lines[-5:]}")


def feed(port: serial.Serial, pcm: bytes, rate: int) -> tuple[list[dict], list[str]]:
    global _pending
    n = len(pcm) // 2
    port.reset_input_buffer()
    _pending = b""
    port.write(f"ext feed {n} {rate}\n".encode())   # "\n" only: the byte after it is already a sample
    read_until(port, lambda s: s.startswith("ext feed: send") or s.startswith("err"), 5)
    # Read the device's output WHILE writing: its `ext event` lines come out as it goes, and an unread output backs up
    # (the tty buffer is only a few KB), which stalls core 0, overflows the 4-deep event queue, cuts lines, and on a
    # long feed (extractor/vectors/long_stream_rise, 170 s) tripped the 8 s watchdog (Pico 2 W, 2026-09-26).
    done = threading.Event()
    got: list[bytes] = []

    def reader():
        while not done.is_set():
            b = port.read(port.in_waiting or 1)
            if b:
                got.append(b)

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        for i in range(0, len(pcm), 4096):         # USB flow control holds us back when the ring is full
            port.write(pcm[i:i + 4096])
    finally:
        done.set()
        th.join()
    _pending += b"".join(got)
    lines = read_until(port, lambda s: s.startswith("ext feed: done"), 30 + n / 16000)
    lines += read_until(port, lambda s: s.startswith("ext: core-1 load"), 3)
    events = []
    for s in lines:
        if s.startswith("ext event "):
            events.append(json.loads(s[len("ext event "):]))
        elif s.startswith("ext features ") and events:
            events[-1]["features"] = json.loads(s[len("ext features "):])
    stats = [s for s in lines if s.startswith("ext:")]
    return events, stats


def compare(ref: list[dict], got: list[dict]) -> dict:
    out = {"n_ref": len(ref), "n_got": len(got), "problems": [], "dt_max": 0, "fp_max_dev": 0.0, "p16_max_dev": 0.0}
    if len(ref) != len(got):
        out["problems"].append(f"{len(got)} events, reference {len(ref)}")
    for r, g in zip(ref, got):
        if (r["label"], r["text"]) != (g["label"], g["text"]):
            out["problems"].append(f"t={r['t_start_ms']}: {g['label']!r} {g['text']!r} vs {r['label']!r} {r['text']!r}")
        dt = max(abs(r["t_start_ms"] - g["t_start_ms"]), abs(r["t_end_ms"] - g["t_end_ms"]))
        out["dt_max"] = max(out["dt_max"], dt)
        if dt > T_TOL:
            out["problems"].append(f"t={r['t_start_ms']}: times off by {dt} ms")
        rr, gf = r.get("raw") or {}, g.get("features") or {}
        for key, dkey in (("fp", "fp_max_dev"), ("pitch16", "p16_max_dev")):
            a, b = rr.get(key) or [], gf.get(key) or []
            if len(a) != len(b):
                out["problems"].append(f"t={r['t_start_ms']}: {key} length {len(b)} vs {len(a)}")
                continue
            for va, vb in zip(a, b):
                out[dkey] = max(out[dkey], abs(va - vb))
                if not within(vb, va):
                    out["problems"].append(f"t={r['t_start_ms']}: {key} {vb} vs {va}")
    out["pass"] = not out["problems"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--vectors", nargs="*", help="vector cases (none listed = all)")
    ap.add_argument("--wav", type=Path)
    ap.add_argument("--ref", type=Path, help="reference events for --wav, one JSON object per line")
    ap.add_argument("--json", type=Path, help="write the results here")
    a = ap.parse_args()
    port = serial.Serial(a.port, 115200, timeout=0.05)
    time.sleep(0.2)
    port.write(b"\n")
    time.sleep(0.2)
    port.reset_input_buffer()
    results, ok = {}, True
    jobs = []
    if a.vectors is not None:
        man = json.loads((VEC / "manifest.json").read_text())
        for c in man["cases"]:
            if not a.vectors or c["name"] in a.vectors:
                ref = json.loads((VEC / f"{c['name']}.events.json").read_text())["events"]
                jobs.append((c["name"], (VEC / f"{c['name']}.pcm").read_bytes(), c["rate"], ref))
    if a.wav:
        with wave.open(str(a.wav)) as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1 or w.getframerate() not in (16000, 48000):
                sys.exit("--wav: PCM16 mono at 16 or 48 kHz only")
            pcm, rate = w.readframes(w.getnframes()), w.getframerate()
        ref = [json.loads(l) for l in a.ref.read_text().splitlines() if l.strip()] if a.ref else None
        jobs.append((a.wav.name, pcm, rate, ref))
    for name, pcm, rate, ref in jobs:
        events, stats = feed(port, pcm, rate)
        r = {"events": events, "stats": stats}
        if ref is not None:
            r.update(compare(ref, events))
            ok &= r["pass"]
            print(f"{name:<20} {'PASS' if r['pass'] else 'FAIL'} {r['n_got']}/{r['n_ref']} events, dt max {r['dt_max']} ms, "
                  f"fp max dev {r['fp_max_dev']:.4g}, pitch16 max dev {r['p16_max_dev']:.4g}")
            for p in r["problems"][:5]:
                print("    " + p)
        else:
            print(f"{name}: {len(events)} events")
            for e in events:
                print(f"    [{e['t_start_ms']}..{e['t_end_ms']}] {e['label']}: {e['text']}")
        for s in stats:
            if "hop mean" in s or "sound end" in s:
                print("    " + s)
        results[name] = r
    if a.json:
        a.json.write_text(json.dumps(results, indent=1) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
