#!/usr/bin/env python3
"""Record your own hums / mouth sounds for the demo console, and turn them into its sound data: the same schema as
gen_demo_sounds.py (real extractor output: 10 ms frames, fp1, pitch16, the line), written to
demo/web/data/sounds.recorded.json instead of the synthetic sounds.json.

    python demo/tools/record_demo_sounds.py --list-devices
    python demo/tools/record_demo_sounds.py                        # guided session, all sounds, default mic
    python demo/tools/record_demo_sounds.py --device "Microphone Array" --takes 3 --session me1
    python demo/tools/record_demo_sounds.py --only rise,pop        # re-record some into the latest session
    python demo/tools/record_demo_sounds.py --from demo/recordings/me1     # rebuild the JSON, no mic
    python demo/tools/record_demo_sounds.py --from D:/takes        # any folder of <sound>.wav (any rate, mono/stereo)

Session (per sound, in order): rise fall arch dip flat pop click hiss clickpop hum_long
  instruction, Enter, a 3-2-1 countdown (recorded: the quiet lead the noise floor needs), GO, a fixed window;
  then the extractor runs on the take and prints what it heard (label, line, pitch16 sparkline, SNR).
  Right labels = kept automatically; otherwise Enter = retry, k = keep anyway, s = skip. --takes N keeps N good
  takes per sound and uses the one with the best SNR.

Output
  demo/recordings/<session>/          private (.gitignore)
    <sound>.wav                       the take used (16 kHz mono PCM16, exactly what the extractor saw)
    takes/<sound>-NN.wav              every kept take
    takes.jsonl                       one line per take: expected / heard labels, kept, snr, the events
    session.json                      device, capture rate, time
  demo/web/data/sounds.recorded.json  {"synthetic": false, "recorded": true, "sounds": {name: entry}}: every name of
                                      the synthetic set (clickpop -> clickpop.1 / clickpop.2) plus hum_long; a sound
                                      without a usable recording is copied from sounds.json ("source": "synthetic").
                                      A WAV the extractor hears as other labels counts as unusable, unless it was
                                      kept with k in the session or --keep-mismatch is given.

Needs numpy, scipy, soundfile, and sounddevice for the mic (python -m pip install --user sounddevice soundfile).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import gen_demo_sounds as gd  # also puts extractor/ on sys.path
from vox_extract.resample import to_16k, to_mono

RATE = 16000
RECORDINGS = gd.DEMO / "recordings"
OUT = gd.DEMO / "web" / "data" / "sounds.recorded.json"
COUNTDOWN_S = 0.4   # per count; 3 counts = 1.2 s of quiet lead before GO

# name, expected labels, window after GO (s), instruction
SOUNDS = [
    ("rise", ["rise"], 2.5, "Hum RISING from low to high, about half a second."),
    ("fall", ["fall"], 2.5, "Hum FALLING from high to low, about half a second."),
    ("arch", ["arch"], 2.5, "Hum UP then DOWN, like a questioning 'mm-HMM-mm' (under a second)."),
    ("dip", ["dip"], 2.5, "Hum DOWN then UP, like 'mm-hm?' dipping in the middle (under a second)."),
    ("flat", ["flat"], 2.5, "Hum ONE steady note for about a second."),
    ("pop", ["pop"], 2.5, "ONE lip pop ('p' with closed lips, no voice)."),
    ("click", ["click"], 2.5, "ONE tongue click ('tsk' / cluck), nothing else."),
    ("hiss", ["hiss"], 2.5, "Hiss 'ssss' for about half a second."),
    ("clickpop", ["click", "pop"], 2.5, "Tongue CLICK, then a lip POP about 0.3 s later."),
    ("hum_long", ["flat"], 4.0, "Hum one steady, relaxed note and HOLD it about 2.5 seconds."),
]
NAMES = [s[0] for s in SOUNDS]
ALIASES = {"click_pop": "clickpop", "humlong": "hum_long", "long": "hum_long"}   # other file names accepted


# ------------------------------------------------------------------------------------ extractor side

def choose(evs: list[dict], want: list[str]) -> tuple[list[dict], bool]:
    """The events to use for a sound, and whether they are exactly what was asked for.
    Exact labels > the wanted labels in a row among extras > (keep anyway) the loudest / first ones."""
    labels = [e["label"] for e in evs]
    if labels == want:
        return evs, True
    n = len(want)
    for i in range(len(evs) - n + 1):
        if labels[i:i + n] == want:
            return evs[i:i + n], False
    if len(evs) < n:
        return [], False
    if n == 1:
        return [max(evs, key=lambda e: e["raw"].get("level_db", -99))], False
    return evs[:n], False


def snr(evs: list[dict]) -> float:
    return float(np.mean([e["raw"].get("snr_db", 0.0) for e in evs])) if evs else -99.0


def spark(p16: list[float]) -> str:
    """ASCII sparkline of pitch16 (semitones); a span under 2 st is drawn as flat as it is."""
    if not p16:
        return ""
    lo, hi = min(p16), max(p16)
    span = max(hi - lo, 2.0)
    marks = "_.-~^"
    return "".join(marks[min(4, int((v - lo) / span * 5))] for v in p16) + f"  ({hi - lo:.1f} st)"


def show(evs: list[dict]) -> None:
    if not evs:
        print("    heard: nothing")
    for e in evs:
        raw = e["raw"]
        print(f"    heard: {e['label']:<6} {e['t_end_ms'] - e['t_start_ms']:5.0f} ms  snr {raw.get('snr_db', 0):4.1f} dB"
              f"  {spark(raw.get('pitch16') or [])}")
        print(f"           {e['text']}")


def load16(path: Path) -> np.ndarray:
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    return to_16k(to_mono(x), int(sr)).astype(np.float32)


def save16(path: Path, x: np.ndarray) -> None:
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(x, -1, 1), RATE, subtype="PCM_16")


# ------------------------------------------------------------------------------------ building the JSON

def synthetic_set() -> dict:
    return json.loads(gd.OUT.read_text())["sounds"] if gd.OUT.exists() else gd.build()["sounds"]


def synthetic_hum_long() -> list[dict]:
    """hum_long has no synthetic twin in sounds.json: synthesize a steady 2.5 s hum (extractor/synth.py)."""
    import synth
    rng = np.random.default_rng(0)
    s, info = synth.make_hum("flat", rng, RATE, exc=0.0, dur_ms=2500)
    x, _ = synth.place([(s, "flat", info)], RATE, rng, 25.0, "pink", lead_ms=800, tail_ms=700, level_dbfs=-22)
    evs, _ = choose(gd.events(x), ["flat"])
    return gd.entries("hum_long", evs, x)


def find_wav(d: Path, name: str) -> Path | None:
    for p in sorted(d.glob("*.wav")):
        stem = p.stem.lower()
        if stem == name or ALIASES.get(stem) == name:
            return p
    return None


def build(d: Path, keep_mismatch: bool = False) -> dict:
    """A take whose labels are not what was asked for falls back to synthetic, unless it was kept anyway
    (k in the session: session.json "keep_anyway") or keep_mismatch."""
    meta = d / "session.json"
    keep = set(json.loads(meta.read_text()).get("keep_anyway", [])) if meta.exists() else set()
    syn = synthetic_set()
    sounds: dict[str, dict] = {}
    fallback = []
    for name, want, _, _ in SOUNDS:
        wav = find_wav(d, name)
        got: list[dict] = []
        if wav is None:
            print(f"  {name:<9} no recording: synthetic")
        else:
            x = load16(wav)
            evs = gd.events(x)
            use, exact = choose(evs, want)
            heard = [e["label"] for e in evs]
            if use and not (exact or keep_mismatch or name in keep or [e["label"] for e in use] == want):
                print(f"  {name:<9} {wav.name}: heard {heard}, wanted {want}: synthetic (--keep-mismatch uses it)")
            elif use:
                got = gd.entries(name, use, x)
                note = "ok" if exact else f"heard {heard}, using {[e['label'] for e in use]}"
                print(f"  {name:<9} {wav.name}: {note}")
            else:
                print(f"  {name:<9} {wav.name}: heard {heard}, wanted {want}: synthetic")
        for g in got:
            g["source"] = "recorded"
        if not got:
            fallback.append(name)
            if name == "hum_long":
                got = synthetic_hum_long()
            else:
                keys = [name] if len(want) == 1 else [f"{name}.{k + 1}" for k in range(len(want))]
                got = [dict(syn[k]) for k in keys]
            for g in got:
                g["source"] = "synthetic"
        for g in got:
            sounds[g["name"]] = g
    return {"generated_by": "demo/tools/record_demo_sounds.py", "synthetic": False, "recorded": True,
            "note": "Real extractor output on the presenter's own RECORDED sounds"
                    + (f"; synthetic stand-ins for {fallback}." if fallback else "."),
            "session": d.name, "fallback": fallback, "fp1_names": gd.FP1_NAMES, "sounds": sounds}


def write(d: Path, out: Path, keep_mismatch: bool = False) -> None:
    print(f"building from {d}")
    j = build(d, keep_mismatch)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(j, separators=(",", ":")) + "\n")
    rec = sum(s["source"] == "recorded" for s in j["sounds"].values())
    print(f"wrote {out}: {len(j['sounds'])} sounds ({rec} recorded), {out.stat().st_size // 1024} KB")


# ------------------------------------------------------------------------------------ the mic

def input_devices() -> list[tuple[int, dict, str]]:
    import sounddevice as sd
    apis = sd.query_hostapis()
    return [(i, dv, apis[dv["hostapi"]]["name"]) for i, dv in enumerate(sd.query_devices())
            if dv["max_input_channels"] > 0]


def list_devices() -> None:
    import sounddevice as sd
    default = sd.default.device[0]
    print("input devices (--device N or a name substring; * = default):")
    for i, dv, api in input_devices():
        print(f" {'*' if i == default else ' '}{i:3d}  {dv['name']}  [{api}, {dv['max_input_channels']} ch, "
              f"{dv['default_samplerate']:.0f} Hz]")


def pick_device(spec: str | None) -> int:
    import sounddevice as sd
    if spec is None:
        return int(sd.default.device[0])
    if spec.isdigit():
        return int(spec)
    hits = [i for i, dv, _ in input_devices() if spec.lower() in dv["name"].lower()]
    if not hits:
        raise SystemExit(f"no input device matches {spec!r}; see --list-devices")
    return hits[0]   # lowest index: MME first on Windows, which takes any sample rate


class Mic:
    """One input stream for the whole session (a fresh stream starts with ~0.5 s of near-digital silence on some
    Windows mics, which would seed the extractor's noise floor wrong). Fixed-length takes at the device's own rate,
    channel 0, resampled to 16 kHz by the extractor's to_16k."""

    def __init__(self, device: int) -> None:
        import sounddevice as sd
        self.device = device
        info = sd.query_devices(device, "input")
        self.name = info["name"]
        self.rate = int(info["default_samplerate"])
        channels = 1
        try:
            sd.check_input_settings(device=device, channels=1, samplerate=self.rate, dtype="float32")
        except Exception:
            channels = int(info["max_input_channels"])
        self.chunks: list[np.ndarray] | None = None   # collecting when not None

        def cb(indata, frames, t, status) -> None:  # noqa: ARG001
            if self.chunks is not None:
                self.chunks.append(indata[:, 0].copy())

        try:
            self.stream = sd.InputStream(samplerate=self.rate, channels=channels, dtype="float32", device=device,
                                         callback=cb)
            self.stream.start()
        except Exception as e:
            raise SystemExit(f"could not open input {device} ({e}); pick another with --list-devices / --device")
        time.sleep(1.0)   # let the device settle

    def record(self, window_s: float) -> np.ndarray:
        n = int((3 * COUNTDOWN_S + window_s) * self.rate)
        self.chunks = []
        try:
            for c in "321":
                print(f"  {c}..", end="", flush=True)
                time.sleep(COUNTDOWN_S)
            print("  GO!", flush=True)
            while sum(c.size for c in self.chunks) < n:
                time.sleep(0.02)
        finally:
            chunks, self.chunks = self.chunks, None
        print("  (stop)")
        x = to_16k(np.concatenate(chunks)[:n], self.rate).astype(np.float32)
        room = 20 * np.log10(np.sqrt(np.mean(x[:int(3 * COUNTDOWN_S * RATE)] ** 2)) + 1e-9)
        peak = 20 * np.log10(np.abs(x).max() + 1e-9)
        print(f"  room (countdown) {room:.0f} dBFS, peak {peak:.0f} dBFS"
              + ("  !! noisy countdown: keep quiet until GO, or find a quieter spot" if room > -40 else "")
              + ("  !! clipping: back off / lower the mic level" if peak > -1 else ""))
        return x


def ask(prompt: str) -> str:
    return input(prompt).strip().lower()


def record_sound(mic: Mic, sess: Path, name: str, want: list[str], window: float, text: str, takes: int,
                 log) -> None:
    print(f"\n=== {name}  (want {' + '.join(want)})\n  {text}")
    kept: list[tuple[float, Path, bool]] = []   # (snr, file, exact)
    n = len(list((sess / "takes").glob(f"{name}-*.wav")))
    while len(kept) < takes:
        k = ask(f"  take {len(kept) + 1}/{takes}: Enter = record, s = skip: ")
        if k == "s":
            break
        x = mic.record(window)
        peak = float(np.abs(x).max()) if x.size else 0.0
        if peak < 1e-4:
            print("  !! digital silence: wrong device, or the mic is muted / blocked in Windows privacy settings")
        elif peak < 0.01:
            print(f"  (very quiet: peak {20 * np.log10(peak):.0f} dBFS; get closer or raise the mic level)")
        evs = gd.events(x)
        show(evs)
        use, exact = choose(evs, want)
        keep = exact
        if not exact:
            hint = f" (k keeps {[e['label'] for e in use]})" if use else ""
            k = ask(f"  wanted {want}.{hint} Enter = retry, k = keep anyway, s = skip: ")
            if k == "s":
                log({"sound": name, "expected": want, "heard": [e["label"] for e in evs], "kept": False,
                     "events": evs})
                break
            keep = k == "k" and bool(use)
            if k == "k" and not use:
                print("  nothing to keep (fewer sounds than wanted); retry")
        rec = {"sound": name, "expected": want, "heard": [e["label"] for e in evs], "exact": exact, "kept": keep,
               "snr_db": round(snr(use), 1), "events": evs}
        if keep:
            n += 1
            p = sess / "takes" / f"{name}-{n:02d}.wav"
            save16(p, x)
            rec["file"] = p.relative_to(sess).as_posix()
            kept.append((snr(use), p, exact))
            print(f"  kept ({p.name})")
        log(rec)
    if kept:
        _, best, exact = max(kept, key=lambda t: (t[2], t[0]))   # right labels first, then SNR
        (sess / f"{name}.wav").write_bytes(best.read_bytes())
        info = read_meta(sess)   # remember a keep-anyway so a rebuild uses it too
        info["keep_anyway"] = sorted((set(info.get("keep_anyway", [])) - {name}) | (set() if exact else {name}))
        write_meta(sess, info)
        print(f"  -> {name}.wav = {best.name}" + (f" (best snr of {len(kept)})" if len(kept) > 1 else ""))


def read_meta(sess: Path) -> dict:
    p = sess / "session.json"
    return json.loads(p.read_text()) if p.exists() else {}


def write_meta(sess: Path, info: dict) -> None:
    (sess / "session.json").write_text(json.dumps(info, indent=1) + "\n")


def latest_session() -> Path:
    dirs = [p for p in RECORDINGS.glob("*") if p.is_dir()] if RECORDINGS.exists() else []
    if not dirs:
        raise SystemExit(f"no session in {RECORDINGS} yet: record one first")
    return max(dirs, key=lambda p: p.stat().st_mtime)


def run_session(a: argparse.Namespace) -> None:
    only = [s.strip() for s in a.only.split(",")] if a.only else None
    bad = [s for s in only or [] if s not in NAMES]
    if bad:
        raise SystemExit(f"unknown sound(s) {bad}; choose from {NAMES}")
    if a.session:
        sess = RECORDINGS / a.session
    elif only:
        sess = latest_session()
    else:
        sess = RECORDINGS / datetime.now().strftime("%Y%m%d-%H%M%S")
    sess.mkdir(parents=True, exist_ok=True)
    mic = Mic(pick_device(a.device))
    print(f"mic: [{mic.device}] {mic.name} at {mic.rate} Hz -> 16 kHz; session {sess}")
    info = read_meta(sess)
    info.update({"device": mic.name, "device_index": mic.device, "capture_rate": mic.rate, "rate": RATE,
                 "time": datetime.now().isoformat(timespec="seconds"), "argv": sys.argv[1:]})
    info.setdefault("keep_anyway", [])
    write_meta(sess, info)
    print("Keep quiet through the countdown (it measures the room), make the sound after GO.")

    def log(rec: dict) -> None:
        with open(sess / "takes.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    try:
        for name, want, window, text in SOUNDS:
            if only is None or name in only:
                record_sound(mic, sess, name, want, window, text, a.takes, log)
    except (KeyboardInterrupt, EOFError):
        print("\nstopped; building from what was kept")
    print()
    write(sess, a.out, a.keep_mismatch)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-devices", action="store_true", help="list input devices and exit")
    ap.add_argument("--device", help="input device: index or name substring (default: the system default)")
    ap.add_argument("--session", help="session folder name under demo/recordings (default: a timestamp)")
    ap.add_argument("--takes", type=int, default=1, help="good takes per sound; the best SNR is used (default 1)")
    ap.add_argument("--only", help="comma list of sounds to (re)record, into the latest session unless --session")
    ap.add_argument("--from", dest="src", type=Path, help="no mic: rebuild the JSON from a folder of <sound>.wav")
    ap.add_argument("--keep-mismatch", action="store_true",
                    help="use a recording even when the extractor heard other labels (default: synthetic)")
    ap.add_argument("--out", type=Path, default=OUT, help=f"output JSON (default {OUT.relative_to(gd.VOX)})")
    a = ap.parse_args()
    if a.list_devices:
        list_devices()
    elif a.src:
        if not a.src.is_dir():
            raise SystemExit(f"{a.src} is not a folder")
        write(a.src, a.out, a.keep_mismatch)
    else:
        run_session(a)


if __name__ == "__main__":
    main()
