#!/usr/bin/env python3
"""Split guided-session takes into single tries, transcribe them locally and auto-flag them for review.

Why: in a guided session the user often says a prompt several times in one take (variations are the point), flubs
some tries, and many phrase takes hit the max length, so the last try is cut off. The recorder assumes one
utterance per take, so its labels are wrong for training / eval as they stand. This makes a PROPOSAL per try;
review_segments.py is where the human decides.

  ./run python segment_takes.py --session recordings/khoa-guided-1            # phrases: ASR + segments + flags
  ./run python segment_takes.py --session recordings/khoa-guided-1 --sounds   # also whistles / clicks: counts + segments
  ./run python review_segments.py --session recordings/khoa-guided-1          # then review

Phrases:
  1. ASR: faster-whisper (default medium.en, int8, CPU) with word timestamps, run in the separate venv .venv-asr
     (asr_transcribe.py; no torch, nothing leaves the machine). Cached in <session>/asr/<model>.jsonl.
  2. Pauses come from the audio energy (100 Hz high-pass, 10 ms frames, floor + 8 dB), NOT from Whisper's word gaps
     (Whisper stretches words over silences: "Open YouTube. Open YouTube." has no word gap but a 0.8 s pause).
     Each pause >= 0.15 s is a candidate cut between the words on either side of it.
  3. Cuts are chosen by a small DP against the prompt's script: every piece should look like one reading of the
     script (weighted word edit distance, fillers / cut-off words cheap), a cut in a short pause costs a little,
     a pause >= 1.5 s is always a cut. Free-form prompts (no script) cut at pauses >= 0.9 s, or >= 0.6 s after
     a sentence end. So "Um, so, can you, like, [0.7 s] uh, scroll down a bit" stays one piece.
  4. Each piece is transcribed again ON ITS OWN (pass 2): Whisper on a whole take of repeats sometimes folds two tries
     into one or invents one. The whole-take words stay the transcript when both passes agree; a disagreement
     makes the piece "unsure" and shows both; a sound pass 1 had no words for takes pass 2's words.
  5. Flags (generous with "unsure"; a human decides):
       good    looks like one full reading (or, free-form, carries the expected intent); fillers and small
               variations are allowed
       flub    cut off (still sounding in the last 0.1 s of a max-length take, or ends in a cut-off word), partial (misses the
               intent words), restart / "wait" / "sorry" / laughing not in the script, no words heard
       unsure  everything else: off-script wording, low ASR confidence, possible Whisper hallucination, a piece
               that may hold two tries, a very long piece, a piece that ends just before the max length
Whistles / clicks (--sounds): the same energy pauses group the take into bursts; a burst group separated by >= 0.6 s
is one attempt. Reports how many takes hold more than one attempt and which hit max length, and writes their
segments too (no transcript; the extractor events of the take are in labels.jsonl).

Output (PRIVATE, under the session folder, gitignored):
  asr/<model>.jsonl        raw word-timestamped transcripts
  segments_auto.jsonl      one proposal per segment (rewritten on each run; ids are stable: <take stem>_sNN)
The review log (segments.jsonl), the reviewed list and the clips are written by review_segments.py only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts"
ASR_PY = HERE / ".venv-asr" / "bin" / "python"
DEFAULT_MODEL = "medium.en"
ASR_PROMPT = "neutral"     # asr_transcribe.PROMPTS: disfluency style + names, no command words

FRAME_S = 0.01
THR_DB = 8.0              # voiced = frame energy above the floor + this
BRIDGE_S = 0.12           # voiced gaps shorter than this are closures inside a word, not pauses
MIN_PAUSE_S = 0.15        # shortest pause that can be a cut (some repeats come back-to-back)
FORCE_CUT_S = 1.5         # a pause this long is always a cut
FREE_CUT_S, FREE_SENT_CUT_S = 0.9, 0.6
PAD_PRE_S, PAD_POST_S = 0.10, 0.15
END_TOL_S = 0.6           # voiced this close to the end of a max-length take = runs to the end (check by ear)
CUT_TOL_S = 0.1           # still voiced in the last 0.1 s of a max-length take = cut off
KEY_S = 0.8               # the key press sits at ~0.4 s (GO is at 1.0 s): voiced audio before this is not speech
PARTIAL_COST = 0.5        # a piece that is only the start of the script (a cut-off / abandoned try)
SOUND_GROUP_S = 0.6       # whistles / clicks: bursts closer than this are one attempt (tries come ~0.9 s apart)

FILLERS = {"um", "uh", "er", "erm", "ah", "hmm", "mm", "hm", "oh", "like", "so", "okay", "ok", "yeah", "well",
           "just", "please", "hey", "canti", "and", "the", "a", "maybe", "can", "you", "could", "for", "me", "thanks"}
FLUB_WORDS = {"wait", "sorry", "oops", "no", "actually", "again", "haha", "ha", "laughs", "laughter", "laughing",
              "damn", "shit", "fuck", "whoops", "hold", "restart", "redo"}
HALLUCINATIONS = [("thanks", "for", "watching"), ("thank", "you", "for", "watching"), ("please", "subscribe"),
                  ("subscribe",), ("thank", "you"), ("you",), ("bye",)]

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
       "seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def num_words(n: int) -> list[str]:
    if n < 20:
        return [ONES[n]]
    if n < 100:
        return [TENS[n // 10]] + ([ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        return [ONES[n // 100], "hundred"] + (num_words(n % 100) if n % 100 else [])
    return [str(n)]


def tokens(text: str) -> list[str]:
    """lower-case words; digits -> number words; a trailing '-' (cut-off word) is kept; other punctuation dropped."""
    out: list[str] = []
    text = text.replace("…", " ").replace("—", " - ").replace("–", " - ")
    for raw in re.split(r"[\s,.;:!?\"()\[\]]+", text.lower()):
        if not raw:
            continue
        cut = raw.endswith("-") and len(raw) > 1
        w = raw.strip("-'")
        if not w:
            if raw == "-" and out and not out[-1].endswith("-"):
                out[-1] += "-"            # Whisper writes a cut-off as "fif -"
            continue
        parts = re.split(r"-", w)
        for i, p in enumerate(parts):
            if not p:
                continue
            if p.isdigit():
                out += num_words(int(p))
            else:
                out.append(p)
        if cut and out:
            out[-1] += "-"
    return out


def base(t: str) -> str:
    return t.rstrip("-")

# ------------------------------------------------------------------------------------ intent keys


NAV_KEYS = {"scroll down": [{"scroll", "swipe"}, {"down"}], "scroll up": [{"scroll", "swipe"}, {"up"}],
            "go back": [{"back", "previous", "last"}], "go home": [{"home"}], "next": [{"next", "skip"}],
            "pause": [{"pause", "stop"}], "volume down": [{"down", "lower", "quieter"}],
            "volume up": [{"up", "louder"}], "play": [{"play"}]}


def intent_keys(expect: list[str], say: str | None) -> list[set[str]]:
    """Word sets the piece must contain (one word of each set) to carry the expected intent."""
    keys: list[set[str]] = []
    for e in expect:
        m = re.match(r"(\w+)\((.*)\)", e)
        if not m:
            continue
        kind, arg = m.group(1), m.group(2)
        if kind == "OpenApp":
            keys.append({arg.lower().replace(" ", "")})
        elif kind == "Nav":
            keys += NAV_KEYS.get(arg, [set(tokens(arg))])
        elif kind == "Tap":
            keys.append(set(tokens(arg)))
        elif kind == "Timer":
            keys.append({"timer"})
            if say:   # the script's own number words (the last clause wins in a correction)
                st = tokens(say.split(" no,")[-1] if " no," in say else say)
                nums = [t for t in st if t in ONES + TENS + ["hour", "half", "hundred"]]
                if nums:
                    keys.append({nums[-1]})
            else:
                sec = int(arg)
                keys.append(set(num_words(sec // 60)) if sec % 60 == 0 and sec < 6000 else {"minute", "minutes"})
    return keys


def has_keys(toks: list[str], keys: list[set[str]]) -> list[str]:
    bs = {base(t) for t in toks if not t.endswith("-")}
    return ["/".join(sorted(k)) for k in keys if not (k & bs)]

# ------------------------------------------------------------------------------------ distance to the script


def tok_cost(t: str) -> float:
    return 0.3 if (t in FILLERS or t.endswith("-")) else 1.0


def edit(a: list[str], b: list[str], prefixes: bool = False):
    """weighted word edit distance: fillers and cut-off words are cheap to insert / delete.
    prefixes=True: also the distance of a to every proper prefix of b (list, index k = b[:k])."""
    n, m = len(a), len(b)
    d = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        d[i, 0] = d[i - 1, 0] + tok_cost(a[i - 1])
    for j in range(1, m + 1):
        d[0, j] = d[0, j - 1] + tok_cost(b[j - 1])
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            x, y = a[i - 1], b[j - 1]
            sub = 0.0 if x == y else (0.3 if base(x) == base(y) or (x.endswith("-") and base(y).startswith(base(x)))
                                      or (y.endswith("-") and base(x).startswith(base(y))) else 1.0)
            d[i, j] = min(d[i - 1, j] + tok_cost(x), d[i, j - 1] + tok_cost(y), d[i - 1, j - 1] + sub)
    return (float(d[n, m]), [float(v) for v in d[n, :m]]) if prefixes else float(d[n, m])


def piece_cost(seg: list[str], script: list[str]) -> float:
    """how far a piece is from ONE reading of the script; a piece that is only the start of the script (an
    abandoned or cut-off try) is cheap, so it is not glued onto the try before it."""
    full, pre = edit(seg, script, prefixes=True)
    return min(full, min(pre[1:], default=full) + PARTIAL_COST)


def script_len(s: list[str]) -> float:
    return max(1.0, sum(tok_cost(t) for t in s))

# ------------------------------------------------------------------------------------ energy


def energy(path: Path) -> tuple[np.ndarray, float, float]:
    x, sr = sf.read(str(path), dtype="float64", always_2d=True)
    x = x.mean(axis=1)
    y = sosfilt(butter(4, 100, "hp", fs=sr, output="sos"), x)
    hop = int(sr * FRAME_S)
    n = len(y) // hop
    db = 10 * np.log10(np.mean(y[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    return db, float(np.percentile(db, 10)), len(x) / sr


def voiced_regions(db: np.ndarray, floor: float) -> list[tuple[float, float]]:
    on = db > floor + THR_DB
    regs: list[list[float]] = []
    i = 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            s, e = i * FRAME_S, j * FRAME_S
            if regs and s - regs[-1][1] < BRIDGE_S:
                regs[-1][1] = e
            else:
                regs.append([s, e])
            i = j
        else:
            i += 1
    return [(s, e) for s, e in regs if e - s >= 0.04]


def pauses_of(regs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(regs[i][1], regs[i + 1][0]) for i in range(len(regs) - 1) if regs[i + 1][0] - regs[i][1] >= MIN_PAUSE_S]


def overlap(a0: float, a1: float, regs: list[tuple[float, float]], tol: float = 0.05) -> float:
    return sum(max(0.0, min(a1 + tol, e) - max(a0 - tol, s)) for s, e in regs)

# ------------------------------------------------------------------------------------ one phrase take


def clean_words(words: list[dict], regs: list[tuple[float, float]]) -> tuple[list[dict], list[dict], bool]:
    """drop words with no voiced audio under them (Whisper hallucinations in silence) and a trailing stock phrase
    ("Thanks for watching!") that Whisper adds at a cut-off end. Returns kept, dropped, suspicious."""
    kept, dropped = [], []
    for w in words:
        (kept if overlap(w["s"], w["e"], regs) > 0.03 else dropped).append(w)
    sus = False
    toks = [tuple(tokens(w["w"])) for w in kept]
    for ph in HALLUCINATIONS:
        k = len(ph)
        if len(kept) > k and tuple(t for tt in toks[-k:] for t in tt) == ph:
            tail = kept[-k:]
            # only a tail that Whisper is unsure of, or that sits at the very end of the file
            if np.mean([w["p"] for w in tail]) < 0.6 or ph in HALLUCINATIONS[:4]:
                dropped += tail
                kept = kept[:-k]
                sus = True
                break
    return kept, dropped, sus


def cut_points(words: list[dict], pauses: list[tuple[float, float]]) -> dict[int, float]:
    """word index k (cut before words[k]) -> the longest energy pause that falls between words k-1 and k."""
    mids = [(w["s"] + w["e"]) / 2 for w in words]
    cuts: dict[int, float] = {}
    for ps, pe in pauses:
        c = (ps + pe) / 2
        k = sum(m < c for m in mids)
        if 0 < k < len(words):
            cuts[k] = max(cuts.get(k, 0.0), pe - ps)
    return cuts


def choose_cuts(wt: list[list[str]], cuts: dict[int, float], script: list[str] | None,
                ends_sentence: list[bool]) -> list[int]:
    n = len(wt)
    if not n:
        return []
    if script is None:
        return sorted(k for k, g in cuts.items() if g >= FREE_CUT_S or (g >= FREE_SENT_CUT_S and ends_sentence[k - 1]))
    forced = {k for k, g in cuts.items() if g >= FORCE_CUT_S}

    def lam(g: float) -> float:
        return max(0.0, 0.6 - g) * 2.0

    L = script_len(script)
    best = [float("inf")] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    pos = [0] + sorted(cuts) + [n]
    for bi, j in enumerate(pos[1:], 1):
        for ai in range(bi - 1, -1, -1):
            i = pos[ai]
            seg = [t for ws in wt[i:j] for t in ws]
            c = best[i] + piece_cost(seg, script) / L + (lam(cuts[i]) if i in cuts else 0.0)
            if c < best[j]:
                best[j], back[j] = c, i
            if i in forced:
                break              # a piece cannot span a forced cut
    out, j = [], n
    while j > 0:
        j = back[j]
        if j > 0:
            out.append(j)
    return sorted(out)


def flag_piece(toks: list[str], script: list[str] | None, keys: list[set[str]], expect: list[str], kind: str,
               probs: list[float], cut_off: bool, sus: bool, dur: float, pwords: list[str], near_end: bool) -> tuple[str, list[str], float | None]:
    reasons: list[str] = []
    flub = unsure = False
    if not toks:
        return "flub", ["no words recognised (noise, breath or a mumble)"], None
    if cut_off:
        flub = True
        reasons.append("cut off: still sounding when the take hit its max length")
    elif near_end:
        unsure = True
        reasons.append("ends just before the max length: check the last word by ear")
    if toks[-1].endswith("-"):
        flub = True
        reasons.append("ends in a cut-off word")
    miss = has_keys(toks, keys)
    if miss:
        flub = True
        reasons.append("missing intent word(s): " + ", ".join(miss))
    stoks = set(script or [])
    extra_flub = sorted({base(t) for t in toks} & FLUB_WORDS - {base(t) for t in stoks})
    if extra_flub:
        flub = True
        reasons.append("restart / flub word(s) not in the script: " + ", ".join(extra_flub))
    dist = None
    if script is not None:
        dist = round(edit(toks, script) / script_len(script), 2)
        if dist > 0.34:
            unsure = True
            reasons.append(f"differs from the script (distance {dist})")
        if len(toks) >= 1.7 * len(script) and len(script) >= 2:
            unsure = True
            reasons.append("long: may hold two tries")
        heads = [t for t in toks if t.endswith("-")]
        if heads and not any(t.endswith("-") for t in script):
            unsure = True
            reasons.append("contains a cut-off word: " + " ".join(heads))
    else:
        if dur > 5.0:
            unsure = True
            reasons.append("long free-form piece: may hold two tries")
        if expect == ["NONE"] and len(toks) < 2:
            unsure = True
            reasons.append("very short")
    if probs and float(np.mean(probs)) < 0.6:
        unsure = True
        reasons.append(f"low ASR confidence ({np.mean(probs):.2f})")
    low = [(w, p) for w, p in zip(pwords, probs) if p < 0.25 and not set(tokens(w)) <= FILLERS]
    if low:
        unsure = True
        reasons.append("unsure ASR word(s): " + ", ".join(f"{w} {p:.2f}" for w, p in low))
    if sus:
        unsure = True
        reasons.append("Whisper added a stock phrase at the end (dropped); check the ending by ear")
    return ("flub" if flub else "unsure" if unsure else "good"), reasons, dist


def piece_row(row: dict, prompt: dict, seg: str, start: float, end: float, v1: float, dur: float,
              words: list[dict], **extra) -> dict:
    maxlen = row.get("stop_reason") == "max length"
    return {"seg": seg, "block": "phrases", "pid": row["pid"], "take": row["take"], "file": row["file"],
            "start_ms": round(start * 1000), "end_ms": round(end * 1000), "dur_ms": round((end - start) * 1000),
            "pass1_transcript": " ".join(w["w"] for w in words),
            "pass1_words": [{**w, "s": round(w["s"] - start, 3), "e": round(w["e"] - start, 3)} for w in words],
            "runs_to_end": bool(v1 >= dur - END_TOL_S), "stop_reason": row.get("stop_reason"),
            "cut_off": bool(maxlen and v1 >= dur - CUT_TOL_S), "voiced_end_ms": round(v1 * 1000),
            "take_dur_ms": round(dur * 1000), "kind": row["kind"], "cond": row.get("cond"), "prompt": row["prompt"],
            "say": row.get("say"), "expect": row["expect"], "expect_intent": row["expect"], "expect_sounds": None,
            "note": prompt.get("note"), **extra}


def segment_phrase_take(row: dict, asr: dict, sess: Path, prompt: dict) -> list[dict]:
    """PASS 1: cut one take into pieces (energy pauses + whole-take word timestamps + the DP against the script).
    Flags come later (flag_pieces), from a second ASR pass over each piece on its own."""
    wav = sess / row["file"]
    db, floor, dur = energy(wav)
    regs = voiced_regions(db, floor)
    pauses = pauses_of(regs)
    words, dropped, sus = clean_words(asr["words"], regs)
    sregs = [r for r in regs if r[1] > KEY_S]
    script = tokens(row["say"]) if row.get("say") else None
    wt = [tokens(w["w"]) for w in words]
    ends_sentence = [bool(re.search(r"[.?!]$", w["w"])) for w in words]
    cuts = cut_points(words, pauses)
    ks = choose_cuts(wt, cuts, script, ends_sentence)
    bounds = [0] + ks + [len(words)]
    stem = Path(row["file"]).stem
    out = []
    groups = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] > bounds[i]]
    # the time window of each piece: from the middle of the pause before it to the middle of the pause after it
    win = []
    for gi, (i, j) in enumerate(groups):
        lo = 0.0 if gi == 0 else (words[i - 1]["e"] + words[i]["s"]) / 2
        hi = dur if gi == len(groups) - 1 else (words[j - 1]["e"] + words[j]["s"]) / 2
        # snap the window edges to the middle of the energy pause that made the cut
        for ps, pe in pauses:
            c = (ps + pe) / 2
            if gi > 0 and abs(c - lo) < 0.6 and words[i - 1]["s"] < c < words[i]["e"]:
                lo = c
            if gi < len(groups) - 1 and abs(c - hi) < 0.6 and words[j - 1]["s"] < c < words[j]["e"]:
                hi = c
        win.append((lo, hi))
    used = []
    for gi, (i, j) in enumerate(groups):
        lo, hi = win[gi]
        w0, w1 = words[i]["s"], words[j - 1]["e"]
        rs = [(s, e) for s, e in sregs if e > max(lo, w0 - 0.4) and s < min(hi, w1 + 0.4)]
        v0 = max(lo, min([s for s, _ in rs], default=w0))
        v1 = min(hi, max([e for _, e in rs], default=w1))
        start, end = max(lo, v0 - PAD_PRE_S), min(hi, v1 + PAD_POST_S)
        used.append((start, end))
        out.append(piece_row(row, prompt, f"{stem}_s{gi + 1:02d}", start, end, v1, dur, words[i:j],
                             gap_before_ms=round(cuts.get(i, 0.0) * 1000) if gi else None,
                             pass1_stock_tail=bool(sus and gi == len(groups) - 1)))
    # voiced audio that no word covers (a mumble, or a try Whisper folded into a neighbour): its own piece
    for s, e in _uncovered(sregs, used, dur):
        out.append(piece_row(row, prompt, f"{stem}_u{int(s * 100):04d}", max(0.0, s - PAD_PRE_S),
                             min(dur, e + PAD_POST_S), e, dur, [], uncovered=True))
    if not out and row.get("heard"):
        out.append(piece_row(row, prompt, f"{stem}_s01", KEY_S, dur, dur, dur, [], uncovered=True))
    out.sort(key=lambda r: r["start_ms"])
    if dropped and out:
        out[-1]["dropped_words"] = [w["w"] for w in dropped]    # for the reviewer: words Whisper put on silence
    return out


def flag_pieces(pieces: list[dict], pass2: dict[str, dict], sess: Path) -> None:
    """Flags, with a second ASR pass over each piece on its own as a cross-check. On a take full of repeats Whisper
    sometimes folds two tries into one or invents one; on a short slice it tends to add a junk word at the end and
    is less confident. So: pass 1 (whole take) is the transcript when the passes agree; a disagreement makes the
    piece 'unsure' and shows both; a piece pass 1 had no words for (uncovered sound) takes pass 2's words."""
    regs_cache: dict[str, list] = {}
    for p in pieces:
        if p["file"] not in regs_cache:
            db, floor, _ = energy(sess / p["file"])
            regs_cache[p["file"]] = voiced_regions(db, floor)
        r2 = pass2.get(p["seg"])
        off = p["start_ms"] / 1000
        regs = [(s - off, e - off) for s, e in regs_cache[p["file"]]]
        w2, dropped, sus2 = clean_words(r2["words"], regs) if r2 else ([], [], False)
        w1 = p["pass1_words"]
        t1 = [t for w in w1 for t in tokens(w["w"])]
        while w2 and w2[-1]["p"] < 0.3 and not (set(tokens(w2[-1]["w"])) & set(t1[-2:])):
            dropped.append(w2.pop())          # a junk word Whisper tacked onto the end of a short slice
        t2 = [t for w in w2 for t in tokens(w["w"])]
        extra: list[str] = []
        if w1:
            words, sus = w1, p.get("pass1_stock_tail", False)
            if t2 and edit(t2, t1) / script_len(t1) > 0.3:
                extra.append(f"the two ASR passes disagree; the piece on its own sounds like: "
                             f"{' '.join(w['w'] for w in w2)!r}")
            elif not t2:
                extra.append("the piece on its own gave no words")
        else:
            words, sus = w2, sus2
            if w2:
                extra.append("the whole-take pass skipped this sound (Whisper folded repeats?): words from the piece "
                             "on its own")
        toks = [t for w in words for t in tokens(w["w"])]
        script = tokens(p["say"]) if p.get("say") else None
        keys = intent_keys(p["expect"], p.get("say"))
        near_end = p["stop_reason"] == "max length" and p["runs_to_end"]
        flag, reasons, dist = flag_piece(toks, script, keys, p["expect"], p["kind"], [w["p"] for w in words],
                                         p["cut_off"], sus, p["dur_ms"] / 1000, [w["w"] for w in words], near_end)
        if extra and flag == "good":
            flag = "unsure"
        p.update({"transcript": " ".join(w["w"] for w in words), "tokens": toks, "words": words,
                  "pass2_transcript": " ".join(w["w"] for w in w2), "flag": flag, "reasons": reasons + extra,
                  "script_distance": dist})
        if dropped:
            p["dropped_words"] = p.get("dropped_words", []) + [w["w"] for w in dropped]


