"""Operator-driven near-field recording and verified private-file export.

Run later on the coordinator's selected device using voxlib's VOX_SERIAL,
ANDROID_ADB_SERVER_PORT and VOX_SOCKET_PORT. No phone settings are changed.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import select
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

from voxlib import APP, Vox, adb

GESTURES = ["rise", "fall", "click", "click click", "hiss"]


def safe_sid(sid) -> str:
    """The app's sids are ints (1, 2, ... per service start); everything here keys them as strings."""
    if isinstance(sid, bool) or not isinstance(sid, (str, int)) or not re.fullmatch(r"[A-Za-z0-9_-]+", str(sid)):
        raise ValueError(f"unsafe session id: {sid!r}")
    return str(sid)


def output_dir(path: Path) -> Path:
    """Resolve symlinks; discover worktrees without invoking git discovery commands."""
    path = path.expanduser().resolve()
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            result = subprocess.run(["git", "check-ignore", "-q", "--", str(path) + "/"],
                                    cwd=parent, capture_output=True)
            if result.returncode != 0:
                raise ValueError("pull directory is inside a git work tree and is not gitignored")
            return path
    return path


def checked(vox, op: str, **kw) -> dict:
    reply = vox.control(op, **kw)
    if not reply.get("ok"):
        raise RuntimeError(f"{op}: {reply.get('error', reply)}")
    return reply


def stop(vox) -> None:
    """measure_stop answers ok:false once the session ended by itself (max_s); only one still running is an error."""
    if not vox.control("measure_stop").get("ok") and vox.control("measure_status").get("running"):
        raise RuntimeError("measure_stop failed; the measurement is still running")


def sessions(lines: list[bytes]) -> dict[str, list[bytes]]:
    """Per sid, the event lines of its LAST complete session (through its measure_stop). Sids are wall-clock ms and
    unique; keeping the last one per sid is a guard against a repeated sid. An unfinished session is left out."""
    current: dict[str, list[bytes]] = {}
    done: dict[str, list[bytes]] = {}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue   # a blank line, or one cut off by the rotation
        if not isinstance(event, dict) or event.get("sid") is None:
            continue
        sid = str(event["sid"])
        current.setdefault(sid, []).append(line)
        if event.get("ev") == "measure_stop":
            done[sid] = current.pop(sid)
    return done


def event(block: list[bytes], ev: str) -> dict | None:
    return next((e for e in map(json.loads, block) if e.get("ev") == ev), None)


def plan(noisy: bool = False) -> list[dict]:
    phases = []
    for volume in (30, 60, 90):
        phases.append(dict(phase=f"1-media-{volume}", max_s=60, prompt=False,
                           instruction=f"Start a Short on the speaker at {volume}% volume; stay silent."))
    for gesture in GESTURES:
        phases.append(dict(phase=f"2-user-{gesture.replace(' ', '-')}", max_s=55, prompt=True,
                           gestures=[gesture], takes=10,
                           instruction=f"Pause media. Perform {gesture!r} once per prompt, 10 times."))
    for volume in (30, 60, 90):
        phases.append(dict(phase=f"3-media-{volume}", max_s=90, prompt=True,
                           instruction=f"Start a Short on the speaker at {volume}% volume; follow the prompts."))
    if noisy:
        for kind, seconds in ((1, 60), (3, 90)):
            phases.append(dict(phase=f"{kind}-media-60-noisy", max_s=seconds, prompt=kind == 3,
                               instruction="Use a noisy room, speaker at 60%. " +
                               ("Stay silent." if kind == 1 else "Follow the prompts.")))
    return phases


def wait_phase(vox, sid: str, seconds: int, takes: int | None = None) -> bool:
    """Return false on q/EOF. Leave 1.5 s for the final prompted reaction.

    A stopped session answers measure_status with only {running: false} (no sid, no seconds), so the end is read
    from `running` and an early end (capture stop/restart, service stop) from the host clock."""
    began = time.monotonic()
    deadline = began + seconds + 10
    last_prompt = None
    previous = 0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if ready:
            line = sys.stdin.readline()
            if not line or line.strip().lower() == "q":
                return False
        status = vox.control("measure_status")
        if not status.get("running") or str(status.get("sid")) != sid:
            if takes and previous < takes:
                raise RuntimeError("capture ended before all prompts (see the measure_stop reason)")
            if not takes and time.monotonic() - began < seconds - 2:
                raise RuntimeError("capture ended before the planned duration (see the measure_stop reason)")
            return True
        if takes:
            count = status["prompts"]
            if count > takes or count - previous > 1:
                raise RuntimeError("missed prompt boundary; repeat this phase")
            previous = count
            if count == takes and last_prompt is None:
                last_prompt = time.monotonic()
            if last_prompt is not None and time.monotonic() >= last_prompt + 1.5:
                return True
    raise RuntimeError("measurement did not finish before its deadline")


