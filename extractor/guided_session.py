#!/usr/bin/env python3
"""Guided recording session on the desktop USB mic: spoken phrases, whistles, clicks / pops.

One prompt at a time in big text. Enter records a take: 1 s of pre-roll is kept, and the take stops on its own
after silence (or at the prompt's max length), plus 0.5 s. Resumable: quit with q, run the same command again, and it
continues where you stopped.

Blocks (prompts are tracked, non-personal files):
  phrases   prompts/phrases_v1.json   60 spoken commands, fillers, corrections, chatter, 8 free-form   (~7 min)
  whistles  prompts/sounds_v1.json    rise / fall / arch / dip x5 in quiet, then x5 with a video      (~4 min)
  clicks    prompts/sounds_v1.json    click x10, click-click x10, click runs x5, pop x10, pop-click x5, pop-pop x5  (~4 min)
            (click-pop x5 was retired 2026-09-27 when pop-pop became listen; old takes keep their labels)

Keys (single key press, no Enter needed on a terminal):
  Enter  record this prompt       r  redo the last take       s  skip this prompt       q  quit (resume later)

Output: recordings/<session>/ (gitignored, PRIVATE: never commit it, never upload it anywhere)
  labels.jsonl          one line per take (append-only; the last line per prompt id wins): block, prompt id and text,
                        expected result, times, level, file, and for whistles / clicks the extractor events + actions
  takes/<block>/*.wav   each take: 1 s before GO to 0.5 s after the sound ended
  run-NN/               one folder per sitting: session.wav, events.jsonl, messages.jsonl, config.json
  session.json          source, rates, synthetic flag, prompt files, sittings

Commands
  ./run python guided_session.py --list-devices
  ./run python guided_session.py --session khoa-guided-1                      # all three blocks
  ./run python guided_session.py --session khoa-guided-1 --block whistles     # one block
  ./run python guided_session.py --score recordings/khoa-guided-1             # replay: default vs wstrong patch
  ./run python guided_session.py --score recordings/khoa-guided-1 --clips     # same, on the human-reviewed clips
                                  (segment_takes.py + review_segments.py: one clip per try instead of one per take)
  ./run python guided_session.py --source fake --session selftest --auto      # SYNTHETIC self-test, no mic
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

import record as R
from range_layout import getkey
from vox_extract import Config
from vox_extract.policy import not_deliberate

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts"
BLOCKS = ["phrases", "whistles", "clicks"]
PRE_S, POST_S = 1.0, 0.5
KEY_GUARD_S = 0.6          # after the key press: wait before GO, so the key's own click is not in the take window
# app mirror (android Vocab.DEFAULT_BINDINGS): sound sequence -> action
APP_BINDINGS = {("rise",): "swipe_up", ("fall",): "swipe_down", ("arch",): "swipe_right", ("dip",): "swipe_left",
                ("pop",): "tap", ("hiss",): "back", ("flat",): "long_press", ("pop", "pop"): "listen_for_phrase",
                ("click", "click"): "home", ("hiss", "click"): "back"}
GAP_MS = 600

# ------------------------------------------------------------------------------------ the plan


def load_plan(blocks: list[str]) -> tuple[list[dict], dict]:
    ph = json.loads((PROMPTS / "phrases_v1.json").read_text())
    so = json.loads((PROMPTS / "sounds_v1.json").read_text())
    plan: list[dict] = []
    for b in blocks:
        if b == "phrases":
            for p in ph["prompts"]:
                plan.append({"block": "phrases", "pid": p["id"], "kind": p["kind"],
                             "text": p["say"] if p["say"] else p["instruction"], "say": p["say"],
                             "expect": p["expect"], "note": p.get("note"), "max_s": p["max_s"],
                             "silence_s": 2.2 if p["kind"] == "free" else 1.8, "no_sound_s": 8.0, "cond": "quiet", "fake": [["talk_short" if p["kind"] == "chatter" else "talk", 0.0]]})
        else:
            for p in so["blocks"][b]:
                if p.get("retired"):
                    continue
                plan.append({"block": b, "pid": p["id"], "kind": p["cls"], "text": p["instruction"], "say": None,
                             "expect_sounds": p["expect_sounds"], "expect_now": p["expect_now"],
                             "expect_intent": p["expect_intent"], "note": p.get("note"), "max_s": p["max_s"],
                             "silence_s": 1.0, "no_sound_s": 5.0, "cond": p["cond"], "fake": p["fake"],
                             **({"run_len": p["run_len"]} if "run_len" in p else {})})
    files = {n: hashlib.sha256((PROMPTS / n).read_bytes()).hexdigest()[:12] for n in ("phrases_v1.json", "sounds_v1.json")}
    return plan, files


BLOCK_INTRO = {
    "phrases": ["SPOKEN COMMANDS.", "Read each line OUT LOUD, the way you'd talk to your phone, fillers and all.",
                "For the free-form ones, say it in your own words.", "Speak at your normal distance from the mic."],
    "whistles": ["WHISTLES.", "About 2 s of silence between whistles; don't breathe in loudly right before one.",
                 "FALLS: start high and fall a lot (at least half an octave).", "Don't touch the desk or the mic while whistling."],
    "clicks": ["CLICKS AND POPS.", "Tongue click = 'tsk' / cluck. Lip pop = a 'p' with closed lips, no voice.",
               "Do exactly the number asked, then stay quiet until the next prompt."],
}

# ------------------------------------------------------------------------------------ terminal UI

TTY = sys.stdout.isatty()


def sty(s: str, code: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if TTY else s


def clear() -> None:
    if TTY:
        print("\x1b[2J\x1b[H", end="")
    else:
        print("\n" + "-" * 60)


def wrap(text: str, width: int) -> list[str]:
    out, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return out + ([cur] if cur else [])


def big(text: str) -> None:
    """The prompt, large as a terminal allows: bold bright text, short centred lines, framed, with air around it.
    (Zoom the terminal, e.g. Ctrl + '+', to make it bigger still.)"""
    cols = os.get_terminal_size().columns if TTY else 80
    width = max(20, min(44, cols - 8))
    lines = wrap(text, width)
    w = max(len(l) for l in lines) + 6
    pad = " " * max(0, (cols - w) // 2)
    print(pad + sty("┌" + "─" * (w - 2) + "┐", "2"))
    for line in lines:
        print(pad + sty("│", "2") + " " * (w - 2) + sty("│", "2"))
        print(pad + sty("│", "2") + sty(line.center(w - 2), "1;97") + sty("│", "2"))
    print(pad + sty("│", "2") + " " * (w - 2) + sty("│", "2"))
    print(pad + sty("└" + "─" * (w - 2) + "┘", "2"))


def header(t: dict, idx_in_block: int, n_block: int, done_all: int, n_all: int, bi: int, nb: int) -> None:
    cols = os.get_terminal_size().columns if TTY else 80
    bar_w = max(10, min(40, cols - 50))
    fill = int(bar_w * idx_in_block / max(1, n_block))
    cond = "  WITH VIDEO" if t["cond"] == "video" else ""
    print(sty(f" {t['block'].upper()}{cond}  {idx_in_block + 1}/{n_block}", "1;96") +
          f"   [{'#' * fill}{'.' * (bar_w - fill)}]   block {bi + 1} of {nb}, total {done_all}/{n_all}\n\n")


# ------------------------------------------------------------------------------------ scoring helpers


def app_actions(events: list[dict], train_guard: bool = False, trust_labels: bool = False) -> list[dict]:
    """The phone's default profile over these events (a mirror of Sequencer + DEFAULT_BINDINGS, device clock):
    a sequence waits while a longer bound sequence starts with it; a sound within the gap joins it even when that makes
    an unbound sequence ("pop click", "click rise": nothing happens), as Sequencer.add does; a gap over GAP_MS splits.
    train_guard: the PROPOSED rule (not in the app): click-click acts only if no click starts within 500 ms after
    it and none ended within 600 ms before it (so a run of 3+ clicks does nothing)."""
    def lab(e: dict) -> str:
        return e["label"] if trust_labels or not not_deliberate(e["label"], e["text"]) else "unknown"
    out: list[dict] = []
    pend: list[dict] = []

    def resolve(g: list[dict]) -> None:
        if g:
            out.append({"t_ms": g[0]["t_start_ms"], "end_ms": g[-1]["t_end_ms"], "sounds": [lab(e) for e in g],
                        "action": APP_BINDINGS.get(tuple(lab(e) for e in g), "none")})

    def longer(seq: tuple) -> bool:
        return any(len(b) > len(seq) and b[:len(seq)] == seq for b in APP_BINDINGS)

    for e in sorted(events, key=lambda x: x["t_start_ms"]):
        if pend and e["t_start_ms"] - pend[-1]["t_end_ms"] > GAP_MS:
            resolve(pend)
            pend = []
        seq = tuple(lab(x) for x in pend + [e])
        pend.append(e)
        if not longer(seq):
            resolve(pend)
            pend = []
    resolve(pend)
    if train_guard:
        clicks = [e for e in events if lab(e) == "click"]
        for a in out:
            if a["sounds"] == ["click", "click"] and a["action"] == "home":
                after = any(0 <= c["t_start_ms"] - a["end_ms"] <= 500 for c in clicks)
                before = any(0 <= a["t_ms"] - c["t_end_ms"] <= 600 for c in clicks)
                if after or before:
                    a["action"] = "none"
                    a["guard"] = "click train"
    return out


def expected_now(sounds: list[str]) -> list[str]:
    """The actions today's default bindings give a prompt's sounds made quickly (250 ms apart). --score judges takes by
    this, not by the expect_now stored with the take, which were the bindings when it was recorded (kept as is)."""
    evs = [{"t_start_ms": i * 300, "t_end_ms": i * 300 + 50, "label": s, "text": ""} for i, s in enumerate(sounds)]
    return [x["action"] for x in app_actions(evs, trust_labels=True) if x["action"] != "none"]


def slim(e: dict) -> dict:
    r = e.get("raw", {})
    return {"t_start_ms": e["t_start_ms"], "t_end_ms": e["t_end_ms"], "label": e["label"], "text": e["text"],
            "sounds_like": e.get("sounds_like"), "raw": r}

# ------------------------------------------------------------------------------------ recording


def fake_cue(fake: R.FakeSource, cls: str) -> None:
    """SYNTHETIC: like FakeSource.cue, but the clip is trimmed to its active part (synth.py pads clips with up to
    seconds of background), so a fake take behaves like a person who starts right after GO."""
    c = fake.synth.make_clip(cls, fake.rng, fake.rate, 60.0, "pink").audio.astype(np.float32)
    hop = fake.rate // 100
    fr = np.sqrt(np.mean(c[: c.size // hop * hop].reshape(-1, hop).astype(np.float64) ** 2, axis=1)) + 1e-12
    on = np.flatnonzero(20 * np.log10(fr) > 20 * np.log10(fr.max()) - 35)
    if on.size:
        c = c[max(0, on[0] - 2) * hop: (on[-1] + 5) * hop]
    with fake.lock:
        fake.pending.append(c)


def take_one(rec: R.Recorder, t: dict, fake: R.FakeSource | None) -> dict:
    """Record one take. Returns sample marks and whether any sound was heard."""
    key = rec.n
    rec.wait_s(KEY_GUARD_S)
    go = rec.n
    print(sty("   ●  GO", "1;92"), flush=True)
    if fake:
        for cls, off in t["fake"]:
            rec.wait_until(go + int(off * rec.rate))
            fake_cue(fake, cls)
    blk = rec.rate // 20
    pre = rec.audio(max(0, go - rec.rate // 2), go)
    base = np.median(20 * np.log10(np.sqrt(np.mean(pre[: pre.size // blk * blk].reshape(-1, blk).astype(np.float64) ** 2, axis=1)) + 1e-9)) \
        if pre.size >= blk else -80.0
    heard, quiet_since, last_loud = False, None, go
    reason = "max length"
    while True:
        if not rec.wait_s(0.05):
            reason = "capture ended"
            break
        x = rec.audio(rec.n - blk, rec.n)
        lv = 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9) if x.size else -120.0
        el = (rec.n - go) / rec.rate
        if lv > base + 8:
            heard, quiet_since, last_loud = True, None, rec.n
        elif heard and lv < base + 5:
            quiet_since = quiet_since or rec.n
            if (rec.n - quiet_since) / rec.rate >= t["silence_s"]:
                reason = "silence"
                break
        if el >= t["max_s"]:
            break
        if not heard and el >= t["no_sound_s"]:
            reason = "no sound"
            break
    if heard and reason == "max length":
        rec.wait_s(POST_S)                       # still sounding at the cap: keep 0.5 s more
    end = min(rec.n, last_loud + int(POST_S * rec.rate)) if heard else rec.n
    return {"key": key, "go": go, "end": max(end, go), "heard": heard, "stop_reason": reason, "base_db": round(float(base), 1)}


def settle(rec: R.Recorder) -> None:
    """Let the extractor finish the last sound (it reports ~0.15 s after a sound ends)."""
    rec.wait_s(0.3 + (rec.cfg.hangover_frames + 4) * rec.cfg.frame_ms / 1000)
    for _ in range(40):
        if rec.ex.seg.seg is None:
            break
        rec.wait_s(0.1)


def read_rows(out: Path) -> list[dict]:
    f = out / "labels.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def run_session(a: argparse.Namespace) -> None:
    import soundfile as sf
    blocks = a.block or BLOCKS
    plan, files = load_plan(blocks)
    a.source = a.source or "auto"
    src = R.make_source(a)
    fake = src if isinstance(src, R.FakeSource) else None
    name = a.session or datetime.now().strftime("guided-%Y%m%d-%H%M%S")
    if fake and "synthetic" not in name:
        name += "-synthetic"
    out = HERE / "recordings" / name
    out.mkdir(parents=True, exist_ok=True)
    rows = read_rows(out)
    if rows and any(r.get("synthetic") for r in rows) != bool(fake):
        raise SystemExit(f"{out} mixes a real and a SYNTHETIC source; use another --session")
    state: dict[str, dict] = {}
    for r in rows:
        state[r["pid"]] = r
    done = {p for p, r in state.items() if r["status"] in ("kept", "skipped")}
    todo = [t for t in plan if t["pid"] not in done]
    auto = a.auto or (fake is not None and not a.interactive)
    if not todo:
        print(f"session {name}: every prompt of {', '.join(blocks)} is done. Score it with:\n"
              f"  ./run python guided_session.py --score recordings/{name}")
        return
    if not fake and isinstance(src, R.PwSource) and "CMEDIA" not in (src.target or ""):
        print(sty(f"NOTE: recording from {src.target}, not the CMEDIA USB mic. Pass --device "
                  "alsa_input.usb-CMEDIA_Q9-1-00.mono-fallback (see --list-devices) if that's wrong.", "1;93"))
    runs = sorted(p.name for p in out.glob("run-*"))
    run = f"run-{len(runs) + 1:02d}"
    cfg = R.load_cfg(a.config)
    rec = R.Recorder(src, cfg, out / run, print_events=False)
    (out / run / "config.json").write_text(cfg.to_json())
    meta_p = out / "session.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {
        "created": datetime.now().isoformat(timespec="seconds"), "session": name, "synthetic": bool(fake),
        "private": "the user's voice: never commit, never upload", "prompt_files": files, "runs": []}
    rec.start()
    sig = R.check_signal(rec, 1.5, a.allow_silent)
    meta["runs"].append({"run": run, "started": datetime.now().isoformat(timespec="seconds"), "source": src.name,
                         "capture_rate": src.rate, "synthetic": bool(fake), "blocks": blocks, "signal_check": sig,
                         "config": json.loads(cfg.to_json()), "argv": sys.argv[1:]})
    meta_p.write_text(json.dumps(meta, indent=1))
    labels = (out / "labels.jsonl").open("a")
    n_take = len(rows)
    by_block = {b: [t for t in plan if t["block"] == b] for b in blocks}
    last: dict | None = next((r for r in reversed(rows) if r["status"] == "kept"), None)
    last_t = next((t for t in plan if last and t["pid"] == last["pid"]), None)
    quit_ = False
    t_start = time.monotonic()
    try:
        for bi, b in enumerate(blocks):
            items = [t for t in by_block[b] if t["pid"] not in done]
            if not items:
                continue
            clear()
            print(sty(f"\n  BLOCK {bi + 1} of {len(blocks)}: {b.upper()}   ({len(items)} prompts left)\n", "1;96"))
            for line in BLOCK_INTRO[b]:
                print("   " + line)
            if any(t["pid"] in done for t in by_block[b]):
                print(sty("\n   (resuming where you stopped)", "93"))
            print(sty("\n   Keys:  Enter = record   r = redo last take   s = skip   q = quit (resume later)", "2"))
            print(sty("\n   Press Enter to begin this block (q to stop here).", "1"))
            if getkey(auto) == "q":
                quit_ = True
                break
            video_on = False
            i = 0
            while i < len(items):
                t = items[i]
                if t["cond"] == "video" and not video_on:
                    clear()
                    print(sty("\n   START A VIDEO NOW", "1;93"))
                    print("   on the COMPUTER speakers (not the phone), normal volume, speech or music, about 1 m from the mic.\n"
                          "   Keep it playing for the next 20 whistles. Whistle a bit louder than the video.\n")
                    print(sty("   Press Enter once it is playing.", "1"))
                    if getkey(auto) == "q":
                        quit_ = True
                        break
                    video_on = True
                idx = [x["pid"] for x in by_block[b]].index(t["pid"])
                clear()
                header(t, idx, len(by_block[b]), len(done), len(plan), bi, len(blocks))
                if t["say"]:
                    print(sty("   Say:\n", "2"))
                    big(f"“{t['say']}”")
                else:
                    big(t["text"])
                if fake:
                    print(sty("   [SYNTHETIC fake mic]", "93"))
                print(sty("\n   Enter = record    r = redo last    s = skip    q = quit", "2"))
                k = getkey(auto)
                if k == "q":
                    quit_ = True
                    break
                if k == "s":
                    n_take += 1
                    row = {"take": n_take, "pid": t["pid"], "block": b, "status": "skipped", "run": run,
                           "synthetic": bool(fake), "time": datetime.now().isoformat(timespec="seconds")}
                    labels.write(json.dumps(row) + "\n")
                    labels.flush()
                    done.add(t["pid"])
                    i += 1
                    continue
                redo = False
                if k == "r":
                    if not last_t:
                        continue
                    t, redo = last_t, True
                    clear()
                    header(t, [x["pid"] for x in plan if x["block"] == t["block"]].index(t["pid"]),
                           len([x for x in plan if x["block"] == t["block"]]), len(done), len(plan), bi, len(blocks))
                    print(sty("   REDO of the last take:\n", "1;93"))
                    big(f"“{t['say']}”" if t["say"] else t["text"])
                    print(sty("\n   Press Enter to record it again (s = cancel the redo).", "2"))
                    if getkey(auto) != "\n":
                        continue
                m = take_one(rec, t, fake)
                print(sty("   ■  stop", "1;91") + sty(f"   ({m['stop_reason']})", "2"), flush=True)
                settle(rec)
                ms = lambda s: round(s * 1000 / rec.rate, 1)  # noqa: E731
                clip = rec.audio(m["go"] - int(PRE_S * rec.rate), m["end"])
                n_take += 1
                fname = f"takes/{b}/{t['pid']}_t{n_take:03d}.wav"
                (out / "takes" / b).mkdir(parents=True, exist_ok=True)
                sf.write(str(out / fname), clip, rec.rate, subtype="PCM_16")
                row = {"take": n_take, "pid": t["pid"], "block": b, "kind": t["kind"], "cond": t["cond"], "prompt": t["text"],
                       "say": t["say"], "status": "kept", "redo": redo, "run": run, "file": fname,
                       "key_ms": ms(m["key"]), "go_ms": ms(m["go"]), "end_ms": ms(m["end"]),
                       "clip_offset_ms": ms(m["go"] - int(PRE_S * rec.rate)), "window_ms": [ms(m["go"]) - 100, ms(m["end"])],
                       "heard": m["heard"], "stop_reason": m["stop_reason"], "base_db": m["base_db"],
                       "level": R.level_report(rec.audio(m["go"], m["end"])), "synthetic": bool(fake),
                       "time": datetime.now().isoformat(timespec="seconds"), "note": t.get("note")}
                if b == "phrases":
                    row["expect"] = t["expect"]
                else:
                    evs = rec.events_between(ms(m["go"]) - 100, ms(m["end"]))
                    acts = app_actions(evs)
                    row.update({"expect_sounds": t["expect_sounds"], "expect_now": t["expect_now"],
                                "expect_intent": t["expect_intent"], "events": [slim(e) for e in evs],
                                "sounds": [e["label"] for e in evs], "actions": [x["action"] for x in acts if x["action"] != "none"]})
                    if "run_len" in t:
                        row["run_len"] = t["run_len"]
                labels.write(json.dumps(row, default=float) + "\n")
                labels.flush()
                last, last_t = row, t
                if not m["heard"]:
                    print(sty("   nothing heard: press r to redo it, or go on", "1;93"))
                elif b != "phrases":
                    print(f"   heard: {' '.join(row['sounds']) or '-'}  ->  {', '.join(row['actions']) or 'no action'}")
                if not redo:
                    done.add(t["pid"])
                    i += 1
                if not auto:
                    time.sleep(0.8)
            if quit_:
                if video_on:
                    print(sty("\n   (you can stop the video now)", "93"))
                break
            if video_on:
                clear()
                print(sty("\n   STOP THE VIDEO NOW.", "1;93"))
                print(sty("   Press Enter when it's stopped.", "1"))
                getkey(auto)
            if bi < len(blocks) - 1:
                clear()
                print(sty(f"\n   Block {b.upper()} done. Take a short break (drink some water).", "1;92"))
                print("   Press Enter for the next block, or q to stop here and resume later.")
                if getkey(auto) == "q":
                    quit_ = True
                    break
    except KeyboardInterrupt:
        print("\ninterrupted: everything so far is saved")
    labels.close()
    rec.wait_s(0.3)
    rec.stop()
    meta["runs"][-1].update({"duration_s": round(rec.n / rec.rate, 1), "wall_s": round(time.monotonic() - t_start, 1)})
    meta_p.write_text(json.dumps(meta, indent=1))
    left = [t for t in plan if t["pid"] not in done]
    print(f"\n{len(done)}/{len(plan)} prompts done in {name}" + (" (SYNTHETIC)" if fake else ""))
    if left:
        print(f"resume with the same command:  ./run python guided_session.py --session {name}"
              + (f" --block {' '.join(blocks)}" if a.block else ""))
    print(f"score with:  ./run python guided_session.py --score recordings/{name}")
    print("these recordings are private: they stay in extractor/recordings/ (gitignored); never commit or upload them.")

# ------------------------------------------------------------------------------------ scoring


def load_clips(d: Path) -> list[dict]:
    """The human-reviewed clip set of a session (review_segments.py): one row per kept try, with the clip wav
    (relative to the session), prompt, expected intent / sounds, transcript, source take and times. For training
    and scoring; [] when the session has not been reviewed."""
    f = d / "clips.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def clip_rows(d: Path, kept: list[dict]) -> tuple[list[dict], dict]:
    """--clips: each reviewed take becomes its kept clips (window = the clip's span in the run's session.wav); a
    reviewed take with every segment dropped is left out; a take nobody reviewed stays whole."""
    clips = load_clips(d)
    if not clips:
        raise SystemExit(f"--clips: no {d / 'clips.jsonl'}; run segment_takes.py and review_segments.py first")
    rv = d / "segments_reviewed.jsonl"
    reviewed = {json.loads(l)["take"] for l in rv.read_text().splitlines()
                if l.strip() and json.loads(l)["decision"] != "pending"} if rv.exists() else set()
    by_take: dict[int, list[dict]] = defaultdict(list)
    for c in clips:
        by_take[c["take"]].append(c)
    out, n = [], Counter()
    for r in kept:
        if r["take"] not in reviewed:
            out.append(r)
            n["whole"] += 1
            continue
        for c in by_take.get(r["take"], []):
            out.append({**r, "take_pid": r["pid"], "pid": c["seg"], "window_ms": c["session_ms"],
                        "transcript": c["transcript"], "clip": c["clip"]})
            n["clips"] += 1
        if not by_take.get(r["take"]):
            n["dropped takes"] += 1
    return out, dict(n)


def score(a: argparse.Namespace) -> None:
    d = Path(a.score)
    if not d.exists():
        d = HERE / a.score
    rows = read_rows(d)
    final = {}
    for r in rows:
        final[r["pid"]] = r
    kept = [r for r in final.values() if r["status"] == "kept"]
    if a.clips:
        kept, n = clip_rows(d, kept)
        print(f"--clips: scoring the reviewed clips: {n}")
    meta = json.loads((d / "session.json").read_text())
    synth = meta.get("synthetic")
    print(f"session {d.name}{' (SYNTHETIC)' if synth else ''}: {len(kept)} takes kept, "
          f"{sum(r['status'] == 'skipped' for r in final.values())} skipped")
    from eval_real import wstrong
    variants = a.variants.split(",")
    by_run: dict[str, list[dict]] = defaultdict(list)
    for r in kept:
        if r["block"] != "phrases":
            by_run[r["run"]].append(r)
    res: dict[str, list[dict]] = {v: [] for v in variants}
    for run, rs in sorted(by_run.items()):
        x, sr = R.load_wav(d / run / "session.wav")
        cfg = Config.from_dict(json.loads((d / run / "config.json").read_text()))
        for v in variants:
            if v == "wstrong":
                wstrong.enable()
            else:
                wstrong.disable()
            evs = [e.to_dict() for e in R.run_stream(x, sr, cfg)]
            wstrong.disable()
            for r in rs:
                lo, hi = r["window_ms"]
                w = [e for e in evs if lo <= e["t_start_ms"] < hi]
                ctx = [e for e in evs if lo - 2000 <= e["t_start_ms"] < hi + 2000]
                now = [x_["action"] for x_ in app_actions(ctx) if lo <= x_["t_ms"] < hi and x_["action"] != "none"]
                grd = [x_["action"] for x_ in app_actions(ctx, train_guard=True) if lo <= x_["t_ms"] < hi and x_["action"] != "none"]
                res[v].append({"pid": r["pid"], "block": r["block"], "kind": r["kind"], "cond": r["cond"], "sounds": [e["label"] for e in w],
                               "like": [e.get("sounds_like") for e in w], "now": now, "guard": grd,
                               "ok_now": now == (expected_now(r["expect_sounds"]) if "expect_sounds" in r else r["expect_now"]), "ok_intent_guard": grd == r["expect_intent"], "run_len": r.get("run_len")})
    for v in variants:
        rs = res[v]
        if not rs:
            continue
        print(f"\n== {v} ==  (actions: app default bindings; 'guard' = with the PROPOSED click train guard)")
        print(f"  {'block/class':<24}{'cond':<7}{'takes':>6}{'ok':>5}{'wrong':>7}   heard / actions")
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rs:
            groups[(r["block"], r["kind"], r["cond"])].append(r)
        for (b, k, c), g in groups.items():
            ok = sum(r["ok_now"] for r in g)
            wrong = sum(bool(r["now"]) and not r["ok_now"] for r in g)
            acts = Counter(" ".join(r["now"]) or "-" for r in g).most_common(3)
            extra = ""
            if b == "clicks":
                extra = f"   | with guard: ok {sum(r['ok_intent_guard'] for r in g)}/{len(g)} {Counter(' '.join(r['guard']) or '-' for r in g).most_common(2)}"
            print(f"  {b + '/' + k:<24}{c:<7}{len(g):>6}{ok:>5}{wrong:>7}   {acts}{extra}")
        wh = [r for r in rs if r["block"] == "whistles"]
        if wh:
            for c in ("quiet", "video"):
                g = [r for r in wh if r["cond"] == c]
                if g:
                    print(f"  whistles {c}: right {sum(r['ok_now'] for r in g)}/{len(g)}, "
                          f"wrong action {sum(bool(r['now']) and not r['ok_now'] for r in g)}/{len(g)}")
        runs = [r for r in rs if r["kind"] == "click_run"]
        if runs:
            print(f"  click runs: homes today {sum(r['now'].count('home') for r in runs)}, "
                  f"with the train guard {sum(r['guard'].count('home') for r in runs)}")
        pairs = [r for r in rs if r["kind"] == "click_click"]
        if pairs:
            print(f"  click-click pairs: home today {sum(r['now'] == ['home'] for r in pairs)}/{len(pairs)}, "
                  f"with the train guard {sum(r['guard'] == ['home'] for r in pairs)}/{len(pairs)}")
    ph = [r for r in kept if r["block"] == "phrases"]
    if ph and a.clips:
        print(f"\nphrases: {len(ph)} reviewed clips / whole takes (the phone recognizer scores them: phone_asr.py)")
        by: dict[str, list[dict]] = defaultdict(list)
        for r in ph:
            by[r.get("take_pid", r["pid"])].append(r)
        for pid in sorted(by):
            g = by[pid]
            print(f"  {pid}  {g[0]['kind']:<10} {len(g):>2} clip(s)  {(g[0]['say'] or '[free] ' + g[0]['prompt'])[:48]:<50}"
                  f" -> {' + '.join(g[0]['expect'])}")
            for r in g:
                if "clip" in r:
                    print(f"          {r['clip']:<40} {r['transcript'][:60]}")
    elif ph:
        print(f"\nphrases: {len(ph)} takes (ASR scoring comes later; transcripts are not made here)")
        for r in sorted(ph, key=lambda r: r["pid"]):
            print(f"  {r['pid']}  {r['kind']:<10} {r['file']:<34} {(r['say'] or '[free] ' + r['prompt'])[:52]:<54} -> {' + '.join(r['expect'])}")
    outp = d / ("score_clips.json" if a.clips else "score.json")
    keys = ("pid", "kind", "file", "say", "prompt", "expect", "run", "window_ms", "take_pid", "clip", "transcript")
    outp.write_text(json.dumps({"session": d.name, "synthetic": synth, "clips": bool(a.clips), "variants": res,
                                "phrases": [{k: r[k] for k in keys if k in r} for r in ph]},
                               indent=1, default=float))
    print(f"\nwrote {outp}")

# ------------------------------------------------------------------------------------ main


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", help="folder name under recordings/ (same name = resume)")
    ap.add_argument("--block", nargs="*", choices=BLOCKS, help="only these blocks (default: all three, in order)")
    ap.add_argument("--source", default="auto", choices=["auto", "pw", "sd", "fake"])
    ap.add_argument("--device", help="PipeWire source name (pw) or PortAudio device (sd); default: the default source")
    ap.add_argument("--rate", type=int, default=48000, choices=[16000, 48000])
    ap.add_argument("--config", help="extractor Config JSON (default: as shipped)")
    ap.add_argument("--allow-silent", action="store_true")
    ap.add_argument("--auto", action="store_true", help="no key presses (for --source fake tests)")
    ap.add_argument("--interactive", action="store_true", help="fake source: still read keys")
    ap.add_argument("--fake-speed", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--score", metavar="DIR", help="replay a session through the extractor and score it")
    ap.add_argument("--variants", default="default,wstrong", help="--score: default and/or wstrong (eval_real/wstrong.py)")
    ap.add_argument("--clips", action="store_true", help="--score: use the human-reviewed clips (clips.jsonl) "
                    "instead of whole takes; writes score_clips.json")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    if a.list_devices:
        return R.list_devices()
    if a.score:
        return score(a)
    run_session(a)


if __name__ == "__main__":
    main()
