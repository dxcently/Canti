#!/usr/bin/env python3
"""Record from the microphone (or read WAVs), print VOX event lines live, and save WAV + JSONL.

Modes
  live (default)   capture until Ctrl-C (or --seconds), print every sound's line as it ends and
                   the default-profile action of each group (phone-style grouping, gaps <= 600 ms)
  --prompt         guided recording session: asks for each gesture --reps times and each negative
                   class (talk, laugh, cough, music, silence, fan / air) for --neg-seconds, and
                   saves a labelled dataset under recordings/<session>/
  --calibrate      measure the room and your normal hum level; sets loud_calib_db for loudness
  --wav F [F ...]  run the extractor over WAV files instead of the mic
  --enroll KIND    record enrollment examples for phone-side personalization (wiki/personalization.md):
                   --enroll custom --name meow | --enroll ignore --name sneeze | --enroll gesture --gesture rise
                   --takes N takes (default 5); each kept take's fp1 + pitch16 go to
                   recordings/enroll/<kind>/<name>/examples.jsonl (the android/suite/enroll.py push format),
                   the clips to takes/NNN.wav, every take (with all its events) to takes.jsonl, and the raw
                   session to run-<time>/ (session.wav, events.jsonl, messages.jsonl, session.json)
  --replay DIR     re-run the extractor (current code / --config) over a saved session and score it
  --list-devices   show capture sources and whether PipeWire / ALSA sees a microphone plugged in

Sources (--source)
  pw     PipeWire:  pw-record --raw (auto-picks the default non-monitor source; --device NAME)
  sd     PortAudio via the sounddevice package (--device index or name)
  fake   SYNTHETIC microphone (synth.py) for testing this tool without a mic; prompts are answered
         with generated sounds. Anything recorded with it is marked synthetic.
  auto   pw if pw-record exists, else sd

Output (recordings/<name>/)
  session.wav      everything captured, at the capture rate (PCM 16)
  events.jsonl     one line per sound: t_start_ms, t_end_ms (session time), label, text, raw features
  messages.jsonl   the phone's feature messages (android/PROTOCOL.md v1), one sound per message
  labels.jsonl     (--prompt) one line per take: class, instruction, window, expected and detected
  takes/*.wav      (--prompt) each take with 1 s before and 0.5 s after
  session.json     source, rates, config snapshot, vocabulary digest, synthetic flag, timings
  config.json      the Config used (reload with --config)

Examples
  ./run python record.py --list-devices
  ./run python record.py                                   # live, Ctrl-C to stop
  ./run python record.py --prompt --session alice1 --reps 5
  ./run python record.py --replay recordings/alice1
  ./run python record.py --enroll custom --name meow --takes 5
  ./run python record.py --source fake --prompt --session selftest --reps 2 --auto
"""

from __future__ import annotations

import argparse
import json
import queue
import random
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from vox_extract import Config
from vox_extract.classify import Event
from vox_extract.extractor import Extractor, load_wav
from vox_extract.policy import action_for, group
from vox_extract.protocol import DebugSocket, message
from vox_extract.resample import to_16k
from vox_extract.vocab import DEFAULT_BINDINGS, digest
from vox_extract.personal import CONTOUR_GESTURES

HERE = Path(__file__).resolve().parent
GROUP_GAP_MS = 600

# ------------------------------------------------------------------------------------ the plan

GESTURE_PROMPTS = {
    # class: (instruction, take seconds, expected sequence)
    "rise": ("Hum with the pitch going UP, low to high (about half a second to a second).", 3.0, ["rise"]),
    "fall": ("Hum with the pitch going DOWN, high to low (about half a second to a second).", 3.0, ["fall"]),
    "arch": ("Hum UP then DOWN, like a questioning 'mm-HMM-mm' (under a second).", 3.0, ["arch"]),
    "dip": ("Hum DOWN then UP, like 'mm-hm?' dipping in the middle (under a second).", 3.0, ["dip"]),
    "flat": ("Hum ONE steady note for about 1.5 seconds (long press).", 4.0, ["flat"]),
    "pop": ("Make ONE lip pop ('p' with closed lips, no voice).", 2.5, ["pop"]),
    "click": ("Make ONE tongue click ('tsk' / cluck), nothing else.", 2.5, ["click"]),
    "hiss": ("Hiss 'ssss' for about half a second.", 3.0, ["hiss"]),
    "click_pop": ("Tongue click, then quickly a lip pop (less than half a second apart).", 3.0, ["click", "pop"]),
}
WHISTLE_PROMPTS = {
    f"whistle_{c}": (f"WHISTLE instead of humming: {GESTURE_PROMPTS[c][0][4:]}", GESTURE_PROMPTS[c][1], [c])
    for c in ("rise", "fall", "arch", "dip", "flat")
}
NEGATIVE_PROMPTS = {
    "talk": "Talk normally for the whole time. For example read aloud: 'The quick brown fox jumps over the "
            "lazy dog. I think we should meet at noon, and then walk to the station together.'",
    "laugh": "Laugh (naturally, a few times) for the whole time.",
    "cough": "Cough or clear your throat a few times, with pauses.",
    "music": "Play music on a speaker near the mic (any song, normal volume). Press s to skip if you can't.",
    "silence": "Stay quiet. Don't touch anything.",
    "fan": "Turn on a fan or air noise near the mic (fan, hair dryer on cold, air vent). Press s to skip.",
}
# fake-mic stand-ins for the negative classes (synth.py names)
FAKE_NEG = {"talk": "talk", "laugh": "laugh", "cough": "cough", "music": "music", "silence": "silence", "fan": "air"}


def expected_action(seq: list[str]) -> str:
    return DEFAULT_BINDINGS.get(tuple(seq), "none")


# ------------------------------------------------------------------------------------ sources

class Source:
    rate = 48000
    synthetic = False
    name = "?"

    def start(self) -> None: ...
    def read(self) -> np.ndarray | None: ...   # blocking; float32 mono; None = end of stream
    def stop(self) -> None: ...


