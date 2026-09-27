"""Voice joystick core (wiki/voice-cursor.md, "Joystick cursor"): audio ticks in, cursor position out. No GUI, no I/O.

This is the part meant to move into the app (Kotlin) as it is, so it keeps to plain per-tick state machines:
  Analyzer  20 ms of audio -> one Tick: pitch (st), voiced, F1/F2 (Hz). The per-frame maths is voice_cursor_v2's
            (MPM pitch, LPC formants with the broad-F2 rule), plus a streaming form of its F2 continuity filter.
            On the phone this is what the Pico (or the phone-mic extractor) would stream.
  Mover     Ticks -> cursor. A sound starts on voice and moves the cursor while it lasts: up/down by pitch (one of
            three vertical modes: "home" = above/below the person's relaxed hum, the default; "glide" = the
            direction the pitch moves, with momentum; "start" = above/below the note the sound started on), sideways
            by the vowel (ee right, oo left); it stops when the sound ends, rewinds the release, then snaps to the
            nearest element within snap_dp. A sound starts on clear voice (clarity >= the person's clarity_on) and
            continues through less clear ticks (clarity >= clarity_continue): hysteresis, so creak does not chop it.
  PopDetector  ticks -> pops: a short impulsive burst from quiet, not voice (a fallback beside the extractor's
            detector, whose thresholds a quiet lip pop can miss), with thresholds a 3-pop setup can learn.
  Clicker   pop events -> click, after the pop-pop gap.
All settings come from prompts/joystick_v1.json (and voice_cursor_v2.json for the per-frame analysis).
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import voice_cursor_test as V

HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / "prompts" / "joystick_v1.json"
DP_PER_INCH = 160.0


def load_spec(path: Path | str = SPEC_PATH) -> dict:
    spec = json.loads(Path(path).read_text())
    V.use_spec(V.load_spec(V.spec_path(spec["analysis_from"])))
    return spec


# ------------------------------------------------------------------------------------ per-tick analysis

@dataclass
class Tick:
    t_ms: float
    f0: float            # Hz, 0 = none
    clarity: float
    db: float
    voiced: bool
    f1: float            # Hz, nan = none
    f2: float
    why: str = ""        # why an unvoiced tick is unvoiced: "quiet" (level < floor + 6 dB), "unclear" (clarity), "no pitch"
    f0_raw: float = 0.0  # the pitch estimate before the voicing gate (0 = none)
    over_db: float = 0.0 # level over the floor


class F2Continuity:
    """Streaming form of voice_cursor_test.f2_continuity: a value more than jump_hz from the last accepted one is
    held back (nan) until `need` values in a row agree with each other. (The batch form also accepts the held-back
    run afterwards; live, only the present can be accepted.)"""

    def __init__(self, jump_hz: float | None, need: int):
        self.jump, self.need = jump_hz, need
        self.last, self.since, self.run = np.nan, 0, []

    def push(self, v: float) -> float:
        if not self.jump:
            return v
        if np.isnan(v):
            self.since += 1
            if self.since > self.need:
                self.last, self.run = np.nan, []
            return np.nan
        self.since = 0
        if np.isnan(self.last) or abs(v - self.last) <= self.jump:
            self.last, self.run = v, []
            return v
        self.run = [x for x in self.run if abs(x - v) <= self.jump] + [v]
        if len(self.run) >= self.need:
            self.last, self.run = v, []
            return v
        return np.nan


class Analyzer:
    """16 kHz audio (any chunk size) -> one Tick per tick_ms, on the newest analysis window."""

    def __init__(self, spec: dict):
        from scipy.signal import butter
        A = V.A
        self.fs, self.win = A["fs"], A["win"]
        self.hop = int(spec["tick"]["tick_ms"] * self.fs / 1000)
        self.vo = spec["voicing"]
        self.buf = np.zeros(self.win)
        self.pending = np.zeros(0)
        self.n = 0                                   # samples consumed
        self.b, self.a = butter(2, A["hpf_hz"] / (self.fs / 2), "high") if A.get("hpf_hz") else (None, None)
        self.zi = np.zeros(2)
        self.levels: deque[float] = deque(maxlen=int(self.vo["floor_window_s"] * 1000 / spec["tick"]["tick_ms"]))
        self.f2c = F2Continuity(A.get("f2_jump_hz"), A.get("f2_jump_frames", 5))
        self.clarity_on = self.vo["clarity_min"]       # the start threshold; the setup can set a person's own
        self.f0_max_hz: float | None = None            # the pitch ceiling; None = voice_cursor_v2's (1100 Hz). The
                                                       # whistle step and a calibrated whistle range raise it

    @property
    def floor_db(self) -> float:
        return float(np.percentile(self.levels, self.vo["floor_pct"])) if self.levels else -90.0

    def push(self, x: np.ndarray) -> list[Tick]:
        from scipy.signal import lfilter
        x = np.asarray(x, np.float64)
        if self.b is not None:
            x, self.zi = lfilter(self.b, self.a, x, zi=self.zi)
        self.pending = np.concatenate([self.pending, x])
        out = []
        while self.pending.size >= self.hop:
            step, self.pending = self.pending[:self.hop], self.pending[self.hop:]
            self.buf = np.concatenate([self.buf, step])[-self.win:]
            self.n += self.hop
            out.append(self._tick(self.n * 1000 / self.fs))
        return out

    def _tick(self, t_ms: float) -> Tick:
        fr = self.buf
        db = float(20 * np.log10(np.sqrt(np.mean(fr * fr)) + 1e-9))
        floor = self.floor_db
        f0, cl = V._nsdf_f0(fr - fr.mean(), self.fs, self.f0_max_hz)
        f1 = f2 = np.nan
        if cl < self.clarity_on:
            self.levels.append(db)                   # the floor learns from non-periodic ticks only: a long note
        elif db >= floor + self.vo["level_over_floor_db"]:     # must not raise its own floor
            fm = V._formants(fr, self.fs)
            if fm:
                f1, f2 = fm
        voiced = bool(f0 > 0 and cl >= self.clarity_on and db >= floor + self.vo["level_over_floor_db"])
        f2 = self.f2c.push(f2 if voiced else np.nan)
        if np.isnan(f2):
            f1 = np.nan
        why = "" if voiced else ("quiet" if db < floor + self.vo["level_over_floor_db"] else
                                 "unclear" if cl < self.clarity_on else "no pitch")
        return Tick(t_ms, f0 if voiced else 0.0, cl, db, voiced, f1, f2, why, float(f0), db - floor)


# ------------------------------------------------------------------------------------ elements and the magnet

@dataclass
class Element:
    """A clickable element's bounds in dp (left, top, right, bottom) and a label."""
    l: float
    t: float
    r: float
    b: float
    label: str = ""

    @property
    def centre(self) -> tuple[float, float]:
        return (self.l + self.r) / 2, (self.t + self.b) / 2

    @property
    def area(self) -> float:
        return (self.r - self.l) * (self.b - self.t)

    def dist(self, x: float, y: float) -> float:
        """Distance from a point to the bounds (0 inside)."""
        dx = max(self.l - x, 0.0, x - self.r)
        dy = max(self.t - y, 0.0, y - self.b)
        return float(np.hypot(dx, dy))

    def contains(self, x: float, y: float) -> bool:
        return self.l <= x <= self.r and self.t <= y <= self.b


