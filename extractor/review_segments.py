#!/usr/bin/env python3
"""Fast human review of the segments proposed by segment_takes.py: keep / drop / fix each try.

  ./run python review_segments.py --session recordings/khoa-guided-1               # review (resumes)
  ./run python review_segments.py --session recordings/khoa-guided-1 --summary     # counts only, no review
  ./run python review_segments.py --session recordings/khoa-guided-1 --export      # rewrite the clip set only

Order: every unsure / flub segment first (by prompt), then the likely-good ones grouped per prompt, where one key
accepts all the likely-good tries of that prompt at once. Each segment plays on show.

Keys (single key, no Enter):
  k  keep            d  drop            e  edit the transcript (then keep)
  a  keep all remaining likely-good segments of this prompt (whistles / clicks: of this class + condition;
     only in the likely-good pass)
  space  replay      b  back one        s  skip for now          q  quit (resume later: same command)

Files (PRIVATE, all under the session folder, gitignored; labels.jsonl and the take wavs are never touched):
  segments.jsonl            append-only decision log, one self-contained line per decision (the last line per
                            segment wins; a decision whose start/end no longer match the proposal is ignored)
  segments_reviewed.jsonl   the current state of every proposed segment (keep / drop / pending), rewritten
  clips/<block>/<seg>.wav   the kept segments cut out of the takes (derived; rewritten)
  clips.jsonl               the clip manifest for scoring and training: prompt, expected intent, transcript, source
                            take and times; read by guided_session.py --score --clips
Playback: the first of aplay / pw-play / paplay on PATH, through the default output.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
TTY = sys.stdout.isatty()
FLAG_ORDER = {"flub": 0, "unsure": 0, "good": 1}


def sty(s: str, code: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if TTY else s


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def session_dir(s: str) -> Path:
    d = Path(s)
    if not d.is_absolute() and not d.exists():
        d = HERE / s
    return d.resolve()

# ------------------------------------------------------------------------------------ state


def load(sess: Path) -> tuple[list[dict], dict[str, dict], int]:
    """proposals, the current decision per segment id, and the number of stale decisions ignored."""
    props = read_jsonl(sess / "segments_auto.jsonl")
    if not props:
        raise SystemExit(f"no {sess / 'segments_auto.jsonl'}: run segment_takes.py first")
    pmap = {p["seg"]: p for p in props}
    dec: dict[str, dict] = {}
    for d in read_jsonl(sess / "segments.jsonl"):
        dec[d["seg"]] = d
    stale = 0
    for k in list(dec):
        p = pmap.get(k)
        if p is None or (p["start_ms"], p["end_ms"], p["file"]) != (dec[k]["start_ms"], dec[k]["end_ms"], dec[k]["file"]):
            stale += 1
            del dec[k]
    return props, dec, stale


def order(props: list[dict]) -> list[dict]:
    """phrases first, then whistles / clicks; in each, unsure / flub first, then likely-good grouped per prompt."""
    return sorted(props, key=lambda p: (p["block"] != "phrases", FLAG_ORDER.get(p["flag"], 0), group_key(p), p["take"],
                                        p["start_ms"]))


def group_key(p: dict) -> tuple:
    """what 'a' (keep all likely-good) covers: one prompt for phrases; one class + condition for whistles / clicks."""
    return (p["block"], p["pid"]) if p["block"] == "phrases" else (p["block"], p["kind"], p.get("cond") or "")


def decision_row(p: dict, decision: str, transcript: str, bulk: bool = False) -> dict:
    return {"seg": p["seg"], "decision": decision, "transcript": transcript,
            "edited": transcript != p["transcript"], "auto_transcript": p["transcript"], "auto_flag": p["flag"],
            "bulk": bulk, "block": p["block"], "pid": p["pid"], "take": p["take"], "file": p["file"],
            "start_ms": p["start_ms"], "end_ms": p["end_ms"], "time": datetime.now().isoformat(timespec="seconds")}


def write_reviewed(sess: Path, props: list[dict], dec: dict[str, dict]) -> Path:
    out = sess / "segments_reviewed.jsonl"
    rows = []
    for p in sorted(props, key=lambda p: (p["block"], p["pid"], p["take"], p["start_ms"])):
        d = dec.get(p["seg"])
        rows.append({**{k: v for k, v in p.items() if k not in ("words", "tokens")},
                     "decision": d["decision"] if d else "pending",
                     "transcript": d["transcript"] if d else p["transcript"],
                     "auto_transcript": p["transcript"], "edited": bool(d and d["edited"]),
                     "decided": d["time"] if d else None})
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return out


def export_clips(sess: Path, props: list[dict], dec: dict[str, dict]) -> tuple[Path, int]:
    """cut every kept segment out of its take into clips/<block>/<seg>.wav and write clips.jsonl."""
    meta = json.loads((sess / "session.json").read_text()) if (sess / "session.json").exists() else {}
    labels = {}
    for r in read_jsonl(sess / "labels.jsonl"):
        labels[r["pid"]] = r
    kept = [p for p in props if dec.get(p["seg"], {}).get("decision") == "keep"]
    root = sess / "clips"
    want = {root / p["block"] / f"{p['seg']}.wav" for p in kept}
    if root.exists():                       # the clip set is derived: drop clips that are no longer kept
        for f in root.rglob("*.wav"):
            if f not in want:
                f.unlink()
    cache: dict[str, tuple[np.ndarray, int]] = {}
    rows = []
    for p in sorted(kept, key=lambda p: (p["block"], p["pid"], p["take"], p["start_ms"])):
        if p["file"] not in cache:
            cache[p["file"]] = sf.read(str(sess / p["file"]), dtype="int16")
        x, sr = cache[p["file"]]
        a, b = int(p["start_ms"] * sr / 1000), int(p["end_ms"] * sr / 1000)
        out = root / p["block"] / f"{p['seg']}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), x[a:b], sr, subtype="PCM_16")
        lab = labels.get(p["pid"], {})
        d = dec[p["seg"]]
        rows.append({"clip": str(out.relative_to(sess)), "seg": p["seg"], "block": p["block"], "pid": p["pid"],
                     "kind": p["kind"], "cond": p.get("cond"), "prompt": p["prompt"], "say": p.get("say"),
                     "expect": p.get("expect"), "expect_intent": p.get("expect_intent"),
                     "expect_sounds": p.get("expect_sounds"), "expect_now": lab.get("expect_now"),
                     "run_len": lab.get("run_len"), "transcript": d["transcript"],
                     "auto_transcript": p["transcript"], "edited": d["edited"], "auto_flag": p["flag"],
                     "src": p["file"], "take": p["take"], "run": lab.get("run"), "start_ms": p["start_ms"],
                     "end_ms": p["end_ms"], "session_ms": [round(lab.get("clip_offset_ms", 0) + p["start_ms"], 1),
                                                          round(lab.get("clip_offset_ms", 0) + p["end_ms"], 1)],
                     "cut_off": p.get("cut_off"), "runs_to_end": p.get("runs_to_end"), "rate": sr,
                     "synthetic": bool(meta.get("synthetic"))})
    mf = sess / "clips.jsonl"
    mf.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return mf, len(rows)

# ------------------------------------------------------------------------------------ playback + keys


def find_player() -> list[str] | None:
    for name, args in (("aplay", ["-q"]), ("pw-play", []), ("paplay", [])):
        p = shutil.which(name)
        if p:
            return [p, *args]
    return None


class Player:
    def __init__(self, sess: Path, enabled: bool):
        self.cmd = find_player() if enabled else None
        self.proc: subprocess.Popen | None = None
        # the temporary clip stays inside the private session folder, and is removed on exit
        self.tmp = Path(tempfile.mkdtemp(prefix=".review-", dir=sess))
        self.cache: dict[str, tuple[np.ndarray, int]] = {}
        self.sess = sess

    def play(self, p: dict) -> None:
        self.stop()
        if not self.cmd:
            return
        if p["file"] not in self.cache:
            self.cache[p["file"]] = sf.read(str(self.sess / p["file"]), dtype="int16")
        x, sr = self.cache[p["file"]]
        a, b = int(p["start_ms"] * sr / 1000), int(p["end_ms"] * sr / 1000)
        f = self.tmp / "seg.wav"
        sf.write(str(f), x[a:b], sr, subtype="PCM_16")
        self.proc = subprocess.Popen([*self.cmd, str(f)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def close(self) -> None:
        self.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


KEYS = "kdeabsq "


def getkey() -> str:
    if sys.stdin.isatty():
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            termios.tcflush(fd, termios.TCIFLUSH)
            while True:
                ch = sys.stdin.read(1)
                if ch.lower() in KEYS:
                    return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    line = sys.stdin.readline()           # not a terminal (tests): one key per line; empty line = replay
    if not line:
        return "q"
    ch = line.rstrip("\n")[:1].lower()
    return ch if ch in KEYS else " "


def edit_line(text: str) -> str:
    """read one line with the current transcript pre-filled (readline when there is one)."""
    try:
        import readline
        readline.set_startup_hook(lambda: readline.insert_text(text))
        try:
            s = input("   transcript> ")
        finally:
            readline.set_startup_hook(None)
    except ImportError:
        print(f"   (current: {text})")
        s = input("   transcript> ") or text
    except EOFError:
        return text
    return s.strip()

# ------------------------------------------------------------------------------------ screen


def show(p: dict, i: int, n: int, dec: dict[str, dict], counts: Counter, pass_name: str, group: list[dict],
         player_ok: bool) -> None:
    if TTY:
        print("\x1b[2J\x1b[H", end="")
    else:
        print("\n" + "-" * 70)
    done = sum(1 for _ in dec)
    print(sty(f" {pass_name}   segment {i + 1}/{n}   decided {done}   kept {counts['keep']}  dropped {counts['drop']}",
              "1;96"))
    print()
    if p["block"] == "phrases":
        say = p.get("say")
        print("   " + sty("prompt  ", "2") + sty(f"“{say}”" if say else f"[free] {p['prompt']}", "1;97"))
        print("   " + sty("expect  ", "2") + " + ".join(p.get("expect") or []) + sty(f"    ({p['pid']}, {p['kind']})", "2"))
    else:
        print("   " + sty("prompt  ", "2") + sty(p["prompt"], "1;97"))
        print("   " + sty("expect  ", "2") + " ".join(p.get("expect_sounds") or []) + "  ->  "
              + " ".join(p.get("expect_intent") or []) + sty(f"    ({p['pid']}, {p['cond']})", "2"))
        if p.get("sounds") is not None:
            print("   " + sty("heard   ", "2") + (" ".join(p["sounds"]) or "-") + sty("   (extractor, live)", "2"))
    if p.get("note"):
        print("   " + sty("note    ", "2") + p["note"])
    print()
    col = {"good": "92", "unsure": "93", "flub": "91"}.get(p["flag"], "0")
    stem = Path(p["file"]).name
    print("   " + sty(f"[{p['flag'].upper()}]", "1;" + col) +
          sty(f"  {stem}  {p['start_ms'] / 1000:.2f}-{p['end_ms'] / 1000:.2f} s"
              f"  (take {p.get('take_dur_ms', 0) / 1000:.1f} s, {p.get('stop_reason')})", "2"))
    tr = dec[p["seg"]]["transcript"] if p["seg"] in dec else p["transcript"]
    print("\n   " + sty(tr or "(no words recognised)", "1"))
    if p.get("cut_off"):
        print("   " + sty("CUT OFF: still sounding when the take hit its max length", "91"))
    for r in p.get("reasons", []):
        print("   " + sty("· " + r, "2"))
    if p.get("dropped_words"):
        print("   " + sty("· Whisper words on silence, dropped: " + " ".join(p["dropped_words"]), "2"))
    if p["seg"] in dec:
        d = dec[p["seg"]]
        print("\n   " + sty(f"decided: {d['decision'].upper()}" + (" (edited)" if d["edited"] else ""), "1;95"))
    if group:
        what = p["pid"] if p["block"] == "phrases" else f"{p['kind']} / {p.get('cond')}"
        print(sty(f"\n   likely-good tries of {what} still to decide ({len(group)}):", "2"))
        for g in group[:8]:
            print(sty(f"     {'>' if g is p else ' '} {g['transcript'][:66] or g['seg']}", "2"))
    print()
    bulk = "   a = keep ALL of this prompt's likely-good" if group else ""
    print(sty("   k keep   d drop   e edit   space replay   b back   s skip   q quit" + bulk, "2"))
    if not player_ok:
        print(sty("   (no playback: no aplay / pw-play / paplay, or --no-play)", "93"))

# ------------------------------------------------------------------------------------ main loop


def review(sess: Path, a: argparse.Namespace) -> None:
    props, dec, stale = load(sess)
    if a.block:
        props = [p for p in props if p["block"] in a.block]
    q = order(props)
    if not q:
        raise SystemExit("no segments to review")
    log = (sess / "segments.jsonl").open("a")
    player = Player(sess, not a.no_play)
    if stale:
        print(sty(f"{stale} earlier decisions no longer match a proposal (segments were regenerated): ignored", "93"))
    counts = Counter(d["decision"] for d in dec.values())

    def record(p: dict, decision: str, transcript: str, bulk: bool = False) -> None:
        row = decision_row(p, decision, transcript, bulk)
        log.write(json.dumps(row) + "\n")
        log.flush()
        old = dec.get(p["seg"])
        if old:
            counts[old["decision"]] -= 1
        dec[p["seg"]] = row
        counts[decision] += 1

    skipped: set[str] = set()

    def next_open(i: int) -> int | None:
        for j in list(range(i + 1, len(q))) + list(range(0, i + 1)):
            if q[j]["seg"] not in dec and q[j]["seg"] not in skipped:
                return j
        return None

    i = next_open(-1)
    if i is None:
        print("every segment has a decision. Re-open one with --redo PID, or export with --export.")
        i = 0 if a.redo else None
    if a.redo:
        i = next((j for j, p in enumerate(q) if p["pid"] == a.redo or p["seg"] == a.redo), i)
    history: list[int] = []
    try:
        while i is not None:
            p = q[i]
            good_pass = p["flag"] == "good"
            group = [g for g in q if group_key(g) == group_key(p) and g["flag"] == "good" and
                     (g["seg"] not in dec or g is p)] if good_pass else []
            show(p, i, len(q), dec, counts, "LIKELY-GOOD pass (per prompt)" if good_pass else "UNSURE / FLUB pass",
                 group, bool(player.cmd))
            player.play(p)
            k = getkey()
            if k == " ":
                continue
            if k == "q":
                break
            if k == "b":
                if history:
                    i = history.pop()
                elif i > 0:
                    i -= 1
                continue
            if k == "s":                   # skipped segments stay pending until the next run
                skipped.add(p["seg"])
                history.append(i)
                i = next_open(i)
                continue
            if k == "a":
                if not group:
                    continue
                for g in group:
                    if g["seg"] not in dec or g is p:
                        record(g, "keep", dec[g["seg"]]["transcript"] if g["seg"] in dec else g["transcript"], bulk=True)
            elif k == "e":
                player.stop()
                cur = dec[p["seg"]]["transcript"] if p["seg"] in dec else p["transcript"]
                record(p, "keep", edit_line(cur))
            elif k in ("k", "d"):
                cur = dec[p["seg"]]["transcript"] if p["seg"] in dec else p["transcript"]
                record(p, "keep" if k == "k" else "drop", cur)
            history.append(i)
            i = next_open(i)
    except KeyboardInterrupt:
        print()
    finally:
        player.close()
        log.close()
    rv = write_reviewed(sess, props if not a.block else read_jsonl(sess / "segments_auto.jsonl"), dec)
    allp, alld, _ = load(sess)
    mf, n = export_clips(sess, allp, alld)
    pend = sum(1 for p in allp if p["seg"] not in alld)
    print(f"\nkept {sum(d['decision'] == 'keep' for d in alld.values())}, dropped "
          f"{sum(d['decision'] == 'drop' for d in alld.values())}, pending {pend}")
    print(f"wrote {rv.name}, {mf.name} ({n} clips in clips/)" + ("" if not pend else
          f"\nresume with:  ./run python review_segments.py --session {a.session}"))


def summary(sess: Path) -> None:
    props, dec, stale = load(sess)
    by = defaultdict(list)
    for p in props:
        by[(p["block"], p["pid"])].append(p)
    print(f"{len(props)} segments, {len(dec)} decided ({stale} stale decisions ignored)")
    print(f"  {'block':<9}{'pid':<24}{'segs':>5}{'good':>5}{'unsu':>5}{'flub':>5}{'cut':>5}{'kept':>6}{'drop':>6}")
    for (b, pid), g in sorted(by.items()):
        c = Counter(p["flag"] for p in g)
        d = Counter(dec[p["seg"]]["decision"] for p in g if p["seg"] in dec)
        print(f"  {b:<9}{pid:<24}{len(g):>5}{c['good']:>5}{c['unsure']:>5}{c['flub']:>5}"
              f"{sum(bool(p.get('cut_off')) for p in g):>5}{d['keep']:>6}{d['drop']:>6}")
    tot = Counter(p["flag"] for p in props)
    print(f"  total: {dict(tot)}; cut off {sum(bool(p.get('cut_off')) for p in props)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True)
    ap.add_argument("--block", nargs="*", choices=["phrases", "whistles", "clicks"], help="only these blocks")
    ap.add_argument("--no-play", action="store_true", help="do not play audio")
    ap.add_argument("--redo", metavar="PID|SEG", help="start at this prompt / segment even if decided")
    ap.add_argument("--summary", action="store_true", help="print counts and exit")
    ap.add_argument("--export", action="store_true", help="only rewrite segments_reviewed.jsonl + clips, then exit")
    a = ap.parse_args()
    sess = session_dir(a.session)
    if a.summary:
        return summary(sess)
    if a.export:
        props, dec, _ = load(sess)
        write_reviewed(sess, props, dec)
        mf, n = export_clips(sess, props, dec)
        print(f"wrote {mf} ({n} clips)")
        return
    review(sess, a)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
