"""Offline replica of what the Android app does with a stream of sounds: would-act counts for the desktop tools.

Used by android/tools/mic_live.py (phone logs) and extractor/eval_real/aec_desktop.py (desktop extractor output),
tested against the Kotlin Sequencer's cases in tests/test_sequencer_sim.py. Aggregate scoring only.

Why not policy.group + policy.action_for: that groups up to three sounds within the gap and looks the whole group up.
The app does not. Its Sequencer (android/.../Sequencer.kt) ACTS AT ONCE unless a longer bound sequence starts with the
sounds so far, so a lone hiss is `back` straight away and "hiss hiss click" is two backs, not one unbound group. On
hiss-heavy input policy.group undercounts the app about 10x (wiki/phone-mic-echo.md, 2026-09-27).

What is mirrored (device clock only; every sound has t_start_ms / t_end_ms):
- Bindings: the app's Vocab.DEFAULT_BINDINGS + APP_ONLY_BINDINGS ([APP_BINDINGS]): pop pop = listen_for_phrase,
  click click = home, click hiss = forward, hiss click = back (absorbed: see below), single sounds as usual.
  NOTE: vocab.DEFAULT_BINDINGS is deliberately NOT this table. It is the training contract (finetune schema) and
  still binds click pop and lacks click hiss; do not "fix" it from here.
- Profile.sequences: a sequence whose shorter prefix has the same action is not "bound" but "absorbed" (default:
  hiss click = back = hiss). The prefix acts at once; the rest, if it follows within the gap, is swallowed.
- Sequencer.add: a sound joins the pending group iff its device gap (start - previous end) is 0..gap_ms (a gap below
  -50 ms is a clock reset: split); the group resolves at once when no bound sequence continues it or it reaches
  3 sounds; otherwise it waits. The wait ends (timeout) gap_ms + jitter_ms after the waiting sound ARRIVED; offline,
  arrival = t_end_ms + a constant latency, so a follow-up that ends later than prev.t_end + gap + jitter misses it
  even if it started within the gap (the app's "late" note).
- Decider (rules): a group with an `unknown` (PhoneGate) or a not-deliberate sound (policy.not_deliberate, the mirror
  of Decider.notDeliberate) does nothing; else its binding, or nothing if unbound.
- MicPopGate: from a phone or USB mic a lone pop has no default action unless the user bound it (pop_allowed).
- PhoneGate ([phone_gate]): the media gate's pop / hum rule and the media-hiss centroid rule, for event dicts that
  carry the extractor's numbers (`gate` from the phone's mic_sound log, or `raw` from the desktop extractor).
Not mirrored: MediaGate / media_lock (drops everything while media plays except a pop pop unlock), the touch guard,
user rules, personal sounds, the model deciders, cursor and phrase modes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .policy import not_deliberate

# android Vocab.DEFAULT_BINDINGS + Vocab.APP_ONLY_BINDINGS (2026-09-27).
APP_BINDINGS: dict[tuple[str, ...], str] = {
    ("rise",): "swipe_up",
    ("fall",): "swipe_down",
    ("arch",): "swipe_right",
    ("dip",): "swipe_left",
    ("pop",): "tap",
    ("hiss",): "back",
    ("flat",): "long_press",
    ("pop", "pop"): "listen_for_phrase",
    ("click", "click"): "home",
    ("hiss", "click"): "back",
    ("click", "hiss"): "forward",
}
GAP_MS = 600          # Settings.gapMs default
JITTER_MS = 150       # Sequencer jitterMs default
MAX_LEN = 3
CLOCK_SLACK_MS = 50   # Sequencer.CLOCK_SLACK_MS

# PhoneGate.kt
POP_SNR_DB = 14.0
HUM_SNR_DB = 14.0
HUM_CLARITY = 0.8
HISS_MEDIA_MAX_CENTROID_HZ = 6500
HUMS = {"rise", "fall", "arch", "dip", "flat"}


def bound_and_absorbed(bindings: dict[tuple[str, ...], str]) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]]]:
    """Profile.sequences (gesture mode, no user rules): live bindings split into bound and absorbed."""
    live = {s: a for s, a in bindings.items() if a != "none"}
    bound, absorbed = set(), set()
    for s, a in live.items():
        (absorbed if any(live.get(s[:i]) == a for i in range(1, len(s))) else bound).add(s)
    return bound, absorbed


def _num(e: dict, k: str):
    g = e.get("gate") or e.get("raw") or {}
    return g.get(k)


def phone_gate(e: dict, media_gate: bool = True, speaker_media: bool = True,
               hiss_max_centroid_hz: int = HISS_MEDIA_MAX_CENTROID_HZ) -> str | None:
    """Why PhoneGate turns this sound into `unknown`, or None. [media_gate]: PhoneGate.active (the mode's condition
    holds); [speaker_media]: media plays on the phone's own speaker (the hiss rule's condition); 0 = hiss rule off."""
    lab = e["label"]
    if media_gate:
        snr = _num(e, "snr_db") or 0.0
        if lab in ("pop", "click") and snr < POP_SNR_DB:
            return "pop"
        if lab in HUMS:
            if snr < HUM_SNR_DB:
                return "hum-db"
            if (_num(e, "clarity_med") or 0.0) < HUM_CLARITY:
                return "hum-clarity"
    if lab == "hiss" and speaker_media and hiss_max_centroid_hz > 0:
        c = _num(e, "centroid_hz")
        if c is not None and c > hiss_max_centroid_hz:
            return "hiss-centroid"
    return None


@dataclass
class Group:
    labels: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    starts: list[int] = field(default_factory=list)
    ends: list[int] = field(default_factory=list)
    ended_by: str = ""
    absorbed: list[str] = field(default_factory=list)


class Sequencer:
    """Sequencer.kt on the device clock. add() one sound at a time in time order; resolved groups land in .out."""

    def __init__(self, bindings: dict[tuple[str, ...], str] | None = None, gap_ms: int = GAP_MS,
                 jitter_ms: int = JITTER_MS, max_len: int = MAX_LEN):
        self.bound, self.absorb = bound_and_absorbed(bindings or APP_BINDINGS)
        self.gap, self.jitter, self.max_len = gap_ms, jitter_ms, max_len
        self.out: list[Group] = []
        self.pending: Group | None = None
        self.deadline: float | None = None   # arrival clock (t_end) at which a waiting group times out
        self.tail: dict | None = None        # {"group", "tails", "matched", "last_end"}

    def _resolve(self, why: str) -> None:
        p = self.pending
        if p is None:
            return
        self.pending, self.deadline = None, None
        p.ended_by = why
        n = len(p.labels)
        seq = tuple(p.labels)
        tails = [a for a in self.absorb if len(a) > n and a[:n] == seq]
        self.tail = {"group": p, "tails": tails, "matched": n, "last_end": p.ends[-1]} if why == "no-continuation" and tails else None
        self.out.append(p)

    def _absorbed(self, label: str, start: int, end: int) -> bool:
        t = self.tail
        if t is None:
            return False
        gap = start - t["last_end"]
        nxt = [s for s in t["tails"] if s[t["matched"]] == label]
        if not (-CLOCK_SLACK_MS <= gap <= self.gap) or not nxt:
            return False
        t["matched"] += 1
        t["last_end"] = end
        t["tails"] = [s for s in nxt if len(s) > t["matched"]]
        t["group"].absorbed.append(label)
        if not t["tails"]:
            self.tail = None
        return True

    def add(self, label: str, start: int, end: int, text: str = "") -> None:
        # the waiting group's timer fires before this sound arrives (arrival = its end)
        if self.pending is not None and self.deadline is not None and end > self.deadline:
            self._resolve("timeout")
        if self.pending is None and self._absorbed(label, start, end):
            return
        self.tail = None
        if self.pending is not None:
            gap = start - self.pending.ends[-1]
            if gap < -CLOCK_SLACK_MS:
                self._resolve("device-clock-reset")
            elif gap > self.gap:
                self._resolve("device-gap")
        if self.pending is None:
            self.pending = Group()
        p = self.pending
        p.labels.append(label); p.texts.append(text); p.starts.append(start); p.ends.append(end)
        seq = tuple(p.labels)
        waiting = [b for b in self.bound if len(b) > len(seq) and b[:len(seq)] == seq]
        if len(seq) >= self.max_len:
            self._resolve("max-length")
        elif not waiting:
            self._resolve("no-continuation")
        else:
            self.deadline = end + self.gap + self.jitter

    def flush(self) -> list[Group]:
        self._resolve("timeout" if self.pending is not None and self.deadline is not None else "flush")
        return self.out


def decide(g: Group, bindings: dict[tuple[str, ...], str] | None = None, mic: bool = True, pop_allowed: bool = False) -> str:
    """RuleDecider (default profile) + MicPopGate for one resolved group: the action, or "none"."""
    for lab, text in zip(g.labels, g.texts):
        if not_deliberate(lab, text):
            return "none"
    seq = tuple(g.labels)
    if mic and seq == ("pop",) and not pop_allowed:
        return "none"
    return (bindings or APP_BINDINGS).get(seq, "none")


def app_actions(events: list[dict], *, gate: dict | None = None, mic: bool = True, pop_allowed: bool = False,
                bindings: dict[tuple[str, ...], str] | None = None, gap_ms: int = GAP_MS,
                jitter_ms: int = JITTER_MS) -> list[tuple[Group, str]]:
    """Every resolved group and its action. [events]: dicts with label, text, t_start_ms, t_end_ms (+ gate / raw).
    An event with `"gated": <reason>` (the phone's mic_sound log: PhoneGate already ran on the phone) or, when
    [gate] is given (phone_gate kwargs), one that phone_gate() gates, enters the sequencer as `unknown`."""
    q = Sequencer(bindings, gap_ms, jitter_ms)
    for e in sorted(events, key=lambda e: e["t_start_ms"]):
        g = e.get("gated") or (phone_gate(e, **gate) if gate is not None else None)
        q.add("unknown" if g else e["label"], int(e["t_start_ms"]), int(e["t_end_ms"]), e.get("text", ""))
    return [(g, decide(g, bindings, mic, pop_allowed)) for g in q.flush()]


def would_act(events: list[dict], minutes: float, **kw) -> dict:
    """{"would_act", "would_act_pm", "actions": Counter-dict, "groups"} under app_actions(**kw)."""
    acts = [a for _, a in app_actions(events, **kw)]
    fire = [a for a in acts if a != "none"]
    return {"groups": len(acts), "would_act": len(fire), "would_act_pm": len(fire) / max(minutes, 1e-9),
            "actions": dict(Counter(fire))}
