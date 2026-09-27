#!/usr/bin/env python3
"""Voice joystick prototype (wiki/voice-cursor.md, "Joystick cursor"): a fake phone screen driven live by the mic.

Sing, and the cursor moves while the sound lasts. Up/down has three modes, switched live:
  1  home (default) pitch ABOVE your home note moves up, BELOW moves down, further off = faster. Home is your
                    relaxed hum from the setup, then it follows the median start note of your last hums (at most 2 st
                    away). The strip at the phone's right edge shows your range, home (the dead zone around it) and
                    your pitch.
  2  glide          the direction your pitch MOVES steers: glide up = up, glide down = down, and a held note keeps
                    going the same way; glide back to stop going up/down. No range needed.
  3  start          the first prototype: above/below the note the sound STARTED on.
"ee" moves it right, "oo" left, "ah" not sideways; mix them for diagonals. The longer a sound lasts, the faster it
goes (a short sound is a nudge). Stop singing: it stops there, and if a clickable element is within a finger's width
(48 dp) it snaps to it and highlights it. A lip pop clicks (after the pop-pop gap); SPACE does the same.

Setup (about 20-25 s; skip it with --skip-setup, which reuses the last one): on the mic it asks for
  1. a relaxed 'mm' hum, 3 s, at the note that comes out without thinking -> home, and your own voicing threshold
  2. a 5 s glide over your whole range (lowest comfortable note to highest and back) -> the range (creak dropped)
  3. 'ee', 'ah', 'oo' held about 2 s each -> the vowel centres; it prints how well they separate
  4. three lip pops, a second apart -> the pop detector's thresholds; it prints how many it heard (n/3)
  5. three single tongue clicks -> the level gate's quietest example, and the per-person click / pop rule
  6. a 5 s whistle glide, lowest to highest and back -> the whistle range (its own home), beside the voice range
  7. two short 'tss' hisses -> the level gate
  8. 3 s of silence -> the room's noise floor and its loudest transient (the level gate stays above it)
It saves recordings/joystick/range.json (range, home, voicing threshold), vowels.json, pops.json and calib2.json
(clicks, whistle, hiss, room, the level gate and the click / pop rule; numbers only).
A step that fails says why and WAITS: R = retry that step, S = skip it (its defaults stay: the spec's voicing threshold,
the range's middle as home, the spec's range, the default vowel centres, the default pop thresholds). Failures: nothing
steady heard within 10 s of the prompt (home, range, each vowel), a hum too short or rough, a range under 4 st, a vowel
with too few clear frames in 12 s or vowels that overlap (a vowel steers its own way under half the time), fewer than
2 of 3 pops, fewer than 2 of 3 clicks or 2 of 2 hisses in 8 s, no steady whistle in 10 s, a whistle range under
3 st or one that overlaps the voice range, a steady tone in the room, or a room transient as loud as the quietest
calibrated sound. Skipped steps are listed in range.json ("skipped"); a skipped pops / vowels step writes its file with
"skipped" and no numbers, so --skip-setup (and eval_real/calib_gestures.py) keeps the defaults for it.
--setup-steps clicks,whistle,hiss,room runs only those steps, in that order, on top of the last saved setup (the app's
calib_start {steps}): the other steps keep their saved values and skip state; the setup ends after the last listed step
(a skip never wraps round to another step).

The level gate (calibration v2; joystick_core.derive_gate, spec level_gate): after the setup, a discrete sound (pop,
click, hiss) quieter than the quietest calibrated one minus a margin is ignored ("below level gate" in the log).
The click / pop rule relabels a pop as a click (or back) only when the person's own pops and clicks separate on at
least two features and all of them agree; each relabel is logged. A whistle over the split between the voice range's
top and the whistle range's bottom steers against the whistle home and range (home mode).

The phone is a harvested emulator screen (1080 x 2400 px at 420 dpi = 411 x 914 dp, finetune/data/real-targets-v2/
emulator: screenshot + clickable bounds). All settings are in prompts/joystick_v1.json; the logic is
joystick_core.py, the part meant for the app.

Keys:  1 / 2 / 3 = vertical mode home / glide / start   space = pop (click) by key   c = recentre
       m = cursor mode on/off   r = rotate   n / p = next / previous screen   t = start the task
       h = home hum   g = range glide   v = vowels   o = pops   k = clicks   w = whistle   x = hiss   b = room
       s = the whole setup   q / Esc = quit (task saved)
       after a failed setup step: r = retry the step, s = skip it (nothing else moves until you choose)

Commands
  ./run python joystick.py --task 12 --trace               # setup, then the scored task: 12 random targets
  ./run python joystick.py --vowels recordings/vcursor-2    # range + vowel centres from a voice_cursor session
  ./run python joystick.py --skip-setup                     # reuse the last setup (range, home, vowels, pops)
  ./run python joystick.py --setup-steps clicks,whistle,hiss,room   # the last setup + only the calibration v2 steps
  ./run python joystick.py --source fake --task 12          # SYNTHETIC singer drives it (watch it)
  ./run python joystick.py --source fake --task 30 --headless --mode start   # self-test, no window, fast

Nothing is recorded: no audio is written. A task's numbers (no audio) go to recordings/joystick/task-<time>.json
(gitignored), also when you quit early. --trace writes per-tick numbers (pitch, clarity, level, formants, vowel
weights, the cursor's state, every pop-detector burst and extractor event) to recordings/joystick/trace-<time>.jsonl.
The setup writes only numbers: range and home (st), the voicing threshold, the vowel centres (Bark), pop thresholds.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import joystick_core as J
import joystick_ind as I

HERE = Path(__file__).resolve().parent
SCREENS = HERE.parent / "finetune" / "data" / "real-targets-v2" / "emulator" / "screens.jsonl"
PNG_ROOT = HERE.parent / "finetune"
OUT = HERE / "recordings" / "joystick"
RATE = 16000


# ------------------------------------------------------------------------------------ screens

def load_screens(spec: dict, min_elements: int = 4) -> list[dict]:
    """Harvested emulator screens with a screenshot and enough usable elements."""
    tk_ = spec["task"]
    out = []
    for line in SCREENS.read_text().splitlines():
        row = json.loads(line)
        w, h, els = J.screen_from_harvest(row)
        use = [e for e in els if min(e.r - e.l, e.b - e.t) >= tk_["min_side_dp"] and e.area <= tk_["max_area_frac"] * w * h]
        png = PNG_ROOT / row["screenshot"] if row.get("screenshot") else None
        if len(use) >= min_elements:
            out.append({"id": row["screen_id"], "w": w, "h": h, "elements": els, "png": png if png and png.exists() else None})
    return out


def rotated(sc: dict) -> dict:
    """A crude landscape relayout of a screen (the elements scaled into swapped dimensions; no screenshot)."""
    w, h = sc["h"], sc["w"]
    fx, fy = w / sc["w"], h / sc["h"]
    els = [J.Element(e.l * fx, e.t * fy, e.r * fx, e.b * fy, e.label) for e in sc["elements"]]
    return {"id": sc["id"] + " (landscape)", "w": w, "h": h, "elements": els, "png": None}


# ------------------------------------------------------------------------------------ the scored task

class Task:
    """N random targets, one at a time; scores time, misses, false clicks, overshoot, sounds and timeouts."""

    def __init__(self, spec: dict, screens: list[dict], n: int, seed: int):
        self.cfg, self.snap = spec["task"], spec["magnet"]["snap_dp"]
        self.screens, self.n = screens, n
        self.rng = np.random.default_rng(seed)
        self.trials: list[dict] = []
        self.cur: dict | None = None
        self.done = False

    def next(self, now_ms: float, cx: float, cy: float) -> dict | None:
        """Pick the next target (a screen and an element far enough from the cursor); None when finished."""
        if len(self.trials) >= self.n:
            self.done, self.cur = True, None
            return None
        c = self.cfg
        for _ in range(200):
            sc = self.screens[int(self.rng.integers(len(self.screens)))]
            ok = [i for i, e in enumerate(sc["elements"])
                  if min(e.r - e.l, e.b - e.t) >= c["min_side_dp"] and e.area <= c["max_area_frac"] * sc["w"] * sc["h"]
                  and e.dist(min(cx, sc["w"]), min(cy, sc["h"])) >= c["min_start_dist_dp"]]
            if ok:
                i = ok[int(self.rng.integers(len(ok)))]
                break
        e = sc["elements"][i]
        self.cur = {"screen": sc, "target": i, "t0": now_ms, "start": (cx, cy), "size_dp": [e.r - e.l, e.b - e.t],
                    "dist_dp": float(np.hypot(e.centre[0] - cx, e.centre[1] - cy)),
                    "down_dp": float(e.centre[1] - cy), "right_dp": float(e.centre[0] - cx),
                    "misses": 0, "false_clicks": 0, "sounds": 0, "overshoot_dp": [], "passes": 0, "modes": []}
        return self.cur

    def on_hum_end(self, ev: dict) -> None:
        if not self.cur:
            return
        e = self.cur["screen"]["elements"][self.cur["target"]]
        self.cur["sounds"] += 1
        if ev.get("mode") and ev["mode"] not in self.cur["modes"]:
            self.cur["modes"].append(ev["mode"])
        dmin = min(e.dist(x, y) for _, x, y in ev["path"]) if ev["path"] else e.dist(*ev["stop"])
        dstop = e.dist(*ev["stop"])
        if dmin <= self.snap:                      # it came within reach during this sound
            self.cur["overshoot_dp"].append(round(max(0.0, dstop - dmin), 1))
            if dstop > self.snap:
                self.cur["passes"] += 1            # ... and stopped out of reach again

    def on_click(self, now_ms: float, idx: int | None) -> str:
        c = self.cur
        if not c:
            return "no task"
        if idx == c["target"]:
            self._close(now_ms, True)
            return "HIT"
        if idx is None:
            c["misses"] += 1
            return "miss (nothing there)"
        c["false_clicks"] += 1
        return f"FALSE CLICK on {c['screen']['elements'][idx].label!r}"

    def poll(self, now_ms: float) -> bool:
        """True when the current target timed out."""
        if self.cur and now_ms - self.cur["t0"] > self.cfg["timeout_s"] * 1000:
            self._close(now_ms, False)
            return True
        return False

    def _close(self, now_ms: float, hit: bool, quit_: bool = False) -> None:
        c = self.cur
        self.trials.append({"screen": c["screen"]["id"], "target": c["screen"]["elements"][c["target"]].label,
                            "size_dp": [round(v) for v in c["size_dp"]], "dist_dp": round(c["dist_dp"]),
                            "down_dp": round(c["down_dp"]), "right_dp": round(c["right_dp"]),
                            "hit": hit, "time_s": round((now_ms - c["t0"]) / 1000, 2), "misses": c["misses"],
                            "false_clicks": c["false_clicks"], "sounds": c["sounds"], "passes": c["passes"],
                            "overshoot_dp": c["overshoot_dp"], "modes": c["modes"], **({"quit": True} if quit_ else {})})
        self.cur = None

    def abort(self, now_ms: float) -> None:
        """Quit mid-task: the target on screen is kept as a partial trial (not reached, quit: true)."""
        if self.cur:
            self._close(now_ms, False, quit_=True)

    def summary(self) -> dict:
        tr = self.trials
        if not tr:
            return {"targets": 0}
        hits = [t for t in tr if t["hit"]]
        ts = np.array([t["time_s"] for t in hits]) if hits else np.zeros(0)
        ov = [o for t in tr for o in t["overshoot_dp"]]
        by = {}
        for name, sel in (("below", lambda t: t["down_dp"] > 100), ("above", lambda t: t["down_dp"] < -100),
                          ("level", lambda t: abs(t["down_dp"]) <= 100)):
            g = [t for t in tr if "down_dp" in t and sel(t) and not t.get("quit")]
            gh = [t["time_s"] for t in g if t["hit"]]
            by[name] = {"n": len(g), "hit": len(gh), "time_s_median": round(float(np.median(gh)), 2) if gh else None}
        return {"targets": len(tr), "hit": len(hits), "not_reached": len(tr) - len(hits),
                "quit": sum(1 for t in tr if t.get("quit")), "by_direction": by,
                "time_s_median": round(float(np.median(ts)), 2) if ts.size else None,
                "time_s_p90": round(float(np.percentile(ts, 90)), 2) if ts.size else None,
                "misses": sum(t["misses"] for t in tr), "false_clicks": sum(t["false_clicks"] for t in tr),
                "sounds_per_target_median": float(np.median([t["sounds"] for t in tr])),
                "passes": sum(t["passes"] for t in tr),
                "overshoot_dp_median": round(float(np.median(ov)), 1) if ov else None,
                "overshoot_dp_p90": round(float(np.percentile(ov, 90)), 1) if ov else None}


# ------------------------------------------------------------------------------------ the synthetic singer

FAKE_FORMANTS = {"ee": (330, 2300, 3000), "ah": (760, 1250, 2500), "oo": (330, 900, 2300)}


FAKE_VOICES = {
    # like the user's vcursor-2 range (92-195 Hz = 9.0-21.9 st); every hum starts 1.2 st above the bottom, as the
    # user's home note does, and no note goes outside the range
    "low": {"lo_hz": 92.4, "hi_hz": 194.6, "home_st_above_lo": 1.2},
    # the first prototype's fake singer: a random start note of 100-150 Hz, any pitch reachable
    "free": {"lo_hz": None, "hi_hz": None, "home_st_above_lo": None},
}


class FakeSinger:
    """A closed-loop synthetic user: it sees the cursor 250 ms late, sings toward the target (vowel for sideways,
    pitch for up/down, per the mover's vertical mode), stops near it, and pops when the target is highlighted. It
    makes the audio, so the whole chain runs: analysis, mover, magnet, the extractor's pop detector, the clicker.
    Vertical policy: start = a step off the note it started on; home = a step off the home note; glide =
    start at the middle, glide full_st up / down to set the direction, glide back to stop. Its voice ("low": the
    user's range, starting near the bottom) never leaves [lo_hz, hi_hz]."""

    def __init__(self, seed: int, spec: dict, voice: str = "low"):
        self.rng = np.random.default_rng(seed)
        self.dz = spec["pitch"]["dead_zone_st"]
        self.full = spec["pitch"]["full_speed_st"]
        self.gfull = spec["vertical"]["glide"]["full_st"]
        self.snap = spec["magnet"]["snap_dp"]
        v = FAKE_VOICES[voice]
        self.voice = voice
        self.lo, self.hi = v["lo_hz"], v["hi_hz"]
        self.home = self.lo * 2 ** (v["home_st_above_lo"] / 12) if self.lo else None
        self.m_int = 0.0                  # glide mode: the momentum it believes it has set
        self.t = 0.0                      # ms of audio made
        self.phase = 0.0
        self.f0 = 120.0
        self.amp = 0.0
        self.fm = np.array(FAKE_FORMANTS["ah"], float)
        self.zi = [np.zeros(2) for _ in range(3)]
        self.zs = np.zeros(1)
        self.mode, self.until = "rest", 800.0
        self.ref, self.off, self.vowel = 120.0, 0.0, "ah"
        self.release_at: float | None = None
        self.pop_buf = np.zeros(0, np.float32)
        self.seen: list[tuple[float, float, float]] = []
        self.lead_s = 0.25

    def see(self, t_ms: float, x: float, y: float) -> tuple[float, float]:
        self.seen.append((t_ms, x, y))
        while len(self.seen) > 2 and self.seen[1][0] <= t_ms - 250:
            self.seen.pop(0)
        return self.seen[0][1], self.seen[0][2]

    def decide(self, mv: J.Mover, task: Task | None) -> None:
        """Called every tick with the live mover and task."""
        now = self.t
        cx, cy = self.see(now, mv.x, mv.y)
        if not task or not task.cur:
            return
        e = task.cur["screen"]["elements"][task.cur["target"]]
        tx, ty = e.centre
        dx, dy = tx - cx, ty - cy
        if self.mode == "rest" and now >= self.until:
            if mv.sound is None and mv.snapped == task.cur["target"]:
                import synth
                self.pop_buf = 0.2 * synth.make_pop(self.rng, RATE)[0].astype(np.float32)
                self.mode, self.until = "wait_click", now + 1400
            elif mv.sound is None:
                vm = mv.mode
                if vm == "start":
                    self.ref = self.home if self.home else 2 ** self.rng.uniform(np.log2(100), np.log2(150))
                    self.off = 0.0
                else:
                    self.ref = 55 * 2 ** (mv.mid / 12)
                    self.off = self._mid_step(mv, dy) if vm == "home" else 0.0
                self.f0 = self.ref * 2 ** ((self.off + self.rng.normal(0, 0.1)) / 12)
                self.mode, self.start_t, self.release_at, self.m_int = "hum", now, None, 0.0
                self.vowel = "ah"
        elif self.mode == "wait_click" and now >= self.until:
            self.mode, self.until = "rest", now + 200
        elif self.mode == "hum" and self.release_at is None:
            reach = 0.6 * self.snap
            # it sees the cursor 250 ms late and leads it by its speed (a person learns to let go early)
            sp = mv.state.get("speed", 0.0)
            vx, vy = mv.state.get("dx", 0.0), mv.state.get("dy", 0.0)
            nv = float(np.hypot(vx, vy)) or 1.0
            dx -= sp * vx / nv * self.lead_s
            dy -= sp * vy / nv * self.lead_s
            # sideways: the vowel; up/down: a pitch step off the start note, smaller when close
            want_v = "ee" if dx > reach * 0.7 else ("oo" if dx < -reach * 0.7 else "ah")
            if now - self.start_t > 200:           # after the start note has been taken
                self.vowel = want_v
                if mv.mode == "start":
                    step = 0.0 if abs(dy) < reach * 0.4 else (self.dz + 1.0 + (self.full - self.dz - 1.0) * min(1.0, abs(dy) / 350))
                    self.off = step * (1 if dy < 0 else -1)
                elif mv.mode == "home":
                    self.off = self._mid_step(mv, dy)
                else:                                  # glide: change the momentum it has set, by gliding
                    want = 0.0 if abs(dy) < reach * 0.4 else (1.0 if dy < 0 else -1.0)
                    if want != self.m_int and now - getattr(self, "glide_t", -1e9) > 300:
                        self.off += (want - self.m_int) * self.gfull
                        self.m_int, self.glide_t = want, now
            px, py = tx - dx, ty - dy                 # where it expects the cursor to end up
            ix, iy = min(12.0, 0.3 * (e.r - e.l)), min(12.0, 0.3 * (e.b - e.t))     # aim well inside, not at the edge
            if (e.l + ix <= px <= e.r - ix and e.t + iy <= py <= e.b - iy and abs(dx) < max(reach, (e.r - e.l) / 2)
                    and abs(dy) < max(reach, (e.b - e.t) / 2)) or now - self.start_t > 6000:
                self.release_at = now

    def _mid_step(self, mv: J.Mover, dy: float) -> float:
        """home mode: the offset from home it sings for a vertical distance dy (dp, down positive)."""
        if abs(dy) < 0.6 * self.snap * 0.4:
            return 0.0
        full = mv.full_st(dy > 0)
        return (self.dz + 0.8 + (full - self.dz - 0.8) * min(1.0, abs(dy) / 350)) * (1 if dy < 0 else -1)

    def audio(self, n: int) -> np.ndarray:
        from scipy.signal import lfilter
        dt = 1000 / RATE
        # targets for this chunk
        if self.mode == "hum":
            tgt_amp = 0.0 if (self.release_at is not None and self.t - self.release_at > 60) else 0.08
            f_tgt = self.ref * 2 ** (self.off / 12)
            if self.lo:                               # its voice's range
                f_tgt = min(max(f_tgt, self.lo), self.hi)
            if self.release_at is not None:           # release: a small pitch fall while fading
                f_tgt = f_tgt * 2 ** (-1.5 / 12)
            if self.release_at is not None and self.t - self.release_at > 120:
                self.mode, self.until = "rest", self.t + self.rng.uniform(250, 450)
        else:
            tgt_amp, f_tgt = 0.0, self.f0
        k = np.arange(n)
        a = self.amp + (tgt_amp - self.amp) * np.minimum(1, (k + 1) / (0.03 * RATE))
        self.amp = float(a[-1])
        f0 = self.f0 * (f_tgt / self.f0) ** np.minimum(1, (k + 1) / (0.08 * RATE))
        self.f0 = float(f0[-1])
        f0 = f0 * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * (self.t / 1000 + k / RATE)))    # vibrato, about +-0.2 st
        ph = self.phase + np.cumsum(f0 / RATE)
        src = np.diff(np.floor(np.r_[self.phase, ph])) - f0 / RATE
        self.phase = float(ph[-1] % 1.0)
        y, self.zs = lfilter([1.0], [1.0, -0.95], src, zi=self.zs)
        self.fm += (np.array(FAKE_FORMANTS[self.vowel], float) - self.fm) * min(1.0, n / (0.06 * RATE))
        for j, (f, bw) in enumerate(zip(self.fm, (80, 100, 120))):
            r = np.exp(-np.pi * bw / RATE)
            c = -2 * r * np.cos(2 * np.pi * f / RATE)
            y, self.zi[j] = lfilter([1 + c + r * r], [1, c, r * r], y, zi=self.zi[j])      # unity gain at DC
        y = y / 3.0 * a + self.rng.normal(0, 1e-3, n)
        if self.pop_buf.size:
            m = min(n, self.pop_buf.size)
            y[:m] += self.pop_buf[:m]
            self.pop_buf = self.pop_buf[m:]
        self.t += n * dt
        return y.astype(np.float32)


