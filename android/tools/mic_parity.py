"""JNI parity and speed of the phone-mic extractor ON THE DEVICE, through the debug socket's `mic_feed` op.

Every extractor/vectors case is sent as PCM16 to the app, run through the same libvx_jni.so the live mic uses
(20 ms pushes through a direct buffer, like the audio thread), and its events are compared with the vector's
reference events exactly as firmware/tools/check_extract.py compares them (compare_events). --bench repeats each case
N times and reports the per-hop time the device measured (p50/p90/p99/max) and the real-time factor.

    ./dev bash -c "../extractor/run python tools/mic_parity.py"                 # $VOX_SERIAL, default the suite's emulator
    VOX_SERIAL=R5CX62H7PNJ ./dev bash -c "../extractor/run python tools/mic_parity.py --bench 20"

Needs a debuggable build with the debug socket on (`debug_source`), the accessibility service running, and numpy
(extractor/run provides it, for check_extract's imports). No microphone and no permission are involved: the audio is
the synthetic vectors, sent over adb.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANDROID = HERE.parent
VOX = ANDROID.parent
sys.path.insert(0, str(ANDROID / "suite"))
sys.path.insert(0, str(VOX / "firmware" / "tools"))

from voxlib import SERIAL, Vox  # noqa: E402
from check_extract import compare_events  # noqa: E402

VECTORS = VOX / "extractor" / "vectors"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", type=int, default=0, metavar="N", help="also time N repeats of every case")
    ap.add_argument("--chunk-ms", type=int, default=20, help="samples per push, in ms (the live read size)")
    ap.add_argument("--only", help="comma-separated case names")
    ap.add_argument("--json", help="write the full results here")
    a = ap.parse_args()

    man = json.loads((VECTORS / "manifest.json").read_text())
    cases = [c for c in man["cases"] if not a.only or c["name"] in a.only.split(",")]
    vox = Vox()
    ping = vox.control("ping")
    if not ping.get("ok"):
        raise SystemExit(f"{SERIAL}: the app does not answer: {ping}")
    results, fails, n_events = {}, 0, 0
    bench = {"hop_p50_us": [], "hop_p99_us": [], "hop_max_us": [], "rtf": []}
    print(f"device {SERIAL}, {len(cases)} cases, {a.chunk_ms} ms pushes")
    for c in cases:
        name, rate = c["name"], c["rate"]
        pcm = base64.b64encode((VECTORS / f"{name}.pcm").read_bytes()).decode()
        ref = json.loads((VECTORS / f"{name}.events.json").read_text())["events"]
        r = vox.control("mic_feed", pcm_b64=pcm, rate=rate, raw=True, chunk_ms=a.chunk_ms)
        if not r.get("ok"):
            print(f"  {name}: ERROR {r.get('error')}"); fails += 1; continue
        got = r["mic"]["events"]
        ce = compare_events(ref, got)
        n_events += ce["matched"]
        entry = {"events": ce, "native": r["mic"].get("native")}
        line = (f"  {'PASS' if ce['pass'] else 'FAIL'} {name:28s} {rate:5d} Hz  events {ce['n_got']}/{ce['n_ref']}  "
                f"exact times {ce['times_exact']}/{ce['matched']}  fp dev {ce['fp_max_dev']:.4f}")
        if a.bench:
            b = vox.control("mic_feed", pcm_b64=pcm, rate=rate, repeat=a.bench, chunk_ms=a.chunk_ms)["mic"]
            hop = b["stats"]["hop_us"]
            rtf = b["wall_ms"] / max(1, b["audio_ms"])
            entry["bench"] = {"repeat": a.bench, "hop_us": hop, "wall_ms": b["wall_ms"], "audio_ms": b["audio_ms"], "rtf": rtf}
            bench["hop_p50_us"].append(hop["p50"]); bench["hop_p99_us"].append(hop["p99"])
            bench["hop_max_us"].append(hop["max"]); bench["rtf"].append(rtf)
            line += f"  hop p50 {hop['p50']:.0f} us p99 {hop['p99']:.0f} us  x{1 / max(rtf, 1e-9):.0f} real time"
        print(line)
        if not ce["pass"]:
            fails += 1
            print("     ", json.dumps({k: ce[k] for k in ("unmatched_ref", "unmatched_got", "label_text_mismatch",
                                                          "dt_start_max", "dt_end_max", "fp_violations", "pitch16_violations")}))
        results[name] = entry
    print(f"{len(cases) - fails}/{len(cases)} cases pass, {n_events} events compared")
    if a.bench and bench["rtf"]:
        med = lambda v: sorted(v)[len(v) // 2]  # noqa: E731
        print(f"bench: hop p50 (median over cases) {med(bench['hop_p50_us']):.0f} us, p99 {med(bench['hop_p99_us']):.0f} us, "
              f"worst max {max(bench['hop_max_us']):.0f} us; real-time factor {med(bench['rtf']):.4f} "
              f"({1 / max(med(bench['rtf']), 1e-9):.0f}x faster than real time, one core)")
    if a.json:
        Path(a.json).write_text(json.dumps({"serial": SERIAL, "cases": results}, indent=1))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