def pactl(*args: str) -> str:
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def pw_sources() -> list[dict]:
    """Capture sources from `pactl list sources`: name, description, monitor?, ports + availability."""
    out, cur = [], None
    for line in pactl("list", "sources").splitlines():
        s = line.strip()
        if line.startswith("Source #"):
            cur = {"name": "", "description": "", "ports": [], "active_port": "", "monitor": False}
            out.append(cur)
        elif cur is None:
            continue
        elif s.startswith("Name:"):
            cur["name"] = s.split(":", 1)[1].strip()
            cur["monitor"] = cur["name"].endswith(".monitor")
        elif s.startswith("Description:"):
            cur["description"] = s.split(":", 1)[1].strip()
        elif s.startswith("Active Port:"):
            cur["active_port"] = s.split(":", 1)[1].strip()
        elif ("available" in s or "availability unknown" in s) and "(type:" in s:
            port = s.split(":", 1)[0]
            avail = "not available" if "not available" in s else ("unknown" if "availability unknown" in s else "available")
            cur["ports"].append((port, avail))
    return out


def default_pw_source() -> str | None:
    d = pactl("get-default-source").strip()
    if d and not d.endswith(".monitor"):
        return d
    for s in pw_sources():
        if not s["monitor"]:
            return s["name"]
    return None


