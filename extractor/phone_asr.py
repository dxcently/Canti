#!/usr/bin/env python3
"""Run the reviewed phrase clips through the PHONE's own on-device recognizer (Canti's live path) and score them.

Whisper (segment_takes.py) only splits the takes and gives word timings; the score that matters is what Canti's
live path hears: Android's on-device SpeechRecognizer with the app's own settings, then PhraseGrammar.

  ./run python phone_asr.py --session recordings/khoa-guided-1 --dry-run          # convert + check, no device
  VOX_SERIAL=emulator-5580 ./run python phone_asr.py --control-only               # feasibility: public-domain clip
  VOX_SERIAL=<serial> ./run python phone_asr.py --session recordings/khoa-guided-1 # all kept phrase clips

Per clip: 48 kHz take slice -> 16 kHz mono PCM16 WAV in memory (0.3 s silence before, 1.2 s after, like a live window
that opens a moment before the speech and ends on the endpointer) -> base64 over the app's debug socket
(`asr_audio` op) -> the app streams it through a pipe into createOnDeviceSpeechRecognizer with EXTRA_AUDIO_SOURCE
and the live path's intent extras -> poll `asr_audio_result` -> the n-best, confidences and PhraseGrammar's parse.
NOTHING is written to the phone's storage (the audio lives in the app's memory for the one recognition), and the
app logs no transcript text. On-device only: the op refuses when on-device recognition is unavailable and never
uses an online recognizer.

Guard: Android documents that a recognizer that does not support EXTRA_AUDIO_SOURCE silently records from the MIC
instead. So every run starts with two control clips: 2 s of digital silence (must give no words) and 7 s of a
PUBLIC-DOMAIN LibriVox reading from MUSAN (must give its words). If either fails, or the app saw a new recording
start during a recognition (mic_opened), the run stops before any of the user's clips is sent.

Output (PRIVATE, under the session): phone_asr.jsonl, one row per clip per run (append-only): the phone's n-best +
confidences, the grammar's command for it, the Whisper transcript and the grammar's command for that, the expected
intent and the verdicts. The Whisper transcripts go through the same on-phone grammar (`grammar` op, text only).
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
SUITE = HERE.parent / "android" / "suite"
RATE = 16000
PAD_BEFORE_S, PAD_AFTER_S = 0.3, 1.2
# Public domain (LibriVox via MUSAN, speech/librivox/LICENSE): 7 s from 20 s into speech-librivox-0168 (English).
# Whisper medium.en hears: "By Fred Abboud. The War of Antichrist with the Church and Christian Civilization."
CONTROL_WAV = HERE.parent / "datasets" / "musan" / "musan" / "speech" / "librivox" / "speech-librivox-0168.wav"
CONTROL_SPAN_S = (20.0, 27.0)
CONTROL_WORDS = {"war", "antichrist", "church", "christian", "civilization"}
POLL_S, RESULT_TIMEOUT_S = 0.25, 15.0   # + the clip's length (the app gives up at length + 10 s)


def wav_bytes(x: np.ndarray, sr: int) -> bytes:
    """mono int16 at 16 kHz with the window padding, as a WAV file in memory."""
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x.astype(np.float64)
    if sr != RATE:
        g = np.gcd(sr, RATE)
        x = resample_poly(x, RATE // g, sr // g)
    x = np.concatenate([np.zeros(int(PAD_BEFORE_S * RATE)), x, np.zeros(int(PAD_AFTER_S * RATE))])
    pcm = np.clip(np.round(x), -32768, 32767).astype(np.int16)
    b = io.BytesIO()
    sf.write(b, pcm, RATE, format="WAV", subtype="PCM_16")
    return b.getvalue()


def load_int16(path: Path, span: tuple[float, float] | None = None) -> tuple[np.ndarray, int]:
    x, sr = sf.read(str(path), dtype="int16")
    if span:
        x = x[int(span[0] * sr): int(span[1] * sr)]
    return x, sr

# ------------------------------------------------------------------------------------ scoring


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def verdict(expect: list[str] | None, cmd: dict | None) -> str:
    """match | wrong | none (no command) | decider (text left for the phrase decider) | n/a.
    cmd is the op's structured command: {type, label|name|query|phrase|seconds|stream|op|action|semantic, describe}."""
    if not expect or cmd is None:
        return "n/a"
    t = cmd.get("type")
    if len(expect) != 1:
        return "n/a (two commands: the grammar refuses these by design)" if t == "ignore" else "n/a"
    e = expect[0]
    m = re.match(r"(\w+)\((.*)\)", e)
    if e == "NONE":
        return "match" if t == "ignore" else "decider" if t == "phrase" else "wrong"
    if not m:
        return "n/a"
    kind, arg = m.group(1), m.group(2)
    if t == "ignore":
        return "none"
    if t == "phrase":
        return "decider"
    if kind == "OpenApp":
        ok = (t == "open_app" and norm(cmd.get("label")) == norm(arg)) or (t == "app_missing" and norm(cmd.get("name")) == norm(arg))
    elif kind == "Nav":
        ok = (t == "nav" and cmd.get("phrase") == arg) or \
             (t == "swipe" and arg in ("next", "the one before") and cmd.get("semantic") in ("next", "previous")
              and (cmd.get("semantic") == "next") == (arg == "next")) or \
             (t == "volume" and arg in ("volume down", "volume up") and
              (("down" in arg) == str(cmd.get("op", "")).startswith(("-", "down", "lower", "step -"))))
    elif kind == "Tap":
        ok = t == "tap" and norm(arg) in norm(cmd.get("query"))
    elif kind == "Timer":
        ok = t == "timer" and cmd.get("seconds") == int(arg)
    else:
        ok = False
    return "match" if ok else "wrong"