def _uncovered(regs, used, dur, min_len=0.25):
    """voiced stretches (merged over pauses < 0.6 s) outside every piece, after the 1 s pre-roll."""
    groups: list[list[float]] = []
    for s, e in regs:
        if e < KEY_S:
            continue           # pre-roll: the key press
        if groups and s - groups[-1][1] < 0.6:
            groups[-1][1] = e
        else:
            groups.append([s, e])
    out = []
    for s, e in groups:
        if e - s < min_len:
            continue
        cov = sum(max(0.0, min(e, b) - max(s, a)) for a, b in used)
        if cov < 0.2 * (e - s):
            out.append((s, e))
    return out

# ------------------------------------------------------------------------------------ whistles / clicks


def segment_sound_take(row: dict, sess: Path) -> tuple[list[dict], dict]:
    wav = sess / row["file"]
    db, floor, dur = energy(wav)
    regs = [r for r in voiced_regions(db, floor) if r[1] > KEY_S]     # skip the pre-roll key press
    groups: list[list[float]] = []
    for s, e in regs:
        if groups and s - groups[-1][1] < SOUND_GROUP_S:
            groups[-1][1] = e
        else:
            groups.append([s, e])
    groups = [g for g in groups if g[1] - g[0] >= 0.05]
    stem = Path(row["file"]).stem
    maxlen = row.get("stop_reason") == "max length"
    evs = row.get("events") or []
    off = row.get("clip_offset_ms", 0.0)
    segs = []
    for gi, (s, e) in enumerate(groups):
        start, end = max(0.0, s - PAD_PRE_S), min(dur, e + PAD_POST_S)
        inside = [x["label"] for x in evs if start * 1000 <= x["t_start_ms"] - off < end * 1000]
        n_exp = len(row.get("expect_sounds") or []) if not row.get("run_len") else row["run_len"]
        runs = e >= dur - END_TOL_S
        reasons, flag = [], "unsure"
        if maxlen and e >= dur - CUT_TOL_S:
            flag, reasons = "flub", ["cut off at the end of the take"]
        elif len(groups) > 1:
            reasons = [f"take has {len(groups)} attempts"]
        segs.append({"seg": f"{stem}_s{gi + 1:02d}", "block": row["block"], "pid": row["pid"], "take": row["take"],
                     "file": row["file"], "start_ms": round(start * 1000), "end_ms": round(end * 1000),
                     "dur_ms": round((end - start) * 1000), "transcript": "", "tokens": [], "words": [],
                     "sounds": inside, "n_expected": n_exp, "runs_to_end": bool(runs),
                     "stop_reason": row.get("stop_reason"), "cut_off": bool(maxlen and e >= dur - CUT_TOL_S),
                     "voiced_end_ms": round(e * 1000), "take_dur_ms": round(dur * 1000),
                     "flag": flag if (len(groups) > 1 or flag == "flub") else "good", "reasons": reasons,
                     "kind": row["kind"], "cond": row.get("cond"), "prompt": row["prompt"], "say": None,
                     "expect": None, "expect_intent": row.get("expect_intent"),
                     "expect_sounds": row.get("expect_sounds"), "note": row.get("note")})
    deliberate = [x for x in evs if x["label"] not in ("hiss", "unknown", "noise")]
    info = {"pid": row["pid"], "kind": row["kind"], "cond": row["cond"], "attempts": len(groups),
            "n_events": len(deliberate), "n_expected": n_exp if groups else None,
            "max_length": maxlen, "sounds": row.get("sounds", []), "expect_sounds": row.get("expect_sounds"),
            "run_len": row.get("run_len")}
    return segs, info

