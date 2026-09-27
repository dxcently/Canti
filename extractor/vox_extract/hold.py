"""Hold messages: a live report while a steady tone is still going (hold-to-scroll).

A sound is normally reported once, when it ends. For "hum a swipe, then hold a flat hum to keep scrolling" the phone
must know that a tone is being held NOW and when it stops, so the extractor sends two small messages per held sound:

  hold start  once, while the gate is open, at the first frame above the close threshold where the sound has lasted
              hold_start_ms and its last hold_start_ms of frames look like one steady tone:
                voiced fraction >= hold_min_voiced_frac (voiced = as classify: clarity, f0, level over the floor),
                median clarity >= hold_min_clarity,
                |median pitch of the later half - earlier half of the voiced frames| <= hold_max_drift_st,
                median absolute deviation of the pitch <= hold_max_mad_st,
                pitch std >= machine_max_pitch_std_st (a perfectly steady motor is not a voice).
              It carries the window's median f0 and `flat`: the window's pitch is within hold_flat_st of the sound's
              start pitch (a sound that moved and then settled is steady but not flat).
              Glide-and-hold comes first: once the sound's last hold_glide_ms (250) pass the same steadiness test and
              their median pitch is at least hold_glide_min_st from the sound's start pitch and within
              hold_glide_peak_st of its highest (up) / lowest (down) voiced pitch so far, and that test has then
              passed on every frame for hold_glide_delay_ms more (late start), `hold start` goes out, with from =
              "glide" and dir = "up" / "down" (flat = False). Only a sound after at least hold_glide_quiet_ms of
              quiet (from the previous sound's end) is tested. A rise / fall whose end note is held that long thus
              becomes a hold in the glide's direction; one with a shorter tail stays a plain rise / fall.
  hold pitch  after hold start, every hold_pitch_ms of the sound while it is still going (0 = never): the median f0
              of the voiced frames since the last report (skipped when under hold_pitch_min_voiced_frac of them are
              voiced). The phone's pitch throttle scales the hold-scroll speed by it (PROTOCOL.md "Hold pitch").
              Compact on purpose (~60 bytes, 5 per second at 200 ms): no t_start_ms, no flat.
  hold end    when that sound's gate closes, before its event (the event then carries held = True).

Pops, clicks and hisses never qualify (too short, or unvoiced). Every sound gets an id (1, 2, ... per stream) that its
hold messages and its event share. The test reads only the sound's own per-frame arrays (e_db, f0, clarity).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Config
from .segmenter import SegmentStats


@dataclass
class Hold:
    kind: str            # "start" | "pitch" | "end"
    sound: int           # the sound's id (its event carries the same)
    t_start_ms: int      # the sound's start (as its event's t_start_ms)
    t_ms: int            # start / pitch: how far the sound had got; end: the sound's end (its t_end_ms)
    f0_hz: float = 0.0   # start and pitch: median f0 of the window
    flat: bool = False   # start only
    source: str = ""     # start only: "glide" (glide-and-hold), "" (a steady hum)
    dir: str = ""        # start only, glide: "up" | "down"

    def to_dict(self) -> dict:
        if self.kind == "pitch":
            return {"hold": "pitch", "sound": self.sound, "t_ms": self.t_ms, "f0_hz": self.f0_hz}
        d = {"hold": self.kind, "sound": self.sound, "t_start_ms": self.t_start_ms, "t_ms": self.t_ms}
        if self.kind == "start":
            d["f0_hz"] = self.f0_hz
            d["flat"] = self.flat
            if self.source:
                d["from"] = self.source
                d["dir"] = self.dir
        return d


def hold_window(cfg: Config) -> int:
    """Frames in the hold window; 0 = hold messages off."""
    if cfg.hold_start_ms <= 0:
        return 0
    return max(2, int(round(cfg.hold_start_ms / cfg.frame_ms)))


def glide_window(cfg: Config) -> int:
    """Frames in the glide-and-hold window; 0 = off."""
    if cfg.hold_glide_ms <= 0:
        return 0
    return max(2, int(round(cfg.hold_glide_ms / cfg.frame_ms)))


def glide_delay(cfg: Config) -> int:
    """Frames the glide test must keep passing after it first does before hold start goes out (0 = at once)."""
    if cfg.hold_glide_delay_ms <= 0:
        return 0
    return max(1, int(round(cfg.hold_glide_delay_ms / cfg.frame_ms)))


def pitch_frames(cfg: Config) -> int:
    """Frames between hold pitch reports; 0 = none."""
    if cfg.hold_pitch_ms <= 0:
        return 0
    return max(1, int(round(cfg.hold_pitch_ms / cfg.frame_ms)))


def pitch_report(seg: SegmentStats, cfg: Config, k: int) -> float | None:
    """Median f0 (Hz, 0.1) of the voiced frames among the sound's last k frames, or None if too few are voiced."""
    if k <= 0 or seg.n < k:
        return None
    e, f0, clar = np.array(seg.e_db[-k:]), np.array(seg.f0[-k:]), np.array(seg.clarity[-k:])
    voiced = _voiced(e, f0, clar, seg.floor_db, cfg)
    nv = int(np.count_nonzero(voiced))
    if nv == 0 or nv / k < cfg.hold_pitch_min_voiced_frac:
        return None
    return round(float(np.median(f0[voiced])), 1)