# ------------------------------------------------------------------------------------ the session (audio thread side)

class Session:
    """Everything that runs per audio chunk: analysis, mover, pop detector, clicker, task, and the fake singer."""

    def __init__(self, spec: dict, screens: list[dict], a: argparse.Namespace, vowels: dict | None,
                 range_st: tuple[float, float] | None = None, voice: dict | None = None):
        from vox_extract.extractor import Extractor
        self.spec, self.screens = spec, screens
        self.an = J.Analyzer(spec)
        self.idx = next((i for i, s in enumerate(screens) if s["id"] == a.screen), 0)
        self.landscape = False
        sc = screens[self.idx]
        vowels = dict(vowels or {})
        vzone = {k: vowels.pop(k) for k in ("dead_zone", "full") if k in vowels}
        self.mv = J.Mover(spec, sc["w"], sc["h"], vowels or None, range_st)
        if vzone:
            self.mv.vw = dict(self.mv.vw, **vzone)
        self.mv.set_mode(getattr(a, "mode", None) or spec["vertical"]["mode"])
        self.mv.set_screen(sc["w"], sc["h"], sc["elements"])
        self.screen = sc
        self.ex = Extractor(input_rate=RATE)
        self.pd = J.PopDetector(spec)             # pops from the ticks' level (runs next to the extractor's)
        self.pop_labels = {"pop"}                 # extractor labels that click (the pop setup can add the user's)
        self.pops_cal = False                     # the pop setup heard at least 2 of 3 (else the SPACE hint shows)
        self.voice = dict(voice or {})            # home_st, clarity_on (range.json); pop thresholds (pops.json)
        if self.voice.get("home_st") is not None:
            self.mv.set_home(self.voice["home_st"])
        if self.voice.get("clarity_on"):
            self.an.clarity_on = float(self.voice["clarity_on"])
        if self.voice.get("pop"):
            self.pd.c.update(self.voice["pop"])
            self.pop_labels |= set(self.voice.get("pop_labels", []))
            self.pops_cal = True
        self.pops_path = getattr(a, "pops_out", OUT / "pops.json")
        self.ex_log: list[dict] = []              # extractor events, written with the next tick's trace row
        self.last_pop_t = -1e9
        self.pop_by: dict[str, int] = {}
        self.clicker = J.Clicker(spec)
        self.task = Task(spec, screens, a.task, a.seed) if a.task else None
        self.fake = FakeSinger(a.seed, spec, getattr(a, "fake_voice", "low")) if a.source == "fake" else None
        self.range_path = getattr(a, "range_out", OUT / "range.json")
        self.trace = None
        if getattr(a, "trace", False):
            OUT.mkdir(parents=True, exist_ok=True)
            self.trace_path = OUT / f"trace-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
            self.trace = self.trace_path.open("w")
        self.t_ms = 0.0
        self.log: list[str] = []
        self.cmds: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.vsetup: dict | None = None
        self.rsetup: dict | None = None
        self.hsetup: dict | None = None
        self.psetup: dict | None = None
        self.dsetup: dict | None = None           # clicks / hiss: {"kind", "t0", "ex"}
        self.wsetup: dict | None = None           # the whistle glide (as rsetup)
        self.rmsetup: dict | None = None          # the room: {"t0", "ex", "db", "run", "max_run"}
        self.calib2_path = getattr(a, "calib2_out", OUT / "calib2.json")
        self.gate = J.derive_gate(self._examples(), self.voice.get("room"), spec)
        self.click_pop = J.derive_click_pop(self._examples()["pops"], self._examples()["clicks"], spec)
        if self.voice.get("whistle"):
            self.mv.set_whistle(self.voice["whistle"])
        self._whistle_ticks()
        self.failed: dict | None = None           # a setup step that failed: {"step", "why"}; waits for R / S
        self.setup_queue: list[str] = []
        self.setup_steps: list[str] = self.parse_steps(getattr(a, "setup_steps", None)) or list(self.SETUP)
        self.vowel_report: dict | None = None
        self.vowels_path = a.vowels_out
        self.last_click: tuple[float, float, str, float] | None = None
        self.pops = 0
        if self.task:
            self._next_target()

    def say(self, s: str) -> None:
        self.log.append(f"{self.t_ms / 1000:7.1f}s  {s}")
        self.log = self.log[-12:]
        if self.headless_print:
            print(self.log[-1], flush=True)

    headless_print = False

    def set_screen(self, sc: dict) -> None:
        self.screen = sc
        self.mv.set_screen(sc["w"], sc["h"], sc["elements"])

    def _next_target(self) -> None:
        c = self.task.next(self.t_ms, self.mv.x, self.mv.y)
        if c is None:
            self.say("task finished: " + json.dumps(self.task.summary()))
            return
        self.landscape = False
        self.set_screen(c["screen"])
        e = c["screen"]["elements"][c["target"]]
        self.say(f"target {len(self.task.trials) + 1}/{self.task.n}: {e.label!r} ({e.r - e.l:.0f} x {e.b - e.t:.0f} dp, "
                 f"{c['dist_dp']:.0f} dp away)")

    @property
    def in_setup(self) -> bool:
        return bool(self.hsetup or self.rsetup or self.vsetup or self.psetup or self.dsetup or self.wsetup or self.rmsetup
                    or self.failed)

    START_TIMEOUT_MS = 10000                      # a step with nothing steady heard this long after its prompt fails
    VOWEL_TIMEOUT_MS = 12000                      # a vowel without enough clear frames this long after its prompt
    STEP_NAMES = {"home": "HOME", "range": "RANGE SETUP", "vowels": "VOWEL SETUP", "pops": "POPS", "clicks": "CLICKS",
                  "whistle": "WHISTLE", "hiss": "HISS", "room": "ROOM"}
    SETUP = ["home", "range", "vowels", "pops", "clicks", "whistle", "hiss", "room"]
    # the app's step names (calib_start {steps}) -> the prototype's
    APP_STEPS = {"hum": "home", "glide": "range", "vowels": "vowels", "pops": "pops", "clicks": "clicks",
                 "whistle": "whistle", "hiss": "hiss", "room": "room"}

    @classmethod
    def parse_steps(cls, text: str | None) -> list[str] | None:
        """--setup-steps: an ordered subset of the app's step names (None = all)."""
        if not text:
            return None
        steps = [x.strip() for x in text.split(",") if x.strip()]
        bad = [x for x in steps if x not in cls.APP_STEPS]
        if not steps or bad or len(set(steps)) != len(steps):
            raise ValueError(f"--setup-steps: an ordered subset of {','.join(cls.APP_STEPS)}, no repeats (got {text!r})")
        return [cls.APP_STEPS[x] for x in steps]

    def command(self, c: str) -> None:
        if self.failed:                           # R / S only (the window sends r as "rotate", s as "setup")
            if c in ("retry", "rotate"):
                self._retry()
            elif c in ("skip", "setup"):
                self._skip()
            else:
                self.say(f"{self.STEP_NAMES[self.failed['step']]} failed: press R to retry it or S to skip it")
            return
        if c in ("home", "mid", "glide", "start"):
            self.mv.set_mode(c)
            self.say({"home": "MODE 1 home: above / below your home note (your relaxed hum)",
                      "glide": "MODE 2 glide: glide up / down to steer, glide back to stop",
                      "start": "MODE 3 start: above / below the note you start on"}[self.mv.mode])
        elif c == "setup":
            self.setup_queue = list(self.setup_steps)
            self._next_setup()
        elif c in ("range", "hum", "pops", "clicks", "whistle", "hiss", "room"):
            self.setup_queue = [{"hum": "home"}.get(c, c)]
            self._next_setup()
        elif c == "pop":
            self._pop(self.t_ms, "key")
        elif c == "recentre":
            self.mv.recentre(); self.say("recentred")
        elif c == "mode":
            self.mv.enabled = not self.mv.enabled
            self.say("cursor mode " + ("ON (the cursor kept its place)" if self.mv.enabled else "OFF"))
        elif c == "rotate":
            self.landscape = not self.landscape
            base = self.screens[self.idx] if not (self.task and self.task.cur) else self.task.cur["screen"]
            self.set_screen(rotated(base) if self.landscape else base)
            self.say(f"rotated: cursor clamped to ({self.mv.x:.0f}, {self.mv.y:.0f}) dp")
        elif c in ("next", "prev") and not (self.task and self.task.cur):
            self.idx = (self.idx + (1 if c == "next" else -1)) % len(self.screens)
            self.landscape = False
            self.set_screen(self.screens[self.idx]); self.say(f"screen {self.screen['id']}")
        elif c == "task" and not self.task:
            self.task = Task(self.spec, self.screens, 12, int(time.time())); self._next_target()
        elif c == "vowels":
            self.setup_queue = ["vowels"]
            self._next_setup()

    def _next_setup(self) -> None:
        if not self.setup_queue:
            if self.task and self.task.cur and not self.in_setup:   # the setup's time is not the target's
                self.task.cur["t0"] = self.t_ms
            return
        step = self.setup_queue.pop(0)
        if step == "home":
            self.hsetup = {"t0": None, "st": [], "cl": [], "t_prompt": self.t_ms}
            self.say("HOME: hum 'mm' relaxed for 3 s, the note that comes out without thinking")
        elif step == "range":
            self.rsetup = {"t0": None, "st": [], "t_prompt": self.t_ms}
            self.say("RANGE SETUP: glide from your LOWEST comfortable note to your HIGHEST and back (5 s)")
        elif step == "pops":
            self.psetup = {"t0": self.t_ms, "n0": len(self.pd.bursts), "ex": []}
            self.say("POPS: pop your lips 3 times, about a second apart (8 s)")
        elif step == "clicks":
            self.dsetup = {"kind": "clicks", "t0": self.t_ms, "ex": []}
            self.say("CLICKS: click your tongue 3 times, about a second apart (8 s)")
        elif step == "hiss":
            self.dsetup = {"kind": "hiss", "t0": self.t_ms, "ex": []}
            self.say("HISS: 2 short 'tss' hisses, about a second apart (8 s)")
        elif step == "whistle":
            self.wsetup = {"t0": None, "st": [], "t_prompt": self.t_ms}
            self.an.f0_max_hz = self.spec["calib_v2"]["whistle"]["tick_f0_max_hz"]
            self.say("WHISTLE: whistle from your LOWEST note to your HIGHEST and back (5 s)")
        elif step == "room":
            self.rmsetup = {"t0": self.t_ms, "ex": [], "db": [], "run": 0, "max_run": 0}
            self.say("ROOM: stay quiet for 3 s (the room's noise)")
        else:
            self.vsetup = {"order": ["ee", "ah", "oo"], "i": 0, "frames": {"ee": [], "ah": [], "oo": []}, "t0": None,
                           "t_prompt": self.t_ms, "cent": dict(self.mv.cent), "vw": dict(self.mv.vw)}
            self.say("VOWEL SETUP: hold 'ee' (as in see) for 2 s, at a middle pitch")

    def _fail(self, step: str, why: str) -> None:
        """A setup step failed: say why and wait for R (retry the step) or S (skip it, its defaults stay)."""
        self.hsetup = self.rsetup = self.vsetup = self.psetup = self.dsetup = self.wsetup = self.rmsetup = None
        if step == "whistle":
            self._whistle_ticks()
        self.failed = {"step": step, "why": why}
        self.say(f"{self.STEP_NAMES[step]}: {why}. Press R to retry this step, S to skip it (the defaults stay)")

    def _retry(self) -> None:
        step, self.failed = self.failed["step"], None
        self.setup_queue.insert(0, step)
        self._next_setup()

    def _mark(self, step: str, skipped: bool) -> None:
        s = set(self.voice.get("skipped", []))
        (s.add if skipped else s.discard)(step)
        self.voice["skipped"] = sorted(s)

    def _skip(self) -> None:
        """Skip the failed step: its defaults (the spec's) stay, and the saved files say it was skipped."""
        step, self.failed = self.failed["step"], None
        if step == "home":
            for k in ("home_st", "clarity_on"):
                self.voice.pop(k, None)
            self.an.clarity_on = self.spec["voicing"]["clarity_min"]
            self.mv.home_setup = None
            self.mv.home_hist.clear()
        elif step == "range":
            for k in ("lo_st", "hi_st"):
                self.voice.pop(k, None)
            self.mv.set_range(*self.spec["vertical"]["home"]["range_st"])
        elif step == "vowels":
            self.mv.cent = {k: np.array(v, float) for k, v in self.spec["vowel"]["centroids_bark"].items()
                            if k in ("ee", "ah", "oo")}
            self.mv.vw = self.spec["vowel"]
            self.vowel_report = None
            self._write(self.vowels_path, {"skipped": ["vowels"], "note": "the vowel setup was skipped: the default "
                                           "vowel centres stay; private, stays local"})
        elif step == "pops":
            self.pd.c = dict(self.spec["pop"])
            self.pop_labels, self.pops_cal = {"pop"}, False
            for k in ("pop", "pop_labels"):
                self.voice.pop(k, None)
            self._write(self.pops_path, {"skipped": ["pops"], "note": "the pop setup was skipped: the default pop "
                                         "thresholds stay; private, stays local"})
            self.voice.pop("pops_examples", None)
        elif step in ("clicks", "hiss"):
            self.voice.pop(f"{step}_examples", None)
        elif step == "whistle":
            self.voice.pop("whistle", None)
            self.mv.set_whistle(None)
            self._whistle_ticks()
        elif step == "room":
            self.voice.pop("room", None)
        if step in ("pops", "clicks", "hiss", "room"):
            self._derive()
        self._mark(step, True)
        self._save_voice()
        self.say(f"{self.STEP_NAMES[step]}: skipped, its defaults stay (saved)")
        self._next_setup()

    @staticmethod
    def _write(path: Path, d: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d, indent=1))

    def _pop(self, t_ms: float, how: str) -> None:
        """A pop from SPACE, the tick detector or the extractor (the two mic detectors hearing the same pop: once)."""
        if how != "key" and abs(t_ms - self.last_pop_t) < self.spec["pop"]["merge_ms"] + 100:
            return
        if how != "key":
            self.last_pop_t = t_ms
        self.pop_by[how] = self.pop_by.get(how, 0) + 1
        self.pops += 1
        r = self.clicker.pop(t_ms)
        if r == "pop_pop":
            self.say("pop pop: listen (the intent cursor's numbered targets; unchanged, not in this prototype)")

    def _click(self) -> None:
        x, y = self.mv.x, self.mv.y
        i = J.hit(self.mv.elements, x, y)
        label = self.mv.elements[i].label if i is not None else "nothing"
        res = self.task.on_click(self.t_ms, i) if self.task and self.task.cur else ""
        self.last_click = (x, y, res or label, self.t_ms)
        self.say(f"click at ({x:.0f}, {y:.0f}) dp on {label!r} {res}")
        if res == "HIT":
            self._next_target()

    def feed(self, chunk: np.ndarray) -> None:
        while not self.cmds.empty():
            self.command(self.cmds.get())
        with self.lock:
            for tk in self.an.push(chunk):
                self.t_ms = tk.t_ms
                nb = len(self.pd.bursts)
                pt = self.pd.push(tk)
                evs = [{"ev": "burst", **{k: round(v, 1) if isinstance(v, float) else v for k, v in f.items()}}
                       for f in self.pd.bursts[nb:]] + ([{"ev": "pop_tick", "t0": pt}] if pt is not None else [])
                evs += self.ex_log
                self.ex_log = []
                if self.in_setup:
                    self.setup_tick(tk)
                    self._trace(tk, evs)
                    continue
                self.mv.push(tk)
                if self.fake:
                    self.fake.decide(self.mv, self.task)
                if pt is not None:
                    self._pop(pt, "tick")
                for ev in self.mv.events:
                    if ev["ev"] == "hum_end":
                        sn = self.mv.snapped
                        self.say(f"stop ({ev['stop'][0]:.0f}, {ev['stop'][1]:.0f}) {ev['dur_ms']:.0f} ms: {ev['why'] or '?'}"
                                 + (" [onset undone]" if ev["reanchors"] and self.mv.mode != "start" else "")
                                 + (f" -> {self.mv.elements[sn].label!r}" if sn is not None else ""))
                        if self.task:
                            self.task.on_hum_end(ev)
                    evs.append({k: (round(v, 1) if isinstance(v, float) else [round(q, 1) for q in v] if k == "stop" else v)
                                for k, v in ev.items() if k != "path"})
                self.mv.events.clear()
                if self.clicker.poll(self.t_ms) == "click":
                    evs.append({"ev": "click", "x": self.mv.x, "y": self.mv.y})
                    self._click()
                self._trace(tk, evs)
                if self.task and self.task.poll(self.t_ms):
                    self.say("target NOT REACHED (timeout)")
                    self._next_target()
            for e in self.ex.push(chunk):
                row = {"ev": "ex", "label": e.label, "t0": e.t_start_ms, "t1": e.t_end_ms}
                self.ex_log.append(row)
                if self.in_setup:
                    self.ex_event(e.t_start_ms, e.label, e.raw)
                    continue
                label = self._judge(e.label, e.raw, row)
                if label in self.pop_labels:
                    self._pop(e.t_start_ms, "extractor")

    def setup_tick(self, tk: J.Tick) -> None:
        """One tick of the running setup step (nothing runs while a step has failed and waits for R / S)."""
        if self.failed:
            pass
        elif self.hsetup:
            self._home_setup(tk)
        elif self.rsetup:
            self._range_setup(tk)
        elif self.vsetup:
            self._vowel_setup(tk)
        elif self.psetup:
            self._pop_setup(tk)
        elif self.dsetup:
            self._discrete_setup(tk)
        elif self.wsetup:
            self._whistle_setup(tk)
        elif self.rmsetup:
            self._room_setup(tk)

    def ex_event(self, t_ms: float, label: str, raw: dict) -> None:
        """An extractor event during the setup: the pops, clicks, hiss and room steps read them."""
        ex = (t_ms, label, J.example(raw))
        for su in (self.psetup, self.dsetup, self.rmsetup):
            if su is not None:
                su["ex"].append(ex)

    def _judge(self, label: str, raw: dict, row: dict) -> str | None:
        """A live extractor event: the level gate (a quiet pop / click / hiss is ignored), then the click / pop rule
        (relabel only when confident). Both are logged in the trace row; returns the label that acts (None = none)."""
        why = J.gate_reason(self.gate, label, raw.get("snr_db"), raw.get("level_db"))
        if why:
            row["ignored"] = why
            self.say(f"ignored {label}: below level gate ({why['snr_db']:.0f} dB < {why['min_snr_db']:.0f} or "
                     f"{why['level_dbfs']:.0f} dBFS < {why['min_level_dbfs']:.0f})")
            return None
        r = J.relabel(self.click_pop, label, raw)
        if r:
            row["relabel"] = r
            self.say(f"relabel {r['from']} -> {r['to']} (your own pops / clicks: {r['votes']})")
            return r["to"]
        return label

    def _examples(self) -> dict[str, list[dict]]:
        return {k: self.voice.get(f"{k}_examples") or [] for k in ("pops", "clicks", "hiss")}

    def _derive(self) -> None:
        """The level gate and the click / pop rule from the examples so far (and the room), saved to calib2.json."""
        ex = self._examples()
        self.gate = J.derive_gate(ex, self.voice.get("room"), self.spec)
        self.click_pop = J.derive_click_pop(ex["pops"], ex["clicks"], self.spec)
        self._write(self.calib2_path, {"version": 2, **{k: self.voice.get(k) for k in (
            "pops_examples", "clicks_examples", "hiss_examples", "whistle", "room")},
            "level_gate": self.gate, "click_pop": self.click_pop,
            "note": "calibration v2 (joystick setup): the extractor's numbers for the setup's pops, clicks and "
            "hisses, the whistle range (st), the room, the level gate and the click / pop rule; numbers only; "
            "private, stays local"})

    def _whistle_ticks(self) -> None:
        """The ticks' pitch ceiling: the whistle's while a whistle range is set, else the voice's."""
        self.an.f0_max_hz = self.spec["calib_v2"]["whistle"]["tick_f0_max_hz"] if self.voice.get("whistle") else None

    def _trace(self, tk: J.Tick, events: list[dict]) -> None:
        """One line per tick: the analysis and the cursor's state (numbers only, no audio)."""
        if not self.trace:
            return
        st, mv = self.mv.state, self.mv
        vw = st.get("vowel") or {}
        r = lambda v, n=2: None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), n)  # noqa: E731
        row = {"t": r(tk.t_ms, 0), "f0": r(tk.f0, 1), "st": r(J.V.st(tk.f0)) if tk.f0 > 0 else None,
               "clarity": r(tk.clarity, 3), "db": r(tk.db, 1), "floor": r(self.an.floor_db, 1), "voiced": tk.voiced,
               "f0_raw": r(tk.f0_raw, 1), "home": r(mv.mid), "clarity_on": r(self.an.clarity_on, 3),
               "why": tk.why, "f1": r(tk.f1, 0), "f2": r(tk.f2, 0), "w": {k: r(v, 3) for k, v in vw.items()},
               "x_vowel": r(st.get("x_vowel"), 3), "mode": mv.mode, "ref": r(st.get("ref")), "sm": r(st.get("sm")),
               "offset": r(st.get("offset")), "momentum": r(st.get("momentum"), 3), "dx": r(st.get("dx"), 3),
               "dy": r(st.get("dy"), 3), "speed": r(st.get("speed"), 1), "x": r(mv.x, 1), "y": r(mv.y, 1),
               "phase": "setup" if self.in_setup else st.get("phase"), "edge": st.get("edge") or None,
               "snapped": mv.snapped, "events": events or None}
        self.trace.write(json.dumps(row) + "\n")

    @staticmethod
    def steady(st: list[float], step: float = 0.35, run: int = 8) -> np.ndarray:
        """The ticks in runs of at least `run` (160 ms) whose pitch moves at most `step` st per tick (NaN =
        unvoiced). Creak (vocal fry, about 60-65 Hz for this voice) jumps about 0.4 st tick to tick; a held note or a
        5 s glide moves under 0.2. On live test 2's trace this keeps 0 of 724 creak ticks (under 6 st) and 86% of the
        rest (3187 of 3701)."""
        v = np.asarray(st, float)
        ok = np.abs(np.diff(v)) <= step                   # NaN compares False
        keep = np.zeros(v.size, bool)
        i = 0
        while i < ok.size:
            if not ok[i]:
                i += 1
                continue
            j = i
            while j < ok.size and ok[j]:
                j += 1
            if j - i + 1 >= run:                          # ticks i..j
                keep[i:j + 1] = True
            i = j
        return v[keep]

    def _save_voice(self) -> None:
        """range.json: the range, home and the voicing threshold (numbers only)."""
        rng = self.mv.range
        if "range" not in self.voice.get("skipped", []):      # a skipped range is the spec's, not a measurement
            self.voice.update({"lo_st": round(rng[0], 2), "hi_st": round(rng[1], 2)})
        self.range_path.parent.mkdir(parents=True, exist_ok=True)
        self.range_path.write_text(json.dumps({**{k: v for k, v in self.voice.items() if k in ("home_st", "clarity_on", "lo_st", "hi_st", "skipped")},
                                               "note": "range: 5th / 95th percentile of the steady voiced ticks of the "
                                               "joystick's 5 s glide (creak dropped); home_st: median of the relaxed "
                                               "hum; clarity_on: its own voicing threshold; st = 12 log2(f0 / 55); "
                                               "skipped: setup steps skipped (their defaults stay); "
                                               "private, stays local"}, indent=1))

    def _home_fits(self) -> None:
        """Home must leave room on both sides: at least 1 st inside the range (else it is clamped)."""
        h, (lo, hi) = self.voice.get("home_st"), self.mv.range
        if h is None or hi - lo < 4.0:
            return
        c = float(np.clip(h, lo + 1.0, hi - 1.0))
        if abs(c - h) > 0.05:
            self.say(f"home {h:.1f} st is at the edge of your range {lo:.1f}-{hi:.1f}: moved to {c:.1f}")
            self.voice["home_st"] = round(c, 2)
            self.mv.set_home(c)

    def _started(self, su: dict, tk: J.Tick) -> bool:
        """A setup step's clock starts on the first steady voiced run (8 ticks), not on the first voiced tick: in
        live test 2 creak blips (2-4 st) a second into the setup started the 5 s glide's clock before the glide."""
        v = float(J.V.st(tk.f0)) if tk.voiced else np.nan
        su["quiet"] = 0.0 if tk.voiced else su.get("quiet", 0.0) + self.mv.tick_ms   # a step ends on a real stop
        if su["t0"]:
            su["st"].append(v)
            return True
        su.setdefault("recent", []).append(v)
        su["recent"] = su["recent"][-8:]
        if len(su["recent"]) == 8 and self.steady(su["recent"]).size == 8:
            su["t0"], su["st"] = tk.t_ms - 140, list(su["recent"])
            return True
        return False

    def _home_setup(self, tk: J.Tick) -> None:
        hs = self.hsetup
        if not self._started(hs, tk):
            if tk.t_ms - hs["t_prompt"] >= self.START_TIMEOUT_MS:
                self._fail("home", f"no steady hum heard in {self.START_TIMEOUT_MS // 1000} s")
            return
        if tk.f0_raw > 0 and tk.over_db >= 10.0:        # loud and pitched: its clarity, whatever the threshold
            hs["cl"].append(tk.clarity)
        dur = tk.t_ms - hs["t0"]
        if (dur >= 3000 and hs["quiet"] >= self.spec["voicing"]["end_gap_ms"]) or dur >= 5000:
            v = self.steady(hs["st"])
            if v.size < 40:
                self._fail("home", f"too short or too rough ({v.size} steady ticks, need 40): a relaxed 'mm', 3 s")
                return
            self.hsetup = None
            home = float(np.median(v))
            vo = self.spec["voicing"]
            lo_c, hi_c = vo["person_clarity"]
            con = float(np.clip(np.percentile(hs["cl"], 10) - vo["person_margin"], lo_c, hi_c))
            self.an.clarity_on = con
            self.mv.set_home(home)
            self.voice.update({"home_st": round(home, 2), "clarity_on": round(con, 3)})
            self._mark("home", False)
            self._home_fits()
            self._save_voice()
            self.say(f"home {self.mv.mid:.1f} st ({55 * 2 ** (self.mv.mid / 12):.0f} Hz), voicing threshold "
                     f"{con:.2f} (clarity; {len(hs['cl'])} ticks) (saved)")
            self._next_setup()

    def _range_setup(self, tk: J.Tick) -> None:
        rs = self.rsetup
        if not self._started(rs, tk):
            if tk.t_ms - rs["t_prompt"] >= self.START_TIMEOUT_MS:
                self._fail("range", f"no steady voice heard in {self.START_TIMEOUT_MS // 1000} s")
            return
        if tk.t_ms - rs["t0"] >= 5000 and rs["quiet"] >= self.spec["voicing"]["end_gap_ms"]:
            v = self.steady(rs["st"])
            lo, hi = (float(np.percentile(v, 5)), float(np.percentile(v, 95))) if v.size >= 50 else (0.0, 0.0)
            if hi - lo < 4.0:
                self._fail("range", f"too small or too short ({hi - lo:.1f} st, {v.size} steady ticks; need 4 st, "
                                    "50 ticks): glide wider, lowest to highest and back")
                return
            self.rsetup = None
            self.mv.set_range(lo, hi)
            self._mark("range", False)
            self._home_fits()
            self._save_voice()
            self.say(f"range {lo:.1f}-{hi:.1f} st ({55 * 2 ** (lo / 12):.0f}-{55 * 2 ** (hi / 12):.0f} Hz), "
                     f"home {self.mv.mid:.1f} st (saved)")
            self._next_setup()

    def _pop_setup(self, tk: J.Tick) -> None:
        """Three lip pops: the bursts that look like pops at the loosest bounds (whatever today's thresholds say)
        set the detector's thresholds, and the extractor labels they got are accepted from then on."""
        ps, c = self.psetup, self.pd.c
        cal = c["calibrate"]
        new = self.pd.bursts[ps["n0"]:]
        cand = [f for f in new if f["peak_db"] >= cal["find_peak_db"] and f["rise_db"] >= cal["find_rise_db"]
                and f["core"] <= cal["core_ticks"][1] and f["peak_i"] <= c["peak_within"]
                and f["ticks"] <= c["max_ticks"] and f["voiced"] <= c["max_voiced"]]
        done = len(cand) >= 3 and tk.t_ms - cand[2]["t"] > 700
        if not done and tk.t_ms - ps["t0"] < 8000:
            return
        self.psetup = None
        cand = sorted(cand, key=lambda f: -f["peak_db"])[:3]
        heard = sum(self.pd.judge(f) for f in cand)
        matched = [(lab, raw) for f in cand for t0, lab, raw in ps["ex"] if abs(t0 - f["t"]) < 250]
        labels = [lab for lab, _ in matched]
        rep = {"bursts": len(new), "pop_like": len(cand), "heard_before": heard,
               "extractor": {lab: labels.count(lab) for lab in set(labels)}}
        if len(cand) < 2:
            self._fail("pops", f"heard {len(cand)}/3 pops, need 2 (pop your lips a bit louder, a second apart)")
            return
        newc = self.pd.calibrate(cand)
        learnt = [lab for lab in set(labels) if labels.count(lab) >= 2 and lab in ("pop", "click")]
        self.pop_labels |= set(learnt)
        self.pops_cal = True
        self.voice.update({"pop": newc, "pop_labels": sorted(self.pop_labels),
                           "pops_examples": [{"label": lab, **raw} for lab, raw in matched if lab in J.GATE_LABELS]})
        self._derive()
        self.pops_path.parent.mkdir(parents=True, exist_ok=True)
        self.pops_path.write_text(json.dumps({"pop": newc, "pop_labels": sorted(self.pop_labels), "setup": rep,
                                              "peaks_db": [round(f["peak_db"], 1) for f in cand],
                                              "ticks": [f["ticks"] for f in cand],
                                              "extractor_raw": [{"label": lab, **{k: (round(float(v), 1) if v is not None
                                                                                       else None) for k, v in raw.items()}}
                                                                for lab, raw in matched],
                                              "note": "lip-pop thresholds (dB over the floor, ticks) from the "
                                              "joystick's pop setup; ticks: each setup pop's burst length (20 ms "
                                              "ticks); extractor_raw: the gesture extractor's reading of them "
                                              "(for eval_real/calib_gestures.py); numbers only; private, stays "
                                              "local"}, indent=1))
        self.say(f"POPS: heard {len(cand)}/3 (the old thresholds: {heard}/3); peak >= {newc['peak_db']:.0f} dB, "
                 f"rise >= {newc['rise_db']:.0f} dB, extractor said {rep['extractor'] or 'nothing'} (saved)")
        self._mark("pops", False)
        self._save_voice()
        self._next_setup()

    def _discrete_setup(self, tk: J.Tick) -> None:
        """clicks (3 tongue clicks: any discrete label, at most max_dur_ms) or hiss (2 'tss': label hiss): the
        extractor's events in the window; the strongest `ask` of them are the examples."""
        ds = self.dsetup
        kind = ds["kind"]
        c = self.spec["calib_v2"][kind]
        cand = [e for e in ds["ex"] if e[2]["snr_db"] is not None and e[2]["level_db"] is not None
                and (e[1] in J.GATE_LABELS and (e[2]["dur_ms"] or 0) <= c["max_dur_ms"] if kind == "clicks" else e[1] == "hiss")]
        done = len(cand) >= c["ask"] and tk.t_ms - sorted(e[0] for e in cand)[c["ask"] - 1] > c["settle_ms"]
        if not done and tk.t_ms - ds["t0"] < c["window_ms"]:
            return
        top = sorted(cand, key=lambda e: -e[2]["snr_db"])[:c["ask"]]
        self.dsetup = None
        if len(top) < c["need"]:
            what = {"clicks": "clicks", "hiss": "hisses"}[kind]
            tip = {"clicks": "click your tongue a bit louder, about a second apart",
                   "hiss": "a short, sharp 'tss', a bit louder"}[kind]
            self._fail(kind, f"heard {len(top)}/{c['ask']} {what}, need {c['need']} ({tip})")
            return
        self.voice[f"{kind}_examples"] = [{"label": lab, **raw} for _, lab, raw in top]
        labels = [lab for _, lab, _ in top]
        self._mark(kind, False)
        self._derive()
        self._save_voice()
        self.say(f"{self.STEP_NAMES[kind]}: heard {len(top)}/{c['ask']} ({', '.join(labels)}), quietest "
                 f"{min(r['snr_db'] for _, _, r in top):.0f} dB over the floor; level gate >= "
                 f"{self.gate['min_snr_db']:.0f} dB and {self.gate['min_level_dbfs']:.0f} dBFS (saved)")
        self._next_setup()

    def _whistle_setup(self, tk: J.Tick) -> None:
        """A 5 s whistle glide at the whistle's pitch ceiling: the range (5th / 95th percentile of the steady
        ticks), its home (the median) and the split from the voice range (the midpoint between the voice range's
        top and the whistle range's bottom)."""
        ws = self.wsetup
        c = self.spec["calib_v2"]["whistle"]
        if not self._started(ws, tk):
            if tk.t_ms - ws["t_prompt"] >= self.START_TIMEOUT_MS:
                self._fail("whistle", f"no steady whistle heard in {self.START_TIMEOUT_MS // 1000} s")
            return
        if tk.t_ms - ws["t0"] < c["glide_ms"] or ws["quiet"] < self.spec["voicing"]["end_gap_ms"]:
            return
        v = self.steady(ws["st"])
        n = c["min_steady_ticks"]
        lo, hi = (float(np.percentile(v, 5)), float(np.percentile(v, 95))) if v.size >= n else (0.0, 0.0)
        if hi - lo < c["min_range_st"]:
            self._fail("whistle", f"too small or too short ({hi - lo:.1f} st, {v.size} steady ticks; need "
                                  f"{c['min_range_st']:.0f} st, {n} ticks): whistle from your lowest to your highest "
                                  "and back")
            return
        top = self.mv.range[1]
        if lo <= top:
            self._fail("whistle", f"the whistle overlaps your voice range (whistle from {55 * 2 ** (lo / 12):.0f} Hz, "
                                  f"voice up to {55 * 2 ** (top / 12):.0f} Hz): whistle higher, or skip")
            return
        self.wsetup = None
        w = {"lo_st": round(lo, 2), "hi_st": round(hi, 2), "home_st": round(float(np.median(v)), 2),
             "split_st": round((top + lo) / 2, 2)}
        self.voice["whistle"] = w
        self.mv.set_whistle(w)
        self._whistle_ticks()
        self._mark("whistle", False)
        self._derive()
        self._save_voice()
        self.say(f"whistle {lo:.1f}-{hi:.1f} st ({55 * 2 ** (lo / 12):.0f}-{55 * 2 ** (hi / 12):.0f} Hz), home "
                 f"{w['home_st']:.1f} st, over {w['split_st']:.1f} st steers by the whistle (saved)")
        self._next_setup()

    def _room_setup(self, tk: J.Tick) -> None:
        """3 s of silence: the ticks' level (the noise floor), no steady tone (a voiced run would move the cursor), and
        the loudest extractor transient in it; the level gate stays room_margin_db over that transient. Fails when
        the transient is as loud as the quietest calibrated sound in both SNR and level (the gate could not keep it
        out)."""
        rm = self.rmsetup
        c = self.spec["calib_v2"]["room"]
        g = self.spec["level_gate"]
        if tk.t_ms - rm["t0"] <= c["window_ms"]:
            rm["db"].append(tk.db)
            rm["run"] = rm["run"] + 1 if tk.voiced else 0
            rm["max_run"] = max(rm["max_run"], rm["run"])
        if tk.t_ms - rm["t0"] < c["window_ms"] + c["settle_ms"]:
            return
        self.rmsetup = None
        if rm["max_run"] >= c["max_voiced_run_ticks"]:
            self._fail("room", f"not quiet: a steady tone was heard for {rm['max_run'] * self.mv.tick_ms:.0f} ms (a "
                               "voice, music or a hum): make the room quiet and retry")
            return
        tr = [e for e in rm["ex"] if e[1] in J.GATE_LABELS and rm["t0"] <= e[0] <= rm["t0"] + c["window_ms"]
              and e[2]["snr_db"] is not None and e[2]["level_db"] is not None]
        ts = max((e[2]["snr_db"] for e in tr), default=None)
        tl = max((e[2]["level_db"] for e in tr), default=None)
        ex = [e for k in self._examples().values() for e in k if e.get("snr_db") is not None and e.get("level_db") is not None]
        if tr and ex:
            ws, wl = min(e["snr_db"] for e in ex), min(e["level_db"] for e in ex)
            cap = g["cap_below_weakest_db"]
            if ts + g["room_margin_db"] > ws - cap and tl + g["room_margin_db"] > wl - cap:
                self._fail("room", f"a sound in the room was as loud as your quietest calibrated sound ({ts:.0f} dB over "
                                   f"the floor, yours {ws:.0f} dB): make the room quieter and retry, or skip")
                return
        room = {"floor_dbfs": round(float(np.median(rm["db"])), 2) if rm["db"] else None,
                "transient_snr_db": None if ts is None else round(float(ts), 2),
                "transient_level_dbfs": None if tl is None else round(float(tl), 2), "transients": len(tr)}
        self.voice["room"] = room
        self._mark("room", False)
        self._derive()
        self._save_voice()
        self.say(f"room: floor {room['floor_dbfs']} dBFS, {len(tr)} transient(s)"
                 + (f", loudest {ts:.0f} dB over the floor" if tr else "") + f"; level gate >= "
                 f"{self.gate['min_snr_db']:.0f} dB and {self.gate['min_level_dbfs']:.0f} dBFS (saved)")
        self._next_setup()

    def vowel_accuracy(self, frames: dict[str, list[tuple[float, float]]]) -> dict:
        """Each setup frame through the mover's vowel rule with the new centres (smoothed over the live 100 ms):
        how often each vowel would steer right / not / left. In-sample: the centres come from the same frames."""
        mv, vw = self.mv, self.mv.vw
        n_s = max(1, round(vw["smooth_ms"] / mv.tick_ms))
        out = {}
        for v, fr in frames.items():
            xs = []
            for b1, b2 in fr:
                w = mv.vowel_weights_bark(b1, b2) or {}
                xs.append(w.get("ee", 0.0) - w.get("oo", 0.0))
            xs = np.convolve(xs, np.ones(n_s) / n_s, mode="valid") if len(xs) >= n_s else np.array(xs)
            out[v] = {"n": int(xs.size), "x": xs}
        return out

    def _vowel_report(self, frames: dict) -> dict:
        vw = self.mv.vw
        acc = self.vowel_accuracy(frames)
        ah = np.abs(acc["ah"]["x"]) if acc["ah"]["n"] else np.zeros(1)
        if float(np.mean(ah > vw["dead_zone"])) > 0.10:            # 'ah' steers sideways too often: widen
            dz = float(min(0.7, np.percentile(ah, 90)))
            if dz > vw["dead_zone"]:
                self.mv.vw = vw = dict(vw, dead_zone=round(dz, 2), full=round(max(vw["full"], dz + 0.3), 2))
                self.say(f"'ah' drifted sideways: vowel dead zone widened to {dz:.2f}")
        rep = {}
        for v, a in acc.items():
            x = a["x"]
            rep[v] = {"n": a["n"], "right": round(float(np.mean(x > vw["dead_zone"])), 2) if a["n"] else None,
                      "none": round(float(np.mean(np.abs(x) <= vw["dead_zone"])), 2) if a["n"] else None,
                      "left": round(float(np.mean(x < -vw["dead_zone"])), 2) if a["n"] else None}
            self.say(f"  {v}: right {rep[v]['right']:.0%}  none {rep[v]['none']:.0%}  left {rep[v]['left']:.0%}"
                     f"  ({a['n']} frames)" if a["n"] else f"  {v}: no frames")
        self.vowel_report = {"per_vowel": rep, "dead_zone": vw["dead_zone"], "full": vw["full"]}
        return rep

    VOWEL_WANT = {"ee": "right", "ah": "none", "oo": "left"}
    VOWEL_MIN_OWN = 0.5                           # a vowel must steer its own way at least this often (in-sample)

    def _vowel_setup(self, tk: J.Tick) -> None:
        vs = self.vsetup
        v = vs["order"][vs["i"]]
        if vs.get("quiet_ms", 200) < 200:            # the last vowel must end first (its tail is not this vowel)
            vs["quiet_ms"] = 0 if tk.voiced else vs["quiet_ms"] + self.mv.tick_ms
            vs["t_prompt"] = tk.t_ms                 # its clock starts once the last one has ended
            return
        if tk.voiced and not np.isnan(tk.f2):
            vs["t0"] = vs["t0"] or tk.t_ms
            if tk.t_ms - vs["t0"] > 300:
                vs["frames"][v].append((float(J.V.bark(tk.f1)), float(J.V.bark(tk.f2))))
        n = len(vs["frames"][v])
        if not (vs["t0"] and (n >= 80 or (not tk.voiced and n >= 30))):
            if tk.t_ms - vs["t_prompt"] >= self.VOWEL_TIMEOUT_MS:
                self._fail("vowels", f"no clear '{v}' heard in {self.VOWEL_TIMEOUT_MS // 1000} s" if not n else
                           f"only {n} clear frames of '{v}' in {self.VOWEL_TIMEOUT_MS // 1000} s (need 30): hold it "
                           "steady for 2 s")
                self.mv.cent, self.mv.vw = vs["cent"], vs["vw"]
            return
        vs["i"] += 1
        vs["t0"], vs["quiet_ms"] = None, 0
        if vs["i"] < 3:
            self.say(f"VOWEL SETUP: now hold '{vs['order'][vs['i']]}' for 2 s (stop first)")
            return
        cent = {k: [round(float(np.median([p[0] for p in f])), 2), round(float(np.median([p[1] for p in f])), 2)]
                for k, f in vs["frames"].items()}
        self.mv.cent = {k: np.array(c) for k, c in cent.items()}
        self.say(f"vowels: {cent}; per frame (in-sample):")
        rep = self._vowel_report(vs["frames"])
        bad = [(k, want, rep[k][want] or 0.0) for k, want in self.VOWEL_WANT.items() if (rep[k][want] or 0.0) < self.VOWEL_MIN_OWN]
        if bad:
            self.mv.cent, self.mv.vw = vs["cent"], vs["vw"]      # the centres from before this setup stay
            self.vowel_report = None
            self._fail("vowels", "they overlap: " + ", ".join(f"'{k}' steered {w} only {x:.0%} of the time"
                                                               for k, w, x in bad))
            return
        self.vsetup = None
        self._write(self.vowels_path, {"centroids_bark": cent, "dead_zone": self.mv.vw["dead_zone"],
                                       "full": self.mv.vw["full"], "accuracy": self.vowel_report["per_vowel"],
                                       "note": "vowel centres (F1, F2 Bark) and the sideways dead zone, from the "
                                       "joystick vowel setup; private, stays local"})
        self.say("vowels set (saved)")
        self._mark("vowels", False)
        self._save_voice()
        self._next_setup()


