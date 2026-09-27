"""Golden traces for the Kotlin voice joystick (app/.../joystick/JoystickCore.kt, JoyCalibration.kt): synthetic
sung audio (no recordings) -> extractor/joystick_core.py Analyzer -> ticks; the ticks (rounded, as stored) -> the
Python Mover / PopDetector / Clicker and the prototype's setup steps (joystick.Session) -> the expected outputs.
JoystickParityTest feeds the same ticks to the Kotlin port and compares.

  extractor/run python /home/khoa/VOX/android/tools/gen_joystick_golden.py
writes app/src/test/resources/joystick_golden.json. Deterministic (fixed seeds).
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

HERE = Path(__file__).resolve().parent
VOX = HERE.parent.parent
sys.path.insert(0, str(VOX / "extractor"))

import joystick as JS  # noqa: E402
import joystick_core as J  # noqa: E402
import synth  # noqa: E402

SPEC = J.load_spec()
RATE = 16000
OUT = HERE.parent / "app" / "src" / "test" / "resources" / "joystick_golden.json"
LO_HZ, HI_HZ = 92.4, 194.6                        # FakeSinger's "low" voice (the user's vcursor-2 range)
LO_ST, HI_ST = float(J.V.st(LO_HZ)), float(J.V.st(HI_HZ))
HOME_ST = LO_ST + 1.2
VOWELS = {k: [float(J.V.bark(f[0])), float(J.V.bark(f[1]))] for k, f in JS.FAKE_FORMANTS.items()}
W_DP, H_DP = 411.0, 914.0
ELEMENTS = [(180, 300, 228, 348, "button"), (0, 500, 411, 560, "row"), (40, 100, 88, 148, "icon"),
            (0, 0, 411, 914, "container"), (300, 700, 330, 730, "small"), (20, 800, 391, 880, "panel")]


def sing(plan: list[tuple], seed: int, marks: list | None = None) -> np.ndarray:
    """plan: (seconds, st0, st1, vowel) for a sung glide st0 -> st1 (st on the 55 Hz scale), (seconds, None) for
    silence, ("pop",) for a lip pop (40 ms, then the plan continues after it), ("whistle", seconds, hz0, hz1) for a
    whistled glide (a sine, log-linear), ("ex", label, raw) for an extractor event at that point (no audio: calibration
    v2's discrete steps read extractor events; appended to marks as (t_ms, label, raw))."""
    rng = np.random.default_rng(seed)
    f0s, amps, vows = [], [], []
    pops, whistles = [], []
    n_total = 0
    for step in plan:
        if step[0] == "pop":
            pops.append(n_total)
            continue
        if step[0] == "ex":
            if marks is not None:
                marks.append((n_total * 1000.0 / RATE, step[1], step[2]))
            continue
        if step[0] == "whistle":
            n = int(step[1] * RATE)
            whistles.append((n_total, n, step[2], step[3]))
            f0s.append(np.full(n, np.nan)); amps.append(np.zeros(n)); vows += ["ah"] * n
            n_total += n
            continue
        dur, st0 = step[0], step[1]
        n = int(dur * RATE)
        if st0 is None:
            f0s.append(np.full(n, np.nan)); amps.append(np.zeros(n)); vows += ["ah"] * n
        else:
            st1, v = step[2], step[3]
            st = np.linspace(st0, st1, n)
            f0s.append(55 * 2 ** (st / 12)); amps.append(np.full(n, 0.08)); vows += [v] * n
        n_total += n
    f0 = np.concatenate(f0s)
    amp = np.concatenate(amps)
    # 30 ms attack / release ramps
    k = int(0.03 * RATE)
    amp = np.convolve(amp, np.ones(k) / k, mode="same")
    f0 = np.where(np.isnan(f0), 120.0, f0) * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * np.arange(f0.size) / RATE))
    ph = np.cumsum(f0 / RATE)
    src = np.diff(np.floor(np.r_[0.0, ph])) - f0 / RATE
    y = lfilter([1.0], [1.0, -0.95], src)
    out = np.zeros_like(y)
    # formants per 20 ms block, moving 1/3 of the way each block (FakeSinger's 60 ms glide), filter state carried
    fm = np.array(JS.FAKE_FORMANTS[vows[0]], float)
    zi = [np.zeros(2) for _ in range(3)]
    blk = 320
    for i in range(0, y.size, blk):
        fm += (np.array(JS.FAKE_FORMANTS[vows[i]], float) - fm) * min(1.0, blk / (0.06 * RATE))
        z = y[i:i + blk]
        for j, (f, bw) in enumerate(zip(fm, (80, 100, 120))):
            r = np.exp(-np.pi * bw / RATE)
            c = -2 * r * np.cos(2 * np.pi * f / RATE)
            z, zi[j] = lfilter([1 + c + r * r], [1, c, r * r], z, zi=zi[j])
        out[i:i + blk] = z
    out = out / 3.0 * amp + rng.normal(0, 1e-3, out.size)
    for at, n, h0, h1 in whistles:
        f = h0 * (h1 / h0) ** np.linspace(0, 1, n)
        env = np.minimum(1.0, np.minimum(np.arange(n), n - 1 - np.arange(n)) / (0.03 * RATE))
        out[at:at + n] += 0.05 * env * np.sin(2 * np.pi * np.cumsum(f) / RATE)
    for at in pops:
        p = 0.2 * synth.make_pop(rng, RATE)[0]
        m = min(p.size, out.size - at)
        out[at:at + m] += p[:m]
    return out.astype(np.float32)