# ------------------------------------------------------------------------------------ main


def final_rows(sess: Path) -> dict[str, dict]:
    rows = [json.loads(l) for l in (sess / "labels.jsonl").read_text().splitlines() if l.strip()]
    final: dict[str, dict] = {}
    for r in rows:
        final[r["pid"]] = r
    return {p: r for p, r in final.items() if r.get("status") == "kept"}


def run_asr(sess: Path, files: list[str], model: str, pieces: Path | None = None) -> Path:
    """whole takes (files) or, with pieces, a JSON list of {id, file, start_ms, end_ms} slices."""
    out = sess / "asr" / (f"{model}.pieces.jsonl" if pieces else f"{model}.jsonl")
    if not ASR_PY.exists():
        raise SystemExit(f"no ASR venv at {ASR_PY}; see README (faster-whisper in .venv-asr)")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["VIRTUAL_ENV"] = str(ASR_PY.parent.parent)
    cmd = [str(ASR_PY), str(HERE / "asr_transcribe.py"), "--root", str(sess), "--out", str(out), "--model", model,
           "--prompt", ASR_PROMPT, *([f"--pieces={pieces}"] if pieces else [str(sess / f) for f in files])]
    t0 = time.monotonic()
    subprocess.run(cmd, check=True, env=env)
    print(f"asr step: {time.monotonic() - t0:.1f} s", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, help="session folder, e.g. recordings/khoa-guided-1")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="faster-whisper model (default medium.en)")
    ap.add_argument("--sounds", action="store_true", help="also whistles / clicks (energy only)")
    ap.add_argument("--no-phrases", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    sess = Path(a.session)
    if not sess.is_absolute() and not sess.exists():
        sess = HERE / a.session
    sess = sess.resolve()
    rows = final_rows(sess)
    ph = json.loads((PROMPTS / "phrases_v1.json").read_text())
    pmap = {p["id"]: p for p in ph["prompts"]}
    segs: list[dict] = []
    if not a.no_phrases:
        prow = [r for r in rows.values() if r["block"] == "phrases"]
        if prow:
            if any(r.get("synthetic") for r in prow):
                print("NOTE: SYNTHETIC session (fake talk audio): transcripts will be nonsense; this only tests the "
                      "pipeline.", flush=True)
            asr_p = run_asr(sess, [r["file"] for r in prow], a.model)
            asr = {}
            for line in asr_p.read_text().splitlines():
                if line.strip():
                    x = json.loads(line)
                    if x["model"] == a.model and x.get("asr_prompt") == ASR_PROMPT:
                        asr[x["file"]] = x
            pieces: list[dict] = []
            for r in sorted(prow, key=lambda r: r["pid"]):
                pieces += segment_phrase_take(r, asr[r["file"]], sess, pmap.get(r["pid"], {}))
            req = sess / "asr" / "pieces.json"
            req.write_text(json.dumps([{"id": p["seg"], "file": p["file"], "start_ms": p["start_ms"],
                                        "end_ms": p["end_ms"]} for p in pieces]))
            p2 = run_asr(sess, [], a.model, pieces=req)
            bounds = {q["seg"]: (q["file"], q["start_ms"], q["end_ms"]) for q in pieces}
            pass2 = {}
            for line in p2.read_text().splitlines():
                if line.strip():
                    x = json.loads(line)
                    if (x["model"] == a.model and x.get("asr_prompt") == ASR_PROMPT
                            and bounds.get(x["id"]) == (x["file"], x["start_ms"], x["end_ms"])):
                        pass2[x["id"]] = x
            flag_pieces(pieces, pass2, sess)
            segs += pieces
    info = []
    if a.sounds:
        for r in sorted((r for r in rows.values() if r["block"] != "phrases"), key=lambda r: r["take"]):
            s, i = segment_sound_take(r, sess)
            segs += s
            info.append(i)
    # keep the other block's proposals when only one is regenerated
    out = sess / "segments_auto.jsonl"
    old = [json.loads(l) for l in out.read_text().splitlines() if l.strip()] if out.exists() else []
    blocks_done = ({"phrases"} if not a.no_phrases else set()) | ({"whistles", "clicks"} if a.sounds else set())
    keep_old = [s for s in old if s["block"] not in blocks_done]
    allsegs = keep_old + segs
    out.write_text("".join(json.dumps(s) + "\n" for s in allsegs))
    report(segs, info, rows, a.quiet)
    print(f"\nwrote {out} ({len(allsegs)} segments)")
    print(f"review with:  ./run python review_segments.py --session {a.session}")


def report(segs: list[dict], info: list[dict], rows: dict, quiet: bool) -> None:
    ph = [s for s in segs if s["block"] == "phrases"]
    if ph:
        by = defaultdict(list)
        for s in ph:
            by[s["pid"]].append(s)
        print(f"\nPHRASES: {len(ph)} segments from {len(by)} takes  "
              f"{dict(Counter(s['flag'] for s in ph))}   cut off: {sum(s['cut_off'] for s in ph)} segments")
        cut_takes = sorted({s["pid"] for s in ph if s["cut_off"]})
        print(f"takes whose last try runs into the max length: {len(cut_takes)}")
        print(f"  {'pid':<5}{'kind':<11}{'segs':>5}{'good':>5}{'unsu':>5}{'flub':>5}  script / transcripts")
        for pid in sorted(by):
            g = by[pid]
            c = Counter(s["flag"] for s in g)
            r = rows[pid]
            print(f"  {pid:<5}{r['kind']:<11}{len(g):>5}{c['good']:>5}{c['unsure']:>5}{c['flub']:>5}  "
                  f"{(r.get('say') or '[free] ' + r['prompt'])[:60]}")
            if not quiet:
                for s in g:
                    mark = {"good": " ", "unsure": "?", "flub": "x"}[s["flag"]]
                    print(f"        {mark} {s['start_ms'] / 1000:5.2f}-{s['end_ms'] / 1000:5.2f}  {s['transcript'][:70]}"
                          + (f"   [{'; '.join(s['reasons'])[:90]}]" if s["reasons"] else ""))
    if info:
        for b in ("whistles", "clicks"):
            g = [i for i in info if i["pid"].startswith("wh_" if b == "whistles" else "ck_")]
            if not g:
                continue
            multi = [i for i in g if i["attempts"] > 1]
            ml = [i for i in g if i["max_length"]]
            if b == "whistles":
                more = [i for i in g if i["n_events"] > 1]
            else:
                more = [i for i in g if i["n_expected"] and i["n_events"] > i["n_expected"]]
            print(f"\n{b.upper()}: {len(g)} takes; more than one attempt (energy groups >= {SOUND_GROUP_S} s apart): "
                  f"{len(multi)}; hit max length: {len(ml)}; both: {sum(i['attempts'] > 1 and i['max_length'] for i in g)}")
            print(f"  cross-check, the live extractor heard more sounds than asked (hiss / unknown not counted): "
                  f"{len(more)} takes; of those at max length: {sum(i['max_length'] for i in more)}")
            if multi:
                print("  by class/cond: " + ", ".join(f"{k}: {v}" for k, v in sorted(Counter(
                    f"{i['kind']}/{i['cond']}" for i in multi).items())))
            if not quiet:
                for i in g:
                    if i["attempts"] > 1 or i["max_length"]:
                        print(f"    {i['pid']:<22} attempts {i['attempts']}  max_len {str(i['max_length']):<5} "
                              f"heard {' '.join(i['sounds']) or '-'}  expect {' '.join(i['expect_sounds'] or [])}"
                              + (f" x{i['run_len']}" if i["run_len"] else ""))


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