def _t(ms: float) -> int:
    return int(round(max(0.0, ms)))


def _voiced(e: np.ndarray, f0: np.ndarray, clar: np.ndarray, floor_db: float, cfg: Config) -> np.ndarray:
    return (clar >= cfg.voiced_clarity) & (f0 > 0) & (e >= floor_db + cfg.voiced_min_db_over_floor)


def check(seg: SegmentStats, cfg: Config, w: int) -> tuple[float, bool] | None:
    """The hold test on the sound's last w frames. Returns (f0_hz, flat) if it qualifies, else None."""
    med = _steady(seg, cfg, w)
    if med is None:
        return None
    return _hz(med), abs(med - _start_st(seg, cfg)) <= cfg.hold_flat_st


def glide_check(seg: SegmentStats, cfg: Config, w: int) -> tuple[float, str] | None:
    """Glide-and-hold on the sound's last w frames: steady, and at least hold_glide_min_st away from the sound's
    start pitch. Returns (f0_hz, "up" | "down") if it qualifies, else None."""
    med = _steady(seg, cfg, w)
    if med is None:
        return None
    d = med - _start_st(seg, cfg)
    if abs(d) < cfg.hold_glide_min_st:
        return None
    if cfg.hold_glide_peak_st > 0:
        ea, fa, ca = np.array(seg.e_db), np.array(seg.f0), np.array(seg.clarity)
        st = 12.0 * np.log2(fa[_voiced(ea, fa, ca, seg.floor_db, cfg)] / 100.0)
        peak = float(np.max(st)) if d > 0 else float(np.min(st))
        if abs(peak - med) > cfg.hold_glide_peak_st:
            return None
    return _hz(med), "up" if d > 0 else "down"


def _hz(st: float) -> float:
    return round(float(100.0 * 2.0 ** (st / 12.0)), 1)


def _start_st(seg: SegmentStats, cfg: Config) -> float:
    """The sound's start pitch (st re 100 Hz): median of its first edge_frames voiced frames (all its frames so far).
    Only called after _steady passed, so there is at least one voiced frame."""
    ea, fa, ca = np.array(seg.e_db), np.array(seg.f0), np.array(seg.clarity)
    fv = fa[_voiced(ea, fa, ca, seg.floor_db, cfg)][:cfg.edge_frames]
    return float(np.median(12.0 * np.log2(fv / 100.0)))