def r6(v: float) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(round(float(v), 6))


def ticks_of(x: np.ndarray, clarity_on: float | None = None, f0_max_from_ms: float | None = None) -> list[J.Tick]:
    """f0_max_from_ms: from then on the ticks use the whistle ceiling (calib_v2.whistle.tick_f0_max_hz), as the app
    does from the whistle step on."""
    an = J.Analyzer(SPEC)
    if clarity_on:
        an.clarity_on = clarity_on
    out = []
    for i in range(0, x.size, 320):
        if f0_max_from_ms is not None and i * 1000 / RATE >= f0_max_from_ms:
            an.f0_max_hz = SPEC["calib_v2"]["whistle"]["tick_f0_max_hz"]
        for tk in an.push(x[i:i + 320]):
            # stored rounded: the Python outputs below come from the rounded ticks, as the Kotlin test reads them
            out.append(J.Tick(r6(tk.t_ms), r6(tk.f0), r6(tk.clarity), r6(tk.db), tk.voiced,
                              np.nan if np.isnan(tk.f1) else r6(tk.f1), np.nan if np.isnan(tk.f2) else r6(tk.f2),
                              tk.why, r6(tk.f0_raw), r6(tk.over_db)))
    return out


def tick_row(tk: J.Tick) -> list:
    return [tk.t_ms, tk.f0, tk.clarity, tk.db, 1 if tk.voiced else 0, r6(tk.f1), r6(tk.f2), tk.why, tk.f0_raw, tk.over_db]


def run_core(name: str, mode: str, plan: list[tuple], seed: int, home: float | None, whistle: dict | None = None) -> dict:
    ticks = ticks_of(sing(plan, seed), f0_max_from_ms=0.0 if whistle else None)
    els = [J.Element(*e) for e in ELEMENTS]
    mv = J.Mover(SPEC, W_DP, H_DP, VOWELS, (LO_ST, HI_ST))
    mv.set_whistle(whistle)
    mv.set_mode(mode)
    if home is not None:
        mv.set_home(home)
    mv.set_screen(W_DP, H_DP, els)
    pd, ck = J.PopDetector(SPEC), J.Clicker(SPEC)
    rows, events = [], []
    for tk in ticks:
        mv.push(tk)
        st = mv.state
        pt = pd.push(tk)
        pop_r = ck.pop(pt) if pt is not None else None
        click = ck.poll(tk.t_ms)
        for ev in mv.events:
            events.append({"ev": ev["ev"], "t_ms": ev["t_ms"], "x": r6(ev["x"]), "y": r6(ev["y"]),
                           "snapped": ev.get("snapped"), "dur_ms": r6(ev.get("dur_ms", 0.0)),
                           "stop": [r6(v) for v in ev["stop"]] if "stop" in ev else None})
        mv.events.clear()
        rows.append({"x": r6(mv.x), "y": r6(mv.y), "phase": st.get("phase"), "snapped": mv.snapped,
                     "speed": r6(st.get("speed", 0.0)), "sm": r6(st.get("sm")), "offset": r6(st.get("offset")),
                     "momentum": r6(st.get("momentum", 0.0)), "x_vowel": r6(st.get("x_vowel", 0.0)),
                     "mid": r6(mv.mid), "pop": r6(pt) if pt is not None else None, "pop_r": pop_r, "click": click,
                     "band": st.get("band")})
    return {"name": name, "mode": mode, "home_st": home, "range_st": [LO_ST, HI_ST], "whistle": whistle,
            "ticks": [tick_row(t) for t in ticks],
            "expect": rows, "events": events,
            "bursts": [{k: (r6(v) if isinstance(v, float) else v) for k, v in b.items()} for b in pd.bursts]}