# ------------------------------------------------------------------------------------ the device


class Phone:
    def __init__(self, serial: str | None, asr_opts: dict | None = None):
        self.asr_opts = asr_opts or {}   # the op's diagnostic knobs (AsrAudioArgs.Options), same for every clip
        if serial:
            os.environ["VOX_SERIAL"] = serial
        sys.path.insert(0, str(SUITE))
        from voxlib import Vox  # noqa: E402  (adb forward to the app's debug socket)
        self.vox = Vox()

    def op(self, op: str, **kw) -> dict:
        r = self.vox.control(op, **kw)
        if not r.get("ok"):
            raise RuntimeError(f"{op}: {r.get('error')}")
        return r

    def recognize(self, wav: bytes) -> dict:
        r = self.op("asr_audio", wav_b64=base64.b64encode(wav).decode("ascii"), **self.asr_opts)
        rid = r["id"]
        t0 = time.monotonic()
        pads = (self.asr_opts.get("lead_ms", 0) + self.asr_opts.get("tail_ms", 0)) / 1000
        limit = RESULT_TIMEOUT_S + (len(wav) - 44) / 2 / RATE + pads
        while time.monotonic() - t0 < limit:
            time.sleep(POLL_S)
            res = self.op("asr_audio_result", id=rid)
            if res.get("state") == "done":
                return res["result"]
        raise TimeoutError(f"asr_audio {rid}: no result in {limit:.0f} s")

    def grammar(self, texts: list[str]) -> list[dict]:
        return self.op("grammar", texts=texts)["results"] if texts else []


class Abort(SystemExit):
    """Stop the whole run now: no further clip is sent."""

    def __init__(self, msg: str):
        super().__init__(f"STOP: {msg}")


def mic_problem(res: dict) -> str | None:
    """The mic guard on one result: the app could not watch the recordings (ambiguous) or a recording started."""
    if not res.get("mic_watch"):
        return "the app could not watch the device's recordings (mic_watch false): file input can't be trusted"
    if res.get("mic_opened") or str(res.get("why", "")).startswith("error: mic"):
        return f"a recording started during a file recognition (mic_opened, sources {res.get('mic_sources')})"
    return None