def magnet(elements: list[Element], x: float, y: float, snap_dp: float, max_area: float) -> int | None:
    """Index of the element the cursor snaps to, or None: the nearest within snap_dp, the smaller one on a tie."""
    best, key = None, None
    for i, e in enumerate(elements):
        if e.area > max_area:
            continue
        d = e.dist(x, y)
        if d <= snap_dp and (key is None or (d, e.area) < key):
            best, key = i, (d, e.area)
    return best


def snap_point(e: Element, x: float, y: float, centre_max_dp: float | None, inset_dp: float = 8.0) -> tuple[float, float]:
    """Where the cursor goes when it snaps to e: its centre, unless e is larger than centre_max_dp on a side (a list
    row, a panel); then just onto it (the nearest point inset_dp inside), so a big element never throws the cursor
    across the screen."""
    if centre_max_dp is None or max(e.r - e.l, e.b - e.t) <= centre_max_dp:
        return e.centre
    if e.contains(x, y):
        return x, y                                  # already on it: stay exactly where it stopped
    ix, iy = min(inset_dp, (e.r - e.l) / 2), min(inset_dp, (e.b - e.t) / 2)
    return min(max(x, e.l + ix), e.r - ix), min(max(y, e.t + iy), e.b - iy)


def hit(elements: list[Element], x: float, y: float) -> int | None:
    """The element a click at (x, y) lands on: the smallest containing it."""
    inside = [(e.area, i) for i, e in enumerate(elements) if e.contains(x, y)]
    return min(inside)[1] if inside else None


# ------------------------------------------------------------------------------------ the mover

@dataclass
class Sound:
    """One sound (a hum or sung vowel) while it lasts."""
    t_on: float
    last_voiced: float
    ref: float | None = None
    ref_t: float | None = None
    pos_at_ref: tuple[float, float] | None = None
    raw: list[tuple[float, float]] = field(default_factory=list)      # (t, st) accepted pitch frames
    jump: list[float] = field(default_factory=list)                   # pending out-of-guard frames (st)
    vx: list[tuple[float, float]] = field(default_factory=list)        # (t, x) vowel frames
    t_moving: float = 0.0
    idle_ms: float = 0.0
    path: list[tuple[float, float, float]] = field(default_factory=list)   # (t, x, y) after each tick
    reanchors: int = 0
    pos_on: tuple[float, float] = (0.0, 0.0)                          # where the cursor was when the sound started
    every: list[tuple[float, float, float]] = field(default_factory=list)   # (t, st, clarity) every voiced tick
    sm: list[tuple[float, float]] = field(default_factory=list)       # (t, smoothed st) since the last jump
    momentum: float = 0.0                                             # glide mode: -1 (down) .. 1 (up)
    gliding: bool = False
    undone: bool = False                                              # the onset undo fired
    gap_why: str = ""                                                 # why the current voice gap is unvoiced
    continued: int = 0                                                # ticks carried by the continue threshold