EX_DELAY_MS = 160.0                               # an extractor event arrives this long after its start (hangover)


def run_setup(name: str, plan: list[tuple], seed: int, actions: dict[float, str] | None = None) -> dict:
    """The prototype's setup (joystick.Session: home hum, range glide, ee / ah / oo, 3 pops, 3 clicks, the whistle
    glide, 2 hisses, 3 s of room) on synthetic audio, fed tick by tick as Session.feed does (nothing runs while a step
    has failed). The plan's ("ex", ...) marks are extractor events, handed to the session EX_DELAY_MS after their start
    (before the tick at or after that time). The ticks use the whistle ceiling from the first whistle on. actions:
    {t_ms: "retry" | "skip"} commands sent before that tick (the UI's RETRY / SKIP buttons)."""
    marks: list = []
    x = sing(plan, seed, marks)
    t_wh, t = None, 0.0
    for stp in plan:
        if stp[0] == "whistle" and t_wh is None:
            t_wh = t
        t += 0.0 if stp[0] in ("pop", "ex") else (stp[1] if stp[0] == "whistle" else stp[0])
    ticks = ticks_of(x, f0_max_from_ms=t_wh)
    exq = [[t0 + EX_DELAY_MS, t0, lab, raw] for t0, lab, raw in marks]
    tmp = Path(tempfile.mkdtemp())
    a = types.SimpleNamespace(screen=None, task=0, seed=seed, source="mic", vowels_out=tmp / "vowels.json",
                              range_out=tmp / "range.json", pops_out=tmp / "pops.json", calib2_out=tmp / "calib2.json",
                              mode="home")
    screens = [{"id": "s", "w": W_DP, "h": H_DP, "elements": []}]
    ses = JS.Session(SPEC, screens, a, None, (SPEC["vertical"]["home"]["range_st"][0], SPEC["vertical"]["home"]["range_st"][1]))
    log = []
    ses.say = lambda m: log.append(m)
    ses.command("setup")
    steps, fails = [], []
    actions = dict(actions or {})
    acts = [[k, c] for k, c in sorted(actions.items())]
    pend = list(exq)

    def active() -> str | None:
        for k, su in (("home", ses.hsetup), ("range", ses.rsetup), ("vowels", ses.vsetup), ("pops", ses.psetup),
                      ("whistle", ses.wsetup), ("room", ses.rmsetup)):
            if su is not None:
                return k
        return ses.dsetup["kind"] if ses.dsetup is not None else None

    for tk in ticks:
        ses.t_ms = tk.t_ms
        for at in [k for k in actions if k <= tk.t_ms]:
            ses.command(actions.pop(at))
            steps.append({"step": "cmd", "t_ms": tk.t_ms})
        while pend and pend[0][0] <= tk.t_ms:
            _, t0, lab, raw = pend.pop(0)
            ses.ex_event(t0, lab, raw)
        before = active()
        was_failed = ses.failed
        ses.pd.push(tk)
        ses.setup_tick(tk)
        after = active()
        if before is not None and after != before:
            steps.append({"step": before, "t_ms": tk.t_ms, "failed": bool(ses.failed)})
        if ses.failed and not was_failed:
            fails.append({"step": ses.failed["step"], "t_ms": tk.t_ms, "why": ses.failed["why"]})
    v = ses.voice
    rep = ses.vowel_report or {}
    return {"name": name, "ticks": [tick_row(t) for t in ticks], "steps_done": steps, "fails": fails, "actions": acts, "log": log,
            "skipped": v.get("skipped", []), "failed_at_end": ses.failed,
            "home_st": v.get("home_st"), "clarity_on": v.get("clarity_on"), "lo_st": v.get("lo_st"), "hi_st": v.get("hi_st"),
            "range_st": [float(ses.mv.range[0]), float(ses.mv.range[1])], "mid": float(ses.mv.mid),
            "centroids_bark": {k: [float(c[0]), float(c[1])] for k, c in ses.mv.cent.items()},
            "vowel_dead_zone": ses.mv.vw["dead_zone"], "vowel_full": ses.mv.vw["full"],
            "vowel_report": rep.get("per_vowel"), "pop": v.get("pop"), "pop_labels": v.get("pop_labels"),
            "ex_events": exq, "pops_examples": v.get("pops_examples"), "clicks_examples": v.get("clicks_examples"),
            "hiss_examples": v.get("hiss_examples"), "whistle": v.get("whistle"), "room": v.get("room"),
            "level_gate": ses.gate, "click_pop": ses.click_pop, "f0_max_at_end": ses.an.f0_max_hz}