SILENCE_OK = {"no speech", "no speech (empty results)", "no speech (segmented)", "error: no speech", "error: no match"}


def diag(res: dict) -> str:
    """What the recognizer did with the audio and what was sent (no words): for a failed control."""
    return (f"    heard {json.dumps(res.get('heard'))}\n    sent {json.dumps(res.get('sent'))}\n"
            f"    service {json.dumps(res.get('service'))}, error_code {res.get('error_code')}, ready_ms {res.get('ready_ms')}, "
            f"fed_all_ms {res.get('fed_all_ms')}, elapsed_ms {res.get('elapsed_ms')}")


def control(phone: Phone) -> dict:
    """The file-input guard, public-domain audio only. Aborts at the FIRST sign of trouble, before anything else is sent:
    2 s of digital silence must end as no speech (no words, no error, no timeout); a 7 s LibriVox reading must give
    >= 2 of its words; the recognizer must have read the whole reading from the pipe; no recording may start."""
    if not CONTROL_WAV.exists():
        raise SystemExit(f"control clip missing: {CONTROL_WAV} (MUSAN, see datasets/SOURCES.md)")
    sil = phone.recognize(wav_bytes(np.zeros(2 * RATE, dtype=np.int16), RATE))
    print(f"control 1/2 silence: why {sil.get('why')}, words {sil.get('hypotheses') or '-'}, mic_watch {sil.get('mic_watch')}, "
          f"mic_opened {sil.get('mic_opened')}")
    print(diag(sil))
    if p := mic_problem(sil):
        raise Abort(f"control silence: {p}")
    if sil.get("hypotheses"):
        raise Abort(f"control silence gave words {sil['hypotheses'][:1]}: the recognizer is not hearing the file")
    if sil.get("why") not in SILENCE_OK:
        raise Abort(f"control silence ended as {sil.get('why')!r} (want one of {sorted(SILENCE_OK)}): ambiguous")
    x, sr = load_int16(CONTROL_WAV, CONTROL_SPAN_S)
    known = phone.recognize(wav_bytes(x, sr))
    heard = set(re.findall(r"[a-z]+", " ".join(known.get("hypotheses") or []).lower()))
    print(f"control 2/2 public-domain reading: why {known.get('why')}, best {(known.get('hypotheses') or ['-'])[0]!r}, "
          f"fed {known.get('fed_ms')}/{known.get('audio_ms')} ms, mic_opened {known.get('mic_opened')}")
    print(diag(known))
    if p := mic_problem(known):
        raise Abort(f"control reading: {p}")
    if len(heard & CONTROL_WORDS) < 2:
        raise Abort(f"control reading not heard (got {known.get('hypotheses', [])[:1]}, why {known.get('why')}): the "
                    "recognizer may be ignoring the file")
    speech_end_ms = (PAD_BEFORE_S + CONTROL_SPAN_S[1] - CONTROL_SPAN_S[0]) * 1000 - 500
    if (known.get("fed_ms") or 0) < speech_end_ms:
        raise Abort(f"the recognizer read only {known.get('fed_ms')} ms of the reading (want >= {speech_end_ms:.0f})")
    return {"silence": sil, "known": known, "words_heard": sorted(heard & CONTROL_WORDS)}