class Mover:
    """Ticks -> cursor. The position persists across sounds; only recentre() and set_screen() move it otherwise."""

    MODES = ("home", "glide", "start")

    def __init__(self, spec: dict, w_dp: float, h_dp: float, vowels: dict | None = None,
                 range_st: tuple[float, float] | None = None):
        self.s = spec
        self.p, self.vw, self.sp = spec["pitch"], spec["vowel"], spec["speed"]
        self.vt = spec["vertical"]
        self.mode = {"mid": "home"}.get(self.vt["mode"], self.vt["mode"])
        self.range = tuple(range_st or self.vt["home"]["range_st"])
        self.home_setup: float | None = None     # the relaxed hum from the setup (st); None = the range's middle
        self.home_hist: deque[float] = deque(maxlen=self.vt["home"]["adapt_hums"])   # recent hum-start pitches
        self.whistle: dict | None = None          # the calibrated whistle range {lo_st, hi_st, home_st, split_st}
        self.tick_ms = spec["tick"]["tick_ms"]
        self.w, self.h = w_dp, h_dp
        self.x, self.y = w_dp / 2, h_dp / 2
        self.cent = {k: np.array(v, float) for k, v in (vowels or spec["vowel"]["centroids_bark"]).items()
                     if k in ("ee", "ah", "oo")}
        self.run = 0
        self.sound: Sound | None = None
        self.elements: list[Element] = []
        self.snapped: int | None = None
        self.enabled = True                     # cursor mode on
        self.state = {}                         # last tick's readout (for the GUI)
        self.events: list[dict] = []            # hum_start / hum_end, drained by the caller
        self.last_stop = ""                     # why the last sound ended

    @property
    def mid(self) -> float:
        """The home-mode reference: the relaxed hum (from the setup, then the median start pitch of the last few
        hums, at most adapt_bound_st from the setup's), or the range's middle when there is no setup hum."""
        if self.home_setup is None:
            return (self.range[0] + self.range[1]) / 2
        h = self.vt["home"]
        if len(self.home_hist) < 3:
            return self.home_setup
        return float(np.clip(np.median(self.home_hist), self.home_setup - h["adapt_bound_st"],
                             self.home_setup + h["adapt_bound_st"]))

    def full_st(self, down: bool, whistle: bool = False) -> float:
        """home mode: the offset that gives full speed, per side (the room between home and the range's end). In the
        whistle band: the whistle range and the whistle home."""
        if whistle and self.whistle:
            w = self.whistle
            room = w["home_st"] - w["lo_st"] if down else w["hi_st"] - w["home_st"]
        else:
            room = self.mid - self.range[0] if down else self.range[1] - self.mid
        return max(self.p["dead_zone_st"] + 1.0, self.vt["home"]["full_frac"] * room)

    def in_whistle(self, sm: float) -> bool:
        """The pitch is in the whistle band: at or over the split between the voice range's top and the whistle
        range's bottom (calibration v2's whistle step)."""
        return self.whistle is not None and sm >= self.whistle["split_st"]

    def home_ref(self, sm: float) -> float:
        """home mode's reference for this pitch: the whistle home in the whistle band, else the voice home."""
        return self.whistle["home_st"] if self.in_whistle(sm) else self.mid

    def set_whistle(self, w: dict | None) -> None:
        self.whistle = dict(w) if w else None

    @property
    def mid_full_st(self) -> float:
        return self.full_st(False)

    def set_mode(self, mode: str) -> None:
        mode = {"mid": "home"}.get(mode, mode)
        assert mode in self.MODES, mode
        self.mode = mode

    def set_home(self, st: float) -> None:
        self.home_setup = float(st)
        self.home_hist.clear()

    def set_range(self, lo_st: float, hi_st: float) -> None:
        self.range = (float(lo_st), float(hi_st))

    # --- screen
    def set_screen(self, w_dp: float, h_dp: float, elements: list[Element]) -> None:
        """A new screen or a rotation: same coordinates, clamped into the new bounds."""
        self.w, self.h, self.elements = w_dp, h_dp, elements
        self.x, self.y = min(max(self.x, 0.0), w_dp), min(max(self.y, 0.0), h_dp)
        self.snapped = None

    def recentre(self) -> None:
        self.x, self.y, self.snapped = self.w / 2, self.h / 2, None

    # --- per tick
    def push(self, tk: Tick) -> None:
        self.run = self.run + 1 if tk.voiced else 0
        snd = self.sound
        if snd is None:
            if tk.voiced and self.run >= self.s["voicing"]["start_ticks"] and self.enabled:
                t_on = tk.t_ms - (self.run - 1) * self.tick_ms
                self.sound = snd = Sound(t_on=t_on, last_voiced=tk.t_ms, pos_on=(self.x, self.y))
                self.snapped = None
                self.events.append({"ev": "hum_start", "t_ms": t_on, "x": self.x, "y": self.y})
            else:
                self.state = {"t_ms": tk.t_ms, "phase": "idle", "db": tk.db, "mode": self.mode, "stop": self.last_stop}
                return
        if not self.enabled:
            self._end(tk.t_ms, "mode off")
            return
        vo = self.s["voicing"]
        if not tk.voiced:
            # hysteresis: a less clear tick continues the sound (creak, a breathy moment) if it is loud, has a pitch,
            # and that pitch is near the sound's; it then moves like a voiced tick. Only clear voice STARTS a sound.
            near = bool(snd.sm) and tk.f0_raw > 0 and abs(float(V.st(tk.f0_raw)) - snd.sm[-1][1]) <= vo["continue_near_st"]
            if tk.clarity >= vo["clarity_continue"] and tk.over_db >= vo["level_over_floor_db"] and near:
                tk = Tick(tk.t_ms, tk.f0_raw, tk.clarity, tk.db, True, np.nan, np.nan, "", tk.f0_raw, tk.over_db)
                snd.continued += 1
            else:
                if not snd.gap_why:
                    snd.gap_why = tk.why
                if tk.t_ms - snd.last_voiced >= vo["end_gap_ms"]:
                    self._end(tk.t_ms, tk.why)         # the cause at the end: quiet = you stopped
                else:
                    self.state = dict(self.state, phase="gap", t_ms=tk.t_ms)
                return
        snd.last_voiced, snd.gap_why = tk.t_ms, ""
        self._pitch(snd, tk)
        self._vowel(snd, tk)
        dx, dy = self._direction(snd, tk.t_ms)
        dt = self.tick_ms / 1000
        n = float(np.hypot(dx, dy))
        speed = 0.0
        if n > 0:
            snd.t_moving += self.tick_ms / 1000
            snd.idle_ms = 0.0
            ramp = min(1.0, snd.t_moving / self.sp["ramp_s"]) if self.sp.get("mode", "ramp") == "ramp" else 1.0
            speed = self.sp["start_dp_s"] + (self.sp["max_dp_s"] - self.sp["start_dp_s"]) * ramp
            if n > 1:
                dx, dy, n = dx / n, dy / n, 1.0
            nx, ny = self.x + dx * speed * dt, self.y + dy * speed * dt
            self.x, self.y = min(max(nx, 0.0), self.w), min(max(ny, 0.0), self.h)
            edge = [k for k, c in (("left", nx < 0), ("right", nx > self.w), ("top", ny < 0), ("bottom", ny > self.h)) if c]
            self.state["edge"] = "+".join(edge)
        else:
            snd.idle_ms += self.tick_ms
            if snd.idle_ms >= self.sp["ramp_reset_ms"]:
                snd.t_moving = 0.0
        snd.path.append((tk.t_ms, self.x, self.y))
        moving = snd.ref is not None if self.mode == "start" else tk.t_ms - snd.t_on >= self.p["attack_ms"]
        self.state.update({"t_ms": tk.t_ms, "phase": "move" if moving else "settle", "dx": dx, "dy": dy,
                           "speed": speed * n, "db": tk.db, "mode": self.mode, "hz": tk.f0, "momentum": snd.momentum,
                           "stop": self.last_stop})

    def _pitch(self, snd: Sound, tk: Tick) -> None:
        p = self.p
        s = float(V.st(tk.f0))
        n_s = max(1, round(p["smooth_ms"] / self.tick_ms))
        recent = [v for _, v in snd.raw[-n_s:]]
        if recent and abs(s - float(np.median(recent))) > p["jump_guard_st"]:
            snd.jump.append(s)                       # an octave error, or a real leap: wait and see
            if len(snd.jump) * self.tick_ms < p["jump_persist_ms"]:
                return
            snd.raw = [(tk.t_ms, v) for v in snd.jump]   # it held: the new pitch replaces the history
            snd.jump, snd.sm, snd.gliding = [], [], False  # ... and a jump is never a glide
        else:
            snd.jump = []
            snd.raw.append((tk.t_ms, s))
        snd.every.append((tk.t_ms, s, tk.clarity))
        # the reference: the first settled window after the attack
        n_w = max(1, round(p["settle_ms"] / self.tick_ms))
        w = [v for t, v in snd.raw[-n_w:] if t >= snd.t_on + p["attack_ms"]]
        settled = len(w) >= n_w and max(w) - min(w) <= 2 * p["settle_tol_st"]
        sm = float(np.mean([v for _, v in snd.raw[-n_s:]]))
        snd.sm.append((tk.t_ms, sm))
        if self.mode != "start":
            self._onset_undo(snd, tk.t_ms, w, settled)
            if self.mode == "glide":
                self._glide(snd, tk.t_ms)
        if snd.ref is None:
            late = tk.t_ms - snd.t_on >= p["settle_max_ms"] and len(w) >= max(1, n_w // 2)
            if settled or late:
                snd.ref, snd.ref_t, snd.pos_at_ref = float(np.median(w)), tk.t_ms, (self.x, self.y)
        elif (self.mode == "start" and settled and tk.t_ms - snd.t_on <= p["reanchor_grace_ms"]
              and abs(float(np.median(w)) - snd.ref) >= p["reanchor_min_st"]):
            snd.ref = float(np.median(w))                # an onset blip: re-anchor and undo the motion since
            self.x, self.y = snd.pos_at_ref
            snd.ref_t, snd.t_moving, snd.reanchors = tk.t_ms, 0.0, snd.reanchors + 1
        ref = {"home": self.home_ref(sm), "glide": None, "start": snd.ref}[self.mode]
        self.state.update({"st": s, "sm": sm, "ref": ref, "offset": (sm - ref) if ref is not None else None,
                           "band": "whistle" if self.in_whistle(sm) else "voice"})

    def _onset_undo(self, snd: Sound, t_ms: float, w: list[float], settled: bool) -> None:
        """mid / glide: a note that settles far ABOVE the sound's first frames, soon after onset, means the onset was a
        creak or a scoop from below: undo the motion so far (vertical.onset_undo)."""
        ou = self.vt["onset_undo"]
        if snd.undone or not settled or t_ms - snd.t_on > ou["grace_ms"]:
            return
        n_w = len(w)
        early = [(v, c) for t, v, c in snd.every if t < t_ms - n_w * self.tick_ms]
        if len(early) < 3:
            return
        if float(np.median(w)) - float(np.median([v for v, _ in early])) < ou["min_below_st"]:
            return
        if ou.get("clarity_max") is not None and float(np.median([c for _, c in early])) >= ou["clarity_max"]:
            return
        snd.undone = True
        self.x, self.y = snd.pos_on
        snd.t_moving, snd.momentum, snd.gliding = 0.0, 0.0, False
        snd.sm = snd.sm[-1:]
        snd.reanchors += 1

    def _glide(self, snd: Sound, t_ms: float) -> None:
        """glide mode: the pitch's direction of travel adds to the vertical momentum; a held note keeps it."""
        g = self.vt["glide"]
        if t_ms - snd.t_on < self.p["attack_ms"] or len(snd.sm) < 2:
            return
        old = [v for t, v in snd.sm if t <= t_ms - g["window_ms"]]
        if not old:
            return
        change = snd.sm[-1][1] - old[-1]
        if abs(change) >= g["min_st"]:
            step = snd.sm[-1][1] - snd.sm[-2][1]
            if not snd.gliding:                      # the glide just crossed the gate: count it from its start
                step, snd.gliding = change, True
            snd.momentum = float(np.clip(snd.momentum + step / g["full_st"], -1.0, 1.0))
        else:
            snd.gliding = False

    def vowel_weights(self, f1: float, f2: float) -> dict[str, float] | None:
        """Soft weights over ee / ah / oo, or None (no formants, or nothing near a centre)."""
        if np.isnan(f1) or np.isnan(f2) or not self.cent:
            return None
        return self.vowel_weights_bark(float(V.bark(f1)), float(V.bark(f2)))

    def vowel_weights_bark(self, b1: float, b2: float) -> dict[str, float] | None:
        pt = np.array([b1, b2])
        d = {k: float(np.linalg.norm(pt - c)) for k, c in self.cent.items()}
        if min(d.values()) > self.vw["reject_bark"]:
            return None
        sg = self.vw["sigma_bark"]
        w = {k: np.exp(-v * v / (2 * sg * sg)) for k, v in d.items()}
        tot = sum(w.values())
        return {k: float(v / tot) for k, v in w.items()}

    def _vowel(self, snd: Sound, tk: Tick) -> None:
        w = self.vowel_weights(tk.f1, tk.f2)
        if w is not None:
            snd.vx.append((tk.t_ms, w.get("ee", 0.0) - w.get("oo", 0.0)))
        self.state["vowel"] = w

    def _direction(self, snd: Sound, t_ms: float) -> tuple[float, float]:
        p, vw = self.p, self.vw
        if self.mode == "start" and snd.ref is None or not snd.sm or t_ms - snd.t_on < p["attack_ms"]:
            return 0.0, 0.0
        if self.mode == "glide":
            dead = self.vt["glide"]["dead"]           # momentum up = up = smaller y
            dy = -np.sign(snd.momentum) * min(1.0, max(0.0, (abs(snd.momentum) - dead) / (1 - dead)))
        else:
            sm = snd.sm[-1][1]
            off = sm - (self.home_ref(sm) if self.mode == "home" else snd.ref)
            full = self.full_st(off < 0, self.in_whistle(sm)) if self.mode == "home" else p["full_speed_st"]
            mag = min(1.0, max(0.0, (abs(off) - p["dead_zone_st"]) / (full - p["dead_zone_st"])))
            dy = -np.sign(off) * mag                 # higher pitch = up = smaller y
        xs = [x for t, x in snd.vx if t > t_ms - vw["smooth_ms"]]
        x = float(np.mean(xs)) if xs else 0.0
        mx = min(1.0, max(0.0, (abs(x) - vw["dead_zone"]) / (vw["full"] - vw["dead_zone"])))
        self.state["x_vowel"] = x
        return float(np.sign(x) * mx), float(dy)

    def _end(self, t_ms: float, why: str = "") -> None:
        snd = self.sound
        self.sound = None
        self.last_stop = {"quiet": "quiet (level < floor+6dB)", "unclear": "unclear (clarity < 0.8)",
                          "no pitch": "no pitch"}.get(why, why)
        cut = snd.last_voiced - self.s["release"]["rewind_ms"]
        before = [(x, y) for t, x, y in snd.path if t <= cut]
        if snd.path:                                   # rewind the release (never to before the sound)
            self.x, self.y = before[-1] if before else (snd.pos_at_ref or snd.pos_on)
        stop = (self.x, self.y)
        first = [v for _, v, _ in snd.every[:6]]                # the hum's start pitch adapts home (not creak)
        if first and snd.last_voiced - snd.t_on >= 200 and self.range[0] - 1 <= np.median(first) <= self.range[1] + 1:
            self.home_hist.append(float(np.median(first)))
        mg = self.s["magnet"]
        self.snapped = magnet(self.elements, self.x, self.y, mg["snap_dp"], mg["max_area_frac"] * self.w * self.h)
        if self.snapped is not None:
            self.x, self.y = snap_point(self.elements[self.snapped], self.x, self.y, mg.get("centre_max_dp"))
        self.events.append({"ev": "hum_end", "t_ms": t_ms, "t_on": snd.t_on, "stop": stop, "x": self.x, "y": self.y,
                            "snapped": self.snapped, "path": snd.path, "reanchors": snd.reanchors,
                            "dur_ms": snd.last_voiced - snd.t_on, "why": self.last_stop, "mode": self.mode,
                            "continued": snd.continued})
        self.state = {"t_ms": t_ms, "phase": "idle", "mode": self.mode, "stop": self.last_stop}


class Clicker:
    """Pop events -> a click after the pop-pop gap; a second pop inside the gap is pop pop (listen, not a click)."""

    def __init__(self, spec: dict):
        self.gap = spec["click"]["pop_seq_gap_ms"]
        self.pending: float | None = None

    def pop(self, t_ms: float) -> str | None:
        if self.pending is not None and t_ms - self.pending <= self.gap:
            self.pending = None
            return "pop_pop"
        self.pending = t_ms
        return None

    def poll(self, t_ms: float) -> str | None:
        if self.pending is not None and t_ms - self.pending > self.gap:
            self.pending = None
            return "click"
        return None


def screen_from_harvest(row: dict, dpi: float = 420.0) -> tuple[float, float, list[Element]]:
    """A harvested emulator screen (1080 x 2400 px at 420 dpi) -> (w_dp, h_dp, elements in dp)."""
    k = DP_PER_INCH / dpi
    els = []
    for b, name in zip(row["bounds"], row["options"]):
        if not b:
            continue
        els.append(Element(b[0] * k, b[1] * k, b[2] * k, b[3] * k, name.split(" (")[0]))
    return 1080 * k, 2400 * k, els


class PopDetector:
    """Ticks -> pops, from the level alone: a burst from quiet that rises at least rise_db in one tick on the way up,
    peaks at least peak_db over the floor at most peak_within ticks after it first comes within lead_db of that
    peak (impulsive: whatever lead-in it has, the pop itself is sudden), has at most core_ticks within core_db of its peak
    (a lip pop is one impulse with a decaying tail, a hum or a word is not), lasts at most max_ticks at loud_db or
    more, has at most max_voiced voiced ticks (a pop's ring can read as voiced for a tick), and is followed by
    confirm_ms with no voiced tick and nothing confirm_db over the floor (a plosive starting a word or a hum is not). It must also start after_voice_ms
    after the last voiced run, and not in the first warmup_ms (the floor is still settling). Bursts within merge_ms of a pop are the same pop (a lip pop can ring twice). Reported
    confirm_ms after the burst ends, with the burst's start time."""

    def __init__(self, spec: dict):
        self.c = dict(spec["pop"])
        self.hist: deque[Tick] = deque(maxlen=self.c["quiet_ticks"])
        self.burst: list[Tick] | None = None
        self.before = 0.0
        self.pending: tuple[float, float] | None = None     # (t_start, t_confirm)
        self.run = 0
        self.last_voice = -1e9                               # end of the last run of 3+ voiced ticks
        self.last_pop = -1e9
        self.bursts: list[dict] = []                         # every burst it judged (for the setup and the trace)

    def features(self, b: list[Tick]) -> dict:
        ov = np.array([t.over_db for t in b])
        pk = int(np.argmax(ov))
        lead = int(np.argmax(ov >= ov[pk] - self.c["lead_db"]))      # the first tick out of its lead-in
        rise = max(ov[i] - (ov[i - 1] if i else self.before) for i in range(pk + 1))
        return {"t": b[0].t_ms, "ticks": len(b), "peak_db": float(ov[pk]), "peak_i": pk - lead, "rise_db": float(rise),
                "core": int(np.sum(ov >= ov[pk] - self.c["core_db"])), "voiced": sum(t.voiced for t in b)}

    def judge(self, f: dict) -> bool:
        c = self.c
        return (f["ticks"] <= c["max_ticks"] and f["core"] <= c["core_ticks"] and f["peak_i"] <= c["peak_within"]
                and f["peak_db"] >= c["peak_db"] and f["rise_db"] >= c["rise_db"] and f["voiced"] <= c["max_voiced"])

    def push(self, tk: Tick) -> float | None:
        c, out = self.c, None
        self.run = self.run + 1 if tk.voiced else 0
        if self.run >= 3:
            self.last_voice = tk.t_ms
            self.pending = None                              # voice right after the burst: a plosive, not a pop
            self.burst = None
        loud = tk.over_db >= c["loud_db"]
        if self.pending and (tk.over_db >= c["confirm_db"] or tk.voiced):
            self.pending = None                              # more sound right after it: a word, not a pop
        if self.pending and tk.t_ms >= self.pending[1]:
            out, self.pending = self.pending[0], None
            self.last_pop = out
        if self.burst is None:
            quiet = len(self.hist) == self.hist.maxlen and all(t.over_db < c["loud_db"] for t in self.hist)
            if loud and quiet and tk.t_ms - self.last_voice >= c["after_voice_ms"] and tk.t_ms >= c["warmup_ms"]:
                self.burst, self.before = [tk], self.hist[-1].over_db
        elif loud and len(self.burst) <= c["max_ticks"]:
            self.burst.append(tk)
        else:
            b, self.burst = self.burst, None
            f = self.features(b)
            f["pop"] = self.judge(f) and b[0].t_ms - self.last_pop > c["merge_ms"]
            self.bursts.append(f)
            if f["pop"]:
                self.pending = (b[0].t_ms, tk.t_ms + c["confirm_ms"])
        self.hist.append(tk)
        return out

    def calibrate(self, pops: list[dict]) -> dict:
        """Thresholds from the setup's pops (burst features): half the weakest's dB (a pop in use can be softer than
        a pop asked for), within bounds."""
        c, cal = self.c, self.c["calibrate"]
        if len(pops) < 2:
            return {}
        new = {"peak_db": float(np.clip(min(p["peak_db"] for p in pops) * cal["peak_frac"], *cal["peak_db"])),
               "rise_db": float(np.clip(min(p["rise_db"] for p in pops) * cal["rise_frac"], *cal["rise_db"])),
               "core_ticks": int(np.clip(max(p["core"] for p in pops) + 1, *cal["core_ticks"]))}
        c.update(new)
        return new


# ------------------------------------------------------------------------------------ calibration v2: discrete sounds

GATE_LABELS = ("pop", "click", "hiss")
# what the app gates on the phone / USB mic: also `unknown`, which the app's trained-gesture relabel (after the mic)
# could otherwise turn into a click or a pop
PHONE_GATE_LABELS = GATE_LABELS + ("unknown",)
CLICK_POP_FEATURES = ("dur_ms", "snr_db", "level_db", "lf_ratio")


def example(raw: dict) -> dict:
    """The numbers a calibration keeps of one extractor event (its gate raw): nothing else, no audio."""
    out = {}
    for k in ("dur_ms", "snr_db", "level_db", "lf_ratio", "peak_centroid_hz"):
        v = raw.get(k)
        out[k] = None if v is None else round(float(v), 4 if k == "lf_ratio" else 2)
    return out


def derive_gate(examples: dict[str, list[dict]], room: dict | None, spec: dict) -> dict:
    """The per-mic level gate (spec level_gate): a discrete sound (pop / click / hiss, whatever the extractor labelled
    it) must reach min_snr_db over the floor AND min_level_dbfs. One pair per mic, from the weakest example of the
    discrete steps (examples: {"pops": [...], "clicks": [...], "hiss": [...]}, extractor raw numbers): the weakest
    minus margin_*_db, but at least the room's loudest transient plus room_margin_db, and never above the weakest
    minus cap_below_weakest_db (a calibrated example always passes). One pair and not one per label: the extractor
    often labels one gesture as another (the guided clicks came out as hiss and as pop), and a per-label gate lost
    9 % of the held-out real sounds against 0.3 % (eval_real/level_gate.py). Only with examples from the clicks step
    (the quietest gesture: the guided clicks are 14-24 dB over the floor, the pops 28-41): without them the default."""
    g = spec["level_gate"]
    d = g["default"]
    ex = [e for k in ("pops", "clicks", "hiss") for e in examples.get(k) or []
          if e.get("snr_db") is not None and e.get("level_db") is not None]
    if not ex or not any(e.get("snr_db") is not None for e in examples.get("clicks") or []):
        return {"min_snr_db": float(d["min_snr_db"]), "min_level_dbfs": float(d["min_level_dbfs"]),
                "from": "default", "n": 0}
    ws, wl = min(e["snr_db"] for e in ex), min(e["level_db"] for e in ex)
    s, lv = ws - g["margin_snr_db"], wl - g["margin_level_db"]
    if room and room.get("transient_snr_db") is not None:
        s = max(s, room["transient_snr_db"] + g["room_margin_db"])
    if room and room.get("transient_level_dbfs") is not None:
        lv = max(lv, room["transient_level_dbfs"] + g["room_margin_db"])
    s, lv = min(s, ws - g["cap_below_weakest_db"]), min(lv, wl - g["cap_below_weakest_db"])
    return {"min_snr_db": round(float(s), 2), "min_level_dbfs": round(float(lv), 2), "from": "calibration",
            "n": len(ex), "weakest_snr_db": round(float(ws), 2), "weakest_level_dbfs": round(float(wl), 2)}


def default_gate(spec: dict) -> dict:
    return derive_gate({}, None, spec)


def gate_reason(gate: dict | None, label: str, snr_db: float | None, level_db: float | None,
                offset_db: float = 0.0, labels: tuple = GATE_LABELS) -> dict | None:
    """None = the sound passes (not a discrete label, no numbers, or loud enough); else what it missed. offset_db
    moves both thresholds (+ = stricter)."""
    if not gate or label not in labels or snr_db is None or level_db is None:
        return None
    ms, ml = gate["min_snr_db"] + offset_db, gate["min_level_dbfs"] + offset_db
    if snr_db >= ms and level_db >= ml:
        return None
    return {"reason": "below level gate", "label": label, "snr_db": round(float(snr_db), 2),
            "level_dbfs": round(float(level_db), 2), "min_snr_db": round(float(ms), 2),
            "min_level_dbfs": round(float(ml), 2), "from": gate.get("from", "default")}


def derive_click_pop(pops: list[dict], clicks: list[dict], spec: dict) -> dict | None:
    """Per person, from the pops and clicks steps: a feature separates when every pop is on one side and every click
    on the other with at least the feature's min_gap between them; its threshold is the gap's middle. None when fewer
    than min_votes features separate (the rule is then never confident)."""
    c = spec["click_pop"]
    feats = {}
    for f, gap in c["min_gap"].items():
        p = [e[f] for e in pops if e.get(f) is not None]
        k = [e[f] for e in clicks if e.get(f) is not None]
        if len(p) < c["min_each"] or len(k) < c["min_each"]:
            continue
        if min(p) - max(k) >= gap:
            feats[f] = {"thr": round((min(p) + max(k)) / 2, 4), "pop_above": True}
        elif min(k) - max(p) >= gap:
            feats[f] = {"thr": round((min(k) + max(p)) / 2, 4), "pop_above": False}
    return {"features": feats, "min_votes": c["min_votes"]} if len(feats) >= c["min_votes"] else None


def click_pop_vote(rule: dict | None, raw: dict) -> dict | None:
    """The rule's reading of one sound: {"label": "pop" | "click", "votes": {feature: label}} when at least min_votes
    separating features have a value and all of them agree; else None (not confident)."""
    if not rule:
        return None
    votes = {}
    for f, t in rule["features"].items():
        v = raw.get(f)
        if v is None:
            continue
        above = float(v) > t["thr"]
        votes[f] = "pop" if above == t["pop_above"] else "click"
    if len(votes) < rule["min_votes"] or len(set(votes.values())) != 1:
        return None
    return {"label": next(iter(votes.values())), "votes": votes}


def relabel(rule: dict | None, label: str, raw: dict) -> dict | None:
    """pop <-> click only, only when the per-person rule is confident and says the other one: {"from", "to", "votes"}."""
    if label not in ("pop", "click"):
        return None
    v = click_pop_vote(rule, raw)
    if v is None or v["label"] == label:
        return None
    return {"from": label, "to": v["label"], "votes": v["votes"]}
