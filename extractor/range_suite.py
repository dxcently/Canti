#!/usr/bin/env python3
"""The recorded range suite: checks runner + background mixer (round7-plan §3d).

Run against one or more session folders (extractor/recordings/<session>/ on the desktop,
~/VOX/zflip/range/<session>/ on the phone) and write report.md + report.json INTO each session
folder (never into the repo). The session folders are private: this program only reads them and
writes its two report files beside them (it refuses a folder outside the private roots).

Sessions are read through range_layout (the recorders' own contract): the session's saved spec.json,
validate_session, last-row-wins labels/backgrounds and the session's profile ("full" or "short") and
speaker ("self" or another speaker's pseudonymous id). This runner holds no grid of its own; the SNR
steps come from the spec's analysis.snr_db (override with --snr).

The checks (each a section of the report); the extractor runs once per take and once per background:
  1. labels     Python extractor on every take (+ the C++ host build if present) -> heard sequence
                vs expect; recall per gesture / cond key value / cond_id, the exact-sequence rate (the
                app acts on the sequence: click hiss != hiss click), a confusion matrix, the worst 10
                conditions.
  2. gates      the calibration-v2 level gate, derived like the app's calibration (CalibV2 /
                JoyCalibration: the clicks step takes any pop/click/hiss up to max_dur_ms, the hiss step
                hiss, the pops step pop/click/hiss) from the discrete block's CENTRE takes (the app
                calibrates at a normal loudness and distance; the soft/across takes would lower it), then
                the room step on the session's quiet room take (floor, voiced run, loudest transient: the
                gate stays room_margin_db over it; no room when absent or failed, as after an app skip), and
                the near-field features (android/suite/nearfield.py); keep-rate per gesture vs
                would-act/min on each background, the extractor run over the whole background as one
                stream (as the app hears it). --gate-from <session> also scores with ANOTHER session's
                gate (e.g. a second speaker's takes with the user's gate).
  3. mixing     deterministic (seeded) digital mixes of every clean take (no bg, not the range step) with
                background slices at the spec's SNR steps (SNR vs the take's active-segment RMS);
                backgrounds from the session's backgrounds/ plus optional --musan / --esc50 dirs
                (resampled to the take's rate). Nothing is cached on disk (no derived audio copies).
  4. real vs mix   each real-check take's SNR (1 s pre-roll = background only vs the active post-GO
                power minus that noise power); its clean counterparts (same cond_id and expect) mixed with
                the same recorded background at the nearest SNR step; per-background recall real vs mix
                and a 'representative' verdict (--flag percentage points).
  5. app replay   (--emulator) feed each take through the app's mic_feed {deliver:true} on the
                EMULATOR only and compare its `decision` actions with expect -> action
                (vox_extract.vocab.DEFAULT_BINDINGS). Refuses the phone: serial R5CX62H7PNJ, adb server
                port 5037, host port 7788, and any serial that is not emulator-*.
  6. ratings     ratings.jsonl per block with seconds and redos.

With several sessions it also prints a summary grouped by speaker and device (--summary-out writes it
as summary.json/.md into a private folder).

SYNTHETIC-ONLY tests live in tests/test_range_suite_checks.py. Never talk to the phone here.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
NF_DIR = HERE.parent / "android" / "suite"
if str(NF_DIR) not in sys.path:
    sys.path.insert(0, str(NF_DIR))

from vox_extract import Config  # noqa: E402
from vox_extract.extractor import extract_array  # noqa: E402
from vox_extract.policy import not_deliberate  # noqa: E402
from vox_extract.vocab import DEFAULT_BINDINGS  # noqa: E402

import joystick_core as J  # noqa: E402
import nearfield as nf  # noqa: E402
import range_layout as L  # noqa: E402

COND_KEYS = L.COND_KEYS
GESTURES = ("rise", "fall", "arch", "dip", "flat", "click", "hiss", "pop")
DEFAULT_FLAG = 10.0           # real-vs-mix "representative" tolerance, percentage points
FORBIDDEN_SERIAL = "R5CX62H7PNJ"
FORBIDDEN_ADB_PORT = 5037
FORBIDDEN_SOCKET_PORT = 7788
JOY_SPEC = HERE / "prompts" / "joystick_v1.json"


# --------------------------------------------------------------------------------- session loading

def load_session(directory: str | Path) -> dict:
    """One session through range_layout: validated layout, the session's own spec/profile/speaker, the last row per
    take_id (in plan order), the last row per background name, and the ratings."""
    d = Path(directory).expanduser().resolve()
    spec = L.load_spec(d / "spec.json" if (d / "spec.json").exists() else L.SPEC_PATH)
    counts = L.validate_session(d, spec)
    meta = json.loads((d / "session.json").read_text())
    profile = L.session_profile(meta)
    rows = L.latest_rows(d / "labels.jsonl")
    # each row carries its plan cell's quiet flag (the room step: nothing expected, not a gesture take)
    takes = [dict(rows[t["take_id"]], quiet=L.is_quiet(t)) for t in L.build_plan(spec, profile=profile)
             if t["take_id"] in rows]
    return {"dir": d, "meta": meta, "spec": spec, "profile": profile, "speaker": L.session_speaker(meta),
            "device": meta["device"], "counts": counts, "takes": takes,
            "backgrounds": list(L.latest_rows(d / "backgrounds.jsonl", "name").values()),
            "ratings": L.read_rows(d / "ratings.jsonl")}


# --------------------------------------------------------------------------------- audio helpers

def rms(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def frame_powers(x: np.ndarray, rate: int) -> np.ndarray:
    """Mean power of consecutive 10 ms frames."""
    x = np.asarray(x, dtype=np.float64)
    hop = max(1, round(rate * 0.010))
    n = len(x) // hop
    return np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) if n else np.zeros(0)


def active_rms(x: np.ndarray, rate: int, within_db: float = 20.0) -> float:
    """RMS over the 10 ms frames within `within_db` dB of the loudest frame (the 'active span',
    the same definition synth.py / eval_real/common.py use, made rate-aware)."""
    p = frame_powers(x, rate)
    if p.size == 0 or p.max() <= 0:
        return rms(x)
    return float(np.sqrt(np.mean(p[p >= p.max() * 10 ** (-within_db / 10)])))


def estimate_snr(x: np.ndarray, rate: int, go_ms: float, within_db: float = 20.0) -> float | None:
    """A real-check take's SNR on the mixer's scale: the pre-roll before GO is background only (noise power); the
    active post-GO frames hold sound + background, so the sound's power is their mean power minus the noise power.
    None without a pre-roll, a sound, or noise."""
    go = round(go_ms * rate / 1000)
    pn = float(np.mean(frame_powers(x[:go], rate))) if go > 0 else 0.0
    p = frame_powers(x[go:], rate)
    if pn <= 0 or p.size == 0:
        return None
    ps = float(np.mean(p[p >= p.max() * 10 ** (-within_db / 10)])) - pn
    return 10 * math.log10(ps / pn) if ps > 0 else None


def resample_to(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """Any-rate polyphase resample (backgrounds -> the take's rate)."""
    x = np.asarray(x, dtype=np.float32)
    if sr_from == sr_to:
        return x
    from scipy.signal import resample_poly
    g = math.gcd(int(sr_from), int(sr_to))
    return resample_poly(x, int(sr_to) // g, int(sr_from) // g).astype(np.float32)


def mix_seed(base_seed: int, take_id: str, bg_name: str, snr_db: float) -> int:
    """A deterministic seed per (take, background, SNR), so re-runs and re-orders agree (5 and 5.0 alike)."""
    h = int(hashlib.sha1(f"{take_id}|{bg_name}|{float(snr_db):g}".encode()).hexdigest()[:8], 16)
    return (int(base_seed) ^ h) & 0xFFFFFFFF


def mix_deterministic(take: np.ndarray, rate: int, bg: np.ndarray, bg_rate: int,
                      snr_db: float, seed: int) -> tuple[np.ndarray, dict]:
    """Mix `bg` into `take` at snr_db (relative to the take's active-segment RMS). The background is resampled to
    `rate`, a slice of length len(take) is chosen from a seeded RNG (looped if the background is shorter) and scaled
    so its RMS == active_rms / 10**(snr/20). A sum past full scale is clipped at +-1 like the ADC would (never
    rescaled: that would move the take's level under the level gate); `clipped` counts the clipped samples."""
    bg = resample_to(bg, bg_rate, rate)
    n = len(take)
    rng = np.random.default_rng(seed)
    if len(bg) >= n:
        off = int(rng.integers(len(bg) - n + 1))
        seg = bg[off:off + n]
    else:
        off = -1  # looped
        seg = np.resize(bg, n)
    ref = active_rms(take, rate)
    zr = rms(seg)
    gain = ref / (zr * 10 ** (snr_db / 20)) if zr > 1e-20 else 0.0
    y = np.asarray(take, dtype=np.float64) + gain * np.asarray(seg, dtype=np.float64)
    clipped = int(np.count_nonzero(np.abs(y) > 1.0))
    y = np.clip(y, -1.0, 1.0)
    return y.astype(np.float32), {"off": int(off), "gain": float(gain), "bg_rms": float(zr),
                                  "active_rms": float(ref), "clipped": clipped}


def read_take(path: Path) -> tuple[np.ndarray, int]:
    """PCM16 mono/stereo WAV -> (2-D audio (n, ch) in [-1, 1), rate), via nearfield.read_wav."""
    return nf.read_wav(path)


# --------------------------------------------------------------------------------- extraction + gates

def analyze(audio: np.ndarray, rate: int, cfg: Config, wav_t0_ms: float = 0.0, features: bool = True) -> list[dict]:
    """The streaming extractor on channel 0 (one fresh extractor per call), with each event's gate numbers
    (extractor raw) and, when [features], the near-field features. audio may be 1-D (mono) or 2-D (n, ch)."""
    audio2d = audio[:, None] if audio.ndim == 1 else audio
    out: list[dict] = []
    for e in extract_array(np.asarray(audio2d[:, 0], dtype=np.float32), rate, cfg):
        d = e.to_dict()
        raw = d.get("raw") or {}
        out.append({"label": d["label"], "text": d["text"], "t_start_ms": d["t_start_ms"], "t_end_ms": d["t_end_ms"],
                    "snr_db": raw.get("snr_db"), "level_db": raw.get("level_db"), "dur_ms": raw.get("dur_ms"),
                    "example": J.example(raw),
                    "nearfield": nf.features(audio2d, rate, {"wav_t0_ms": float(wav_t0_ms)}, d) if features else None})
    return out


def gate_keep(gate: dict | None, ev: dict) -> bool:
    """The level gate passes this event (the app's CalibV2.gateDrop; non-discrete labels always pass)."""
    return gate is None or J.gate_reason(gate, ev["label"], ev["snr_db"], ev["level_db"]) is None


def would_act(gate: dict | None, ev: dict) -> bool:
    """Would this event act? Survives the level gate and sounds like a deliberate gesture."""
    if ev["label"] == "unknown" or not gate_keep(gate, ev):
        return False
    return not_deliberate(ev["label"], ev["text"]) is None


def is_centre(take: dict) -> bool:
    """A clean take at the grid's centre loudness and distance (what a calibration is recorded at)."""
    cond = take.get("cond") or {}
    return take.get("bg") is None and cond.get("loud") == "normal" and cond.get("dist") == "hand"


def room_step(session: dict, events: dict[str, list[dict]], examples: dict[str, list[dict]], joy: dict) -> dict:
    """The app's calibration room step (JoyCalibration.room == joystick.py _room_setup) on the session's room take:
    over calib_v2.room.window_ms from GO, the ticks' median level (the floor), the longest voiced run (a run of
    max_voiced_run_ticks or more fails: "not quiet"), and the loudest pop/click/hiss extractor event by SNR and by
    level (separately). Fails, like the app, when that transient + room_margin_db is over the weakest calibrated
    example - cap_below_weakest_db in both SNR and level. {"status": "absent" | "not quiet" | "too loud" | "ok",
    "room": RoomNoise as a dict (only when ok; what derive_gate takes), ...}. The ticks come from joystick_core's
    Analyzer on the take from its start (the pre-roll warms its floor, as the app's has run before the step)."""
    quiet = [t for t in session["takes"] if t.get("quiet")]
    if not quiet:
        return {"status": "absent"}
    t = quiet[-1]
    c, g = joy["calib_v2"]["room"], joy["level_gate"]
    win = float(c["window_ms"])
    go = float(t["go_offset_ms"])
    audio, rate = read_take(session["dir"] / t["file"])
    an = J.Analyzer(joy)
    x = resample_to(audio[:, 0], rate, an.fs)
    db, run, max_run = [], 0, 0
    for tk in an.push(x):
        if go <= tk.t_ms <= go + win:
            db.append(tk.db)
            run = run + 1 if tk.voiced else 0
            max_run = max(max_run, run)
    out = {"take_id": t["take_id"], "window_ms": win, "max_voiced_run_ticks": max_run,
           "floor_dbfs": round(float(np.median(db)), 2) if db else None}
    if max_run >= c["max_voiced_run_ticks"]:
        return dict(out, status="not quiet")
    tr = [e for e in events.get(t["take_id"], []) if e["label"] in J.GATE_LABELS and go <= e["t_start_ms"] <= go + win
          and e["snr_db"] is not None and e["level_db"] is not None]
    ts = max((e["snr_db"] for e in tr), default=None)
    tl = max((e["level_db"] for e in tr), default=None)
    ex = [e for k in ("pops", "clicks", "hiss") for e in examples.get(k) or []
          if e.get("snr_db") is not None and e.get("level_db") is not None]
    out["transients"] = len(tr)
    if tr and ex:
        ws, wl = min(e["snr_db"] for e in ex), min(e["level_db"] for e in ex)
        cap = g["cap_below_weakest_db"]
        if ts + g["room_margin_db"] > ws - cap and tl + g["room_margin_db"] > wl - cap:
            return dict(out, status="too loud", transient_snr_db=round(float(ts), 2),
                        transient_level_dbfs=round(float(tl), 2))
    room = {"floor_dbfs": out["floor_dbfs"], "transient_snr_db": None if ts is None else round(float(ts), 2),
            "transient_level_dbfs": None if tl is None else round(float(tl), 2), "transients": len(tr)}
    return dict(out, status="ok", room=room)


def derive_level_gate(session: dict, events: dict[str, list[dict]], joy: dict | None = None) -> dict:
    """The calibration-v2 level gate the app would derive for this speaker and mic (CalibV2.deriveGate ==
    joystick_core.derive_gate), from the discrete block's centre takes, each step's rule as in JoyCalibration:
    clicks = the strongest pop/click/hiss up to calib_v2.clicks.max_dur_ms, hiss = the strongest hiss, pops = the
    strongest pop/click/hiss (the app matches its pop detector's bursts; the take's prompt stands in for it). One
    example per take (the app keeps the strongest `ask` of a step). Then the room step (room_step) on the session's
    room take, as the app runs it after those steps: when it passes, the gate is raised to the room's loudest
    transient + room_margin_db; when it fails or the session has no room take (older sessions), the gate has no room
    (as the app after a skipped room step). gate["room"] says which."""
    joy = joy or json.loads(JOY_SPEC.read_text())
    max_click_ms = joy["calib_v2"]["clicks"]["max_dur_ms"]
    rules = {"click": ("clicks", lambda e: e["label"] in J.GATE_LABELS and (e["dur_ms"] or 0) <= max_click_ms),
             "hiss": ("hiss", lambda e: e["label"] == "hiss"),
             "pop": ("pops", lambda e: e["label"] in J.GATE_LABELS)}
    examples: dict[str, list[dict]] = {"pops": [], "clicks": [], "hiss": []}
    for t in session["takes"]:
        expect = t.get("expect") or []
        if t.get("block") != "discrete" or len(expect) != 1 or expect[0] not in rules or not is_centre(t):
            continue
        bucket, ok = rules[expect[0]]
        cand = [e for e in events.get(t["take_id"], []) if e["snr_db"] is not None and e["level_db"] is not None and ok(e)]
        if cand:
            examples[bucket].append(max(cand, key=lambda e: e["snr_db"])["example"])
    rs = room_step(session, events, examples, joy)
    gate = J.derive_gate(examples, rs.get("room"), joy)
    gate["examples"] = {k: len(v) for k, v in examples.items()}
    gate["room"] = rs
    return gate


# --------------------------------------------------------------------------------- scoring helpers

def recall_counts(expect: list[str], heard: list[str]) -> tuple[int, int]:
    """Order-independent recall: min(expected, heard) per gesture, summed (combos count each sound)."""
    ec, hc = Counter(expect), Counter(heard)
    return sum(min(ec[g], hc[g]) for g in ec), sum(ec.values())


def align(expect: list[str], heard: list[str]) -> list[tuple[str, str]]:
    """Greedy left-to-right alignment for the confusion matrix: each expected sound consumes the
    next heard sound, or 'miss' when the heard sequence runs out."""
    out, i = [], 0
    for e in expect:
        if i < len(heard):
            out.append((e, heard[i])); i += 1
        else:
            out.append((e, "miss"))
    return out


def frac(correct: int, total: int) -> float | None:
    return round(correct / total, 4) if total else None


def add_frac(acc: dict, key, correct: int, total: int) -> None:
    a = acc.setdefault(key, {"correct": 0, "total": 0})
    a["correct"] += correct
    a["total"] += total


def with_rates(acc: dict) -> dict:
    return {k: dict(v, recall=frac(v["correct"], v["total"])) for k, v in acc.items()}


def per_gesture_add(acc: dict, expect: list[str], got: list[str]) -> None:
    """Per expected gesture: how many of its expected sounds were got (a combo's click click counts 2 of 2)."""
    ec, gc = Counter(expect), Counter(got)
    for g, n in ec.items():
        add_frac(acc, g, min(n, gc[g]), n)


# --------------------------------------------------------------------------------- background sources

def background_sources(session: dict, musan_dirs: list[Path], esc50_dirs: list[Path]) -> list[dict]:
    """Session backgrounds/ plus any --musan / --esc50 files, as {name, kind, level, path, seconds}."""
    out: list[dict] = []
    for b in session["backgrounds"]:
        out.append({"name": b["name"], "kind": b["kind"], "level": b.get("level"),
                    "path": session["dir"] / b["file"], "seconds": b.get("seconds")})
    for kind, dirs in (("musan", musan_dirs), ("esc50", esc50_dirs)):
        for d in dirs:
            for w in sorted(Path(d).rglob("*.wav")):
                out.append({"name": f"{kind}:{w.relative_to(d)}", "kind": kind, "level": None,
                            "path": w, "seconds": None})
    return out


class Backgrounds:
    """Background audio (channel 0), read once and resampled once per take rate."""

    def __init__(self, sources: list[dict]):
        self.sources = sources
        self._raw: dict[str, tuple[np.ndarray, int] | None] = {}
        self._at: dict[tuple[str, int], np.ndarray] = {}

    def at(self, src: dict, rate: int) -> np.ndarray | None:
        name = src["name"]
        if name not in self._raw:
            try:
                a, r = read_take(src["path"])
                self._raw[name] = (a[:, 0].astype(np.float32), r) if len(a) else None
            except (OSError, ValueError, EOFError):
                self._raw[name] = None   # an unreadable extra (MUSAN/ESC-50) file: skipped
        if self._raw[name] is None:
            return None
        if (name, rate) not in self._at:
            x, r = self._raw[name]
            self._at[(name, rate)] = resample_to(x, r, rate)
        return self._at[(name, rate)]


# --------------------------------------------------------------------------------- checks

def analyze_takes(session: dict, cfg: Config) -> dict[str, list[dict]]:
    """The extractor (+ near-field features) once per take: {take_id: events}."""
    out = {}
    for t in session["takes"]:
        audio, rate = read_take(session["dir"] / t["file"])
        out[t["take_id"]] = analyze(audio, rate, cfg)
    return out


def analyze_backgrounds(session: dict, cfg: Config) -> dict[str, dict]:
    """Each recorded background through ONE extractor, as the app hears a continuous room: {name: {events, seconds}}."""
    out = {}
    for b in session["backgrounds"]:
        audio, rate = read_take(session["dir"] / b["file"])
        out[b["name"]] = {"events": analyze(audio, rate, cfg), "seconds": len(audio) / rate}
    return out


def check_labels(session: dict, events: dict[str, list[dict]], cpp: dict | None) -> dict:
    per_take, confusion = [], defaultdict(Counter)
    per_gesture: dict = {}
    per_sequence: dict = {}
    per_cond_key: dict = {k: {} for k in COND_KEYS}
    per_cond_id: dict = {}
    correct_total = total_total = exact_total = 0
    for t in session["takes"]:
        if t.get("quiet"):
            continue   # the room step: not a gesture take (its events feed the gate's room step)
        heard = [e["label"] for e in events[t["take_id"]]]
        expect = list(t.get("expect") or [])
        c, tot = recall_counts(expect, heard)
        exact = heard == expect
        correct_total += c
        total_total += tot
        exact_total += exact
        for e, h in align(expect, heard):
            confusion[e][h] += 1
        rec = {"take_id": t["take_id"], "block": t.get("block"), "cond_id": t.get("cond_id"),
               "expect": expect, "heard": heard, "correct": c, "total": tot, "recall": frac(c, tot), "exact": exact}
        if cpp is not None and cpp.get("by_take"):
            rec["cpp_heard"] = cpp["by_take"].get(t["take_id"])
        per_take.append(rec)
        per_gesture_add(per_gesture, expect, heard)
        add_frac(per_sequence, " ".join(expect), int(exact), 1)
        cond = t.get("cond") or {}
        for k in COND_KEYS:
            add_frac(per_cond_key[k], str(cond.get(k, "na")), c, tot)
        add_frac(per_cond_id, str(t.get("cond_id")), c, tot)
    ids = with_rates(per_cond_id)
    worst = sorted(({"cond_id": k, "recall": v["recall"], "n": v["total"]} for k, v in ids.items()),
                   key=lambda r: (r["recall"] if r["recall"] is not None else -1.0, -r["n"]))[:10]
    return {"n_takes": len(per_take), "per_take": per_take,
            "recall": {"overall": frac(correct_total, total_total), "per_gesture": with_rates(per_gesture),
                       "per_cond_key": {k: with_rates(v) for k, v in per_cond_key.items()}, "per_cond_id": ids},
            "exact": {"overall": frac(exact_total, len(per_take)), "per_sequence": with_rates(per_sequence)},
            "confusion": {k: dict(v) for k, v in confusion.items()},
            "worst_conditions": worst}


def _nf_summary(events: list[dict]) -> dict:
    """Per-feature mean/count over one take's (or one background's) events, ignoring nulls."""
    out = {}
    for f in nf.FEATURES:
        vals = [e["nearfield"].get(f) for e in events if e.get("nearfield") and e["nearfield"].get(f) is not None]
        out[f] = {"n": len(vals), "mean": round(float(np.mean(vals)), 4) if vals else None}
    return out


def check_gates(session: dict, events: dict[str, list[dict]], bg_events: dict[str, dict], gate: dict) -> dict:
    """With [gate]: per take, how many expected sounds survive it (keep-rate); per background, how many events would
    act per minute."""
    per_gesture: dict = {}
    kept_total = total_total = 0
    per_take = []
    for t in session["takes"]:
        if t.get("quiet"):
            continue
        evs = events[t["take_id"]]
        expect = list(t.get("expect") or [])
        kept = [e["label"] for e in evs if gate_keep(gate, e)]
        k, tot = recall_counts(expect, kept)
        kept_total += k
        total_total += tot
        per_gesture_add(per_gesture, expect, kept)
        per_take.append({"take_id": t["take_id"], "block": t.get("block"), "cond_id": t.get("cond_id"),
                         "kept": k, "total": tot, "rate": frac(k, tot), "nearfield": _nf_summary(evs)})
    backgrounds = []
    for b in session["backgrounds"]:
        be = bg_events[b["name"]]
        acts = sum(would_act(gate, e) for e in be["events"])
        minutes = be["seconds"] / 60
        backgrounds.append({"name": b["name"], "kind": b["kind"], "level": b.get("level"),
                            "seconds": round(be["seconds"], 3), "events": len(be["events"]), "would_act": acts,
                            "per_min": round(acts / minutes, 3) if minutes else None,
                            "nearfield": _nf_summary(be["events"])})
    return {"gate": gate, "keep_rate": {"overall": frac(kept_total, total_total), "per_gesture": with_rates(per_gesture)},
            "per_take": per_take, "backgrounds": backgrounds}


def mixable(take: dict) -> bool:
    """A clean gesture take the mixer uses (not a real-check take, not the range step's long holds)."""
    return take.get("bg") is None and take.get("block") != "range" and not take.get("quiet")


def check_mixing(session: dict, cfg: Config, gates: dict[str, dict], bgs: Backgrounds, snr_steps: tuple,
                 base_seed: int) -> dict:
    recall_by_kind: dict = defaultdict(dict)
    keep_by: dict = {name: defaultdict(dict) for name in gates}
    n_mixes = clipped_mixes = 0
    for t in session["takes"]:
        if not mixable(t):
            continue
        audio, rate = read_take(session["dir"] / t["file"])
        take_x = audio[:, 0].astype(np.float32)
        expect = list(t.get("expect") or [])
        for src in bgs.sources:
            bg_x = bgs.at(src, rate)
            if bg_x is None or bg_x.size == 0:
                continue
            for snr in snr_steps:
                mix_x, info = mix_deterministic(take_x, rate, bg_x, rate, snr,
                                                mix_seed(base_seed, t["take_id"], src["name"], snr))
                n_mixes += 1
                clipped_mixes += info["clipped"] > 0
                evs = analyze(mix_x, rate, cfg, features=False)
                add_frac(recall_by_kind[src["kind"]], snr, *recall_counts(expect, [e["label"] for e in evs]))
                for name, g in gates.items():
                    add_frac(keep_by[name][src["kind"]], snr,
                             *recall_counts(expect, [e["label"] for e in evs if gate_keep(g, e)]))

    def _finalize(by_kind):
        return {kind: {f"{snr:g}": dict(acc, recall=frac(acc["correct"], acc["total"]))
                       for snr, acc in sorted(by_snr.items(), reverse=True)} for kind, by_snr in by_kind.items()}

    return {"snr_steps": list(snr_steps), "seed": base_seed, "n_mixes": n_mixes, "clipped_mixes": clipped_mixes,
            "recall_vs_snr": _finalize(recall_by_kind), "keep_vs_snr": {n: _finalize(k) for n, k in keep_by.items()}}


def check_real_vs_mix(session: dict, cfg: Config, gate: dict, bgs: Backgrounds, events: dict[str, list[dict]],
                      snr_steps: tuple, base_seed: int, flag: float) -> dict:
    """Real acoustic mixes vs digital ones: per real-check take (bg set, and that background recorded), its estimated
    SNR, and its clean counterparts (same cond_id and expect, no bg) mixed with the same background at the nearest
    SNR step. Verdict per background on the pooled recall (a single take's recall is 0 or 1, so per-take diffs are
    shown but not judged)."""
    src_by_name = {s["name"]: s for s in bgs.sources}
    clean = defaultdict(list)
    for t in session["takes"]:
        if mixable(t):
            clean[(t.get("cond_id"), tuple(t.get("expect") or []))].append(t)
    pre_ms = session["spec"]["analysis"]["pre_roll_s"] * 1000
    rows: list[dict] = []
    pooled: dict = defaultdict(lambda: {"real": [0, 0], "mix": [0, 0], "real_keep": [0, 0], "mix_keep": [0, 0]})
    for t in session["takes"]:
        name = (t.get("bg") or {}).get("name")
        if not name or name not in src_by_name:
            continue
        audio, rate = read_take(session["dir"] / t["file"])
        x = audio[:, 0].astype(np.float32)
        est = estimate_snr(x, rate, t.get("go_offset_ms", pre_ms))
        nearest = min(snr_steps, key=lambda s: abs(s - est)) if est is not None else None
        expect = list(t.get("expect") or [])
        evs = events[t["take_id"]]
        rc = recall_counts(expect, [e["label"] for e in evs])
        rk = recall_counts(expect, [e["label"] for e in evs if gate_keep(gate, e)])
        mc, mk = [0, 0], [0, 0]
        mates = clean.get((t.get("cond_id"), tuple(expect)), [])
        if nearest is not None:
            for m in mates:
                ma, mr = read_take(session["dir"] / m["file"])
                bg_x = bgs.at(src_by_name[name], mr)
                if bg_x is None:
                    continue
                mix_x, _ = mix_deterministic(ma[:, 0].astype(np.float32), mr, bg_x, mr, nearest,
                                             mix_seed(base_seed, m["take_id"], name, nearest))
                me = analyze(mix_x, mr, cfg, features=False)
                for acc, got in ((mc, [e["label"] for e in me]), (mk, [e["label"] for e in me if gate_keep(gate, e)])):
                    c, n = recall_counts(expect, got)
                    acc[0] += c
                    acc[1] += n
        p = pooled[name]
        for key, (c, n) in (("real", rc), ("real_keep", rk)):
            p[key][0] += c
            p[key][1] += n
        if mc[1]:
            for key, acc in (("mix", mc), ("mix_keep", mk)):
                p[key][0] += acc[0]
                p[key][1] += acc[1]
        real_recall, mix_recall = frac(*rc), frac(*mc)
        rows.append({"take_id": t["take_id"], "bg_name": name, "kind": t["bg"].get("kind"),
                     "level": t["bg"].get("level"), "est_snr_db": None if est is None else round(est, 2),
                     "nearest_snr_db": nearest, "counterparts": len(mates), "real_recall": real_recall,
                     "real_keep": frac(*rk), "mix_recall": mix_recall, "mix_keep": frac(*mk),
                     "recall_diff_pp": None if mix_recall is None or real_recall is None
                     else round(100 * (real_recall - mix_recall), 2)})
    per_bg = {}
    for name, p in pooled.items():
        real, mix = frac(*p["real"]), frac(*p["mix"])
        diff = None if real is None or mix is None else round(100 * (real - mix), 2)
        per_bg[name] = {"real_recall": real, "mix_recall": mix, "real_keep": frac(*p["real_keep"]),
                        "mix_keep": frac(*p["mix_keep"]), "n_real": p["real"][1], "n_mix": p["mix"][1],
                        "recall_diff_pp": diff,
                        "verdict": "insufficient" if diff is None else
                        "representative" if abs(diff) <= flag else "not representative"}
    verdicts = [v["verdict"] for v in per_bg.values()]
    overall = None if not verdicts else "insufficient" if all(v == "insufficient" for v in verdicts) else (
        "representative" if all(v in ("representative", "insufficient") for v in verdicts) else "not representative")
    return {"flag": flag, "rows": rows, "per_bg": per_bg, "verdict": overall}


def check_ratings(session: dict) -> list[dict]:
    blocks: dict[str, dict] = {}
    for r in session["ratings"]:
        b = blocks.setdefault(str(r.get("block")), {"n": 0, "sum": 0, "seconds": 0, "redos": 0, "notes": []})
        b["n"] += 1
        rating = r.get("rating")
        if isinstance(rating, (int, float)):
            b["sum"] += float(rating)
        b["seconds"] += int(r.get("seconds") or 0)
        b["redos"] += int(r.get("redos") or 0)
        if r.get("note"):
            b["notes"].append(str(r["note"]))
    out = []
    for block, b in sorted(blocks.items()):
        out.append({"block": block, "n": b["n"], "rating_mean": round(b["sum"] / b["n"], 2) if b["n"] else None,
                    "seconds": b["seconds"], "redos": b["redos"], "notes": b["notes"]})
    return out


def expected_action(expect: list[str]) -> str:
    return DEFAULT_BINDINGS.get(tuple(expect), "none")


def check_device(serial: str, adb_port: int | None, socket_port: int | None = None) -> None:
    """The emulator only: refuse the real phone (serial R5CX62H7PNJ, adb server port 5037, host port 7788) and any
    serial that is not an emulator's."""
    if str(serial) == FORBIDDEN_SERIAL:
        raise ValueError(f"refusing the real phone serial {FORBIDDEN_SERIAL}")
    if not str(serial).startswith("emulator-"):
        raise ValueError(f"app replay runs on an emulator only, not serial {serial!r}")
    if adb_port is None or int(adb_port) == FORBIDDEN_ADB_PORT:
        raise ValueError(f"refusing adb server port {adb_port} (the phone's is {FORBIDDEN_ADB_PORT}; the emulator's 5038)")
    if socket_port is not None and int(socket_port) == FORBIDDEN_SOCKET_PORT:
        raise ValueError(f"refusing host port {FORBIDDEN_SOCKET_PORT} (the phone's forward)")


def replay_pcm(audio: np.ndarray, rate: int) -> tuple[str, int]:
    """Channel 0 as mic_feed's pcm_b64 (PCM16 LE mono) at a rate it takes (16000 | 48000)."""
    mono = np.asarray(audio[:, 0] if audio.ndim == 2 else audio, dtype=np.float64)
    if rate not in (16000, 48000):
        mono, rate = resample_to(mono, rate, 16000).astype(np.float64), 16000
    pcm = np.round(np.clip(mono, -1, 32767 / 32768) * 32768).astype("<i2")
    return base64.b64encode(pcm.tobytes()).decode(), rate


def check_app_replay(session: dict, serial: str, adb_port: int, socket_port: int, settle_s: float = 2.0) -> dict:
    """Feed each take through the app on the EMULATOR via mic_feed {deliver:true} and compare the service's
    `decision` actions with the expected one. voxlib's module defaults (host port 7788, the ambient adb server) are
    overridden here before anything connects. Needs the fixture app with sound_source phone (mic_feed needs the mic
    source). Not run by the tests (no emulator)."""
    check_device(serial, adb_port, socket_port)
    os.environ["ANDROID_ADB_SERVER_PORT"] = str(int(adb_port))
    os.environ["VOX_SERIAL"] = serial
    os.environ["VOX_SOCKET_PORT"] = str(int(socket_port))
    import voxlib
    voxlib.SERIAL, voxlib.SOCKET_PORT = serial, int(socket_port)
    vox = voxlib.Vox()
    stream = voxlib.EventStream()
    rows: list[dict] = []
    try:
        for t in session["takes"]:
            audio, rate = read_take(session["dir"] / t["file"])
            pcm, feed_rate = replay_pcm(audio, rate)
            mark = stream.mark()
            r = vox.control("mic_feed", pcm_b64=pcm, rate=feed_rate, chunk_ms=20, deliver=True)
            time.sleep(settle_s)   # the combo window and any confirmation settle before the next take
            actions = [e.get("action") for e in stream.since(mark) if e.get("ev") == "decision"]
            want = expected_action(list(t.get("expect") or []))
            rows.append({"take_id": t["take_id"], "expect": t.get("expect"), "expected_action": want,
                         "actions": actions, "ok": bool(r.get("ok")),
                         "match": actions == ([] if want == "none" else [want])})
    finally:
        stream.close()
        vox.close()
    return {"rows": rows, "match_rate": frac(sum(r["match"] for r in rows), len(rows))}


# --------------------------------------------------------------------------------- C++ extractor

def cpp_extractor() -> dict:
    """The host C++ port, if already built (firmware/tools/check_extract.sh); else a skip note."""
    cli = HERE.parent / "firmware" / "build" / "host" / "vx_cli"
    if cli.exists():
        return {"available": True, "cli": str(cli)}
    return {"available": False,
            "note": "firmware/build/host/vx_cli not present (build it with firmware/tools/check_extract.sh)"}


def run_cpp(cli: str, wav: Path) -> list[str]:
    import subprocess
    r = subprocess.run([cli, "--wav", str(wav)], capture_output=True, text=True, timeout=60)
    labels = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            labels.append(json.loads(line)["label"])
        except (json.JSONDecodeError, KeyError):
            continue
    return labels


# --------------------------------------------------------------------------------- report

def gate_from_session(directory: str | Path, cfg: Config) -> dict:
    """Another session's calibration-derived gate (e.g. the user's, to judge a second speaker's takes)."""
    other = load_session(directory)
    return {"session": str(other["dir"]), "speaker": other["speaker"], "device": other["device"],
            "gate": derive_level_gate(other, analyze_takes(other, cfg))}


def run_session(directory: str | Path, opts: argparse.Namespace, gate_from: dict | None = None) -> dict:
    session = load_session(directory)
    out_dir = L.private_dir(session["dir"])   # reports only ever land in a private session folder
    cfg = Config.load(opts.config) if opts.config else Config()

    cpp_info = None
    if not opts.no_cpp:
        cpp_info = dict(cpp_extractor())
        if cpp_info["available"]:
            cpp_info["by_take"] = {t["take_id"]: run_cpp(cpp_info["cli"], session["dir"] / t["file"])
                                   for t in session["takes"]}

    events = analyze_takes(session, cfg)
    bg_events = analyze_backgrounds(session, cfg)
    gate = derive_level_gate(session, events)
    gates = {"own": gate}
    if gate_from is not None:
        gates["from"] = gate_from["gate"]
    bgs = Backgrounds(background_sources(session, opts.musan or [], opts.esc50 or []))
    snr_steps = tuple(float(s) for s in (opts.snr or session["spec"]["analysis"]["snr_db"]))

    app_replay = None
    if opts.emulator:
        app_replay = check_app_replay(session, opts.serial, opts.adb_port, opts.socket_port,
                                      getattr(opts, "replay_settle_s", 2.0))

    meta = session["meta"]
    rg = meta.get("range") or {}
    report = {
        "version": 2,
        "session": str(session["dir"]),
        "speaker": session["speaker"],
        "profile": session["profile"],
        "device": session["device"],
        "mic": meta.get("mic"),
        "synthetic": bool(meta.get("synthetic")),
        "spec": meta.get("spec"),
        "layout": session["counts"],
        "generated": datetime.now(timezone.utc).isoformat(),
        "cpp": cpp_info,
        "range": rg,
        "gate": gate,
        "gate_from": None if gate_from is None else {k: gate_from[k] for k in ("session", "speaker", "device", "gate")},
        "labels": check_labels(session, events, cpp_info),
        "gates": {name: check_gates(session, events, bg_events, g) for name, g in gates.items()},
        "mixing": check_mixing(session, cfg, gates, bgs, snr_steps, opts.seed),
        "real_vs_mix": check_real_vs_mix(session, cfg, gate, bgs, events, snr_steps, opts.seed, opts.flag),
        "app_replay": app_replay,
        "ratings": check_ratings(session),
        "notes": [],
    }
    room = gate.get("room") or {}
    if gate["from"] == "calibration" and room.get("status") == "absent":
        report["notes"].append("the level gate has no room step here (no room take: a session recorded before the "
                               "room step; the app raises it to the room's loudest transient + room_margin_db): it is "
                               "at most as strict as the app's")
    elif gate["from"] == "calibration" and room.get("status") in ("not quiet", "too loud"):
        report["notes"].append(f"the room take failed the app's room step ({room['status']}): the level gate has no "
                               "room, as in the app after a skipped room step; re-record the room take to include it")
    if meta.get("synthetic"):
        report["notes"].append("SYNTHETIC session: machinery only, never evidence of real performance")
    if rg.get("below_f0_min") or (isinstance(rg.get("bottom_hz"), (int, float)) and rg["bottom_hz"] < cfg.f0_min_hz):
        report["notes"].append(f"range bottom is below the extractor's f0_min_hz ({cfg.f0_min_hz:g} Hz)")

    (out_dir / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    (out_dir / "report.md").write_text(build_markdown(report))
    return report


def summarize(reports: list[dict]) -> dict:
    """Several sessions' results grouped by speaker, then device: overall and per-gesture recall, the exact-sequence
    rate, the keep-rate with the own gate and with --gate-from's, and recall per cond_id (the cond_ids are the same in
    every profile, so a short session compares cell for cell with a full one)."""
    out: dict = {}
    for r in reports:
        lab = r["labels"]
        g = out.setdefault(r["speaker"], {}).setdefault(r["device"], {
            "sessions": [], "recall": {"correct": 0, "total": 0}, "exact": {"correct": 0, "total": 0},
            "keep": {}, "per_gesture": {}, "per_cond_id": {}})
        g["sessions"].append({"session": r["session"], "profile": r["profile"], "takes": lab["n_takes"],
                              "synthetic": r.get("synthetic", False)})
        for t in lab["per_take"]:
            g["recall"]["correct"] += t["correct"]
            g["recall"]["total"] += t["total"]
            g["exact"]["correct"] += int(t["exact"])
            g["exact"]["total"] += 1
            add_frac(g["per_cond_id"], t["cond_id"], t["correct"], t["total"])
        for gesture, acc in lab["recall"]["per_gesture"].items():
            add_frac(g["per_gesture"], gesture, acc["correct"], acc["total"])
        for name, chk in r["gates"].items():
            for gesture, acc in chk["keep_rate"]["per_gesture"].items():
                add_frac(g["keep"].setdefault(name, {}), gesture, acc["correct"], acc["total"])
    for by_device in out.values():
        for g in by_device.values():
            for key in ("recall", "exact"):
                g[key]["rate"] = frac(g[key]["correct"], g[key]["total"])
            g["per_gesture"] = with_rates(g["per_gesture"])
            g["per_cond_id"] = with_rates(g["per_cond_id"])
            g["keep"] = {name: with_rates(v) for name, v in g["keep"].items()}
    return out


def summary_markdown(summary: dict) -> str:
    rows = []
    for speaker, by_device in sorted(summary.items()):
        for device, g in sorted(by_device.items()):
            keep = {name: frac(sum(a["correct"] for a in v.values()), sum(a["total"] for a in v.values()))
                    for name, v in g["keep"].items()}
            rows.append([speaker, device, len(g["sessions"]), g["recall"]["total"], pct(g["recall"]["rate"]),
                         pct(g["exact"]["rate"]), pct(keep.get("own")), pct(keep.get("from"))])
    return "# range suite — by speaker\n\n" + md_table(
        ["speaker", "device", "sessions", "sounds", "recall %", "exact %", "keep own %", "keep from %"], rows) + "\n"


# --------------------------------------------------------------------------------- markdown

def num(v, fmt: str = ".2f") -> str:
    return format(v, fmt) if v is not None else "-"


def pct(v) -> str:
    return num(v * 100 if v is not None else None, ".1f")


def md_table(headers: list[str], rows: list[list]) -> str:
    body = ["| " + " | ".join(str(c) for c in headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    body += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(body)


def build_markdown(r: dict) -> str:
    out = [f"# range suite — {r['session']} ({r.get('device')}, speaker {r.get('speaker')}, profile {r.get('profile')})", ""]
    if r.get("synthetic"):
        out += ["> SYNTHETIC session: machinery only.", ""]
    rg = r.get("range") or {}
    if rg:
        out.append("**range:** bottom %s Hz · home %s Hz · top %s Hz · whistle %s Hz" % (
            num(rg.get("bottom_hz"), ".1f"), num(rg.get("home_hz"), ".1f"),
            num(rg.get("top_hz"), ".1f"), num(rg.get("whistle_home_hz"), ".1f")))
        if rg.get("below_f0_min"):
            out.append("\n> **bottom is below the extractor's f0_min_hz (75 Hz)**")
        out.append("")

    lab = r["labels"]
    out.append(f"## 1. labels ({lab['n_takes']} takes)")
    out.append(f"overall recall **{pct(lab['recall']['overall'])} %**, exact sequence **{pct(lab['exact']['overall'])} %**")
    if r.get("cpp") and not r["cpp"].get("available"):
        out.append(f"\nC++ extractor: skipped ({r['cpp']['note']})")
    out += ["", "### recall per gesture"]
    out.append(md_table(["gesture", "correct", "total", "recall %"],
                        [[g, a["correct"], a["total"], pct(a["recall"])] for g, a in lab["recall"]["per_gesture"].items()]))
    out += ["", "### exact sequence"]
    out.append(md_table(["expect", "exact", "takes", "%"],
                        [[s, a["correct"], a["total"], pct(a["recall"])] for s, a in lab["exact"]["per_sequence"].items()]))
    out += ["", "### recall per cond key value"]
    for k in COND_KEYS:
        rows = [[v, a["correct"], a["total"], pct(a["recall"])] for v, a in lab["recall"]["per_cond_key"][k].items()]
        if rows:
            out += [md_table([k, "correct", "total", "recall %"], rows), ""]
    out.append("### confusion matrix (expected → heard)")
    heard_cols = sorted({h for row in lab["confusion"].values() for h in row})
    cols = list(GESTURES) + [h for h in heard_cols if h not in GESTURES]
    out.append(md_table([""] + cols, [[e] + [lab["confusion"].get(e, {}).get(h, "") for h in cols]
                                      for e in GESTURES if e in lab["confusion"]]))
    out += ["", "### worst 10 conditions"]
    out.append(md_table(["cond_id", "recall %", "n"], [[w["cond_id"], pct(w["recall"]), w["n"]]
                                                       for w in lab["worst_conditions"]]))

    for name, g in r["gates"].items():
        gate = g["gate"]
        who = "own" if name == "own" else f"from {r['gate_from']['speaker']} ({r['gate_from']['device']})"
        out.append(f"\n## 2. gates — {who}: level gate {gate.get('from')} n={gate.get('n')}, "
                   f">= {num(gate.get('min_snr_db'), '.1f')} dB SNR and {num(gate.get('min_level_dbfs'), '.1f')} dBFS; "
                   f"keep **{pct(g['keep_rate']['overall'])} %**")
        rm = gate.get("room") or {}
        if rm:
            out.append(f"room step: {rm.get('status')}" + (
                f", floor {num(rm.get('floor_dbfs'), '.1f')} dBFS, {rm.get('transients', 0)} transient(s)"
                if rm.get("status") != "absent" else " (no room take)"))
        out.append(md_table(["gesture", "kept", "total", "keep-rate %"],
                            [[gg, a["correct"], a["total"], pct(a["recall"])] for gg, a in g["keep_rate"]["per_gesture"].items()]))
        out += ["", "### backgrounds (would-act / min)"]
        out.append(md_table(["name", "kind", "level", "s", "events", "would-act", "per min"],
                            [[b["name"], b["kind"], b["level"], num(b["seconds"], ".0f"), b["events"], b["would_act"],
                              num(b["per_min"], ".2f")] for b in g["backgrounds"]]))

    m = r["mixing"]
    out.append(f"\n## 3. mixing ({m['n_mixes']} mixes, {m['clipped_mixes']} clipped, seed {m['seed']})")
    for kind, by_snr in m["recall_vs_snr"].items():
        out.append(f"\n### {kind}: recall and keep-rate vs SNR")
        names = list(m["keep_vs_snr"])
        out.append(md_table(["snr dB", "sounds", "recall %"] + [f"keep {n} %" for n in names],
                            [[s, a["total"], pct(a["recall"])] +
                             [pct(m["keep_vs_snr"][n].get(kind, {}).get(s, {}).get("recall")) for n in names]
                             for s, a in by_snr.items()]))

    rv = r["real_vs_mix"]
    out.append(f"\n## 4. real vs mix (verdict: **{rv['verdict'] or '-'}**, flag {rv['flag']} pp)")
    out.append(md_table(["bg", "real sounds", "real recall %", "mix sounds", "mix recall %", "diff pp", "verdict"],
                        [[n, v["n_real"], pct(v["real_recall"]), v["n_mix"], pct(v["mix_recall"]),
                          num(v["recall_diff_pp"], ".1f"), v["verdict"]] for n, v in rv["per_bg"].items()]))
    if rv["rows"]:
        out.append("")
        out.append(md_table(["take", "bg", "est SNR", "nearest", "mates", "real recall %", "mix recall %"],
                            [[x["take_id"], x["bg_name"], num(x["est_snr_db"], ".1f"), num(x["nearest_snr_db"], ".0f"),
                              x["counterparts"], pct(x["real_recall"]), pct(x["mix_recall"])] for x in rv["rows"]]))

    if r.get("app_replay"):
        ar = r["app_replay"]
        out.append(f"\n## 5. app replay (emulator): match **{pct(ar['match_rate'])} %**")
        out.append(md_table(["take", "expect", "expected action", "actions", "match"],
                            [[x["take_id"], x["expect"], x["expected_action"], x["actions"], x["match"]]
                             for x in ar["rows"]]))

    out.append("\n## 6. ratings")
    out.append(md_table(["block", "n", "mean rating", "seconds", "redos", "notes"],
                        [[x["block"], x["n"], num(x["rating_mean"], ".1f"), x["seconds"], x["redos"],
                          "; ".join(x["notes"])] for x in r["ratings"]]))
    if r.get("notes"):
        out.append("\n**notes:** " + "; ".join(r["notes"]))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="+", help="session folders (recordings/<session> or ~/VOX/zflip/range/<session>)")
    ap.add_argument("--config", help="extractor Config JSON to run with (default: the built-in Config)")
    ap.add_argument("--gate-from", type=Path, help="also score with this session's calibration-derived level gate "
                                                   "(e.g. the user's session, to judge a second speaker's takes)")
    ap.add_argument("--summary-out", type=Path, help="write summary.json/.md (by speaker) into this private folder")
    ap.add_argument("--musan", action="append", type=Path, default=[], help="MUSAN dir (extra background sources)")
    ap.add_argument("--esc50", action="append", type=Path, default=[], help="ESC-50 dir (extra background sources)")
    ap.add_argument("--snr", type=float, nargs="+", default=None, help="SNR steps (default: the spec's analysis.snr_db)")
    ap.add_argument("--seed", type=int, default=0, help="base seed for mixing (default 0)")
    ap.add_argument("--flag", type=float, default=DEFAULT_FLAG, help="real-vs-mix 'representative' tolerance (pp)")
    ap.add_argument("--no-cpp", action="store_true", help="skip the C++ host extractor even if built")
    ap.add_argument("--emulator", action="store_true", help="also run app replay via mic_feed on the emulator")
    ap.add_argument("--serial", default="emulator-5580", help="the emulator's serial (never the phone's)")
    ap.add_argument("--adb-port", type=int, default=5038, help="the emulator's adb server port (never 5037)")
    ap.add_argument("--socket-port", type=int, default=7789, help="the host port for the app socket (never 7788)")
    ap.add_argument("--replay-settle-s", type=float, default=2.0, help="app replay: wait after each take")
    a = ap.parse_args(argv)

    if a.emulator:
        check_device(a.serial, a.adb_port, a.socket_port)  # fail fast before touching anything
    summary_dir = L.private_dir(a.summary_out) if a.summary_out else None
    cfg = Config.load(a.config) if a.config else Config()
    gate_from = gate_from_session(a.gate_from, cfg) if a.gate_from else None
    reports = []
    for d in a.sessions:
        reports.append(run_session(d, a, gate_from))
        print(f"wrote report.json + report.md into {d}")
    summary = summarize(reports)
    print(summary_markdown(summary))
    if summary_dir:
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
        (summary_dir / "summary.md").write_text(summary_markdown(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
