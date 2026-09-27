"""Synthetic VOX decision data with code-computed ground truth.

Each row is a jevlike JSONL example (context, options, label) plus VOX fields:
  option_keys  - action keys aligned with options
  kind         - scenario family (default, app_rule, global_rule, sequence, not_deliberate,
                 unbound, phrase, phrase_rule, cursor)
  split        - which split the row was generated for

Held-out splits test what a decision tree cannot do: follow rules it has never seen.
  test_unseen_phrasing  rule sentences and gesture descriptions from templates never used in training
  test_unseen_apps      apps never seen in training

Usage: python -m vox.generate --output data/v0 [--train 40000 ...]
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from . import wordings as W
from .schema import (
    ACTIONS, APPS, CLARITY, CONTOURS, CURSOR_ACTIONS, DEFAULT_BINDINGS, DISCRETE,
    DURATION, EXCURSION, FREED_SEQUENCES, APP_ONLY_BINDINGS, LOUDNESS, PHRASES, APP_SCREENS, SCREEN_SCROLL, screen_text,
    SCREEN_NEXT, SCREEN_PREV, PAUSE_WORDS, PLAY_WORDS,
)

# The decision policy, stated once. Teachers get it as instructions; students learn it from labels.
POLICY = (
    "Pick the phone action for the vocal gesture just heard. "
    "Only act on deliberate gestures: if it sounds like talking, laughing, coughing or background music, "
    "or a hum is noisy, very short, or changes pitch by only a small amount (except a flat hum), choose do nothing. "
    "A flat hum must last at least 400 ms to count. A hiss longer than 1 s or that sounds like background noise is not deliberate. "
    "The user's rule for the current app overrides their global rules, which override the defaults. "
    "Rules for other apps do not apply. A gesture sequence with no binding means do nothing. "
    "Cursor mode is switched on and off by the device button. In cursor mode: rise/fall/arch/dip move the cursor "
    "up/down/right/left, fast if loud else slow; a pop clicks, a flat hum stops, a hiss goes back, unless a rule says otherwise. "
    "In listening mode, map the spoken phrase to the action it asks for, using the user's phrase rules first. "
    "The screen line only breaks ties for phrases: 'next'/'previous' mean swiping in a feed, photo viewer or document; "
    "'pause' when already paused or 'play' when already playing means do nothing. "
    "Never change an explicit gesture or rule because of the screen."
)
DEFAULTS_TEXT = "defaults: rise=swipe up, fall=swipe down, arch=swipe right, dip=swipe left, pop=tap, hiss=go back, long flat hum=long-press, click pop=listen for a phrase, click click=go home, hiss click=go back"


HELDOUT_APPS = {"com.netflix.mediaclient", "com.pinterest", "com.duolingo", "com.google.android.apps.docs"}
TRAIN_APPS = [p for p in APPS if p not in HELDOUT_APPS]

# How users might describe each gesture inside a rule. Last entries are held out.
GESTURE_WORDS = {
    "rise": (["a rising hum", "a low-to-high hum", "humming upward"], ["an upward glide", "a hum that climbs"]),
    "fall": (["a falling hum", "a high-to-low hum", "humming downward"], ["a downward glide", "a hum that drops"]),
    "arch": (["an arch hum (up then down)", "a hum that goes up then down"], ["a rise-and-fall hum", "a hill-shaped hum"]),
    "dip": (["a dip hum (down then up)", "a hum that goes down then up"], ["a fall-and-rise hum", "a valley-shaped hum"]),
    "flat": (["a long flat hum", "a steady hum"], ["a level held note", "an unchanging hum"]),
    "pop": (["a pop", "a lip pop"], ["a popping sound", "a lip smack"]),
    "click": (["a tongue click", "a click"], ["a tongue tut", "a clicking noise"]),
    "hiss": (["a hiss", "an sss sound"], ["a hissing noise", "a long s sound"]),
}
RULE_TEMPLATES = (
    [
        "In {app}, {g} means {a}.",
        "When {app} is open, map {g} to {a}.",
        "{app}: {g} -> {a}",
        "For {app} only, {g} should {a}.",
    ],
    [
        "While I'm using {app}, treat {g} as '{a}'.",
        "If {app} is in front and I make {g}, {a}.",
    ],
)
GLOBAL_TEMPLATES = (
    ["Everywhere, {g} means {a}.", "Globally map {g} to {a}.", "In every app, {g} -> {a}"],
    ["No matter which app, {g} should {a}.", "Across all apps, treat {g} as '{a}'."],
)
DISABLE_TEMPLATES = (
    ["In {app}, ignore {g}.", "Disable {g} in {app}."],
    ["When {app} is open, {g} should do nothing."],
)
PHRASE_TEMPLATES = (
    ["When I say '{p}', {a}.", "Phrase '{p}' -> {a}"],
    ["If I speak the words '{p}', {a}."],
)
# How users describe actions inside rules: (training wordings, held-out wordings). Rules never
# quote the option text verbatim in held-out splits, so string matching can't solve them.
ACTION_WORDS = {
    "swipe_up": (["swipe up", "flick up"], ["push the screen upward"]),
    "swipe_down": (["swipe down", "flick down"], ["drag the page downward"]),
    "swipe_left": (["swipe left", "flick left"], ["slide the screen to the left"]),
    "swipe_right": (["swipe right", "flick right"], ["slide the screen to the right"]),
    "tap": (["tap", "tap the screen"], ["touch the screen once"]),
    "double_tap": (["double-tap", "tap twice"], ["touch the screen two times quickly"]),
    "long_press": (["long-press", "press and hold"], ["keep a finger held down"]),
    "back": (["go back", "press back"], ["return to the previous screen"]),
    "home": (["go home", "go to the home screen"], ["jump to the launcher"]),
    "recents": (["open recent apps", "show the app switcher"], ["show my open apps"]),
    "notifications": (["open notifications", "pull down the notification shade"], ["show my alerts"]),
    "scroll_up": (["scroll up", "scroll up a little"], ["nudge the page up"]),
    "scroll_down": (["scroll down", "scroll down a little"], ["nudge the page down"]),
    "zoom_in": (["zoom in", "magnify"], ["make things bigger"]),
    "zoom_out": (["zoom out", "shrink the view"], ["make things smaller"]),
    "next_item": (["go to the next item", "skip ahead"], ["move on to the following one"]),
    "previous_item": (["go to the previous item", "go back one item"], ["return to the prior one"]),
    "play_pause": (["play or pause", "toggle playback"], ["start or stop the media"]),
    "volume_up": (["turn the volume up", "make it louder"], ["raise the sound level"]),
    "volume_down": (["turn the volume down", "make it quieter"], ["lower the sound level"]),
    "open_camera": (["open the camera", "launch the camera"], ["start the camera app"]),
    "take_photo": (["take a photo", "snap a picture"], ["capture an image"]),
    "like": (["like it", "favourite it"], ["give it a heart"]),
    "listen_for_phrase": (["listen for a phrase", "start listening"], ["wait for my spoken command"]),
}

CUSTOM_PHRASES = ["boom", "banana", "okay go", "flip it", "zap", "hey vox", "cheese", "nope", "yes please", "wiggle"]
HELDOUT_PHRASES = {"previous": "previous_item", "turn it down": "volume_down", "enlarge": "zoom_in",
                   "app switcher": "recents", "favourite": "like"}


def seq_text(seq: tuple[str, ...]) -> str:
    return " then ".join(seq)


@dataclass
class Scene:
    mode: str = "gesture"
    app: str = "com.zhiliaoapp.musically"
    heard: list[str] = field(default_factory=list)   # one line per sound in the sequence
    sequence: tuple[str, ...] = ()
    rules: list[str] = field(default_factory=list)
    phrase: str | None = None
    recent: list[str] = field(default_factory=list)
    cursor: str | None = None
    screen: tuple[str, str, str, str] | None = None   # (kind, media, scroll, keyboard); None = unavailable

    def text(self) -> str:
        lines = [f"mode: {self.mode}", f"app: {APPS[self.app]} ({self.app})"]
        if self.screen:
            lines.append(screen_text(*self.screen))
        if self.cursor:
            lines.append(f"cursor: {self.cursor}")
        if self.phrase is not None:
            lines.append(f"spoken phrase: \"{self.phrase}\"")
        for i, h in enumerate(self.heard, 1):
            lines.append(f"sound {i}: {h}")
        if self.sequence:
            lines.append(f"sequence: {seq_text(self.sequence)}")
        lines.append(DEFAULTS_TEXT)
        lines.append("my rules:" + ("".join(f"\n- {r}" for r in self.rules) if self.rules else " none"))
        if self.recent:
            lines.append("recent actions: " + ", ".join(self.recent))
        return "\n".join(lines)


class Generator:
    def __init__(self, rng: random.Random, heldout_phrasing: bool, apps: list[str], rich: bool = False) -> None:
        self.rng = rng
        self.h = 1 if heldout_phrasing else 0
        self.apps = apps
        # rich: training splits draw from the larger v2 wording banks in wordings.py
        self.rich = rich and not heldout_phrasing

    def pick(self, v1_lists: tuple[list[str], list[str]], rich_list: list[str]) -> str:
        return self.rng.choice(rich_list if self.rich else v1_lists[self.h])

    # --- sound descriptions -------------------------------------------------
    def deliberate_sound(self, g: str, loud: str | None = None) -> str:
        r = self.rng
        loud = loud or r.choice(LOUDNESS[1:] if r.random() < 0.8 else LOUDNESS)
        if g in CONTOURS:
            exc = EXCURSION[0] if g == "flat" else r.choice(EXCURSION[1:] if r.random() < 0.3 else EXCURSION[2:])
            dur = r.choice(DURATION[2:]) if g == "flat" else r.choice(DURATION[1:3])
            like = r.choice(["hum", "hum", "whistle"])
            return (f"hum that {CONTOURS[g]}; pitch change {exc}; duration {dur}; "
                    f"tone {r.choice(CLARITY[1:] if r.random() < 0.15 else CLARITY[2:])}; loudness {loud}; sounds like {like}")
        if g == "hiss":
            return f"{DISCRETE[g]}; duration {r.choice(DURATION[1:3])}; loudness {loud}; sounds like mouth sound"
        return f"{DISCRETE[g]}; instant sound; loudness {loud}; sounds like mouth sound"

    def air_hiss(self) -> str:
        """Fan / air-conditioning / traffic noise that the hiss detector picks up: must map to none."""
        r = self.rng
        dur, like = r.choice([(DURATION[3], "background noise"), (DURATION[3], "mouth sound"), (r.choice(DURATION[1:3]), "background noise")])
        return f"{DISCRETE['hiss']}; duration {dur}; loudness {r.choice(LOUDNESS[:2])}; sounds like {like}"

    def screen(self, app: str, kind: str | None = None) -> tuple[str, str, str, str]:
        r = self.rng
        kind = kind or r.choice(APP_SCREENS[app])
        media = r.choice(["playing", "playing", "paused"]) if kind in ("video feed", "video player") else r.choice(["none"] * 4 + ["playing", "paused"])
        scroll = "not scrollable" if kind in ("camera viewfinder", "dialog") else r.choice(SCREEN_SCROLL)
        keyboard = "open" if kind == "text entry" else r.choice(["hidden"] * 9 + ["open"])
        return kind, media, scroll, keyboard

    @staticmethod
    def phrase_answer(phrase: str, base: str, screen: tuple[str, str, str, str] | None) -> str:
        """Tie-breaker: resolve a screen-dependent phrase. Explicit phrase rules never come through here."""
        if screen is None:
            return base
        kind, media = screen[0], screen[1]
        if base == "next_item":
            return SCREEN_NEXT.get(kind, base)
        if base == "previous_item":
            return SCREEN_PREV.get(kind, base)
        if base == "play_pause":
            if phrase in PAUSE_WORDS and media == "paused":
                return "none"
            if phrase in PLAY_WORDS and media == "playing":
                return "none"
        return base

    def junk_sound(self) -> tuple[str, str, str]:
        """A sound that must map to none, why (kept in meta for error analysis), and its contour."""
        r = self.rng
        g = r.choice(list(CONTOURS))
        why = r.choice(["talking", "laughing", "coughing", "background music", "noisy", "too_short", "small_change", "short_flat"])
        exc = r.choice(EXCURSION[1:])
        dur = r.choice(DURATION[1:3])
        clarity = r.choice(CLARITY[1:])
        like = "hum"
        if why in ("talking", "laughing", "coughing", "background music"):
            like = why
            clarity = r.choice(CLARITY)
        elif why == "noisy":
            clarity = "noisy"
        elif why == "too_short":
            dur = DURATION[0]
        elif why == "small_change":
            g = r.choice(["rise", "fall", "arch", "dip"])
            exc = EXCURSION[0]
        elif why == "short_flat":
            g, exc, dur = "flat", EXCURSION[0], DURATION[1]
        if g == "flat":
            exc = EXCURSION[0]
        text = (f"hum that {CONTOURS[g]}; pitch change {exc}; duration {dur}; tone {clarity}; "
                f"loudness {r.choice(LOUDNESS)}; sounds like {like}")
        return text, why, g

    # --- rule sentences -----------------------------------------------------
    def gword(self, g: str) -> str:
        return self.pick(GESTURE_WORDS[g], W.GESTURE_WORDS_TRAIN[g])

    def seq_words(self, seq: tuple[str, ...]) -> str:
        return " followed by ".join(self.gword(g) for g in seq)

    def aword(self, action: str) -> str:
        """Action wording inside a rule. Training sometimes quotes the option text; held-out never does."""
        if not self.h and self.rng.random() < 0.3:
            return ACTIONS[action]
        return self.pick(ACTION_WORDS[action], W.ACTION_WORDS_TRAIN[action])

    def app_rule(self, app: str, seq: tuple[str, ...], action: str) -> str:
        return self.pick(RULE_TEMPLATES, W.RULE_TEMPLATES_TRAIN).format(app=APPS[app], g=self.seq_words(seq), a=self.aword(action))

    def global_rule(self, seq: tuple[str, ...], action: str) -> str:
        return self.pick(GLOBAL_TEMPLATES, W.GLOBAL_TEMPLATES_TRAIN).format(g=self.seq_words(seq), a=self.aword(action))

    def disable_rule(self, app: str, seq: tuple[str, ...]) -> str:
        return self.pick(DISABLE_TEMPLATES, W.DISABLE_TEMPLATES_TRAIN).format(app=APPS[app], g=self.seq_words(seq))

    def distractor_rules(self, current_app: str, avoid: tuple[str, ...], n: int) -> list[str]:
        """Rules for other apps, or global rules about other gestures: must not change the answer."""
        r, out = self.rng, []
        for _ in range(n):
            other = r.choice([a for a in self.apps if a != current_app])
            seq = self.random_seq(avoid)
            act = r.choice(self.gesture_actions())
            out.append(self.app_rule(other, seq, act))
        return out

    # --- helpers ------------------------------------------------------------
    @staticmethod
    def gesture_actions() -> list[str]:
        return [a for a in ACTIONS if a != "none"]

    def random_seq(self, avoid: tuple[str, ...] = ()) -> tuple[str, ...]:
        r = self.rng
        pool = list(CONTOURS) + list(DISCRETE)
        while True:
            seq = tuple(r.choice(pool) for _ in range(r.choice([1, 1, 2, 2, 3])))
            if seq != avoid:
                return seq

    def recent(self) -> list[str]:
        return [ACTIONS[a] for a in self.rng.sample(self.gesture_actions(), self.rng.choice([0, 0, 1, 2, 3]))]

    def options(self, answer: str, table: dict[str, str], must: list[str] | None = None) -> tuple[list[str], list[str], int]:
        r = self.rng
        if r.random() < 0.3:  # what the phone sends: every option, in table order
            keys = list(table)
            return keys, [table[k] for k in keys], keys.index(answer)
        keys = {answer, "none", *(must or [])}
        pool = [k for k in table if k not in keys]
        keys |= set(r.sample(pool, min(len(pool), r.randint(6, 12))))
        keys = sorted(keys)  # sets iterate in hash order, which changes per run (PYTHONHASHSEED)
        r.shuffle(keys)
        return keys, [table[k] for k in keys], keys.index(answer)

    # --- scenario families --------------------------------------------------
    def make(self, kind: str) -> dict:
        r = self.rng
        app = r.choice(self.apps)
        sc = Scene(app=app, recent=self.recent())
        if r.random() < 0.85:
            sc.screen = self.screen(app)
        meta: dict = {}
        must: list[str] = []

        if kind in ("default", "app_rule", "global_rule", "sequence", "disabled", "unbound"):
            if kind == "sequence":
                seq = self.random_seq()
                while len(seq) < 2 or seq in DEFAULT_BINDINGS:
                    seq = self.random_seq()
            elif kind == "unbound":
                seq = r.choice(FREED_SEQUENCES) if r.random() < 0.3 else self.random_seq()
                while seq in DEFAULT_BINDINGS or seq in APP_ONLY_BINDINGS:  # app-only: resolved by the app, never "none"
                    seq = self.random_seq()
            else:
                seq = r.choice(list(DEFAULT_BINDINGS))
            sc.sequence = seq
            sc.heard = [self.deliberate_sound(g) for g in seq]
            sc.rules = self.distractor_rules(app, seq, r.randint(0, 3))
            answer = DEFAULT_BINDINGS.get(seq, "none")
            if kind in ("app_rule", "sequence"):
                answer = r.choice(self.gesture_actions())
                sc.rules.append(self.app_rule(app, seq, answer))
                if r.random() < 0.4:  # a conflicting global rule that the app rule must override
                    other = r.choice([a for a in self.gesture_actions() if a != answer])
                    sc.rules.append(self.global_rule(seq, other))
                    must.append(other)
                if seq in DEFAULT_BINDINGS:
                    must.append(DEFAULT_BINDINGS[seq])
            elif kind == "global_rule":
                answer = r.choice(self.gesture_actions())
                sc.rules.append(self.global_rule(seq, answer))
                must.append(DEFAULT_BINDINGS[seq])
            elif kind == "disabled":
                sc.rules.append(self.disable_rule(app, seq))
                must.append(answer)
                answer = "none"
            r.shuffle(sc.rules)

        elif kind == "not_deliberate":
            seq = r.choice(list(DEFAULT_BINDINGS)[:4] + [("flat",)])
            if r.random() < 0.2:
                text, why, g = self.air_hiss(), "air_hiss", "hiss"
            else:
                text, why, g = self.junk_sound()
            sc.sequence = (g,)
            sc.heard = [text]
            sc.rules = self.distractor_rules(app, seq, r.randint(0, 2))
            meta["why"] = why
            answer = "none"

        elif kind in ("phrase", "phrase_rule", "screen_phrase"):
            sc.mode = "listening"
            sc.rules = self.distractor_rules(app, (), r.randint(0, 2))
            if kind == "screen_phrase":
                base = r.choice(["next_item", "previous_item", "play_pause"])
                if base == "play_pause":
                    sc.phrase = r.choice(sorted(PAUSE_WORDS | PLAY_WORDS))
                elif self.h and base == "previous_item" and r.random() < 0.5:
                    sc.phrase = "previous"
                else:
                    sc.phrase = r.choice(PHRASES[base])
                sc.screen = self.screen(app) if r.random() < 0.9 else None
                answer = self.phrase_answer(sc.phrase, base, sc.screen)
                meta["base"] = base
                # both readings must be on the menu, or the row is solvable by elimination
                alts = {"next_item": SCREEN_NEXT, "previous_item": SCREEN_PREV}.get(base, {})
                must += [base, *sorted(set(alts.values()))]
            elif kind == "phrase":
                if self.h and r.random() < 0.6:
                    sc.phrase, answer = r.choice(list(HELDOUT_PHRASES.items()))
                else:
                    answer = r.choice(list(PHRASES))
                    sc.phrase = r.choice(PHRASES[answer])
                answer = self.phrase_answer(sc.phrase, answer, sc.screen)
                if r.random() < 0.15:  # mumble / unrelated speech
                    sc.phrase, answer = r.choice(["uh what was that", "hmm", "no I'm talking to someone", "what time is it"]), "none"
            else:
                sc.phrase = r.choice(CUSTOM_PHRASES)
                answer = r.choice(self.gesture_actions())
                sc.rules.append(self.pick(PHRASE_TEMPLATES, W.PHRASE_TEMPLATES_TRAIN).format(p=sc.phrase, a=self.aword(answer)))
                r.shuffle(sc.rules)

        elif kind == "cursor":
            return self.make_cursor(sc)
        else:
            raise ValueError(kind)

        keys, opts, label = self.options(answer, ACTIONS, must)
        return {"context": sc.text(), "options": opts, "label": label, "option_keys": keys, "kind": kind, **({"meta": meta} if meta else {})}

    def make_cursor(self, sc: Scene) -> dict:
        r = self.rng
        sc.mode = "cursor"
        sc.cursor = r.choice(["moving right slow", "moving up fast", "stopped", "stopped", "dragging, stopped"])
        g = r.choice(list(CONTOURS) + ["pop", "click_click", "hiss"])
        loud = r.choice(LOUDNESS)
        direction = {"rise": "up", "fall": "down", "arch": "right", "dip": "left"}
        rules = self.distractor_rules(sc.app, (), r.randint(0, 2))
        if g in direction:
            sc.sequence = (g,)
            sc.heard = [self.deliberate_sound(g, loud)]
            answer = f"move_{direction[g]}_{'fast' if loud == 'loud' else 'slow'}"
            if r.random() < 0.25:  # user rule: diagonal
                diag = r.choice(["up_left", "up_right", "down_left", "down_right"])
                answer = f"move_{diag}_{'fast' if loud == 'loud' else 'slow'}"
                rules.append(f"In cursor mode, {self.gword(g)} moves the cursor {diag.replace('_', '-')}.")
        elif g == "flat":
            sc.sequence = ("flat",)
            sc.heard = [self.deliberate_sound("flat", loud)]
            answer = "stop"
        elif g == "pop":
            sc.sequence = ("pop",)
            sc.heard = [self.deliberate_sound("pop", loud)]
            answer = "click"
        elif g == "hiss":
            sc.sequence = ("hiss",)
            sc.heard = [self.deliberate_sound("hiss", loud)]
            if r.random() < 0.4:
                rules.append(f"In cursor mode, {self.gword('hiss')} starts or ends a drag.")
                answer = "drag_toggle"
            else:
                answer = "back"
        else:
            sc.sequence = ("click", "click")
            sc.heard = [self.deliberate_sound("click", loud) for _ in range(2)]
            answer = "none"  # the button leaves cursor mode; click click is free for a user rule
            if r.random() < 0.5:
                rules.append(f"In cursor mode, {self.seq_words(('click', 'click'))} starts or ends a drag.")
                answer = "drag_toggle"
        if r.random() < 0.12:
            text, _, jg = self.junk_sound()
            sc.heard, sc.sequence, answer = [text], (jg,), "none"
        sc.rules = rules
        r.shuffle(sc.rules)
        keys, opts, label = self.options(answer, CURSOR_ACTIONS)
        return {"context": sc.text(), "options": opts, "label": label, "option_keys": keys, "kind": "cursor"}


KIND_WEIGHTS = {
    "default": 3, "app_rule": 4, "global_rule": 2, "sequence": 3, "disabled": 1, "unbound": 1,
    "not_deliberate": 3, "phrase": 2, "phrase_rule": 2, "cursor": 3, "screen_phrase": 2,
}


def write_split(path: Path, n: int, seed: int, heldout_phrasing: bool, apps: list[str], name: str, rich: bool = False) -> None:
    rng = random.Random(seed)
    gen = Generator(rng, heldout_phrasing, apps, rich)
    kinds, weights = zip(*KIND_WEIGHTS.items())
    with path.open("w") as f:
        for i in range(n):
            row = gen.make(rng.choices(kinds, weights)[0])
            row["id"] = f"{name}-{i}"
            row["split"] = name
            f.write(json.dumps(row) + "\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=Path("data/v0"))
    p.add_argument("--train", type=int, default=40000)
    p.add_argument("--validation", type=int, default=2000)
    p.add_argument("--test", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260926)
    p.add_argument("--rich", action="store_true", help="v2: large training wording banks (wordings.py)")
    p.add_argument("--bank", type=Path, help="also merge an LLM wording bank (filtered by vox.bank); implies --rich")
    a = p.parse_args()
    leak = {h for h in HELDOUT_PHRASES for ws in PHRASES.values() if h in ws}
    assert not leak, f"held-out phrases leaked into schema.PHRASES: {leak}"
    if a.bank:
        from . import bank as B
        held = {"actions": {k: v[1] for k, v in ACTION_WORDS.items()}, "gestures": {k: v[1] for k, v in GESTURE_WORDS.items()},
                "app_rule_templates": RULE_TEMPLATES[1], "global_rule_templates": GLOBAL_TEMPLATES[1],
                "disable_templates": DISABLE_TEMPLATES[1], "phrase_templates": PHRASE_TEMPLATES[1]}
        extra, dropped = B.load(a.bank, held, set(HELDOUT_PHRASES))
        for key, ws in extra["actions"].items():
            W.ACTION_WORDS_TRAIN[key] = list(dict.fromkeys(W.ACTION_WORDS_TRAIN[key] + ws))
        for key, ws in extra["gestures"].items():
            W.GESTURE_WORDS_TRAIN[key] = list(dict.fromkeys(W.GESTURE_WORDS_TRAIN[key] + ws))
        for sec, lst in (("app_rule_templates", W.RULE_TEMPLATES_TRAIN), ("global_rule_templates", W.GLOBAL_TEMPLATES_TRAIN),
                         ("disable_templates", W.DISABLE_TEMPLATES_TRAIN), ("phrase_templates", W.PHRASE_TEMPLATES_TRAIN)):
            lst.extend(t for t in extra[sec] if t not in lst)
        a.rich = True
        a.output.mkdir(parents=True, exist_ok=True)
        (a.output / "bank_dropped.json").write_text(json.dumps(dropped, indent=1) + "\n")
        print(json.dumps({"bank_dropped": {k: len(v) for k, v in dropped.items()}}))
    for name, held, train in (("action", ACTION_WORDS, W.ACTION_WORDS_TRAIN), ("gesture", GESTURE_WORDS, W.GESTURE_WORDS_TRAIN)):
        W.check_disjoint(held, train, name)
    for held, train in ((RULE_TEMPLATES, W.RULE_TEMPLATES_TRAIN), (GLOBAL_TEMPLATES, W.GLOBAL_TEMPLATES_TRAIN),
                        (DISABLE_TEMPLATES, W.DISABLE_TEMPLATES_TRAIN), (PHRASE_TEMPLATES, W.PHRASE_TEMPLATES_TRAIN)):
        assert not set(held[1]) & set(train), "held-out template leaked into training"
    a.output.mkdir(parents=True, exist_ok=True)
    s = a.seed
    write_split(a.output / "train.jsonl", a.train, s, False, TRAIN_APPS, "train", a.rich)
    write_split(a.output / "validation.jsonl", a.validation, s + 1, False, TRAIN_APPS, "validation", a.rich)
    write_split(a.output / "test_iid.jsonl", a.test, s + 2, False, TRAIN_APPS, "test_iid")
    write_split(a.output / "test_unseen_phrasing.jsonl", a.test, s + 3, True, TRAIN_APPS, "test_unseen_phrasing")
    write_split(a.output / "test_unseen_apps.jsonl", a.test, s + 4, False, sorted(HELDOUT_APPS), "test_unseen_apps")
    (a.output / "policy.txt").write_text(POLICY + "\n")
    print(json.dumps({"output": str(a.output), "train": a.train, "validation": a.validation, "test_each": a.test}))


if __name__ == "__main__":
    main()