def _steady(seg: SegmentStats, cfg: Config, w: int) -> float | None:
    """The steadiness test on the sound's last w frames: their median pitch (st re 100 Hz) if they look like one
    steady voiced tone, else None."""
    if w <= 0 or seg.n < w:
        return None
    e = np.array(seg.e_db[-w:])
    f0 = np.array(seg.f0[-w:])
    clar = np.array(seg.clarity[-w:])
    voiced = _voiced(e, f0, clar, seg.floor_db, cfg)
    nv = int(np.count_nonzero(voiced))
    if nv < 2 or nv / w < cfg.hold_min_voiced_frac:
        return None
    if float(np.median(clar)) < cfg.hold_min_clarity:
        return None
    st = 12.0 * np.log2(f0[voiced] / 100.0)
    h = nv // 2
    if abs(float(np.median(st[h:]) - np.median(st[:h]))) > cfg.hold_max_drift_st:
        return None
    med = float(np.median(st))
    if float(np.median(np.abs(st - med))) > cfg.hold_max_mad_st:
        return None
    if float(np.std(st)) < cfg.machine_max_pitch_std_st:
        return None
    return med


class HoldTracker:
    """Per stream: numbers the sounds and sends hold start / pitch / end. Fed by the Extractor after every frame."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.w = hold_window(cfg)
        self.wg = glide_window(cfg)
        self.dg = glide_delay(cfg)
        self.pk = pitch_frames(cfg)
        self.next_pitch = 0       # seg.n at which the next hold pitch is due
        self.sound = 0            # id of the current (or last) sound
        self.cur: SegmentStats | None = None
        self.held = False         # hold start was sent for the current sound
        self.glide_ok = False     # the current sound came after hold_glide_quiet_ms of quiet
        self.glide_run = 0        # frames in a row the glide test has passed (late start)
        self.last_end: int | None = None   # the previous sound's end (ms); None = none yet in this stream

    def _open(self, seg: SegmentStats) -> None:
        self.sound += 1
        self.cur = seg
        self.held = False
        self.glide_run = 0
        self.glide_ok = self.last_end is None or _t(seg.t_start_ms) - self.last_end >= self.cfg.hold_glide_quiet_ms

    def frame(self, seg: SegmentStats | None, active: bool, out: list) -> None:
        """After a frame: seg = the open sound (or None), active = this frame was added to it (not hangover)."""
        if seg is None:
            return
        if seg is not self.cur:
            self._open(seg)
        if not active or self.w <= 0:
            return
        if self.held:
            if self.pk > 0 and seg.n >= self.next_pitch:
                self.next_pitch = seg.n + self.pk
                f = pitch_report(seg, self.cfg, self.pk)
                if f is not None:
                    out.append(Hold("pitch", self.sound, _t(seg.t_start_ms), _t(seg.t_start_ms + seg.n * self.cfg.frame_ms), f))
            return
        t0, t = _t(seg.t_start_ms), _t(seg.t_start_ms + seg.n * self.cfg.frame_ms)
        g = glide_check(seg, self.cfg, self.wg) if self.wg > 0 and self.glide_ok else None   # glide-and-hold first
        if g is not None:
            self.glide_run += 1
            if self.glide_run <= self.dg:   # late start: not yet (the flat test waits too)
                return
            self.held = True
            self.next_pitch = seg.n + self.pk
            out.append(Hold("start", self.sound, t0, t, g[0], False, "glide", g[1]))
            return
        self.glide_run = 0
        r = check(seg, self.cfg, self.w)
        if r is not None:
            self.held = True
            self.next_pitch = seg.n + self.pk
            out.append(Hold("start", self.sound, t0, t, r[0], r[1]))

    def closed(self, seg: SegmentStats, out: list) -> tuple[int, bool]:
        """The sound ended (call before its event). Returns (sound id, held)."""
        if seg is not self.cur:   # not seen open (cannot happen: a sound is open for at least one frame)
            self._open(seg)
        held = self.held
        self.last_end = _t(seg.t_start_ms + seg.n * self.cfg.frame_ms)
        if held:
            out.append(Hold("end", self.sound, _t(seg.t_start_ms), self.last_end))
        self.cur = None
        self.held = False
        return self.sound, held
