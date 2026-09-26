#!/usr/bin/env python3
"""Record the VOX node's microphone over USB serial into a WAV file (16 kHz, mono, 16-bit).

It sends `mic stream` (and `mic gain N`), collects the binary 'A' frames (see vox_serial.py), writes the WAV and
sends `mic off`. Then it reports what came in: frames, lost frames (sequence gaps), CRC errors, and the level. A
file of pure zeros means no mic data (wiring: SD/WS/BCLK, 3.3 V, L/R to GND).

  nix shell --impure --expr 'with import <nixpkgs> {}; python313.withPackages (p: [p.bleak p.pyserial])' \\
      -c python tools/pico_stream.py -s 5 -o rise.wav [--gain 12]

Then run the extractor on it (prints one VOX line per sound):
  cd ~/VOX/extractor && ./run python record.py --wav /absolute/path/to/rise.wav
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vox_serial import VoxSerial  # noqa: E402

RATE = 16000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default="pico.wav", help="output WAV (default pico.wav)")
    ap.add_argument("-s", "--seconds", type=float, default=5.0)
    ap.add_argument("--gain", type=int, choices=[0, 6, 12, 18, 24], help="stream gain in dB (device default 12)")
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the device console while recording")
    a = ap.parse_args()

    ser = VoxSerial(a.port, echo=a.verbose)
    chunks: list[bytes] = []
    first_seq = [None]

    def on_audio(seq: int, payload: bytes) -> None:
        if first_seq[0] is None:
            first_seq[0] = seq
        chunks.append(payload)

    try:
        if a.gain is not None:
            ser.cmd(f"mic gain {a.gain}")
            time.sleep(0.2)
        ser.on_audio = on_audio
        ser.cmd("mic stream")
        ok = ser.wait_for(lambda s: s.startswith("mic stream:"), 3.0)
        if ok is None:
            sys.exit("no answer to `mic stream` (is the VOX firmware running on the port?)")
        print(ok[1])
        print(f"recording {a.seconds:g} s ...", flush=True)
        f0, g0, c0 = ser.audio_frames, ser.audio_seq_gaps, ser.parser.crc_errors
        t0 = time.perf_counter()
        want = int(a.seconds * RATE)
        while sum(len(c) for c in chunks) // 2 < want and time.perf_counter() - t0 < a.seconds + 5:
            time.sleep(0.05)
        dt = time.perf_counter() - t0
        ser.on_audio = None
        ser.cmd("mic off")
        time.sleep(0.3)
        frames, gaps, crc = ser.audio_frames - f0, ser.audio_seq_gaps - g0, ser.parser.crc_errors - c0
    finally:
        ser.close()

    pcm = b"".join(chunks)[: want * 2]
    n = len(pcm) // 2
    with wave.open(a.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    s = struct.unpack(f"<{n}h", pcm) if n else ()
    zeros = sum(1 for x in s if x == 0)
    peak = max((abs(x) for x in s), default=0)
    mean = sum(s) / n if n else 0.0
    rms = math.sqrt(sum((x - mean) ** 2 for x in s) / n) if n else 0.0
    db = lambda v: 20 * math.log10(v / 32768) if v > 0 else float("-inf")  # noqa: E731
    print(f"wrote {a.out}: {n} samples ({n / RATE:.2f} s) in {dt:.2f} s; {frames} frames "
          f"({frames / dt:.0f}/s, expect 100/s), lost frames (seq gaps) {gaps}, CRC errors {crc}")
    print(f"level: rms {db(rms):.1f} dBFS, peak {db(peak):.1f} dBFS, DC {mean:.0f}, zero samples {zeros / max(n, 1):.0%}")
    if n and zeros == n:
        print("ALL ZEROS: no data from the mic. Check SD -> GP20, WS -> GP19, BCLK -> GP18, VDD 3.3 V, GND, L/R -> GND.")
    elif n and len(set(s)) == 1:
        print("CONSTANT: the mic data line is stuck. Check the SD wire.")
    elif peak >= 32767:
        print("CLIPPING: lower the gain (--gain 6 or 0).")
    if gaps or crc:
        print("warning: frames were lost or corrupted on USB; the WAV has holes at those places")
    sys.exit(1 if (gaps or crc or n < want) else 0)


if __name__ == "__main__":
    main()