WHISTLE = {"lo_st": float(J.V.st(950.0)), "hi_st": float(J.V.st(2000.0)), "home_st": float(J.V.st(1400.0)),
           "split_st": (HI_ST + float(J.V.st(950.0))) / 2}


def calib_v2_cases() -> dict:
    """Calibration v2's pure rules on hand-made numbers: derive_gate, gate_reason, derive_click_pop, relabel."""
    def ex(snr, level, dur=40, lf=0.03):
        return {"dur_ms": dur, "snr_db": snr, "level_db": level, "lf_ratio": lf, "peak_centroid_hz": 3000.0}
    pops = [ex(40.0, -13.0, 120, 0.3), ex(36.5, -16.0, 110, 0.25), ex(38.0, -15.0, 140, 0.4)]
    clicks = [ex(20.0, -31.0, 40, 0.02), ex(17.5, -33.5, 50, 0.03), ex(16.0, -34.0, 190, 0.05)]
    hiss = [ex(25.0, -25.0, 150, 0.04), ex(23.0, -26.0, 160, 0.05)]
    gates = []
    for name, e, room in (("none", {}, None), ("pops_only", {"pops": pops}, None),
                          ("all", {"pops": pops, "clicks": clicks, "hiss": hiss}, None),
                          ("room_quiet", {"pops": pops, "clicks": clicks}, {"transient_snr_db": 5.0, "transient_level_dbfs": -60.0}),
                          ("room_raises", {"pops": pops, "clicks": clicks}, {"transient_snr_db": 11.0, "transient_level_dbfs": -40.0}),
                          ("room_capped", {"clicks": clicks}, {"transient_snr_db": 30.0, "transient_level_dbfs": -20.0}),
                          ("room_none", {"clicks": clicks}, {"transient_snr_db": None, "transient_level_dbfs": None})):
        gates.append({"name": name, "examples": e, "room": room, "gate": J.derive_gate(e, room, SPEC)})
    g = gates[2]["gate"]
    reasons = []
    for lab, snr, lvl, off in (("pop", 30.0, -20.0, 0.0), ("click", 7.0, -30.0, 0.0), ("click", 9.0, -43.0, 0.0),
                               ("hiss", 12.0, -39.0, 0.0), ("hiss", 12.0, -39.0, 5.0), ("click", 8.5, -41.0, -2.0),
                               ("rise", 1.0, -80.0, 0.0), ("pop", None, -20.0, 0.0), ("click", 8.0, -42.0, 0.0)):
        reasons.append({"gate": g, "label": lab, "snr_db": snr, "level_db": lvl, "offset_db": off,
                        "why": J.gate_reason(g, lab, snr, lvl, off)})
    rules = []
    for name, p, c in (("sep", pops, clicks), ("one_feature", [ex(30, -20, 100, 0.2), ex(31, -21, 110, 0.2)],
                                                [ex(29, -20.5, 40, 0.19), ex(32, -19, 50, 0.21)]),
                       ("too_few", pops[:1], clicks)):
        rules.append({"name": name, "pops": p, "clicks": c, "rule": J.derive_click_pop(p, c, SPEC)})
    rule = rules[0]["rule"]
    relabels = []
    for lab, r in (("pop", ex(22.0, -30.0, 50, 0.02)), ("pop", ex(39.0, -14.0, 120, 0.3)), ("click", ex(37.0, -15.0, 120, 0.3)),
                   ("click", ex(19.0, -32.0, 40, 0.02)), ("pop", ex(22.0, -15.0, 50, 0.3)), ("hiss", ex(19.0, -32.0)),
                   ("pop", {"dur_ms": 50, "snr_db": 22.0, "level_db": None, "lf_ratio": None})):
        relabels.append({"rule": rule, "label": lab, "raw": r, "out": J.relabel(rule, lab, r)})
    return {"gates": gates, "reasons": reasons, "rules": rules, "relabels": relabels}