def run(vox, phases: list[dict], stereo: bool = False) -> list[str]:
    sids = []
    try:
        if vox.control("measure_status").get("running"):
            raise RuntimeError("a measurement is already running")
        for phase in phases:
            print(f"\n{phase['phase']}: {phase['instruction']}")
            if input("Press Enter when ready, or q to abort: ").strip().lower() == "q":
                break
            # Stop in finally even if a start reply is lost after the app accepted it.
            try:
                reply = checked(vox, "measure_start", phase=phase["phase"], every_ms=5000,
                                gestures=phase.get("gestures", GESTURES), prompt=phase["prompt"],
                                record=True, stereo=stereo, max_s=phase["max_s"])
                sid = safe_sid(reply["sid"])
                sids.append(sid)
                print(f"Recording {sid}; enter q to abort.", flush=True)
                if not wait_phase(vox, sid, phase["max_s"], phase.get("takes")):
                    break
            finally:
                stop(vox)
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
    finally:
        print("Session ids: " + " ".join(sids), flush=True)
    return sids


def wav_info(data: bytes) -> tuple[int, int, int]:
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() not in (1, 2):
            raise ValueError("expected PCM16 mono or stereo WAV")
        frames, channels, rate = wav.getnframes(), wav.getnchannels(), wav.getframerate()
        if len(wav.readframes(frames)) != frames * channels * 2:
            raise ValueError("truncated WAV")
        return frames, channels, rate


def pull(vox, out: Path, sids: list[str] | None = None, clear: bool = False, *,
         validate_output=output_dir) -> list[str]:
    # Range recording supplies a private-path guard that does not invoke git.
    out = validate_output(out)
    if vox.control("measure_status").get("running"):
        raise RuntimeError("stop recording before pulling")
    # EventLog rotates events.jsonl to events.1.jsonl at 2 MB; a whole protocol run can cross that.
    # A missing file (no rotation yet, nothing recorded) is empty, not an error text on stdout.
    quiet = lambda cmd: adb("exec-out", f"run-as {APP} sh -c '{cmd} 2>/dev/null; true'", binary=True)
    raw = quiet("cat files/events.1.jsonl") + b"\n" + quiet("cat files/events.jsonl")
    blocks = sessions(raw.splitlines())
    stored = {safe_sid(s) for s in quiet("ls files/measure").decode().split()}
    selected = sorted({safe_sid(s) for s in sids} if sids else stored, key=lambda s: (len(s), s))
    if not selected:
        raise ValueError("no measurement recordings on the device")
    if clear and not stored <= set(selected):
        raise ValueError("--clear deletes ALL recordings; pull every stored session before clearing")
    if out.exists() and any(out.iterdir()):
        raise ValueError("output is not empty; use a fresh directory")
    out.mkdir(parents=True, exist_ok=True)
    for sid in selected:
        start, stopped = event(blocks.get(sid, []), "measure_start"), event(blocks.get(sid, []), "measure_stop")
        if start is None or stopped is None:
            raise ValueError(f"{sid}: missing start/stop event; cannot verify recording")
        remote = f"files/measure/{sid}/audio.wav"
        size = int(adb("exec-out", "run-as", APP, "stat", "-c", "%s", remote).strip())
        if shutil.disk_usage(out).free - size < 30 * 1024**3:
            raise RuntimeError("pull would leave less than 30 GiB free")
        data = adb("exec-out", "run-as", APP, "cat", remote, binary=True)
        if len(data) != size:
            raise ValueError(f"{sid}: byte size mismatch ({len(data)} != {size})")
        frames, channels, rate = wav_info(data)
        if (channels, rate) != (start["channels"], start["rate"]) or frames != stopped["samples"]:
            raise ValueError(f"{sid}: WAV metadata/sample count mismatch")
        target = out / sid / "audio.wav"
        target.parent.mkdir(exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        if target.stat().st_size != size or target.read_bytes() != data:
            raise ValueError(f"{sid}: local verification failed")
    exported = b"\n".join(line for sid in selected for line in blocks[sid]) + b"\n"
    with (out / "events.jsonl").open("xb") as stream:
        stream.write(exported)
    if (out / "events.jsonl").read_bytes() != exported:
        raise ValueError("local event log verification failed")
    if clear:
        checked(vox, "measure_clear")
    return selected


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--plan", choices=["default"], default="default")
    r.add_argument("--noisy", action="store_true")
    r.add_argument("--stereo", action="store_true")
    p = sub.add_parser("pull")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--sid", action="append", help="repeat to select sessions; default: all logged sessions")
    p.add_argument("--clear", action="store_true")
    args = ap.parse_args()
    if args.cmd == "pull":
        output_dir(args.out)  # Refuse before opening a device connection.
    vox = Vox()
    try:
        if args.cmd == "run":
            run(vox, plan(args.noisy), args.stereo)
        else:
            print("Pulled: " + " ".join(pull(vox, args.out, args.sid, args.clear)))
    finally:
        vox.close()


if __name__ == "__main__":
    main()