# ------------------------------------------------------------------------------------ sources

def fake_loop(ses: Session, stop: threading.Event, realtime: bool) -> None:
    n = RATE // 50
    t0 = time.monotonic()
    while not stop.is_set():
        ses.feed(ses.fake.audio(n))
        if ses.task and ses.task.done:
            break
        if realtime:
            lag = ses.fake.t / 1000 - (time.monotonic() - t0)
            if lag > 0:
                time.sleep(lag)


def mic_loop(ses: Session, stop: threading.Event, device: str | None) -> None:
    import record as R
    src = R.PwSource(device, RATE, RATE // 50)
    src.start()
    try:
        while not stop.is_set():
            x = src.read()
            if x is None:
                ses.say("microphone closed"); break
            ses.feed(x)
    finally:
        src.stop()


# ------------------------------------------------------------------------------------ the window

def import_tk():
    """tkinter; on NixOS the venv's Python has no _tkinter, so borrow nixpkgs' matching python3XXPackages.tkinter."""
    try:
        import tkinter
        return tkinter
    except ImportError:
        import subprocess
        v = f"python{sys.version_info.major}{sys.version_info.minor}Packages.tkinter"
        p = subprocess.run(["nix", "build", "--no-link", "--print-out-paths", f"nixpkgs#{v}"], capture_output=True,
                           text=True).stdout.strip().splitlines()
        if not p:
            raise SystemExit(f"no tkinter: `nix build nixpkgs#{v}` failed; use --headless")
        sys.path.insert(0, f"{p[-1]}/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
        import tkinter
        return tkinter


class Window:
    PX_PER_DP = 0.875                     # 1080 px screenshots shown at 1/3 = 360 px for 411 dp
    PANEL = 330

    def __init__(self, ses: Session, stop: threading.Event):
        tk = import_tk()
        self.tk, self.ses, self.stop = tk, ses, stop
        self.root = tk.Tk()
        self.root.title("Canti voice joystick (prototype)")
        side = int(914 * self.PX_PER_DP) + 20
        self.cv = tk.Canvas(self.root, width=side + self.PANEL, height=side, bg="#111", highlightthickness=0)
        self.cv.pack()
        self.imgs: dict[str, object] = {}
        self.ind: dict[str, object] = {}          # the indicators' PhotoImages, per state
        self.badges = I.load_badges()
        self.show_strip = False                   # d: the debug pitch strip instead of the indicators
        keys = {"space": "pop", "c": "recentre", "m": "mode", "r": "rotate", "n": "next", "p": "prev", "t": "task",
                "v": "vowels", "g": "range", "h": "hum", "o": "pops", "k": "clicks", "w": "whistle", "x": "hiss",
                "b": "room", "s": "setup", "1": "home", "2": "glide",
                "3": "start"}
        for k, c in keys.items():
            self.root.bind(f"<{k}>" if k == "space" else k, lambda _e, c=c: ses.cmds.put(c))
        self.root.bind("d", lambda _e: setattr(self, "show_strip", not self.show_strip))
        for k in ("q", "<Escape>"):
            self.root.bind(k, lambda _e: self.close())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(30, self.draw)

    def close(self) -> None:
        self.stop.set()
        self.root.destroy()

    def img(self, png: Path):
        k = str(png)
        if k not in self.imgs:
            try:
                self.imgs[k] = self.tk.PhotoImage(file=k).subsample(3)
            except Exception:
                self.imgs[k] = None
        return self.imgs[k]

    ART = 4 / I.DEVICE_PX_PER_DP * PX_PER_DP      # window px per art px (the approved 4 device px), 1.33

    def photo(self, k: str, make) -> object:
        if k not in self.ind:
            import base64
            self.ind[k] = self.tk.PhotoImage(data=base64.b64encode(I.png(I.scale(make(), self.ART))))
        return self.ind[k]

    def cursor_img(self, mv: J.Mover, st: dict) -> object:
        """Cursor B: stopped = the ring; voiced and still = crosshair ticks; moving = 1-3 chevrons ahead."""
        dx, dy, sp = st.get("dx") or 0.0, st.get("dy") or 0.0, st.get("speed") or 0.0
        if mv.sound is None:
            return self.photo("cur", lambda: I.rgba(I.cursor()))
        if sp <= 0 or (abs(dx) < 1e-6 and abs(dy) < 1e-6):
            return self.photo("cur-neutral", lambda: I.rgba(I.cursor(neutral=True)))
        d, n = I.heading(dx, dy), I.chevrons(sp, mv.s)
        return self.photo(f"cur-{d}-{n}", lambda: I.rgba(I.cursor(d, n)))

    def face_state(self, mv: J.Mover, st: dict) -> tuple[int | str | None, str]:
        """Face A's state from the mover: the bar's step from the real offset (per mode), and the vowel side."""
        if mv.sound is None or st.get("sm") is None:
            return None, "ah"
        p, lo, hi = mv.p, mv.range[0], mv.range[1]
        if mv.mode == "glide":
            off, dead, full = st.get("momentum") or 0.0, mv.vt["glide"]["dead"], 1.0
        else:
            off = st.get("offset") or 0.0
            dead = p["dead_zone_st"]
            full = mv.full_st(off < 0) if mv.mode == "home" else p["full_speed_st"]
        past = 1 if st["sm"] > hi else -1 if st["sm"] < lo else 0
        x, dz = st.get("x_vowel") or 0.0, mv.vw["dead_zone"]
        return I.bar_step(off, dead, full, past), "ee" if x > dz else "oo" if x < -dz else "ah"

    def badge_img(self, mv: J.Mover, st: dict) -> object:
        n, v = self.face_state(mv, st)
        k = I.key(n, v)
        if self.badges and k in self.badges:
            return self.photo("badge-" + k, lambda: self.badges[k])
        return self.photo("screen-" + k, lambda: I.screen_only(n, v))

    def indicators(self, ox: float, oy: float, mv: J.Mover, st: dict) -> None:
        """The approved indicators at their size: snapped brackets, Cursor B, and the badge (top right, as the
        mockup: 16 device px from the edge, 720 device px down)."""
        k, cv = self.PX_PER_DP, self.cv
        dpx = I.DEVICE_PX_PER_DP
        if mv.snapped is not None and mv.sound is None:
            e = mv.elements[mv.snapped]
            l, t, r, b = (round(v * dpx) for v in (e.l, e.t, e.r, e.b))
            g, bx, by = I.brackets(l, t, r, b)
            im = self.photo(f"br-{l}-{t}-{r}-{b}", lambda: I.rgba(g))
            cv.create_image(ox + bx / dpx * k, oy + by / dpx * k, image=im, anchor="nw")
        cv.create_image(ox + mv.x * k, oy + mv.y * k, image=self.cursor_img(mv, st), anchor="center")
        bim = self.badge_img(mv, st)
        cv.create_image(ox + (mv.w - 16 / dpx) * k, oy + 720 / dpx * k, image=bim, anchor="ne")

    def hud(self, mv: J.Mover, st: dict) -> list[str]:
        """The debug line: pitch, reference, vertical speed, vowel, and why the last sound stopped."""
        hz = st.get("hz") or 0.0
        pitch = f"{hz:4.0f} Hz {st['st']:5.1f} st" if hz and st.get("st") is not None else "  -- Hz    -- st"
        ref = {"home": f"home {mv.mid:4.1f}", "start": f"start {st['ref']:4.1f}" if st.get("ref") is not None else "start --",
               "glide": f"mom {st.get('momentum', 0.0):+.2f}"}[mv.mode]
        vw = st.get("vowel") or {}
        vow = (max(vw, key=vw.get) + f" {max(vw.values()):.2f}") if vw else "--"
        vy = -(st.get("dy") or 0.0)
        edge = f"  EDGE {st['edge']}" if st.get("edge") and mv.sound else ""
        return [f"{pitch}  {ref}  vy {vy:+.2f}",
                f"vowel {vow}  x {st.get('x_vowel', 0.0) or 0.0:+.2f}  {st.get('phase', 'idle')}{edge}",
                f"stop: {st.get('stop') or mv.last_stop or '-'}"]

    def strip(self, x: float, top: float, h: float, mv: J.Mover, st: dict) -> None:
        """The debug pitch meter (key d) on the phone's right edge: the range (top = high), home and its dead zone
        (home mode) or the start note (start mode), and the live pitch."""
        cv = self.cv
        lo, hi = mv.range[0] - 1.0, mv.range[1] + 1.0
        yof = lambda v: top + (hi - min(max(v, lo), hi)) / (hi - lo) * h          # noqa: E731
        cv.create_rectangle(x, top, x + 16, top + h, fill="#161616", outline="#888")
        for v, name in zip(mv.range, ("lo", "hi")):
            cv.create_line(x - 3, yof(v), x + 19, yof(v), fill="#aaa")
            cv.create_text(x - 4, yof(v), text=name, fill="#ddd", anchor="e", font=("Courier", 8))
        dz = mv.p["dead_zone_st"]
        centre = mv.mid if mv.mode == "home" else st.get("ref") if mv.mode == "start" else None
        if centre is not None:
            cv.create_rectangle(x, yof(centre + dz), x + 16, yof(centre - dz), fill="#555", outline="")
            cv.create_line(x - 5, yof(centre), x + 21, yof(centre), fill="#fc6", width=3)
            cv.create_text(x - 6, yof(centre), text="home" if mv.mode == "home" else "start", fill="#fc6",
                           anchor="e", font=("Courier", 8, "bold"))
            if mv.mode == "home":
                for f in (mv.full_st(False), -mv.full_st(True)):
                    cv.create_line(x, yof(centre + f), x + 16, yof(centre + f), fill="#fc6", dash=(2, 2))
        if mv.sound and st.get("sm") is not None:
            yy = yof(st["sm"])
            cv.create_oval(x + 1, yy - 7, x + 15, yy + 7, fill="#3af", outline="white")

    def draw(self) -> None:
        s, cv, k = self.ses, self.cv, self.PX_PER_DP
        with s.lock:
            mv, sc = s.mv, s.screen
            st = dict(mv.state)
            ox, oy = 10, 10
            cv.delete("all")
            cv.create_rectangle(ox - 2, oy - 2, ox + sc["w"] * k + 2, oy + sc["h"] * k + 2, outline="#555", width=2,
                                fill="#222")
            if sc.get("png"):
                im = self.img(sc["png"])
                if im is not None:
                    cv.create_image(ox, oy, image=im, anchor="nw")
            tgt = s.task.cur["target"] if s.task and s.task.cur else None
            for i, e in enumerate(mv.elements):
                col, w = "#4a7", 1
                if i == tgt:
                    col, w = "#ff0", 4
                if i == mv.snapped:
                    col, w = "#0f6", 4
                cv.create_rectangle(ox + e.l * k, oy + e.t * k, ox + e.r * k, oy + e.b * k, outline=col, width=w)
            if mv.sound and mv.sound.path:
                pts = [(ox + x * k, oy + y * k) for _, x, y in mv.sound.path[-150:]]
                if len(pts) > 1:
                    cv.create_line(*[c for p in pts for c in p], fill="#39f", width=2)
            cx, cy = ox + mv.x * k, oy + mv.y * k
            if self.show_strip or not mv.enabled:        # debug view: the old dot, the magnet radius, the strip
                r = mv.s["magnet"]["snap_dp"] * k
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#357", dash=(3, 3))
                col = "#f80" if not mv.enabled else ("#3af" if mv.sound else "#29f")
                cv.create_oval(cx - 12, cy - 12, cx + 12, cy + 12, fill=col, outline="white", width=2)
                self.strip(ox + sc["w"] * k - 26, oy + 8, sc["h"] * k - 16, mv, st)
            else:
                self.indicators(ox, oy, mv, st)
            if s.last_click and s.t_ms - s.last_click[3] < 800:
                lx, ly = ox + s.last_click[0] * k, oy + s.last_click[1] * k
                cv.create_oval(lx - 22, ly - 22, lx + 22, ly + 22, outline="#f33", width=3)
            # the panel
            px, y = ox + sc["w"] * k + 24, 16
            txt = lambda t, c="#ddd", f=("Courier", 11): cv.create_text(px, y, text=t, fill=c, anchor="nw", font=f)  # noqa: E731
            txt("voice joystick", "#fff", ("Courier", 13, "bold")); y += 24
            txt(f"screen  {sc['id']}"); y += 18
            txt(f"mode    {'cursor' if mv.enabled else 'OFF'}   {st.get('phase', 'idle')}"); y += 18
            txt(f"cursor  {mv.x:5.0f}, {mv.y:5.0f} dp"); y += 18
            ref, off = st.get("ref"), st.get("offset")
            txt(f"VERTICAL {'1 home' if mv.mode == 'home' else '2 glide' if mv.mode == 'glide' else '3 start'}"
                f"   (keys 1 2 3)", "#fc6", ("Courier", 12, "bold")); y += 20
            for line in self.hud(mv, st):
                txt(line, "#fc6"); y += 16
            y += 4
            # the offset bar: dead zone shaded, full speed at the ends (glide: the momentum)
            p = mv.s["pitch"]
            bx, by, bh = px + 20, y + 10, 160
            fs = {"home": mv.full_st(bool(off is not None and off < 0)), "start": p["full_speed_st"],
                  "glide": 1.0}[mv.mode]
            if mv.mode == "glide":
                off = st.get("momentum") if mv.sound else None
            cv.create_rectangle(bx, by, bx + 16, by + bh, outline="#777")
            dzp = (mv.vt["glide"]["dead"] if mv.mode == "glide" else p["dead_zone_st"]) / fs * bh / 2
            cv.create_rectangle(bx, by + bh / 2 - dzp, bx + 16, by + bh / 2 + dzp, fill="#333", outline="")
            cv.create_line(bx - 4, by + bh / 2, bx + 20, by + bh / 2, fill="#aaa")
            if off is not None:
                oy2 = by + bh / 2 - max(-fs, min(fs, off)) / fs * bh / 2
                cv.create_oval(bx + 2, oy2 - 6, bx + 14, oy2 + 6, fill="#3af")
            unit, zero = ("", "momentum 0") if mv.mode == "glide" else (" st", {"home": "home", "start": "start note"}[mv.mode])
            cv.create_text(bx + 26, by, text=f"+{fs:.1f}{unit} up", fill="#888", anchor="nw", font=("Courier", 9))
            cv.create_text(bx + 26, by + bh / 2 - 6, text=zero, fill="#888", anchor="nw", font=("Courier", 9))
            cv.create_text(bx + 26, by + bh - 12, text=f"-{fs:.1f}{unit} down", fill="#888", anchor="nw", font=("Courier", 9))
            # vowel weights
            vw = st.get("vowel") or {}
            vx = px + 150
            for j, v in enumerate(("oo", "ah", "ee")):
                h = 120 * vw.get(v, 0.0)
                cv.create_rectangle(vx + j * 40, by + bh - h, vx + j * 40 + 26, by + bh,
                                    fill={"oo": "#f6a", "ah": "#aaa", "ee": "#6cf"}[v], outline="")
                cv.create_text(vx + j * 40 + 13, by + bh + 4, text=v, fill="#ccc", anchor="n", font=("Courier", 10))
            cv.create_text(vx, by, text="← oo   ah   ee →", fill="#888", anchor="nw", font=("Courier", 9))
            y = by + bh + 26
            txt(f"speed   {st.get('speed', 0.0):5.0f} dp/s"); y += 18
            if mv.snapped is not None:
                txt(f"snapped {mv.elements[mv.snapped].label[:28]}", "#0f6"); y += 18
            if s.task:
                sm = s.task.summary()
                txt(f"task    {len(s.task.trials)}/{s.task.n} done, {sm.get('hit', 0)} hit", "#ff0"); y += 18
                if s.task.cur:
                    txt(f"        {(s.t_ms - s.task.cur['t0']) / 1000:4.1f} s on this target", "#ff0"); y += 18
            if not s.pops_cal and not s.in_setup:
                txt("no pop? press SPACE (= pop)", "#f80", ("Courier", 12, "bold")); y += 20
            if s.hsetup:
                left = 3 - (s.t_ms - s.hsetup["t0"]) / 1000 if s.hsetup["t0"] else 3
                txt(f"HOME: hum 'mm' relaxed ({max(0, left):.0f} s)", "#f80", ("Courier", 12, "bold")); y += 20
            if s.psetup:
                n = sum(1 for f in s.pd.bursts[s.psetup["n0"]:] if f["peak_db"] >= 6)
                txt(f"POPS: pop your lips 3 times ({n} heard)", "#f80", ("Courier", 12, "bold")); y += 20
            if s.rsetup:
                left = 5 - (s.t_ms - s.rsetup["t0"]) / 1000 if s.rsetup["t0"] else 5
                txt(f"RANGE SETUP: glide low -> high -> low ({max(0, left):.0f} s)", "#f80", ("Courier", 12, "bold")); y += 20
            if s.vsetup:
                txt(f"VOWEL SETUP: hold '{s.vsetup['order'][s.vsetup['i']]}'", "#f80", ("Courier", 12, "bold")); y += 20
            if s.dsetup:
                txt({"clicks": "CLICKS: 3 tongue clicks", "hiss": "HISS: 2 short 'tss'"}[s.dsetup["kind"]], "#f80",
                    ("Courier", 12, "bold")); y += 20
            if s.wsetup:
                txt("WHISTLE: low -> high -> low (5 s)", "#f80", ("Courier", 12, "bold")); y += 20
            if s.rmsetup:
                txt("ROOM: stay quiet (3 s)", "#f80", ("Courier", 12, "bold")); y += 20
            if s.failed:
                txt(f"{s.STEP_NAMES[s.failed['step']]} FAILED", "#f44", ("Courier", 12, "bold")); y += 18
                for k in range(0, len(s.failed["why"]), 44):
                    txt(s.failed["why"][k:k + 44], "#f44", ("Courier", 10)); y += 14
                txt("R = retry this step   S = skip it", "#ff0", ("Courier", 12, "bold")); y += 20
            y += 8
            for line in s.log[-10:]:
                cv.create_text(px, y, text=line[:62], fill="#9a9", anchor="nw", font=("Courier", 9)); y += 14
            y += 6
            txt("1 home  2 glide  3 start  space pop  c centre\nm on/off  r rotate  n/p screen  t task  d strip\n"
                "h hum  g range  v vowels  o pops  s setup  q quit\nk clicks  w whistle  x hiss  b room\n"
                "setup step failed: r retry  s skip", "#777", ("Courier", 9))
        if self.stop.is_set():
            self.root.after(1500, self.root.destroy)
            return
        self.root.after(33, self.draw)


# ------------------------------------------------------------------------------------ main

def load_vowels(path: str | None) -> dict | None:
    """A vowels.json from the setup, or a voice_cursor score.json (the median F1/F2 of its vowel takes, in Bark)."""
    if not path:
        return None
    p = Path(path)
    if p.is_dir():
        p = p / ("vowels.json" if (p / "vowels.json").exists() else "score.json")
    d = json.loads(p.read_text())
    if "centroids_bark" in d:
        return {**d["centroids_bark"], **{k: d[k] for k in ("dead_zone", "full") if k in d}}
    if d.get("skipped"):                           # the vowel setup was skipped: the defaults
        return None
    by: dict[str, list] = {}
    for t in d.get("takes", []):
        if t.get("kind") == "vowel" and t.get("f1_hz") and t.get("f2_hz"):
            by.setdefault(t["vowel"], []).append((float(J.V.bark(t["f1_hz"])), float(J.V.bark(t["f2_hz"]))))
    return {v: [float(np.median([a for a, _ in L])), float(np.median([b for _, b in L]))] for v, L in by.items()} or None


def load_range(path: str | None) -> tuple[float, float] | None:
    """(lo_st, hi_st) from a range.json (the range setup) or a voice_cursor score (person.range), file or dir."""
    if not path:
        return None
    p = Path(path)
    if p.is_dir():
        p = p / ("range.json" if (p / "range.json").exists() else "score.json")
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    r = d.get("person", {}).get("range", d)
    return (float(r["lo_st"]), float(r["hi_st"])) if "lo_st" in r and "hi_st" in r else None


def load_voice(range_json: Path, pops_json: Path, calib2_json: Path | None = None) -> dict:
    """The personal settings of the last setup: home_st, clarity_on and the skipped steps (range.json), the pop
    thresholds and the accepted extractor labels (pops.json; none when the pop setup was skipped), and calibration
    v2's examples, whistle range and room (calib2.json)."""
    v = {}
    if calib2_json and calib2_json.exists():
        d = json.loads(calib2_json.read_text())
        v.update({k: d[k] for k in ("pops_examples", "clicks_examples", "hiss_examples", "whistle", "room")
                  if d.get(k) is not None})
    if range_json.exists():
        d = json.loads(range_json.read_text())
        v.update({k: d[k] for k in ("home_st", "clarity_on", "skipped") if k in d})
    if pops_json.exists():
        d = json.loads(pops_json.read_text())
        v.update({k: d[k] for k in ("pop", "pop_labels") if k in d})
    return v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["pw", "fake"], default="pw", help="pw = PipeWire mic; fake = synthetic singer")
    ap.add_argument("--device", help="PipeWire source name (default: the default source)")
    ap.add_argument("--task", type=int, default=0, help="scored task with N targets")
    ap.add_argument("--screen", help="screen id to start on (e.g. emu-settings-01)")
    ap.add_argument("--vowels", help="vowel centres: recordings/joystick/vowels.json or a voice_cursor score dir/json")
    ap.add_argument("--vowels-out", type=Path, default=OUT / "vowels.json", help="where the vowel setup (v) saves")
    ap.add_argument("--range", help="range (st) for home mode: range.json or a voice_cursor score dir/json (default: "
                    "the --vowels session's score, else recordings/joystick/range.json)")
    ap.add_argument("--range-out", type=Path, default=OUT / "range.json", help="where the range setup (g) saves")
    ap.add_argument("--mode", choices=list(J.Mover.MODES) + ["mid"],
                    help="vertical mode to start in (default: the spec's, home; mid = home)")
    ap.add_argument("--pops-out", type=Path, default=OUT / "pops.json", help="where the pop setup (o) saves")
    ap.add_argument("--calib2-out", type=Path, default=OUT / "calib2.json",
                    help="where calibration v2 (clicks, whistle, hiss, room, level gate) saves")
    ap.add_argument("--skip-setup", action="store_true", help="mic: do not start with the range + vowel setup")
    ap.add_argument("--setup-steps", help="mic: run only these setup steps, in this order, on top of the last setup "
                    "(e.g. clicks,whistle,hiss,room; names hum,glide,vowels,pops,clicks,whistle,hiss,room); s runs them too")
    ap.add_argument("--trace", action="store_true", help="per-tick numbers to recordings/joystick/trace-<time>.jsonl")
    ap.add_argument("--fake-voice", choices=list(FAKE_VOICES), default="low",
                    help="fake source: low = the user's range, hums start 1.2 st above the bottom; free = the old one")
    ap.add_argument("--spec", default=str(J.SPEC_PATH))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--headless", action="store_true", help="no window (fake source: faster than real time)")
    a = ap.parse_args()
    spec = J.load_spec(a.spec)
    screens = load_screens(spec)
    last = a.skip_setup or bool(a.setup_steps)          # start from the last setup (a partial one runs on top of it)
    if not a.vowels and a.source == "pw" and last and a.vowels_out.exists():
        a.vowels = str(a.vowels_out)               # the last setup's
    vowels = load_vowels(a.vowels)
    rng_st, rng_from = None, "spec fallback"
    for src in ([a.range] if a.range else []) + ([a.vowels] if a.vowels else []) + [str(a.range_out)]:
        rng_st = load_range(src)
        if rng_st:
            rng_from = src
            break
    if a.source == "fake":
        vowels = vowels or {k: [float(J.V.bark(f[0])), float(J.V.bark(f[1]))] for k, f in FAKE_FORMANTS.items()}
        v = FAKE_VOICES[a.fake_voice]
        if v["lo_hz"] and not a.range:
            rng_st, rng_from = (float(J.V.st(v["lo_hz"])), float(J.V.st(v["hi_hz"]))), f"fake voice {a.fake_voice}"
    voice = None
    if a.source == "pw" and last:                         # the last setup's home, voicing threshold and pops
        voice = load_voice(a.range_out, a.pops_out, a.calib2_out)
    ses = Session(spec, screens, a, vowels, rng_st, voice)
    ses.say(f"{spec['version']}: {len(screens)} screens, vowels {'own' if vowels else 'default (spec)'}, "
            f"source {a.source}")
    ses.say(f"vertical mode {ses.mv.mode}; range {ses.mv.range[0]:.1f}-{ses.mv.range[1]:.1f} st "
            f"(home {ses.mv.mid:.1f}{'' if ses.mv.home_setup is not None else ', the middle: no setup hum'}) "
            f"from {rng_from}")
    if a.source == "pw" and (not a.skip_setup or a.setup_steps):
        ses.command("setup")
    stop = threading.Event()
    if a.headless:
        if a.source != "fake":
            raise SystemExit("--headless needs --source fake")
        Session.headless_print = True
        t0 = time.monotonic()
        fake_loop(ses, stop, realtime=False)
        print(f"(simulated {ses.t_ms / 1000:.0f} s in {time.monotonic() - t0:.0f} s)")
    else:
        worker = threading.Thread(target=fake_loop if a.source == "fake" else mic_loop,
                                  args=(ses, stop, True) if a.source == "fake" else (ses, stop, a.device), daemon=True)
        win = Window(ses, stop)
        worker.start()
        win.root.mainloop()
        stop.set()
    if ses.trace:
        ses.trace.close()
        print(f"trace: {ses.trace_path}")
    if ses.task:
        ses.task.abort(ses.t_ms)                   # quit early: keep the target on screen as a partial trial
    if ses.task and ses.task.trials:
        sm = ses.task.summary()
        OUT.mkdir(parents=True, exist_ok=True)
        f = OUT / f"task-{datetime.now():%Y%m%d-%H%M%S}.json"
        f.write_text(json.dumps({"spec": spec["version"], "source": a.source, "synthetic": a.source == "fake",
                                 "fake_voice": a.fake_voice if a.source == "fake" else None,
                                 "seed": a.seed, "mode_at_end": ses.mv.mode, "range_st": list(ses.mv.range),
                                 "range_from": rng_from, "summary": sm, "trials": ses.task.trials,
                                 "vowels": "own" if a.vowels or ses.vowel_report else "default",
                                 "vowel_setup": ses.vowel_report, "home_st": round(ses.mv.mid, 2),
                                 "home_setup": ses.voice.get("home_st"), "clarity_on": round(ses.an.clarity_on, 3),
                                 "pops_calibrated": ses.pops_cal, "pops_by": ses.pop_by,
                                 "setup_skipped": ses.voice.get("skipped", [])}, indent=1))
        print(json.dumps(sm, indent=1))
        print(f"saved {f}")


if __name__ == "__main__":
    main()