def main() -> None:
    H = HOME_ST
    home_plan = [(1.2, None), (1.0, H + 3, H + 3, "ah"), (0.4, None),
                 (1.2, H - 2, H - 2, "ee"), (0.12, None), (0.8, H, H, "oo"), (0.5, None),
                 ("pop",), (1.2, None), ("pop",), (0.36, None), ("pop",), (1.4, None),
                 (0.25, H - 9, H - 9, "ah"), (1.0, H + 1, H + 1, "ah"), (0.5, None),
                 (0.5, H + 2, H + 2, "ah"), (0.06, H + 14, H + 14, "ah"), (0.6, H + 2, H + 2, "ah"), (0.5, None),
                 (2.0, H - 3, H + 6, "ee"), (0.6, None),
                 (1.5, H + 7, H + 7, "oo"), (0.6, None), (1.0, H - 1.5, H - 1.5, "ee"), (0.8, None)]
    glide_plan = [(1.2, None), (0.4, H + 2, H + 2, "ah"), (0.4, H + 2, H + 5, "ah"), (0.8, H + 5, H + 5, "ah"),
                  (0.4, H + 5, H + 2, "ah"), (0.6, H + 2, H + 2, "ee"), (0.4, H + 2, H - 1, "ee"), (0.8, H - 1, H - 1, "oo"),
                  (0.5, None), (1.0, H + 4, H + 4, "ah"), (0.6, None)]
    start_plan = [(1.2, None), (1.0, H + 4, H + 4, "ah"), (0.5, None), (0.3, H - 6, H - 6, "ah"), (1.0, H + 3, H + 3, "ah"),
                  (0.5, None), (0.6, H + 5, H + 5, "ee"), (0.6, H + 8, H + 8, "ee"), (0.6, None),
                  (0.6, H + 5, H + 5, "oo"), (0.6, H + 2, H + 2, "oo"), (0.8, None)]
    lo, hi = LO_ST + 0.3, HI_ST - 0.3
    vowels_part = [(2.2, H + 2, H + 2, "ee"), (0.5, None), (2.2, H + 2, H + 2, "ah"), (0.5, None),
                   (2.2, H + 2, H + 2, "oo"), (0.8, None)]
    def raw(dur, snr, level, lf, pc):
        return {"dur_ms": dur, "snr_db": snr, "level_db": level, "lf_ratio": lf, "peak_centroid_hz": pc}
    pops_part = [("ex", "pop", raw(120, 41.5, -12.5, 0.31, 900.0)), ("pop",), (1.0, None),
                 ("ex", "pop", raw(110, 38.2, -15.9, 0.26, 850.0)), ("pop",), (1.0, None),
                 ("ex", "pop", raw(130, 40.1, -13.7, 0.35, 950.0)), ("pop",), (2.5, None)]
    # calibration v2: 3 clicks (one read as a hiss, as the guided single clicks often are), the whistle glide, 2
    # hisses, the room with one faint transient
    v2_part = [("ex", "click", raw(40, 20.3, -31.2, 0.02, 3600.0)), (1.0, None),
               ("ex", "click", raw(40, 18.1, -33.0, 0.03, 3400.0)), (1.0, None),
               ("ex", "hiss", raw(190, 16.4, -34.4, 0.05, 4400.0)), (1.5, None),
               (0.5, None), ("whistle", 2.6, 1000.0, 2000.0), ("whistle", 2.6, 2000.0, 1000.0), (0.8, None),
               ("ex", "hiss", raw(150, 25.0, -25.1, 0.04, 4300.0)), (1.0, None),
               ("ex", "hiss", raw(160, 23.2, -26.3, 0.05, 4200.0)), (1.5, None),
               (1.0, None), ("ex", "click", raw(30, 9.2, -50.3, 0.9, 1200.0)), (4.0, None)]
    setup_plan = ([(1.2, None), (3.4, H, H, "ah"), (0.6, None), (2.6, lo, hi, "ah"), (2.6, hi, lo, "ah"), (0.6, None)]
                  + vowels_part + pops_part + v2_part)
    # the range glide is too small (2 st) -> failed; RETRY at 12.5 s, a full glide; the vowels come as 'ah' only
    # (they overlap) -> failed; SKIP; then no pops at all in 8 s -> failed; SKIP
    # home mode with a whistle range: hum above / below home, then whistle above / below the whistle home
    whistle_plan = [(1.2, None), (1.0, H + 3, H + 3, "ah"), (0.5, None), (1.0, H - 2, H - 2, "ah"), (0.5, None),
                    ("whistle", 1.2, 1700.0, 1700.0), (0.5, None), ("whistle", 1.2, 1100.0, 1100.0), (0.5, None),
                    ("whistle", 1.5, 1100.0, 1900.0), (0.8, None)]
    fail_plan = ([(1.2, None), (3.4, H, H, "ah"), (0.6, None), (2.6, H, H + 2, "ah"), (2.6, H + 2, H, "ah"), (1.5, None),
                  (2.6, lo, hi, "ah"), (2.6, hi, lo, "ah"), (0.6, None),
                  (2.2, H + 2, H + 2, "ah"), (0.5, None), (2.2, H + 2, H + 2, "ah"), (0.5, None), (2.2, H + 2, H + 2, "ah"),
                  (1.5, None), (9.0, None)]
                 # clicks: one in 8 s -> failed, SKIP; whistle: a sung glide inside the voice range -> overlaps, SKIP;
                 # hiss: nothing -> failed, RETRY, two hisses -> passes; room: a pop as loud as a calibrated sound ->
                 # failed, SKIP -> done (the level gate stays the default: no clicks step)
                 + [(0.5, None), ("ex", "click", raw(40, 19.0, -32.0, 0.02, 3500.0)), (8.2, None),
                    (2.5, H + 1, H + 7, "ah"), (2.5, H + 7, H + 1, "ah"), (1.0, None), (10.0, None),
                    (1.0, None), ("ex", "hiss", raw(150, 25.0, -25.1, 0.04, 4300.0)), (1.0, None),
                    ("ex", "hiss", raw(160, 23.2, -26.3, 0.05, 4200.0)), (1.0, None),
                    (1.5, None), ("ex", "pop", raw(100, 30.5, -20.0, 0.3, 900.0)), (4.0, None)])
    fail_actions = {12500.0: "retry", 26000.0: "skip", 35000.0: "skip", 44000.0: "skip", 51500.0: "skip",
                    60400.0: "retry", 68000.0: "skip"}
    out = {"about": "Made by android/tools/gen_joystick_golden.py from synthetic audio (no recordings); ticks: "
                    "[t_ms, f0, clarity, db, voiced, f1, f2, why, f0_raw, over_db] (f1/f2 null = none)",
           "spec_version": SPEC["version"], "w_dp": W_DP, "h_dp": H_DP, "vowels": VOWELS,
           "elements": [list(e) for e in ELEMENTS],
           "cases": [run_core("home", "home", home_plan, 1, HOME_ST), run_core("home_nosetup", "home", home_plan, 2, None),
                     run_core("glide", "glide", glide_plan, 3, HOME_ST), run_core("start", "start", start_plan, 4, None),
                     run_core("home_whistle", "home", whistle_plan, 7, HOME_ST, WHISTLE)],
           "calib_v2": calib_v2_cases(),
           "setup": [run_setup("setup", setup_plan, 5), run_setup("setup_fail", fail_plan, 6, fail_actions)]}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    for c in out["cases"]:
        ev = [e["ev"] for e in c["events"]]
        print(c["name"], len(c["ticks"]), "ticks;", ev.count("hum_start"), "hums;",
              sum(1 for r in c["expect"] if r["pop"] is not None), "pops;",
              sum(1 for r in c["expect"] if r["click"]), "clicks;",
              sum(1 for r in c["expect"] if r["pop_r"] == "pop_pop"), "pop pops;",
              sum(1 for e in c["events"] if e["ev"] == "hum_end" and e["snapped"] is not None), "snaps")
    for s in out["setup"]:
        print(s["name"], "steps", s["steps_done"], "fails", s["fails"], "skipped", s["skipped"], "home", s["home_st"],
              "clarity", s["clarity_on"], "range", s["lo_st"], s["hi_st"], "pop", s["pop"], "report", s["vowel_report"])
        print("  log:", *s["log"], sep="\n    ")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