# ------------------------------------------------------------------------------------ main


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", help="session folder with clips.jsonl (review_segments.py)")
    ap.add_argument("--serial", help="adb serial (default: $VOX_SERIAL, else the suite emulator)")
    ap.add_argument("--control-only", action="store_true", help="only the file-input guard (public-domain clips)")
    ap.add_argument("--dry-run", action="store_true", help="convert every clip and report, no device")
    ap.add_argument("--limit", type=int, help="first N clips only")
    ap.add_argument("--pid", nargs="*", help="only these prompt ids")
    ap.add_argument("--asr-opts", type=json.loads, default={}, help='the asr_audio op\'s diagnostic options as JSON, e.g. '
                    '\'{"segmented": true}\', \'{"feed_at": "start"}\', \'{"realtime": false}\', \'{"lead_ms": 1000, "tail_ms": 2000}\'')
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    clips: list[dict] = []
    sess = None
    if not a.control_only:
        if not a.session:
            raise SystemExit("--session is required (or --control-only)")
        sess = Path(a.session)
        if not sess.exists():
            sess = HERE / a.session
        mf = sess / "clips.jsonl"
        if not mf.exists():
            raise SystemExit(f"no {mf}: review the segments first (review_segments.py)")
        clips = [json.loads(l) for l in mf.read_text().splitlines() if l.strip()]
        clips = [c for c in clips if c["block"] == "phrases" and (not a.pid or c["pid"] in a.pid)]
        if a.limit:
            clips = clips[: a.limit]
    if a.dry_run:
        tot = 0.0
        for c in clips:
            x, sr = load_int16(sess / c["clip"])
            b = wav_bytes(x, sr)
            tot += (len(b) - 44) / 2 / RATE
        print(f"{len(clips)} phrase clips -> 16 kHz WAV, {tot:.0f} s of audio with padding, "
              f"~{tot * 1.0 + len(clips) * 1.5:.0f} s on the phone (paced in real time)")
        print(f"control clip: {CONTROL_WAV} {'found' if CONTROL_WAV.exists() else 'MISSING'}")
        return

    if not (a.serial or os.environ.get("VOX_SERIAL")):
        raise SystemExit("give --serial (or VOX_SERIAL): this never picks a device by default")
    phone = Phone(a.serial, a.asr_opts)
    info = phone.op("asr")
    print(f"device {os.environ.get('VOX_SERIAL')}: asr {json.dumps(info.get('asr'))}")
    if (info.get("asr") or {}).get("on_device_available") is False:
        raise Abort("on-device recognition is unavailable on this device (the op never uses an online recognizer)")
    ctl = control(phone)   # raises Abort at the first bad control result: no user clip is ever sent after one
    print(f"control OK (words {ctl['words_heard']}): the recognizer hears the file, not the mic")
    if a.control_only:
        return

    run = datetime.now().isoformat(timespec="seconds")
    outp = sess / "phone_asr.jsonl"
    stats: dict[str, Counter] = defaultdict(Counter)
    with outp.open("a") as fo:
        for i, c in enumerate(clips):
            x, sr = load_int16(sess / c["clip"])
            res = phone.recognize(wav_bytes(x, sr))
            if p := mic_problem(res):   # never another clip after a mic sign
                raise Abort(f"clip {i + 1} ({c['seg']}): {p}")
            whisper_cmd = (phone.grammar([c["transcript"]]) or [None])[0] if c.get("transcript") else None
            v_phone = verdict(c.get("expect"), (res.get("pick") or {}).get("command"))
            v_whisper = verdict(c.get("expect"), whisper_cmd.get("command") if whisper_cmd else None)
            row = {"run": run, "serial": os.environ.get("VOX_SERIAL"), "seg": c["seg"], "clip": c["clip"],
                   "pid": c["pid"], "kind": c["kind"], "say": c.get("say"), "expect": c.get("expect"),
                   "whisper": c.get("transcript"), "whisper_command": whisper_cmd, "phone": res,
                   "verdict_phone": v_phone, "verdict_whisper": v_whisper, "recognizer": info.get("asr")}
            fo.write(json.dumps(row) + "\n")
            fo.flush()
            stats[c["kind"]][v_phone] += 1
            stats["ALL"][v_phone] += 1
            best = (res.get("hypotheses") or ["-"])[0]
            print(f"  {i + 1:>3}/{len(clips)} {c['seg']:<18} {v_phone:<8} phone {best[:40]!r:<44} "
                  f"whisper {c.get('transcript', '')[:36]!r}")
    print(f"\nwrote {outp}")
    for k in sorted(stats, key=lambda k: (k != "ALL", k)):
        print(f"  {k:<11} {dict(stats[k])}")


if __name__ == "__main__":
    main()
