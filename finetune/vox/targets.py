"""Intent cursor mode: pick the on-screen element the user named ("the like button" -> Like (button, bottom right)).

A separate task and dataset from the gesture decision (data/v5 is untouched). Same row format:
{"context", "options", "label", "option_keys", "kind", "id", "split", "meta"}.

The phone builds the options from accessibility nodes that are clickable or focusable and visible:
  label    = contentDescription, else text, else the last part of viewIdResourceName with _ as spaces, else "unlabeled"
  role     = from className: Button/ImageButton -> button, EditText -> text field, Switch/CheckBox -> switch,
             TabWidget child or selected-tab -> tab, ImageView -> image, list rows -> list item, else "item"
  position = 3x3 grid bucket of the node's centre ("top left" ... "bottom right"; the middle cell is "center")
  option   = f"{label} ({role}, {position})"; a last option NONE_OPTION is always appended
and sends them in reading order (top to bottom, then left to right). 30% of rows here are shuffled so the model
doesn't lean on that order.

Kinds:
  name       the utterance names the element by a synonym (+ optional role word)
  name_pos   two elements share a label; the utterance picks one by position
  position   the utterance names only a position ("the thing in the top right") and exactly one element is there
  unlabeled  the element has no label; the utterance gives role + position
  item       a list item named by its title ("the chat with Mom", "Blinding Lights")
  none       the utterance names something that is not on screen -> NONE_OPTION

Held out (test_unseen_phrasing only): the last synonym(s) of each element and the last utterance templates.
test_unseen_apps uses generate.HELDOUT_APPS with their own element sets.

v2 (2026-09-26): roles follow the harvest mix (real_role). v1 is kept unchanged.

Usage: python -m vox.targets --output data/targets-v2 [--train 30000 --validation 1000 --test 2000]
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from .generate import HELDOUT_APPS
from .schema import APPS, APP_SCREENS, SCREEN_KEYBOARD, SCREEN_MEDIA, SCREEN_SCROLL, screen_text

NONE_OPTION = "none of these (the thing I named is not on screen)"
POSITIONS = ["top left", "top", "top right", "left", "center", "right", "bottom left", "bottom", "bottom right"]
# How people say each position: (training, held-out)
POS_WORDS = {
    "top left": (["in the top left", "at the top left", "in the upper left corner"], ["up in the left corner"]),
    "top": (["at the top", "at the top middle", "along the top"], ["up top"]),
    "top right": (["in the top right", "at the top right", "in the upper right corner"], ["up in the right corner"]),
    "left": (["on the left", "on the left side", "at the left"], ["along the left edge"]),
    "center": (["in the middle", "in the center", "in the middle of the screen"], ["in the centre of the screen"]),
    "right": (["on the right", "on the right side", "at the right"], ["along the right edge"]),
    "bottom left": (["in the bottom left", "at the bottom left", "in the lower left corner"], ["down in the left corner"]),
    "bottom": (["at the bottom", "at the bottom middle", "along the bottom"], ["down low"]),
    "bottom right": (["in the bottom right", "at the bottom right", "in the lower right corner"], ["down in the right corner"]),
}

# label, role, usual positions, training noun synonyms, held-out noun synonyms
ELEMENTS = {
    "like": ("Like", "button", ["bottom right", "right", "bottom left"], ["like", "heart", "like button", "the heart icon"], ["the love icon"]),
    "comment": ("Comment", "button", ["bottom right", "right", "bottom"], ["comment", "comments", "the speech bubble"], ["the reply box"]),
    "share": ("Share", "button", ["bottom right", "right", "top right"], ["share", "share button", "the arrow icon"], ["the forwarding icon"]),
    "save": ("Save", "button", ["bottom right", "right", "top right"], ["save", "bookmark", "the bookmark icon"], ["the ribbon icon"]),
    "search": ("Search", "button", ["top right", "top", "bottom"], ["search", "magnifying glass", "the search icon"], ["the lens icon"]),
    "back": ("Navigate up", "button", ["top left"], ["back arrow", "the back button", "navigate up"], ["the arrow that goes back"]),
    "more": ("More options", "button", ["top right", "right"], ["more options", "three dots", "the menu dots"], ["the kebab menu"]),
    "home_tab": ("Home", "tab", ["bottom left", "bottom"], ["home tab", "the home icon", "home"], ["the house"]),
    "profile": ("Profile", "tab", ["bottom right", "top right"], ["profile", "my profile", "the avatar"], ["my account picture"]),
    "settings": ("Settings", "button", ["top right", "bottom right"], ["settings", "the gear", "settings cog"], ["the preferences"]),
    "close": ("Close", "button", ["top left", "top right"], ["close", "the x", "close button"], ["the cross"]),
    "play": ("Play", "button", ["center", "bottom"], ["play", "play button", "the triangle"], ["the start symbol"]),
    "pause": ("Pause", "button", ["center", "bottom"], ["pause", "pause button", "the two bars"], ["the double line icon"]),
    "next": ("Next", "button", ["bottom", "right", "bottom right"], ["next", "skip", "next track"], ["the forward arrow"]),
    "previous": ("Previous", "button", ["bottom", "left", "bottom left"], ["previous", "the previous button", "last track"], ["the rewind arrow"]),
    "send": ("Send", "button", ["bottom right"], ["send", "send button", "the paper plane"], ["the dart icon"]),
    "attach": ("Attach", "button", ["bottom left", "bottom"], ["attach", "paperclip", "attachment"], ["the clip icon"]),
    "mic": ("Voice message", "button", ["bottom right"], ["microphone", "voice message", "the mic"], ["the recording icon"]),
    "follow": ("Follow", "button", ["top right", "right", "center"], ["follow", "follow button", "subscribe"], ["the join button"]),
    "download": ("Download", "button", ["bottom", "right", "top right"], ["download", "download button", "save offline"], ["the offline icon"]),
    "edit": ("Edit", "button", ["top right", "bottom right"], ["edit", "the pencil", "edit button"], ["the pen"]),
    "delete": ("Delete", "button", ["top right", "bottom"], ["delete", "trash can", "the bin"], ["the garbage can"]),
    "add": ("New", "button", ["bottom right", "top right", "bottom"], ["new", "the plus", "add button", "create"], ["the create icon"]),
    "notifications": ("Notifications", "button", ["top right"], ["notifications", "the bell", "alerts"], ["my updates"]),
    "mute": ("Mute", "button", ["top right", "bottom right"], ["mute", "sound off", "the speaker icon"], ["the muted speaker"]),
    "fullscreen": ("Full screen", "button", ["bottom right"], ["full screen", "expand", "fullscreen button"], ["the expand corners"]),
    "shutter": ("Shutter", "button", ["bottom"], ["shutter", "take picture button", "the big circle"], ["the capture button"]),
    "switch_cam": ("Switch camera", "button", ["bottom right"], ["switch camera", "flip camera", "selfie camera"], ["the rotate camera icon"]),
    "message_box": ("Message", "text field", ["bottom"], ["message box", "the text box", "type a message"], ["the typing area"]),
    "search_box": ("Search or type URL", "text field", ["top"], ["address bar", "search bar", "url bar"], ["the omnibox"]),
    "directions": ("Directions", "button", ["bottom right", "bottom"], ["directions", "route", "get directions"], ["the turn arrow"]),
    "my_location": ("My location", "button", ["bottom right", "right"], ["my location", "recenter", "the location button"], ["the crosshair"]),
    "shuffle": ("Shuffle", "button", ["bottom left", "left"], ["shuffle", "shuffle button", "random order"], ["the crossed arrows"]),
    "repeat": ("Repeat", "button", ["bottom right", "right"], ["repeat", "loop", "repeat button"], ["the cycle icon"]),
    "tabs": ("Switch tabs", "button", ["top right"], ["tabs", "tab switcher", "the tab count"], ["the square with a number"]),
    "reload": ("Reload", "button", ["top", "top right"], ["reload", "refresh", "the circular arrow"], ["the spinning arrow"]),
    "continue": ("Continue", "button", ["bottom", "center"], ["continue", "next step", "the continue button"], ["the proceed button"]),
    "check": ("Check", "button", ["bottom"], ["check", "check answer", "submit"], ["the grade button"]),
    "upvote": ("Upvote", "button", ["left", "bottom left"], ["upvote", "the up arrow", "vote up"], ["the plus-one arrow"]),
    "downvote": ("Downvote", "button", ["left", "bottom left"], ["downvote", "the down arrow", "vote down"], ["the thumbs-down arrow"]),
    "subtitles": ("Subtitles", "button", ["top right", "bottom right"], ["subtitles", "captions", "cc"], ["the text track"]),
    "episodes": ("Episodes", "button", ["bottom", "bottom right"], ["episodes", "episode list", "the episodes button"], ["the season list"]),
}

# What the element does, as a verb phrase: (training, held-out). Used with FUNC_T, never with the noun templates.
FUNC = {
    "like": (["like this", "show some love"], ["love it"]), "comment": (["leave a comment", "write a comment"], ["say something about it"]),
    "share": (["share this", "pass it on"], ["send it to a friend"]), "save": (["save this", "save it for later"], ["keep it for later"]),
    "search": (["search for something", "find something"], ["look something up"]), "back": (["go up a level", "leave this page"], ["get out of here"]),
    "more": (["see more options", "open the menu"], ["show the extra stuff"]), "home_tab": (["go to the home tab", "open home"], ["take me to the start page"]),
    "profile": (["open my profile", "see my page"], ["check my account"]), "settings": (["change settings", "open settings"], ["adjust how it works"]),
    "close": (["close this", "shut it"], ["dismiss it"]), "play": (["start playing", "play it"], ["start playback"]),
    "pause": (["pause it", "stop playing"], ["freeze playback"]), "next": (["skip this", "go to the next one"], ["jump ahead one"]),
    "previous": (["go to the last one", "play the previous one"], ["jump back one"]), "send": (["send it", "send the message"], ["fire it off"]),
    "attach": (["attach something", "add an attachment"], ["add a file"]), "mic": (["record a voice message", "talk instead of typing"], ["record audio"]),
    "follow": (["follow them", "subscribe to them"], ["sign up for their posts"]), "download": (["download this", "save it offline"], ["get it onto my phone"]),
    "edit": (["edit this", "change it"], ["make changes"]), "delete": (["delete this", "remove it"], ["throw it away"]),
    "add": (["make a new one", "create something"], ["start a fresh one"]), "notifications": (["see my notifications", "check my alerts"], ["show me what's new"]),
    "mute": (["mute it", "turn the sound off"], ["silence it"]), "fullscreen": (["go full screen", "fill the screen with it"], ["blow the video up"]),
    "shutter": (["take the picture", "snap it"], ["capture it"]), "switch_cam": (["flip to the front camera", "switch cameras"], ["turn the camera around"]),
    "message_box": (["type something", "write a message"], ["start typing"]), "search_box": (["type a website", "enter an address"], ["go to a website"]),
    "directions": (["get me there", "start a route"], ["navigate there"]), "my_location": (["show where I am", "find me on the map"], ["center on me"]),
    "shuffle": (["shuffle the songs", "play in random order"], ["mix it up"]), "repeat": (["loop it", "repeat this"], ["play it again and again"]),
    "tabs": (["see my tabs", "switch tabs"], ["flip between pages"]), "reload": (["refresh the page", "reload it"], ["load it again"]),
    "continue": (["go on", "move on"], ["keep going"]), "check": (["check my answer", "submit it"], ["see if I'm right"]),
    "upvote": (["upvote this", "vote it up"], ["give it a point"]), "downvote": (["downvote this", "vote it down"], ["take a point away"]),
    "subtitles": (["turn on captions", "show subtitles"], ["show the words"]), "episodes": (["see the episodes", "pick an episode"], ["browse the season"]),
}

# Element sets per app (unknown apps fall back to GENERIC).
GENERIC = ["back", "more", "search", "settings", "close", "share", "home_tab", "profile", "notifications", "add", "edit", "delete"]
APP_ELEMENTS = {
    "com.zhiliaoapp.musically": ["like", "comment", "share", "save", "follow", "profile", "home_tab", "search", "add", "mute"],
    "com.google.android.youtube": ["like", "share", "download", "search", "home_tab", "profile", "play", "pause", "next", "fullscreen", "subtitles", "more", "comment", "follow"],
    "com.google.android.apps.maps": ["search_box", "directions", "my_location", "profile", "more", "share", "save", "close"],
    "com.spotify.music": ["play", "pause", "next", "previous", "shuffle", "repeat", "like", "search", "home_tab", "more", "share", "download"],
    "com.instagram.android": ["like", "comment", "share", "save", "home_tab", "search", "add", "profile", "notifications", "more", "follow", "mute"],
    "com.amazon.kindle": ["back", "search", "more", "settings", "close", "save", "home_tab"],
    "com.google.android.apps.photos": ["share", "edit", "delete", "like", "search", "more", "back", "add", "profile"],
    "com.android.chrome": ["search_box", "tabs", "more", "reload", "back", "home_tab", "share", "download", "close"],
    "com.whatsapp": ["message_box", "send", "attach", "mic", "search", "more", "back", "add", "settings"],
    "com.google.android.GoogleCamera": ["shutter", "switch_cam", "settings", "close", "edit"],
    "org.videolan.vlc": ["play", "pause", "next", "previous", "subtitles", "fullscreen", "repeat", "shuffle", "more", "back", "search"],
    "com.reddit.frontpage": ["upvote", "downvote", "comment", "share", "search", "home_tab", "profile", "add", "notifications", "more", "follow"],
    # held-out apps
    "com.google.android.apps.docs": ["edit", "share", "search", "more", "back", "add", "close", "download", "comment", "profile"],
    "com.duolingo": ["continue", "check", "close", "settings", "profile", "home_tab", "mic", "notifications"],
    "com.netflix.mediaclient": ["play", "pause", "episodes", "subtitles", "download", "search", "profile", "back", "mute", "fullscreen", "next"],
    "com.pinterest": ["save", "share", "search", "home_tab", "profile", "follow", "add", "more", "comment", "like"],
}
# List items named by their title. Train titles and held-out titles are disjoint.
ITEMS = {
    "scrolling list": (["Mom", "Work group", "Alex", "Blinding Lights", "Daily Mix 1", "Recipes", "Weekend trip", "Chapter 3", "Groceries", "Liked Songs"],
                       ["Grandpa", "Road trip playlist", "Book club"]),
}
# Elements a synonym could plausibly name interchangeably. A row never shows two members of one group when the
# utterance names one of them (or names an absent member for "none"): the label would be a coin flip.
CONFUSABLE = [{"search", "search_box"}, {"save", "download"}, {"next", "continue", "fullscreen"}, {"like", "upvote", "follow"},
              {"comment", "message_box"}, {"reload", "repeat"}, {"back", "previous", "close"}, {"add", "edit"},
              {"play", "pause"}, {"share", "send"}, {"tabs", "home_tab"}, {"mic", "mute"}]
GROUP = {k: g for g in CONFUSABLE for k in g}

ITEM_TEMPLATES = (["{t}", "the {t} one", "open {t}", "the one called {t}", "{t} in the list"],
                  ["the row that says {t}"])
ROLE_WORDS = {"button": ["button", "icon"], "tab": ["tab", "icon"], "text field": ["box", "field"], "list item": ["row", "item"],
              "image": ["picture", "image"], "switch": ["toggle", "switch"], "item": ["thing", "one"]}

# Utterance templates: (training, held-out). {s} noun synonym, {v} function phrase, {r} role word, {p} position phrase.
# Noun synonyms that already start with "the"/"my" drop the template's own "the".
NAME_T = (["{s}", "the {s}", "tap the {s}", "press the {s}", "the {s} {r}", "hit the {s} {r}", "I want the {s}", "select the {s}"],
          ["go for the {s} {r}", "that {s} thing"])
FUNC_T = (["{v}", "I want to {v}", "{v} please", "let me {v}"], ["could you {v}"])
NAME_POS_T = (["the {s} {p}", "the {s} {r} {p}", "the {s}, the one {p}", "tap the {s} {p}"],
              ["the {s} that's {p}"])
POS_T = (["the thing {p}", "whatever is {p}", "tap the thing {p}", "the {r} {p}"],
         ["the {r} sitting {p}"])

# --- tree mode (v2 option format) ------------------------------------------------------------------------------------
# v2 option text: `{label}[ · {context}] ({role}, {position}[, {rank}])`. Children of an indented list carry their
# parent row's label as context; list items get a column rank "{k} of {n} down" (or row rank "{k} of {n} from left");
# options that are still identical get ", {k} of {n}". Same rules as android/suite/tree_targets.py decorate()/ordinal().

_NUM_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
              "seventeen eighteen nineteen twenty").split()
_NUM_ORD = ("zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
            "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth").split()


def _ordinal(k: int, n: int) -> str:
    if k == n:
        return "last"
    suf = "th" if k % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suf}"


# Parent rows: a family (letter / lower word / capital word) with a number, or a plain folder name.
TREE_FAMILIES = [("L", "lesson", "Lesson"), ("U", "unit", "Unit"), ("C", "chapter", "Chapter"),
                 ("W", "week", "Week"), ("S", "section", "Section"), ("D", "day", "Day")]
TREE_FOLDERS = ["Work", "Groceries", "2024", "Projects", "School", "Personal", "Inbox", "Archive"]
# Child topics: topic -> an abbreviation people also say.
TREE_TOPICS = {"vocabulary": "vocab", "grammar": "grammar", "reading": "reading", "writing": "writing",
               "listening": "listening", "speaking": "speaking", "quiz": "quiz", "notes": "notes",
               "part": "part", "exercise": "exercise", "practice": "practice", "review": "review",
               "homework": "homework", "test": "test", "summary": "summary"}

# Query templates ({p} parent saying, {c} child saying); Gen.fill drops a doubled "the".
PC_T = ["{p} {c}", "{c} in {p}", "the {c} under {p}", "{c} in the {p}", "open the {c} in {p}",
        "the {c} for {p}", "go to the {c} in {p}", "{c} under {p}"]
C_T = ["open {c}", "the {c}", "{c}", "go to {c}", "open the {c}", "select {c}"]
P_T = ["open {p}", "go to {p}", "{p}", "the {p}", "open the {p}", "select {p}"]


def _v2_ranks(items: list[dict]) -> list[str | None]:
    """Column/row rank per tree_targets.decorate: same role + same x-bucket -> "{k} of {n} down"; same role + same
    y-bucket -> "{k} of {n} from left". items: list of {"role","pos"}; returns an aligned list of rank strings (or None)."""
    ranks = [None] * len(items)
    colw = lambda pos: POSITIONS.index(pos) % 3   # noqa: E731
    roww = lambda pos: POSITIONS.index(pos) // 3  # noqa: E731
    for i, it in enumerate(items):
        role = it["role"]
        col = [j for j, u in enumerate(items) if u["role"] == role and colw(u["pos"]) == colw(it["pos"])]
        col.sort(key=lambda j: (roww(items[j]["pos"]), colw(items[j]["pos"]), j))
        row = [j for j, u in enumerate(items) if u["role"] == role and roww(u["pos"]) == roww(it["pos"])]
        row.sort(key=lambda j: (colw(items[j]["pos"]), roww(items[j]["pos"]), j))
        if len(col) >= 2 and (len(col) > len(row) or (len(col) == len(row) and role != "tab")):
            ranks[i] = f"{_ordinal(col.index(i) + 1, len(col))} of {len(col)} down"
        elif len(row) >= 2:
            ranks[i] = f"{_ordinal(row.index(i) + 1, len(row))} of {len(row)} from left"
    return ranks


def _v2_options(items: list[dict]) -> list[str]:
    """items: list of {"label","context","role","pos"} in reading order -> v2 option strings (rank + repeat number)."""
    ranks = _v2_ranks(items)
    opts = []
    for it, rk in zip(items, ranks):
        ctx = f" · {it['context']}" if it.get("context") else ""
        rank = f", {rk}" if rk else ""
        opts.append(f"{it['label']}{ctx} ({it['role']}, {it['pos']}{rank})")
    groups: dict[str, list[int]] = {}
    for i, o in enumerate(opts):
        groups.setdefault(o, []).append(i)
    out = list(opts)
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        for k, i in enumerate(idxs):
            out[i] = out[i][:-1] + f", {_ordinal(k + 1, len(idxs))} of {len(idxs)})"
    return out


class Gen:
    def __init__(self, rng: random.Random, held: bool, apps: list[str], tree: bool = False, tree_frac: float = 0.35) -> None:
        self.r, self.h, self.apps = rng, 1 if held else 0, apps
        self.tree, self.tree_frac = tree, tree_frac

    def pick(self, pair):
        return self.r.choice(pair[self.h])

    def syn(self, key: str) -> str:
        _, _, _, train, held = ELEMENTS[key]
        return self.r.choice(held if self.h else train)

    def say_name(self, key: str, role: str) -> str:
        """60% a noun synonym in a noun template, 40% what the element does in a verb template."""
        if self.r.random() < 0.4:
            return self.pick(FUNC_T).format(v=self.pick(FUNC[key]))
        return self.fill(self.pick(NAME_T), s=self.syn(key), r=self.r.choice(ROLE_WORDS[role]))

    @staticmethod
    def fill(t: str, **kw) -> str:
        out = t.format(**kw)
        # "the location button" + role word "button" -> no doubled noun
        out = re.sub(r"\b(button|icon|box|tab|bar|field)\s+(button|icon|box|tab|field|row|item)\b", r"\1", out)
        for det in ("the", "my"):
            out = out.replace(f"the {det} ", f"{det} ").replace(f"that {det} ", "that ")
        return out[0].lower() + out[1:] if not out.startswith("I ") else out

    def real_role(self, role: str) -> str:
        """Real accessibility trees rarely say "button": the emulator harvest (40 screens, 301 targets) had
        item 72, list item 70, tab 56, button 50, image 38. Tappable icons often come out as image or item."""
        if role == "button":
            return self.r.choices(["button", "image", "item"], [45, 30, 25])[0]
        if role == "tab":
            return self.r.choices(["tab", "item"], [70, 30])[0]
        return role

    def pos_words(self, pos: str) -> str:
        return self.pick(POS_WORDS[pos])

    # --- tree mode helpers ---
    def _tree_parents(self, n_parents: int) -> list[dict]:
        r = self.r
        parents = []
        if r.random() < 0.25:  # a plain folder list (no number equivalence)
            for name in r.sample(TREE_FOLDERS, n_parents):
                lo = name.lower()
                sayings = [lo, f"the {lo} folder", f"the {lo} list", f"the {lo} section"]
                parents.append({"label": name, "family": None, "num": None, "sayings": sayings})
        else:
            letter, word, Word = r.choice(TREE_FAMILIES)
            for n in r.sample(range(1, 13), n_parents):
                label = r.choice([f"{letter}{n:02d}", f"{Word} {n}"])
                sayings = [f"{word} {n}", f"{letter}{n:02d}", f"{word} {_NUM_WORDS[n]}",
                           f"the {_NUM_ORD[n]} {word}", f"{word} {n:02d}", f"{Word} {n}"]
                parents.append({"label": label, "family": (letter, word, Word), "num": n, "sayings": sayings})
        return parents

    def _child(self, topic: str, num: int | None) -> dict:
        cap = topic.capitalize()
        abbr = TREE_TOPICS[topic]
        if num is None:
            return {"label": cap, "topic": topic, "num": None, "sayings": [topic, abbr, f"the {topic}"]}
        style = self.r.choice(["numfirst", "numlast"])
        label = f"{num:02d} {cap}" if style == "numfirst" else f"{cap} {num}"
        sayings = [f"{topic} {_NUM_WORDS[num]}", f"{abbr} {num}", f"the {_NUM_ORD[num]} {topic}",
                   f"{topic} {num}", f"{topic} {num:02d}", f"{abbr} {_NUM_WORDS[num]}"]
        if num == 1:
            sayings.append(f"the {topic} one")
        return {"label": label, "topic": topic, "num": num, "sayings": sayings}

    def tree_screen(self) -> list[dict]:
        """One synthetic indented-list screen: 1-3 parent rows, each with 2-5 children (some shared across parents)."""
        r = self.r
        n_parents = r.randint(1, 3)
        parents = self._tree_parents(n_parents)
        shared = r.sample(list(TREE_TOPICS), r.randint(1, 2)) if n_parents >= 2 else []
        used = set(shared)
        for pi in range(n_parents):
            kids = [self._child(t, None) for t in shared]
            want = max(r.randint(2, 5), len(shared) + 1)  # at least one non-shared child per parent
            avail = [t for t in TREE_TOPICS if t not in used]
            r.shuffle(avail)
            for t in avail[:want - len(kids)]:
                kids.append(self._child(t, None if r.random() < 0.4 else r.randint(1, 5)))
                used.add(t)
            parents[pi]["children"] = kids
        return parents

    def _absent_parent_saying(self, parents: list[dict]) -> str | None:
        r = self.r
        fams = [p for p in parents if p["family"] is not None]
        if fams:
            letter, word, Word = fams[0]["family"]
            shown = {p["num"] for p in fams}
            avail = [n for n in range(1, 13) if n not in shown]
            if not avail:
                return None
            n = r.choice(avail)
            return r.choice([f"{word} {n}", f"{letter}{n:02d}", f"{word} {_NUM_WORDS[n]}",
                             f"the {_NUM_ORD[n]} {word}", f"{word} {n:02d}", f"{Word} {n}"])
        shown = {p["label"] for p in parents}
        avail = [f for f in TREE_FOLDERS if f not in shown]
        if not avail:
            return None
        lo = r.choice(avail).lower()
        return r.choice([lo, f"the {lo} folder", f"the {lo} list", f"the {lo} section"])

    def tree_row(self) -> dict | None:
        r = self.r
        app = r.choice(self.apps)
        line = screen_text("scrolling list", r.choice(SCREEN_MEDIA), r.choice(SCREEN_SCROLL), r.choice(SCREEN_KEYBOARD))
        parents = self.tree_screen()
        # flatten in reading order; children carry their parent's label as context
        items, parent_idx, child_idx = [], {}, {}
        for pi, p in enumerate(parents):
            parent_idx[pi] = len(items)
            items.append({"label": p["label"], "context": None, "role": "list item", "pi": pi, "ci": None})
            for ci, c in enumerate(p["children"]):
                child_idx[(pi, ci)] = len(items)
                items.append({"label": c["label"], "context": p["label"], "role": "list item", "pi": pi, "ci": ci})
        n = len(items)
        for i, it in enumerate(items):
            it["pos"] = "top" if (n > 1 and i == 0) else ("bottom" if (n > 1 and i == n - 1) else "center")
        opts = _v2_options(items)
        # which child topics appear in exactly one parent (unique -> a child-only query can target them)
        topic_parents: dict[str, set] = {}
        for p in parents:
            seen = set()
            for c in p["children"]:
                if c["topic"] not in seen:
                    topic_parents.setdefault(c["topic"], set()).add(p["label"])
                    seen.add(c["topic"])
        kind = r.choices(["tree_pc", "tree_c", "tree_p", "tree_none"], [40, 15, 20, 25])[0]
        label, target = None, None
        if kind == "tree_pc":
            pi = r.randrange(len(parents))
            p = parents[pi]
            ci = r.randrange(len(p["children"]))
            c = p["children"][ci]
            label, target = child_idx[(pi, ci)], c["label"]
            utt = self.fill(r.choice(PC_T), p=r.choice(p["sayings"]), c=r.choice(c["sayings"]))
        elif kind == "tree_c":
            uniq = [(pi, ci, c) for pi, p in enumerate(parents) for ci, c in enumerate(p["children"])
                    if len(topic_parents[c["topic"]]) == 1]
            if not uniq:
                return None
            pi, ci, c = r.choice(uniq)
            label, target = child_idx[(pi, ci)], c["label"]
            utt = self.fill(r.choice(C_T), c=r.choice(c["sayings"]))
        elif kind == "tree_p":
            pi = r.randrange(len(parents))
            p = parents[pi]
            label, target = parent_idx[pi], p["label"]
            utt = self.fill(r.choice(P_T), p=r.choice(p["sayings"]))
        else:  # tree_none: a parent+child that is not on screen
            if r.random() < 0.5:
                ap = self._absent_parent_saying(parents)
                if ap is None:
                    return None
                c = r.choice(r.choice(parents)["children"])
                utt = self.fill(r.choice(PC_T), p=ap, c=r.choice(c["sayings"]))
            else:
                pi = r.randrange(len(parents))
                p = parents[pi]
                have = {c["topic"] for c in p["children"]}
                topic = r.choice([t for t in TREE_TOPICS if t not in have])
                c = self._child(topic, None if r.random() < 0.5 else r.randint(1, 5))
                utt = self.fill(r.choice(PC_T), p=r.choice(p["sayings"]), c=r.choice(c["sayings"]))
            label, target = len(opts), None
        keys = [f"t{j}" for j in range(len(opts))] + ["none"]
        opts.append(NONE_OPTION)
        ctx = f"mode: cursor\napp: {APPS.get(app, app)} ({app})\n{line}\nspoken target: \"{utt}\""
        return {"context": ctx, "options": opts, "label": label, "option_keys": keys, "kind": kind,
                "meta": {"target": target}}

    def screen(self, app: str) -> tuple[str, list[dict]]:
        r = self.r
        kind = r.choice(APP_SCREENS.get(app, ["other"]))
        media = r.choice(SCREEN_MEDIA)
        line = screen_text(kind, media, r.choice(SCREEN_SCROLL), r.choice(SCREEN_KEYBOARD))
        pool = APP_ELEMENTS.get(app, GENERIC)
        keys = r.sample(pool, r.randint(min(4, len(pool)), min(len(pool), 14)))
        els, used = [], set()
        for k in keys:
            label, role, poses, _, _ = ELEMENTS[k]
            pos = r.choice(poses) if r.random() < 0.8 else r.choice(POSITIONS)
            if (label, pos) in used:
                continue
            used.add((label, pos))
            els.append({"key": k, "label": label, "role": self.real_role(role), "pos": pos})
        if kind == "scrolling list" and r.random() < 0.7:
            train_t, held_t = ITEMS["scrolling list"]
            # held-out rows: one held title (the only possible target) among training titles as distractors
            titles = ([r.choice(held_t)] if self.h else []) + r.sample(train_t, r.randint(2, 4))
            for t, pos in zip(titles, r.sample(["top", "center", "bottom", "left", "right"], len(titles))):
                els.append({"key": f"item:{t}", "label": t, "role": "list item", "pos": pos, "held": t in held_t})
        return line, els

    def row(self) -> dict | None:
        r = self.r
        if self.tree and r.random() < self.tree_frac:
            return self.tree_row()
        app = r.choice(self.apps)
        line, els = self.screen(app)
        kind = r.choices(["name", "name_pos", "position", "unlabeled", "item", "none"], [45, 10, 10, 8, 12, 15])[0]
        target = None
        shown = {e["key"] for e in els}
        clear = lambda k: not (GROUP.get(k, {k}) - {k}) & shown  # noqa: E731
        if kind == "name":
            cands = [e for e in els if not e["key"].startswith("item:") and clear(e["key"])]
            if not cands:
                return None
            target = r.choice(cands)
            utt = self.say_name(target["key"], ELEMENTS[target["key"]][1])  # people name the icon, not the tree role
        elif kind == "name_pos":
            cands = [e for e in els if not e["key"].startswith("item:") and clear(e["key"])]
            if not cands:
                return None
            base = r.choice(cands)
            others = [p for p in POSITIONS if p not in {e["pos"] for e in els if e["label"] == base["label"]}]
            twin = dict(base, pos=r.choice(others))
            els.append(twin)
            target = r.choice([base, twin])
            utt = self.fill(self.pick(NAME_POS_T), s=self.syn(target["key"]), r=r.choice(ROLE_WORDS[ELEMENTS[target["key"]][1]]), p=self.pos_words(target["pos"]))
        elif kind in ("position", "unlabeled"):
            if kind == "unlabeled":
                target = r.choice(els)
                target["label"], target["role"] = "unlabeled", r.choice(["button", "image"])
            else:
                target = r.choice(els)
            if sum(e["pos"] == target["pos"] for e in els) > 1:
                return None  # position alone would be ambiguous
            utt = self.fill(self.pick(POS_T), r=r.choice(ROLE_WORDS[target["role"]]), p=self.pos_words(target["pos"]))
        elif kind == "item":
            items = [e for e in els if e["key"].startswith("item:") and e.get("held", False) == bool(self.h)]
            if not items:
                return None
            target = r.choice(items)
            utt = self.pick(ITEM_TEMPLATES).format(t=target["label"])
        else:  # none: name an element of this app's kind that is not on screen
            absent = [k for k in ELEMENTS if not GROUP.get(k, {k}) & shown and ELEMENTS[k][0] not in {e["label"] for e in els}]
            k = r.choice(absent)
            utt = self.say_name(k, ELEMENTS[k][1])
        order = sorted(range(len(els)), key=lambda i: (POSITIONS.index(els[i]["pos"]) // 3, POSITIONS.index(els[i]["pos"]) % 3, i))
        if r.random() < 0.3:
            r.shuffle(order)
        ordered = [els[i] for i in order]
        if self.tree and r.random() < 0.7:  # flat rows in tree mode get v2 rank (some keep no rank at all)
            opts = _v2_options([{"label": e["label"], "context": None, "role": e["role"], "pos": e["pos"]} for e in ordered])
        else:
            opts = [f"{e['label']} ({e['role']}, {e['pos']})" for e in ordered]
        if len(set(opts)) != len(opts):
            return None
        keys = [f"t{j}" for j in range(len(opts))] + ["none"]
        opts.append(NONE_OPTION)
        label = len(opts) - 1 if target is None else order.index(els.index(target))
        ctx = f"mode: cursor\napp: {APPS.get(app, app)} ({app})\n{line}\nspoken target: \"{utt}\""
        return {"context": ctx, "options": opts, "label": label, "option_keys": keys, "kind": kind,
                "meta": {"target": None if target is None else target["key"]}}


POLICY_TARGETS = ("The user is in cursor mode and said which thing on the screen they want. Each option is one element "
                  "on the screen as 'label (kind, position)'. Pick the element they mean: match by meaning, not exact "
                  "words, and use any position words they say. If nothing on the screen fits, pick none of these.")


def write_split(path: Path, n: int, seed: int, held: bool, apps: list[str], name: str,
                tree: bool = False, tree_frac: float = 0.35) -> None:
    g = Gen(random.Random(seed), held, apps, tree, tree_frac)
    rows, seen = [], set()
    while len(rows) < n:
        row = g.row()
        if row is None or (row["context"], tuple(row["options"])) in seen:
            continue
        seen.add((row["context"], tuple(row["options"])))
        row["id"], row["split"] = f"{name}-{len(rows)}", name
        rows.append(row)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--train", type=int, default=30000)
    p.add_argument("--validation", type=int, default=1000)
    p.add_argument("--test", type=int, default=2000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--tree", action="store_true", help="opt-in tree screens (v2 option format) for a fraction of rows")
    p.add_argument("--tree-frac", type=float, default=0.35, help="fraction of rows that get a tree screen (tree mode)")
    p.add_argument("--tree-probe", type=int, default=300, help="tree_probe.jsonl row count (tree mode only)")
    a = p.parse_args()
    for k, (_, _, _, train, held) in ELEMENTS.items():
        assert not set(train) & set(held) and not set(FUNC[k][0]) & set(FUNC[k][1]), k
    assert set(FUNC) == set(ELEMENTS)
    train_apps = [x for x in APPS if x not in HELDOUT_APPS]
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / "policy.txt").write_text(POLICY_TARGETS + "\n")
    s = a.seed
    write_split(a.output / "train.jsonl", a.train, s, False, train_apps, "train", a.tree, a.tree_frac)
    write_split(a.output / "validation.jsonl", a.validation, s + 1, False, train_apps, "validation", a.tree, a.tree_frac)
    write_split(a.output / "test_iid.jsonl", a.test, s + 2, False, train_apps, "test_iid", a.tree, a.tree_frac)
    write_split(a.output / "test_unseen_phrasing.jsonl", a.test, s + 3, True, train_apps, "test_unseen_phrasing", a.tree, a.tree_frac)
    write_split(a.output / "test_unseen_apps.jsonl", a.test, s + 4, False, sorted(HELDOUT_APPS), "test_unseen_apps", a.tree, a.tree_frac)
    if a.tree:
        write_split(a.output / "tree_probe.jsonl", a.tree_probe, s + 100, False, train_apps, "tree_probe", True, 1.0)


if __name__ == "__main__":
    main()