class PwSource(Source):
    def __init__(self, target: str | None, rate: int, block: int) -> None:
        self.target = target or default_pw_source()
        self.rate, self.block = rate, block
        self.name = f"pipewire:{self.target or 'default'}"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        cmd = ["pw-record", "--rate", str(self.rate), "--channels", "1", "--format", "s16", "--raw",
               "--latency", "20ms"]
        if self.target:
            cmd += ["--target", self.target]
        self.proc = subprocess.Popen(cmd + ["-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def read(self) -> np.ndarray | None:
        assert self.proc and self.proc.stdout
        want = self.block * 2
        buf = b""
        while len(buf) < want:
            chunk = self.proc.stdout.read(want - len(buf))
            if not chunk:
                if not buf:
                    err = self.proc.stderr.read().decode(errors="replace").strip() if self.proc.stderr else ""
                    if err:
                        print(f"pw-record: {err}", file=sys.stderr)
                    return None
                break
            buf += chunk
        buf = buf[: len(buf) // 2 * 2]
        return np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class SdSource(Source):
    def __init__(self, device: str | None, rate: int, block: int) -> None:
        import sounddevice as sd
        self.sd = sd
        self.device = int(device) if device and device.isdigit() else device
        self.rate, self.block = rate, block
        self.q: queue.Queue = queue.Queue()
        self.name = f"sounddevice:{device if device is not None else 'default'}"
        self.stream = None

    def start(self) -> None:
        def cb(indata, frames, t, status):  # noqa: ARG001
            if status:
                print(f"[audio] {status}", file=sys.stderr)
            self.q.put(indata[:, 0].copy())
        try:
            self.stream = self.sd.InputStream(samplerate=self.rate, channels=1, dtype="float32", device=self.device,
                                              blocksize=self.block, callback=cb)
        except Exception as e:
            raise SystemExit(f"PortAudio could not open the input ({e}). Try --source pw, or pick a device from "
                             "--list-devices with --device N.") from None
        self.stream.start()

    def read(self) -> np.ndarray | None:
        try:
            return self.q.get(timeout=1.0)
        except queue.Empty:
            return np.zeros(0, np.float32)

    def stop(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream.close()


class FakeSource(Source):
    """SYNTHETIC microphone: quiet pink background; cue(cls) mixes a synth.py clip in at the current
    position. Runs `speed` times faster than real time (the session waits on sample counts)."""

    synthetic = True

    def __init__(self, rate: int, block: int, speed: float, seed: int) -> None:
        import synth
        self.synth = synth
        self.rate, self.block, self.speed = rate, block, speed
        self.rng = np.random.default_rng(seed)
        self.name = "fake (SYNTHETIC)"
        loop = synth.background(self.rng, "pink", rate * 8, rate) * 10 ** (-62 / 20)
        self.loop = loop.astype(np.float32)
        self.pos = 0
        self.pending: list[np.ndarray] = []  # clip remainders to mix in
        self.lock = threading.Lock()
        self.t_next = 0.0

    def cue(self, cls: str) -> float:
        """Start a synthetic sound of this class now; returns its length in seconds. The clip is made
        nearly dry (60 dB SNR): the source's own continuous background is the room noise, so the
        clip's padding does not step the noise level up and down."""
        if cls == "silence":
            return 0.0
        c = self.synth.make_clip(cls, self.rng, self.rate, 60.0, "pink")
        with self.lock:
            self.pending.append(c.audio.astype(np.float32))
        return len(c.audio) / self.rate

    def start(self) -> None:
        self.t_next = time.monotonic()

    def read(self) -> np.ndarray | None:
        n = self.block
        idx = (self.pos + np.arange(n)) % self.loop.size
        y = self.loop[idx].copy()
        self.pos += n
        with self.lock:
            keep = []
            for p in self.pending:
                m = min(n, p.size)
                y[:m] += p[:m]
                if p.size > n:
                    keep.append(p[n:])
            self.pending = keep
        self.t_next += n / self.rate / self.speed
        d = self.t_next - time.monotonic()
        if d > 0:
            time.sleep(d)
        return y


class WavSource(Source):
    def __init__(self, x: np.ndarray, rate: int, block: int, name: str) -> None:
        self.x, self.rate, self.block, self.name = x, rate, block, name
        self.pos = 0

    def read(self) -> np.ndarray | None:
        if self.pos >= self.x.size:
            return None
        y = self.x[self.pos:self.pos + self.block]
        self.pos += self.block
        return y


def make_source(a: argparse.Namespace) -> Source:
    block = a.rate // 20  # 50 ms
    kind = a.source
    if kind == "auto":
        kind = "pw" if shutil.which("pw-record") else "sd"
    if kind == "pw":
        return PwSource(a.device, a.rate, block)
    if kind == "sd":
        return SdSource(a.device, a.rate, block)
    if kind == "fake":
        return FakeSource(a.rate, block, a.fake_speed, a.seed)
    raise SystemExit(f"unknown source {kind}")


# ------------------------------------------------------------------------------------ the recorder

@dataclass
class Logged:
    ev: dict          # Event.to_dict() + msg id
    msg: dict


class Recorder:
    """Capture thread: source -> session.wav + extractor -> events (printed and logged).
    The main thread waits on sample counts (so the fake source can run faster than real time)."""

    def __init__(self, src: Source, cfg: Config, outdir: Path, print_events: bool = True,
                 show_protocol: bool = False, sender: DebugSocket | None = None, keep_s: float = 180.0) -> None:
        import soundfile as sf
        self.src, self.cfg, self.outdir = src, cfg, outdir
        self.rate = src.rate
        if self.rate in (16000, 48000):
            self.ex = Extractor(cfg, input_rate=self.rate)
            self.resample = False
        else:  # odd rate: resample each block (not the reference path; the device runs 16 kHz)
            self.ex = Extractor(cfg, input_rate=16000)
            self.resample = True
        outdir.mkdir(parents=True, exist_ok=True)
        self.wav = sf.SoundFile(str(outdir / "session.wav"), "w", samplerate=self.rate, channels=1, subtype="PCM_16")
        self.ev_f = (outdir / "events.jsonl").open("a")
        self.msg_f = (outdir / "messages.jsonl").open("a")
        self.print_events, self.show_protocol, self.sender = print_events, show_protocol, sender
        self.n = 0                              # samples captured
        self.cond = threading.Condition()
        self.blocks: list[tuple[int, np.ndarray]] = []   # (first sample, block) for the last keep_s seconds
        self.keep = int(keep_s * self.rate)
        self.events: list[dict] = []
        self.msg_id = 0
        self.pending_group: list[dict] = []
        self.done = False
        self.error: str | None = None
        self.zero_run = 0
        self.warned_zero = False
        self.peak = 0.0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.lock = threading.Lock()   # guards events / printing

    # -- time
    def now_ms(self) -> float:
        return self.n * 1000.0 / self.rate

    def start(self) -> None:
        self.src.start()
        self.thread.start()

    def _run(self) -> None:
        try:
            while not self.done:
                x = self.src.read()
                if x is None:
                    break
                if x.size:
                    self._take(x)
        except Exception as e:  # surface capture errors to the main thread
            self.error = f"{type(e).__name__}: {e}"
        finally:
            for ev in self.ex.flush():
                self._event(ev)
            self._close_group(force=True)
            with self.cond:
                self.done = True
                self.cond.notify_all()

    def _take(self, x: np.ndarray) -> None:
        x = np.asarray(x, dtype=np.float32)
        self.wav.write(x)
        with self.cond:
            self.blocks.append((self.n, x))
            while self.blocks and self.blocks[0][0] + self.blocks[0][1].size < self.n - self.keep:
                self.blocks.pop(0)
        # live signal watchdog: 3 s of exact digital zeros = the device is delivering nothing
        if not np.any(x):
            self.zero_run += x.size
            if self.zero_run >= 3 * self.rate and not self.warned_zero:
                self.warned_zero = True
                print("\n[WARNING] 3 s of exact digital silence: the mic is muted, unplugged or not selected "
                      "(see --list-devices).", file=sys.stderr)
        else:
            self.zero_run = 0
            self.warned_zero = False
        self.peak = max(self.peak, float(np.max(np.abs(x))))
        y = to_16k(x, self.rate) if self.resample else x
        for ev in self.ex.push(y):
            self._event(ev)
        with self.cond:
            self.n += x.size
            self.cond.notify_all()
        self._close_group()

    def _event(self, e: Event) -> None:
        d = e.to_dict()
        self.msg_id += 1
        msg = message([d], self.msg_id, features=True)
        d["msg_id"] = self.msg_id
        with self.lock:
            self.events.append(d)
            self.ev_f.write(json.dumps(d, default=float) + "\n")
            self.ev_f.flush()
            self.msg_f.write(json.dumps(msg) + "\n")
            self.msg_f.flush()
            if self.print_events:
                print(f"  {d['t_start_ms'] / 1000:7.2f}-{d['t_end_ms'] / 1000:6.2f} s  {d['label']:<5} | {d['text']}", flush=True)
            if self.show_protocol:
                print("    " + json.dumps(msg), flush=True)
            if self.sender:
                try:
                    reply = self.sender.send(msg)
                    print(f"    phone: {reply}", flush=True)
                except OSError as err:
                    print(f"    [send failed: {err}]", file=sys.stderr, flush=True)
            if self.pending_group and d["t_start_ms"] - self.pending_group[-1]["t_end_ms"] > GROUP_GAP_MS:
                self._close_group(force=True, locked=True)
            self.pending_group.append(d)
            if len(self.pending_group) == 3:
                self._close_group(force=True, locked=True)

    def _close_group(self, force: bool = False, locked: bool = False) -> None:
        """Print the default-profile action once a group can no longer grow (phone-style grouping)."""
        if not locked:
            with self.lock:
                return self._close_group(force, locked=True)
        g = self.pending_group
        if not g:
            return
        # the extractor reports a sound ~0.15 s after it ends, so wait gap + that before closing
        if force or self.now_ms() - g[-1]["t_end_ms"] > GROUP_GAP_MS + 200:
            act = action_for([(e["label"], e["text"]) for e in g])
            if self.print_events:
                print(f"  {'':16} => {' '.join(e['label'] for e in g)}: {act}  (default profile)", flush=True)
            self.pending_group = []

    # -- main-thread helpers
    def wait_until(self, sample: int) -> bool:
        with self.cond:
            while self.n < sample and not self.done:
                self.cond.wait(timeout=0.5)
            return self.n >= sample

    def wait_s(self, s: float) -> bool:
        return self.wait_until(self.n + int(s * self.rate))

    def audio(self, a: int, b: int) -> np.ndarray:
        """Samples [a, b) if still in the ring buffer."""
        with self.cond:
            parts = []
            for s0, blk in self.blocks:
                lo, hi = max(a, s0), min(b, s0 + blk.size)
                if hi > lo:
                    parts.append(blk[lo - s0:hi - s0])
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)

    def events_between(self, t0_ms: float, t1_ms: float) -> list[dict]:
        with self.lock:
            return [e for e in self.events if t0_ms <= e["t_start_ms"] < t1_ms]

    def stop(self) -> None:
        self.done = True
        self.src.stop()
        self.thread.join(timeout=5)
        self.wav.close()
        self.ev_f.close()
        self.msg_f.close()


# ------------------------------------------------------------------------------------ helpers

def level_report(x: np.ndarray) -> dict:
    if x.size == 0:
        return {"samples": 0}
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    return {"samples": int(x.size), "zero_frac": round(float(np.mean(x == 0)), 4),
            "rms_dbfs": round(20 * np.log10(rms + 1e-12), 1), "peak_dbfs": round(20 * np.log10(float(np.max(np.abs(x))) + 1e-12), 1)}


def check_signal(rec: Recorder, seconds: float, allow_silent: bool) -> dict:
    """Is there a real signal? Exact zeros = no device / muted / jack not detected."""
    start = rec.n
    if not rec.wait_until(start + int(seconds * rec.rate)):
        raise SystemExit(f"capture stopped: {rec.error or 'source ended'}")
    rep = level_report(rec.audio(start, rec.n))
    print(f"signal check ({seconds:.1f} s): rms {rep['rms_dbfs']} dBFS, peak {rep['peak_dbfs']} dBFS, "
          f"exact zeros {100 * rep['zero_frac']:.1f} %")
    bad = None
    if rep["zero_frac"] > 0.99:
        bad = ("DIGITAL SILENCE: the source delivers exact zeros. The mic is muted, unplugged, not selected, "
               "or its jack is not detected (--list-devices shows port availability).")
    elif rep["rms_dbfs"] < -90:
        bad = "The signal is extremely low (below -90 dBFS): check the input gain / mute."
    if bad:
        print(bad, file=sys.stderr)
        if not allow_silent:
            rec.stop()
            raise SystemExit("stopping (use --allow-silent to record anyway)")
    if rep["peak_dbfs"] > -0.5:
        print("warning: the input is clipping; lower the input gain.", file=sys.stderr)
    return rep


def ask(prompt: str, auto: bool, default: str = "") -> str:
    if auto:
        return default
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


def load_cfg(path: str | None) -> Config:
    return Config.load(path) if path else Config()


def session_meta(a: argparse.Namespace, src: Source, cfg: Config, extra: dict | None = None) -> dict:
    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "source": src.name, "synthetic": bool(src.synthetic), "capture_rate": src.rate,
        "extractor_rate": 16000, "vocab_digest": digest(), "config": json.loads(cfg.to_json()),
        "argv": sys.argv[1:], **(extra or {}),
    }


def score_take(take: dict, events: list[dict]) -> dict:
    """What would the phone do with the sounds in this take's window (default profile)?"""
    groups = group(events, GROUP_GAP_MS)
    actions = [action_for([(e["label"], e["text"]) for e in g]) for g in groups]
    acted = [x for x in actions if x != "none"]
    if take["kind"] == "gesture":
        ok = acted == [take["expected_action"]] if take["expected_action"] != "none" else not acted
        labels_ok = [e["label"] for e in events] == take["expected_labels"]
    else:
        ok = not acted
        labels_ok = None
    return {"detected_labels": [e["label"] for e in events], "detected_text": [e["text"] for e in events],
            "actions": actions, "ok": ok, "labels_ok": labels_ok}


# ------------------------------------------------------------------------------------ modes

def run_live(a: argparse.Namespace) -> None:
    cfg = load_cfg(a.config)
    src = make_source(a)
    out = HERE / "recordings" / (a.session or datetime.now().strftime("live-%Y%m%d-%H%M%S"))
    rec = Recorder(src, cfg, out, show_protocol=a.protocol, sender=connect(a.send))
    (out / "config.json").write_text(cfg.to_json())
    print(f"source {src.name} at {src.rate} Hz -> {out}")
    rec.start()
    meta = session_meta(a, src, cfg)
    meta["signal_check"] = check_signal(rec, 1.5, a.allow_silent)
    print("listening (Ctrl-C to stop) ...")
    try:
        if a.seconds:
            rec.wait_s(a.seconds)
        else:
            while not rec.done:
                rec.wait_s(1.0)
    except KeyboardInterrupt:
        pass
    rec.stop()
    meta["duration_s"] = round(rec.n / rec.rate, 2)
    meta["n_events"] = len(rec.events)
    (out / "session.json").write_text(json.dumps(meta, indent=1))
    print(f"\n{len(rec.events)} sounds, {meta['duration_s']} s saved to {out}")


def connect(spec: str | None) -> DebugSocket | None:
    if not spec:
        return None
    host, _, port = spec.rpartition(":")
    return DebugSocket(host or "127.0.0.1", int(port))


def calibrate(rec: Recorder, cfg: Config, auto: bool, fake: FakeSource | None) -> float | None:
    print("\nCALIBRATION. Step 1: stay quiet for 3 seconds.")
    ask("  press Enter to start ", auto)
    rec.wait_s(3.0)
    print(f"  noise floor {rec.ex.floor_db:.1f} dBFS")
    print("Step 2: hum ONE steady note at your normal, comfortable loudness for about 2 seconds.")
    levels = []
    for i in range(2):
        ask(f"  [{i + 1}/2] press Enter, then hum ", auto)
        t0 = rec.now_ms()
        print("  GO")
        dur = fake.cue("flat") if fake else 0.0
        rec.wait_s(max(3.5, dur + 0.3))
        rec.wait_s(0.5)
        evs = [e for e in rec.events_between(t0 - 300, rec.now_ms()) if e["raw"].get("dur_ms", 0) >= 400]
        if evs:
            lv = max(e["raw"]["level_db"] for e in evs)
            levels.append(lv)
            print(f"  level {lv:.1f} dBFS")
        else:
            print("  no hum detected")
    if not levels:
        print("calibration failed: no hum detected; keeping floor-relative loudness")
        return None
    cal = float(np.median(levels))
    cfg.loud_calib_db = round(cal, 1)
    print(f"loud_calib_db = {cfg.loud_calib_db} dBFS (quiet below {cal - cfg.loud_calib_span_db:.1f}, "
          f"loud from {cal + cfg.loud_calib_span_db:.1f})")
    return cal


def build_plan(a: argparse.Namespace) -> list[dict]:
    prompts = dict(GESTURE_PROMPTS)
    if a.whistle:
        prompts.update(WHISTLE_PROMPTS)
    gestures = a.gestures or list(prompts)
    negs = a.negatives if a.negatives is not None else list(NEGATIVE_PROMPTS)
    plan = []
    order = [(g, r) for g in gestures for r in range(a.reps)]
    if a.shuffle:
        random.Random(a.seed).shuffle(order)
    for g, r in order:
        if g not in prompts:
            raise SystemExit(f"unknown gesture {g}; choose from {list(prompts)}")
        ins, secs, seq = prompts[g]
        plan.append({"cls": g, "kind": "gesture", "rep": r, "instruction": ins, "seconds": secs,
                     "expected_labels": seq, "expected_action": expected_action(seq)})
    for ng in negs:
        if ng not in NEGATIVE_PROMPTS:
            raise SystemExit(f"unknown negative {ng}; choose from {list(NEGATIVE_PROMPTS)}")
        for r in range(a.neg_reps):
            plan.append({"cls": ng, "kind": "negative", "rep": r, "instruction": NEGATIVE_PROMPTS[ng],
                         "seconds": a.neg_seconds, "expected_labels": [], "expected_action": "none"})
    return plan


def run_prompt(a: argparse.Namespace) -> None:
    import soundfile as sf
    cfg = load_cfg(a.config)
    src = make_source(a)
    auto = a.auto or isinstance(src, FakeSource) and not a.interactive
    name = a.session or datetime.now().strftime("session-%Y%m%d-%H%M%S")
    out = HERE / "recordings" / name
    if (out / "labels.jsonl").exists() and not a.append:
        raise SystemExit(f"{out} already has a session; pick another --session or pass --append")
    plan = build_plan(a)
    rec = Recorder(src, cfg, out, print_events=True, show_protocol=a.protocol, sender=connect(a.send))
    (out / "takes").mkdir(exist_ok=True)
    fake = src if isinstance(src, FakeSource) else None
    print(f"session {name}: {len(plan)} takes, source {src.name} at {src.rate} Hz -> {out}")
    if fake:
        print("NOTE: the fake source is SYNTHETIC. This session tests the tool, not real voices.")
    rec.start()
    meta = session_meta(a, src, cfg, {"session": name, "plan": len(plan)})
    meta["signal_check"] = check_signal(rec, 2.0, a.allow_silent)
    if a.calibrate:
        meta["loud_calib_db"] = calibrate(rec, cfg, auto, fake)
        meta["config"] = json.loads(cfg.to_json())
    (out / "config.json").write_text(cfg.to_json())
    (out / "session.json").write_text(json.dumps(meta, indent=1))
    if not auto:
        print("\nFor each take: press Enter, wait for GO, make the sound ONCE, then stay quiet until 'stop'.\n"
              "After each take: Enter = keep, r = redo, x = discard.  Before a take: s = skip, q = quit.\n")
    labels_f = (out / "labels.jsonl").open("a")
    results = []
    i = 0
    try:
        while i < len(plan):
            t = plan[i]
            tag = f"[{i + 1}/{len(plan)}] {t['cls']}" + (f" #{t['rep'] + 1}" if t["kind"] == "gesture" else "")
            print(f"\n{tag}: {t['instruction']}")
            if t["expected_action"] != "none":
                print(f"   (expected: {' '.join(t['expected_labels'])} -> {t['expected_action']})")
            k = ask("   Enter = start, s = skip, q = quit > ", auto)
            if k == "q":
                break
            if k == "s":
                i += 1
                continue
            rec.wait_s(1.0)          # a quiet second before GO (the noise floor keeps tracking the room)
            go = rec.n
            secs = t["seconds"]
            if fake:
                fcls = FAKE_NEG.get(t["cls"], t["cls"])
                secs = max(secs, fake.cue(fcls) + 0.2)
            print(f"   GO  ({secs:.1f} s)", flush=True)
            rec.wait_s(secs)
            stop = rec.n
            print("   stop", flush=True)
            rec.wait_s(0.3 + (cfg.hangover_frames + 4) * cfg.frame_ms / 1000)   # let the last sound finish
            for _ in range(40):              # a sound still going on at "stop": wait (up to 4 s) for it to end
                if rec.ex.seg.seg is None:
                    break
                rec.wait_s(0.1)
            t0, t1 = go * 1000 / rec.rate, stop * 1000 / rec.rate
            evs = rec.events_between(t0 - 500, t1)
            sc = score_take(t, evs)
            clip = rec.audio(go - rec.rate, stop + rec.rate // 2)
            lv = level_report(rec.audio(go, stop))
            verdict = "OK" if sc["ok"] else "MISS" if t["kind"] == "gesture" else "FALSE ACCEPT"
            print(f"   -> {verdict}: sounds {sc['detected_labels'] or '-'}, actions {[x for x in sc['actions'] if x != 'none'] or ['none']}"
                  f"   (take rms {lv.get('rms_dbfs')} dBFS)")
            if lv.get("zero_frac", 0) > 0.99:
                print("   [WARNING] this take is digital silence")
            k = ask("   Enter = keep, r = redo, x = discard > ", auto)
            kept = k not in ("r", "x")
            fname = f"takes/{i + 1:03d}_{t['cls']}_{t['rep'] + 1}{'' if kept else '_discarded'}.wav"
            sf.write(str(out / fname), clip, rec.rate, subtype="PCM_16")
            row = {**t, "take": i + 1, "file": fname, "session_file": "session.wav",
                   "go_ms": round(t0, 1), "stop_ms": round(t1, 1), "clip_offset_ms": round(t0 - 1000, 1),
                   "window_ms": [round(t0 - 500, 1), round(t1, 1)], "level": lv, "kept": kept,
                   "synthetic": bool(src.synthetic), **sc, "events": evs}
            labels_f.write(json.dumps(row, default=float) + "\n")
            labels_f.flush()
            if kept:
                results.append(row)
            if k != "r":
                i += 1
    except KeyboardInterrupt:
        print("\ninterrupted")
    labels_f.close()
    rec.wait_s(0.5)
    rec.stop()
    meta["duration_s"] = round(rec.n / rec.rate, 2)
    meta["takes_kept"] = len(results)
    (out / "session.json").write_text(json.dumps(meta, indent=1))
    print_summary(results, "this session" + (" (SYNTHETIC fake mic)" if src.synthetic else ""))
    print(f"\nsaved to {out}\nre-score later with:  ./run python record.py --replay {out.relative_to(HERE)}")



# ------------------------------------------------------------------------------------ enrollment

ENROLL_HELP = {
    "custom": "Make your sound '{name}' ONCE, the way you will use it.",
    "ignore": "Make the sound '{name}' ONCE (a sound VOX must always ignore).",
}
ENROLL_GESTURES = list(CONTOUR_GESTURES) + ["pop", "click", "hiss"]


def pick_event(kind: str, gesture: str | None, evs: list[dict]) -> tuple[int | None, str]:
    """The event of a take that becomes the example. Gesture: the first event with that label (a contour also needs
    its 16-point pitch16). Custom / ignore: the longest event (a meow split in two keeps its main part)."""
    if not evs:
        return None, "no sound detected"
    if kind == "gesture":
        for i, e in enumerate(evs):
            if e["label"] == gesture:
                if gesture in CONTOUR_GESTURES and len(e["raw"].get("pitch16") or []) != 16:
                    return None, f"{gesture} heard but without a pitch track"
                return i, ""
        return None, f"heard {[e['label'] for e in evs]}, not {gesture}"
    i = max(range(len(evs)), key=lambda k: evs[k]["t_end_ms"] - evs[k]["t_start_ms"])
    return i, "" if len(evs) == 1 else f"{len(evs)} sounds in the take; kept the longest"


def enroll_check(name: str, examples: list[dict]) -> None:
    """Consistency check of a class's last 10 examples: own spread, least typical take, clashes with other classes."""
    from vox_extract.personal import EnrollClass, Matcher, euclid, load_floors, standardize, standardizer, within_class
    xs = examples[-10:]
    if len(xs) < 3:
        print("the phone matches a class only from 3 examples on")
        return
    # the floor the app ships (android assets), else the extractor's own scales; None = no floor
    floor = (load_floors(HERE.parent / "android" / "app" / "src" / "main" / "assets" / "fp_floors.json")
             or load_floors(HERE / "results" / "fp1_scales.json"))
    mean, std = standardizer([x["fp"] for x in xs], floor)
    z = [standardize(x["fp"], mean, std) for x in xs]
    wc = within_class(z, euclid)
    odd = max(range(len(z)), key=lambda q: min(euclid(z[q], z[r]) for r in range(len(z)) if r != q))
    print(f"within-class spread {wc:.2f} (standardised by this class alone; the phone standardises over all "
          f"enrolled classes); least typical take: {xs[odd]['file']}")
    classes = []
    for p in sorted((HERE / "recordings" / "enroll").glob("*/*/examples.jsonl")):
        ex = [json.loads(l) for l in p.read_text().splitlines() if l.strip()][-10:]
        classes.append(EnrollClass(p.parent.parent.name, p.parent.name, ex))
    if len(classes) > 1:
        m = Matcher(classes, 1.4, floor)
        clash = [(x["file"], r.cls) for x in xs for r in [m.match(x["fp"], x["pitch16"])] if r.cls not in (None, name)]
        print(f"WARNING: {len(clash)} of these takes match another enrolled class (x1.4): {clash}" if clash
              else f"none of these takes matches another of the {len(classes) - 1} enrolled classes (x1.4)")


def run_enroll(a: argparse.Namespace) -> None:
    """Record labelled enrollment takes into recordings/enroll/<kind>/<name>/ (module docstring)."""
    import re
    import soundfile as sf
    kind = a.enroll
    name = ((a.gesture if kind == "gesture" else a.name) or "").strip().lower()
    if kind == "gesture":
        if name not in ENROLL_GESTURES:
            raise SystemExit(f"--enroll gesture needs --gesture, one of {ENROLL_GESTURES}")
    elif not re.fullmatch(r"[a-z0-9][a-z0-9 -]{0,23}", name):
        raise SystemExit("--enroll custom / ignore needs --name matching [a-z0-9][a-z0-9 -]{0,23} (e.g. meow, kiss, sneeze)")
    cfg = load_cfg(a.config)
    src = make_source(a)
    auto = a.auto or isinstance(src, FakeSource) and not a.interactive
    fake = src if isinstance(src, FakeSource) else None
    cdir = HERE / "recordings" / "enroll" / kind / name
    ex_path = cdir / "examples.jsonl"
    have = [json.loads(l) for l in ex_path.read_text().splitlines() if l.strip()] if ex_path.exists() else []
    run = datetime.now().strftime("run-%Y%m%d-%H%M%S")
    rec = Recorder(src, cfg, cdir / run, print_events=True, show_protocol=a.protocol, sender=connect(a.send))
    (cdir / "takes").mkdir(parents=True, exist_ok=True)
    (cdir / run / "config.json").write_text(cfg.to_json())
    meta = session_meta(a, src, cfg, {"enroll": {"kind": kind, "name": name, "takes": a.takes}})
    print(f"enroll {kind} '{name}': {a.takes} takes ({len(have)} already), source {src.name} at {src.rate} Hz -> {cdir}")
    if len(have) + a.takes > 10:
        print("note: the phone keeps at most 10 examples per class; push only the ones you want")
    if fake:
        print("NOTE: the fake source is SYNTHETIC. These examples test the tool, not a real voice.")
    rec.start()
    meta["signal_check"] = check_signal(rec, 2.0, a.allow_silent)
    ins = GESTURE_PROMPTS[name][0] if kind == "gesture" else ENROLL_HELP[kind].format(name=name)
    print(f"\n{ins}\nUse your normal loudness and distance from the mic, and vary it a little between takes.")
    if not auto:
        print("For each take: press Enter, wait for GO, make the sound ONCE, then stay quiet until 'stop'.\n"
              "After each take: Enter = keep, r = redo, x = discard.  Before a take: q = quit.")
    n0 = len(list((cdir / "takes").glob("*.wav")))
    takes_f = (cdir / "takes.jsonl").open("a")
    ex_f = ex_path.open("a")
    kept: list[dict] = []
    i = n = 0
    try:
        while i < a.takes:
            print(f"\n[{i + 1}/{a.takes}] {kind} '{name}'")
            if ask("   Enter = start, q = quit > ", auto) == "q":
                break
            rec.wait_s(1.0)
            go = rec.n
            secs = a.take_seconds
            if fake:
                secs = max(secs, fake.cue(name if kind == "gesture" else {"custom": "arch", "ignore": "cough"}[kind]) + 0.2)
            print(f"   GO  ({secs:.1f} s)", flush=True)
            rec.wait_s(secs)
            stop = rec.n
            print("   stop", flush=True)
            rec.wait_s(0.3 + (cfg.hangover_frames + 4) * cfg.frame_ms / 1000)
            for _ in range(40):              # a sound still going on at "stop": wait (up to 4 s) for it to end
                if rec.ex.seg.seg is None:
                    break
                rec.wait_s(0.1)
            t0, t1 = go * 1000 / rec.rate, stop * 1000 / rec.rate
            evs = [e for e in rec.events_between(t0 - 500, t1) if e.get("emit", True) and e["raw"].get("fp")]
            j, why = pick_event(kind, name if kind == "gesture" else None, evs)
            if j is not None:
                e = evs[j]
                print(f"   -> example: {e['label']} {e['t_end_ms'] - e['t_start_ms']:.0f} ms | {e['text']}" + (f"   ({why})" if why else ""))
            else:
                print(f"   -> NOT USABLE: {why}" + ("" if auto else "  (r = redo)"))
            k = ask("   Enter = keep, r = redo, x = discard > ", auto)
            keep = j is not None and k not in ("r", "x")
            n += 1
            fname = f"takes/{n0 + n:03d}{'' if keep else '_discarded'}.wav"
            sf.write(str(cdir / fname), rec.audio(go - rec.rate, stop + rec.rate // 2), rec.rate, subtype="PCM_16")
            row = {"kind": kind, "name": name, "file": fname, "run": run, "go_ms": round(t0, 1), "stop_ms": round(t1, 1),
                   "clip_offset_ms": round(t0 - 1000, 1), "kept": keep, "usable": j is not None, "note": why,
                   "synthetic": bool(src.synthetic), "chosen": j, "events": evs}
            takes_f.write(json.dumps(row, default=float) + "\n")
            takes_f.flush()
            if keep:
                ev = evs[j]
                ex = {"kind": kind, "name": name, "fp": ev["raw"]["fp"], "fp_version": ev["raw"]["fp_version"],
                      "pitch16": ev["raw"].get("pitch16") or [], "file": fname, "label": ev["label"],
                      "text": ev["text"], "synthetic": bool(src.synthetic)}
                ex_f.write(json.dumps(ex) + "\n")
                ex_f.flush()
                kept.append(ex)
            if k != "r":
                i += 1
    except KeyboardInterrupt:
        print("\ninterrupted")
    takes_f.close()
    ex_f.close()
    rec.wait_s(0.5)
    rec.stop()
    meta["duration_s"] = round(rec.n / rec.rate, 2)
    meta["examples_kept"] = len(kept)
    (cdir / run / "session.json").write_text(json.dumps(meta, indent=1))
    print(f"\n'{name}': {len(kept)} new examples, {len(have) + len(kept)} in {ex_path.relative_to(HERE)}")
    enroll_check(name, have + kept)
    print(f"push to the phone:  python3 android/suite/enroll.py push extractor/{ex_path.relative_to(HERE)}")

def print_summary(rows: list[dict], title: str) -> dict:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["cls"], []).append(r)
    summary = {}
    print(f"\nsummary, {title}:")
    print(f"  {'class':<16}{'takes':>6}{'ok':>6}   detected")
    for cls, rs in by.items():
        ok = sum(r["ok"] for r in rs)
        det: dict[str, int] = {}
        for r in rs:
            key = " ".join(r["detected_labels"]) or "-"
            det[key] = det.get(key, 0) + 1
        summary[cls] = {"takes": len(rs), "ok": ok, "detected": det, "kind": rs[0]["kind"]}
        print(f"  {cls:<16}{len(rs):>6}{ok:>6}   {det}")
    g = [r for r in rows if r["kind"] == "gesture"]
    n = [r for r in rows if r["kind"] == "negative"]
    if g:
        print(f"  gestures correct: {sum(r['ok'] for r in g)}/{len(g)}")
    if n:
        print(f"  negative takes with a false accept: {sum(not r['ok'] for r in n)}/{len(n)}")
    return summary


def run_replay(a: argparse.Namespace) -> None:
    d = Path(a.replay)
    if not d.is_absolute() and not d.exists():
        d = HERE / d
    meta = json.loads((d / "session.json").read_text())
    cfg = load_cfg(a.config) if a.config else Config.from_dict(meta["config"])
    x, sr = load_wav(d / "session.wav")
    events = [e.to_dict() for e in run_stream(x, sr, cfg)]
    if not (d / "labels.jsonl").exists():
        # a free (unprompted) session: no takes to score, so compare with the events saved at recording time
        old = [json.loads(l) for l in (d / "events.jsonl").read_text().splitlines() if l.strip()] if (d / "events.jsonl").exists() else []
        key = lambda e: (e["t_start_ms"], e["t_end_ms"], e["label"], e["text"])  # noqa: E731
        print(f"replay of {d.name} (free session, no labels.jsonl): {len(old)} saved events -> {len(events)} now")
        for e in events:
            print(f"  {'   ' if key(e) in set(map(key, old)) else 'NEW'} {e['t_start_ms']:6d}-{e['t_end_ms']:6d} ms  {e['label']:<5} | {e['text']}")
        for e in old:
            if key(e) not in set(map(key, events)):
                print(f"  GONE {e['t_start_ms']:6d}-{e['t_end_ms']:6d} ms  {e['label']:<5} | {e['text']}")
        for g in group(events, GROUP_GAP_MS):
            act = action_for([(e["label"], e["text"]) for e in g])
            if act != "none":
                print(f"  => {' '.join(e['label'] for e in g)} at {g[0]['t_start_ms']} ms: {act}  (default profile)")
        outp = d / ("replay.json" if not a.config else f"replay_{Path(a.config).stem}.json")
        outp.write_text(json.dumps({"config": json.loads(cfg.to_json()), "events": events}, indent=1, default=float))
        print(f"wrote {outp}")
        return
    rows = []
    for line in (d / "labels.jsonl").open():
        t = json.loads(line)
        if not t.get("kept", True):
            continue
        lo, hi = t["window_ms"]
        evs = [e for e in events if lo <= e["t_start_ms"] < hi]
        rows.append({**t, **score_take(t, evs), "events": evs})
    title = f"replay of {d.name}" + (" (SYNTHETIC)" if meta.get("synthetic") else "") + (f" with {a.config}" if a.config else "")
    summary = print_summary(rows, title)
    outp = d / ("replay.json" if not a.config else f"replay_{Path(a.config).stem}.json")
    outp.write_text(json.dumps({"config": json.loads(cfg.to_json()), "summary": summary, "takes": rows}, indent=1, default=float))
    print(f"wrote {outp}")


def run_stream(x: np.ndarray, sr: int, cfg: Config) -> list[Event]:
    if sr not in (16000, 48000):
        x, sr = to_16k(x, sr), 16000
    ex = Extractor(cfg, input_rate=sr)
    out = []
    blk = sr // 20
    for i in range(0, x.size, blk):
        out += ex.push(x[i:i + blk])
    return out + ex.flush()


def run_wavs(a: argparse.Namespace) -> None:
    cfg = load_cfg(a.config)
    for p in a.wav:
        x, sr = load_wav(p)
        print(f"{p}  ({x.size / sr:.2f} s at {sr} Hz)")
        events = run_stream(x, sr, cfg)
        dicts = [e.to_dict() for e in events]
        for i, d in enumerate(dicts, 1):
            print(f"  {d['t_start_ms'] / 1000:7.2f}-{d['t_end_ms'] / 1000:6.2f} s  {d['label']:<5} | {d['text']}")
            if a.protocol:
                print("    " + json.dumps(message([d], i)))  # ids must change: the app ignores a repeated id
        for g in group(dicts, GROUP_GAP_MS):
            print(f"  {'':16} => {' '.join(e['label'] for e in g)}: {action_for([(e['label'], e['text']) for e in g])}  (default profile)")
        if a.out:
            o = Path(a.out)
            o.mkdir(parents=True, exist_ok=True)
            with (o / (Path(p).stem + ".events.jsonl")).open("w") as f:
                for i, d in enumerate(dicts, 1):
                    f.write(json.dumps({**d, "message": message([d], i)}, default=float) + "\n")


def list_devices() -> None:
    print("PipeWire / PulseAudio capture sources (pactl):")
    srcs = pw_sources()
    if not srcs:
        print("  (none found; is pactl installed and PipeWire running?)")
    default = pactl("get-default-source").strip()
    for s in srcs:
        if s["monitor"]:
            continue
        mark = "*" if s["name"] == default else " "
        print(f" {mark} {s['name']}\n      {s['description']}; active port: {s['active_port']}")
        for port, av in s["ports"]:
            print(f"        {port}: {av}")
    print("  (monitors of outputs are not listed; * = default)\n"
          "  A mic port 'not available' means the jack is not detected: capture will be digital silence.")
    try:
        import sounddevice as sd
        print("\nPortAudio devices (sounddevice, --source sd --device N):")
        for i, dv in enumerate(sd.query_devices()):
            if dv["max_input_channels"] > 0:
                print(f"  {i:3d} {dv['name']}  ({dv['max_input_channels']} in, {dv['default_samplerate']:.0f} Hz)")
    except Exception as e:  # PortAudio missing is not fatal
        print(f"\n(sounddevice unavailable: {e})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="auto", choices=["auto", "pw", "sd", "fake"])
    ap.add_argument("--device", help="PipeWire source name (pw) or PortAudio device index / name (sd)")
    ap.add_argument("--rate", type=int, default=48000, choices=[16000, 48000], help="capture rate")
    ap.add_argument("--config", help="Config JSON (e.g. recordings/<session>/config.json after --calibrate)")
    ap.add_argument("--session", help="output folder name under recordings/")
    ap.add_argument("--seconds", type=float, help="live mode: stop after this long")
    ap.add_argument("--allow-silent", action="store_true", help="record even if the input is digital silence")
    ap.add_argument("--protocol", action="store_true", help="also print the PROTOCOL.md JSON message per sound")
    ap.add_argument("--send", metavar="HOST:PORT", help="send messages to the app's debug socket (adb forward tcp:7788 ...)")
    ap.add_argument("--prompt", action="store_true", help="guided, labelled recording session")
    ap.add_argument("--reps", type=int, default=5, help="--prompt: takes per gesture")
    ap.add_argument("--gestures", nargs="*", help=f"--prompt: subset of {list(GESTURE_PROMPTS)}")
    ap.add_argument("--whistle", action="store_true", help="--prompt: add whistled contours")
    ap.add_argument("--negatives", nargs="*", help=f"--prompt: subset of {list(NEGATIVE_PROMPTS)} (none: pass the flag alone)")
    ap.add_argument("--neg-seconds", type=float, default=8.0)
    ap.add_argument("--neg-reps", type=int, default=1)
    ap.add_argument("--shuffle", action="store_true", help="--prompt: shuffle the gesture takes")
    ap.add_argument("--append", action="store_true", help="--prompt: add takes to an existing session folder")
    ap.add_argument("--calibrate", action="store_true", help="measure your normal hum level first (sets loud_calib_db)")
    ap.add_argument("--auto", action="store_true", help="no key presses (takes start automatically)")
    ap.add_argument("--interactive", action="store_true", help="fake source: still wait for key presses")
    ap.add_argument("--fake-speed", type=float, default=20.0, help="fake source: times faster than real time")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--wav", nargs="+", help="process WAV files instead of recording")
    ap.add_argument("--out", help="--wav: folder for <name>.events.jsonl")
    ap.add_argument("--enroll", choices=["custom", "ignore", "gesture"], help="record enrollment examples (personalization)")
    ap.add_argument("--name", help="--enroll custom/ignore: the sound's name (e.g. meow)")
    ap.add_argument("--gesture", help="--enroll gesture: rise, fall, arch, dip, flat, pop, click or hiss")
    ap.add_argument("--takes", type=int, default=5, help="--enroll: takes to record (the phone uses 3-10 per class)")
    ap.add_argument("--take-seconds", type=float, default=3.0, help="--enroll: length of each take")
    ap.add_argument("--replay", metavar="DIR", help="re-run and score a saved --prompt session")
    ap.add_argument("--list-devices", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    if a.list_devices:
        return list_devices()
    if a.wav:
        return run_wavs(a)
    if a.replay:
        return run_replay(a)
    if a.enroll:
        return run_enroll(a)
    if a.prompt:
        return run_prompt(a)
    if a.calibrate:
        cfg = load_cfg(a.config)
        src = make_source(a)
        out = HERE / "recordings" / (a.session or datetime.now().strftime("calib-%Y%m%d-%H%M%S"))
        rec = Recorder(src, cfg, out)
        rec.start()
        check_signal(rec, 1.5, a.allow_silent)
        calibrate(rec, cfg, a.auto or isinstance(src, FakeSource), src if isinstance(src, FakeSource) else None)
        rec.stop()
        (out / "config.json").write_text(cfg.to_json())
        (out / "session.json").write_text(json.dumps(session_meta(a, src, cfg), indent=1))
        print(f"use it with:  --config {(out / 'config.json').relative_to(HERE)}")
        return
    run_live(a)


if __name__ == "__main__":
    main()
