"""Synthetic target rows WITH GEOMETRY (STEP 3.8): screens are built as accessibility trees and serialised by the app's
own option code (android/suite/tree_targets.build, byte-identical to Targets.kt), so v1 and v2 text come from the same
layout with no mirrored format rules.

Compared with vox/targets.py (targets-v2, v1 text, no bounds):
  * real layouts: top bar (back, title, actions), tabs, list rows with trailing controls (switch / more / delete / play),
    photo grids, media control rows, feed cards with repeated action buttons, a FAB, bottom navigation, a message bar;
  * repeated identical controls and shared position buckets are kept (they are what v2's context and rank are for);
  * new kinds: "ordinal" ("the second switch", "the last row") and "relational" ("the switch next to Wi-Fi", "the
    more button for Mom"), plus ordinal / relational "none" rows (out of range, a title not on screen). These are only
    solvable from v2 text, so v1 sets leave them out;
  * fewer easy "name" rows; every row is marked synthetic_geometry: true and carries option_format.
Held-out phrasing / apps follow vox/targets.py (its held-out synonyms, templates and HELDOUT_APPS).

    python -m vox.targets_geo --output data/targets-v3 [--train 6000 --validation 500 --test 1000] [--seed 11]
writes data/targets-v3/{v1,v2}/{train,validation,test_iid,test_unseen_phrasing,test_unseen_apps}.jsonl
(the same screens and utterances for both formats, minus the v2-only kinds in v1).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

from . import targets as T
from .generate import HELDOUT_APPS
from .schema import APPS, screen_text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "android" / "suite"))
import tree_targets as tt  # noqa: E402

N = tt.Node
ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"]
# (train, held-out) titles of list rows, by list flavour
TITLES = {
    "settings": (["Wi-Fi", "Bluetooth", "Airplane mode", "Dark theme", "Location", "Battery saver", "Auto-rotate", "Do not disturb",
                  "Hotspot", "NFC", "Notifications", "Sounds", "Wallpaper", "Screen timeout"], ["Data saver", "Night light", "Vibrate", "Nearby share"]),
    "people": (["Mom", "Alex", "Work group", "Sam", "Priya", "Dad", "Chris", "Jordan", "Book club", "Team chat", "Lena", "Omar"],
               ["Grandpa", "Aunt May", "Coach", "Neighbours"]),
    "media": (["Blinding Lights", "Daily Mix 1", "Liked Songs", "Chapter 3", "Episode 12", "Morning run", "Focus", "Road songs",
               "Lo-fi beats", "Podcast intro"], ["Rainy day", "Evening chill", "Episode 4", "Top hits"]),
    "tasks": (["Groceries", "Pay rent", "Call the bank", "Recipes", "Weekend trip", "Gym", "Dentist", "Laundry", "Book flights"],
              ["Water plants", "Renew passport", "Clean garage"]),
}
TRAILING = {"settings": ["switch", "switch", "none"], "people": ["more", "none", "call"], "media": ["play", "more", "download", "none"],
            "tasks": ["delete", "check", "more", "none"]}
CTRL = {  # trailing control: (class, label, key in targets.ELEMENTS or None, spoken words (train, held))
    "switch": ("Switch", None, None, (["switch", "toggle"], ["slider"])),
    "check": ("CheckBox", None, None, (["checkbox", "tick box"], ["check mark"])),
    "more": ("ImageButton", "More options", "more", (["more button", "three dots", "menu"], ["kebab"])),
    "delete": ("ImageButton", "Delete", "delete", (["delete button", "trash can", "bin"], ["garbage can"])),
    "play": ("ImageButton", "Play", "play", (["play button", "play"], ["start button"])),
    "download": ("ImageButton", "Download", "download", (["download button", "download"], ["offline button"])),
    "call": ("ImageButton", "Call", None, (["call button", "phone icon"], ["dial button"])),
}
SWITCH_LABELS = ["onoff", "On/Off", "switch widget", None]   # None: unlabeled
GROUP_WORDS = {"switch": (["switch", "toggle"], ["slider"]), "list item": (["row", "item", "entry"], ["line"]),
               "tab": (["tab"], ["section"]), "tile": (["photo", "picture", "image"], ["thumbnail"])}
ORD_T = (["the {o} {g}", "tap the {o} {g}", "{o} {g}", "the {o} {g} please", "open the {o} {g}"], ["go with the {o} {g}"])
ORD_ROW_T = (["the {o} {g} from the left", "the {o} {g} from left"], ["{o} {g} counting from the left"])
REL_T = (["the {c} next to {t}", "the {c} for {t}", "{t}'s {c}", "the {c} on the {t} row", "tap the {c} by {t}"],
         ["the {c} beside {t}"])
SW_FUNC_T = (["turn on {t}", "turn off {t}", "toggle {t}", "switch {t} on", "switch off {t}"], ["flip {t}"])
ITEM_T = (["{t}", "open {t}", "the {t} one", "the one called {t}", "{t} in the list"], ["the row that says {t}"])


def node(cls, box, text=None, desc=None, click=False, kids=(), **kw) -> tt.Node:
    return N(cls=cls, id=kw.pop("id", None), text=text, desc=desc, left=box[0], top=box[1], right=box[2], bottom=box[3],
             clickable=click, children=list(kids), **kw)


class Screen:
    """A built layout: root node + semantic handles for phrasing."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.kids = []
        self.named = []      # (node, element key) for single named elements
        self.rows = []       # {"row": node, "title": str, "ctrl": node|None, "ctrl_kind": str|None}
        self.groups = []     # {"role": group word key, "nodes": [...], "axis": "down"|"left"}
        self.kind = "other"


class Gen:
    def __init__(self, rng: random.Random, held: bool, apps: list[str]):
        self.r, self.h, self.apps = rng, 1 if held else 0, apps
        self.t = T.Gen(rng, held, apps)   # the old generator's phrasing helpers (synonyms, function phrases, fill)

    def pick(self, pair):
        return self.r.choice(pair[self.h])

    def titles(self, flavour, n):
        tr, hd = TITLES[flavour]
        pool = tr if not self.h else tr + hd
        out = self.r.sample(pool, n)
        if self.h and not any(t in hd for t in out):     # held-out screens show at least one held-out title
            out[self.r.randrange(n)] = self.r.choice([t for t in hd if t not in out])
        return out

    # ---- layout ---------------------------------------------------------------------------------------------------

    def build(self, app: str) -> Screen:
        r = self.r
        w, h = r.choice([(1080, 2400), (1080, 2340), (1080, 2640), (1440, 3200)])
        s = Screen(w, h)
        sy = lambda v: int(v * h / 2400)  # noqa: E731
        sx = lambda v: int(v * w / 1080)  # noqa: E731
        pool = [k for k in T.APP_ELEMENTS.get(app, T.GENERIC) if T.ELEMENTS[k][1] == "button"]
        used = set()
        y = sy(128)
        # top bar
        bar_kids = []
        if r.random() < 0.8:
            b = node("ImageButton", (0, y, sx(147), y + sy(147)), desc="Navigate up", click=True)
            bar_kids.append(b); s.named.append((b, "back")); used.add("back")
        bar_kids.append(node("TextView", (sx(189), y + sy(40), sx(600), y + sy(107)), text=APPS.get(app, app).split(" (")[0]))
        acts = [k for k in r.sample(pool, min(len(pool), r.randint(0, 3))) if k not in used and k != "back"]
        x = w
        for k in acts:
            b = node("ImageButton", (x - sx(126), y, x, y + sy(147)), desc=T.ELEMENTS[k][0], click=True)
            x -= sx(126)
            bar_kids.append(b); s.named.append((b, k)); used.add(k)
        s.kids.append(node("ViewGroup", (0, y, w, y + sy(147)), kids=bar_kids))
        y += sy(147)
        # tabs
        if r.random() < 0.3:
            labels = r.sample(["Chats", "Status", "Calls", "For you", "Following", "All", "Unread", "Albums", "Photos", "Songs", "Artists"], r.randint(2, 4))
            tw = w // len(labels)
            tabs = [node("TabView", (i * tw, y, (i + 1) * tw, y + sy(140)), text=lb, click=True, selected=(i == 0)) for i, lb in enumerate(labels)]
            s.kids.append(node("TabWidget", (0, y, w, y + sy(140)), kids=tabs))
            s.groups.append({"role": "tab", "nodes": tabs, "axis": "left"})
            y += sy(140)
        bottom = h - sy(126)
        nav = None
        if r.random() < 0.5:
            labels = r.sample(["Home", "Search", "Library", "Profile", "Explore", "Inbox", "Settings", "Favorites"], r.randint(3, 5))
            nw = w // len(labels)
            cls = r.choice(["TabView", "FrameLayout"])
            items = [node(cls, (i * nw, bottom - sy(200), (i + 1) * nw, bottom), desc=lb, click=True, selected=(i == 0)) for i, lb in enumerate(labels)]
            nav = node("ViewGroup", (0, bottom - sy(200), w, bottom), kids=items)
            bottom -= sy(200)
        # content
        content = r.choices(["list", "grid", "media", "feed", "chat"], [50, 12, 12, 14, 12])[0]
        s.kind = {"list": "scrolling list", "grid": "photo viewer", "media": "video player", "feed": "video feed", "chat": "scrolling list"}[content]
        if content in ("list", "chat"):
            flavour = "people" if content == "chat" else r.choice(list(TITLES))
            n = r.randint(3, 8)
            rh = sy(r.choice([150, 180, 206, 230]))
            n = min(n, max(2, (bottom - y - sy(40)) // rh - (1 if content == "chat" else 0)))
            ctrl_kind = r.choice(TRAILING[flavour])
            rows = []
            for i, t in enumerate(self.titles(flavour, n)):
                top = y + i * rh
                kids = [node("TextView", (sx(63), top + rh // 5, sx(700), top + rh // 2), text=t)]
                if r.random() < 0.5:
                    kids.append(node("TextView", (sx(63), top + rh // 2, sx(620), top + 4 * rh // 5), text=r.choice(["Off", "On", "2 new", "Yesterday", "3:45", "Not set"])))
                ctrl = None
                if ctrl_kind != "none":
                    cls, lab, _, _ = CTRL[ctrl_kind]
                    if ctrl_kind in ("switch", "check"):
                        lab = r.choice(SWITCH_LABELS) if i == 0 or r.random() < 0.1 else None
                    ctrl = node(cls, (w - sx(190), top + rh // 4, w - sx(40), top + 3 * rh // 4), desc=lab, click=True)
                    kids.append(ctrl)
                row = node("LinearLayout", (0, top, w, top + rh), click=True, kids=kids)
                rows.append(row)
                s.rows.append({"row": row, "title": t, "ctrl": ctrl, "ctrl_kind": None if ctrl_kind == "none" else ctrl_kind})
            if ctrl_kind in ("switch", "check") and s.rows:   # one label for every switch of the list (as real lists do)
                lab = s.rows[0]["ctrl"].desc
                for x_ in s.rows:
                    x_["ctrl"].desc = lab
            s.kids.append(node("RecyclerView", (0, y, w, bottom), scrollable=True, kids=rows))
            s.groups.append({"role": "list item", "nodes": [x_["row"] for x_ in s.rows], "axis": "down"})
            if ctrl_kind in ("switch", "check"):
                s.groups.append({"role": "switch", "nodes": [x_["ctrl"] for x_ in s.rows], "axis": "down", "ctrl_kind": ctrl_kind})
            elif ctrl_kind != "none":
                s.groups.append({"role": ctrl_kind, "nodes": [x_["ctrl"] for x_ in s.rows], "axis": "down", "ctrl_kind": ctrl_kind})
            if content == "chat":
                mb = node("EditText", (sx(150), bottom - sy(150), w - sx(160), bottom - sy(20)), text="Message", click=True, editable=True)
                sd = node("ImageButton", (w - sx(150), bottom - sy(150), w - sx(20), bottom - sy(20)), desc="Send", click=True)
                s.kids.append(node("LinearLayout", (0, bottom - sy(160), w, bottom), kids=[mb, sd]))
                s.named += [(mb, "message_box"), (sd, "send")]
                used |= {"message_box", "send"}
        elif content == "grid":
            cols = r.choice([2, 3, 4])
            cw = w // cols
            nrows = r.randint(2, 4)
            lab = r.choice(["Photo", "image", None, "Video"])
            tiles = [node("FrameLayout", (c * cw, y + k * cw, (c + 1) * cw, y + (k + 1) * cw), desc=lab, click=True)
                     for k in range(nrows) for c in range(cols) if y + (k + 1) * cw <= bottom]
            s.kids.append(node("RecyclerView", (0, y, w, bottom), scrollable=True, kids=tiles))
            s.groups.append({"role": "tile", "nodes": tiles, "axis": "grid", "cols": cols})
        elif content == "media":
            keys = r.choice([["previous", "play", "next"], ["shuffle", "previous", "pause", "next", "repeat"], ["previous", "pause", "next"]])
            bw = sx(160)
            x0 = (w - bw * len(keys)) // 2
            yy = bottom - sy(420)
            btns = [node("ImageButton", (x0 + i * bw, yy, x0 + (i + 1) * bw, yy + sy(160)), desc=T.ELEMENTS[k][0], click=True) for i, k in enumerate(keys)]
            s.kids.append(node("LinearLayout", (0, yy, w, yy + sy(160)), kids=btns))
            s.named += list(zip(btns, keys)); used |= set(keys)
        else:  # feed: 1-2 cards, each with a repeated action row
            keys = [k for k in ["like", "comment", "share", "save"] if r.random() < 0.85] or ["like", "share"]
            authors = self.titles("people", r.randint(1, 2))
            ch = (bottom - y) // len(authors)
            cards = []
            for j, au in enumerate(authors):
                top = y + j * ch
                bw = sx(140)
                ay = top + ch - sy(170)
                acts = [node("ImageButton", (sx(30) + i * bw, ay, sx(30) + (i + 1) * bw, ay + sy(140)), desc=T.ELEMENTS[k][0], click=True) for i, k in enumerate(keys)]
                cards.append(node("LinearLayout", (0, top, w, top + ch), kids=[
                    node("TextView", (sx(160), top + sy(30), sx(700), top + sy(100)), text=au),
                    node("ImageView", (0, top + sy(120), w, ay - sy(10))),
                    node("LinearLayout", (0, ay, w, ay + sy(140)), kids=acts + [node("TextView", (sx(640), ay + sy(40), sx(900), ay + sy(100)), text=f"{r.randint(2, 900)} likes")])]))
                s.rows.append({"row": cards[-1], "title": au, "ctrl": None, "ctrl_kind": None, "acts": dict(zip(keys, acts))})
            s.kids.append(node("RecyclerView", (0, y, w, bottom), scrollable=True, kids=cards))
        if nav is not None:
            s.kids.append(nav)
            s.groups.append({"role": "tab" if nav.children[0].cls == "TabView" else "item", "nodes": nav.children, "axis": "left"})
        if content in ("list", "grid") and r.random() < 0.4 and "add" not in used:
            fab = node("ImageButton", (w - sx(220), bottom - sy(220), w - sx(40), bottom - sy(40)), desc=T.ELEMENTS["add"][0], click=True)
            s.kids.append(fab); s.named.append((fab, "add")); used.add("add")
        s.root = node("FrameLayout", (0, 0, w, h), kids=s.kids)
        s.used = used
        return s

    # ---- phrasing -------------------------------------------------------------------------------------------------

    @staticmethod
    def ord_groups(s: Screen) -> list[dict]:
        """Groups an ordinal can name unambiguously: a known group word, no grid (people count a grid in reading order,
        which the per-column rank does not state), and the only group of its role on the screen."""
        roles = [g.get("srole") for g in s.groups]
        return [g for g in s.groups if g.get("srole") in GROUP_WORDS and g["axis"] != "grid" and roles.count(g["srole"]) == 1]

    def words(self, g: dict) -> list[str]:
        if g.get("ctrl_kind") == "check":
            return CTRL["check"][3][self.h]
        return GROUP_WORDS[g["srole"]][self.h]

    def row(self) -> dict | None:
        r = self.r
        app = r.choice(self.apps)
        s = self.build(app)
        tg = {}
        for fmt in ("v1", "v2"):
            tg[fmt] = tt.build(s.root, s.w, s.h, fmt=fmt)
        boxes = [tuple(t["bounds"]) for t in tg["v2"]]
        if len(set(boxes)) != len(boxes) or len(boxes) < 2:
            return None
        idx = lambda n: boxes.index((n.left, n.top, n.right, n.bottom)) if (n.left, n.top, n.right, n.bottom) in boxes else None  # noqa: E731
        for g in s.groups:   # the role the app's serialiser gives the group (e.g. bottom-nav FrameLayouts become tabs)
            rs = {tg["v2"][i]["role"] for i in (idx(n) for n in g["nodes"]) if i is not None}
            g["srole"] = rs.pop() if len(rs) == 1 else None
        kind = r.choices(["name", "item", "ordinal", "relational", "position", "none", "none_ord", "none_rel"],
                         [18, 14, 20, 18, 6, 12, 6, 6])[0]
        target, acceptable, utt = None, None, None
        labels_on = [t["label"] for t in tg["v2"]]
        if kind == "name":
            c = [(n, k) for n, k in s.named if labels_on.count(T.ELEMENTS[k][0]) == 1 and not (T.GROUP.get(k, {k}) - {k}) & s.used]
            if not c:
                return None
            n, k = r.choice(c)
            target, utt = n, self.t.say_name(k, T.ELEMENTS[k][1])
        elif kind == "item":
            c = [x for x in s.rows if x.get("title") and "acts" not in x and labels_on.count(x["title"]) == 1]
            if not c:
                return None
            x = r.choice(c)
            target, utt = x["row"], self.pick(ITEM_T).format(t=x["title"])
        elif kind == "ordinal":
            gs = [g for g in self.ord_groups(s) if len(g["nodes"]) >= 2]
            if not gs:
                return None
            g = r.choice(gs)
            nodes = g["nodes"]
            if g["axis"] == "grid":   # "the second photo" = reading order in a grid (row by row)
                k = r.randrange(min(len(nodes), len(ORD)))
                target = nodes[k]
                o = ORD[k] if r.random() < 0.8 or k != len(nodes) - 1 else "last"
                utt = self.pick(ORD_T).format(o=o, g=r.choice(GROUP_WORDS["tile"][self.h]))
            else:
                k = r.randrange(min(len(nodes), len(ORD)))
                target = nodes[k]
                o = "last" if k == len(nodes) - 1 and r.random() < 0.5 else ORD[k]
                words = self.words(g)
                tmpl = ORD_ROW_T if g["axis"] == "left" and r.random() < 0.4 else ORD_T
                utt = self.pick(tmpl).format(o=o, g=r.choice(words))
                if g["axis"] == "down" and o in ("first", "last") and r.random() < 0.3:
                    utt = f"the {'top' if o == 'first' else 'bottom'} {r.choice(words)}"
        elif kind == "relational":
            c = [x for x in s.rows if x.get("ctrl") is not None or x.get("acts")]
            if not c:
                return None
            x = r.choice(c)
            if x.get("acts"):
                k, n = r.choice(list(x["acts"].items()))
                target = n
                utt = self.pick(REL_T).format(c=self.t.syn(k).removeprefix("the "), t=x["title"]).replace("next to", "under")
            elif x["ctrl_kind"] in ("switch", "check") and r.random() < 0.5:
                target, acceptable = x["ctrl"], [x["ctrl"], x["row"]]    # tapping the row toggles it too
                utt = self.pick(SW_FUNC_T).format(t=x["title"])
            else:
                target = x["ctrl"]
                utt = self.pick(REL_T).format(c=r.choice(CTRL[x["ctrl_kind"]][3][self.h]), t=x["title"])
        elif kind == "position":
            buckets = [t["position"] for t in tg["v2"]]
            c = [(n, t) for n, t in ((n, tg["v2"][idx(n)]) for n, _ in s.named if idx(n) is not None) if buckets.count(t["position"]) == 1]
            if not c:
                return None
            n, t = r.choice(c)
            target = n
            utt = self.t.fill(self.t.pick(T.POS_T), r=r.choice(T.ROLE_WORDS[t["role"]]), p=self.t.pos_words(t["position"]))
        elif kind == "none":
            shown = s.used
            absent = [k for k in T.ELEMENTS if not T.GROUP.get(k, {k}) & shown and T.ELEMENTS[k][0] not in labels_on]
            k = r.choice(absent)
            utt = self.t.say_name(k, T.ELEMENTS[k][1])
        elif kind == "none_ord":
            gs = [g for g in self.ord_groups(s) if g["axis"] == "down" and 2 <= len(g["nodes"]) < len(ORD) - 1]
            if not gs:
                return None
            g = r.choice(gs)
            utt = self.pick(ORD_T).format(o=ORD[len(g["nodes"]) + r.randint(0, 1)], g=r.choice(self.words(g)))
        else:  # none_rel: a control for a title that is not on screen
            c = [x for x in s.rows if x.get("ctrl") is not None]
            if not c:
                return None
            x = r.choice(c)
            flavour = next(f for f, (a, b) in TITLES.items() if x["title"] in a + b)
            gone = [t for t in TITLES[flavour][self.h and 1 or 0] if t not in {y["title"] for y in s.rows}]
            if not gone:
                return None
            utt = self.pick(REL_T).format(c=r.choice(CTRL[x["ctrl_kind"]][3][self.h]), t=r.choice(gone))
        if target is not None and idx(target) is None:
            return None
        line = screen_text(s.kind, r.choice(["none", "playing", "paused"]), r.choice(["can scroll both ways", "at the top", "not scrollable"]), "hidden")
        ctx = f"mode: cursor\napp: {APPS.get(app, app)} ({app})\n{line}\nspoken target: \"{utt}\""
        lab = len(boxes) if target is None else idx(target)
        acc = sorted({lab} | ({idx(n) for n in acceptable if idx(n) is not None} if acceptable else set()))
        out = {}
        for fmt in ("v1", "v2"):
            if fmt == "v1" and kind in ("ordinal", "relational", "none_ord", "none_rel"):
                continue   # not solvable from v1 text (no rank / context)
            opts = tt.options(tg[fmt])
            if fmt == "v1" and len(set(opts)) != len(opts):
                return None
            out[fmt] = {"context": ctx, "options": opts, "label": lab, "option_keys": [f"t{j}" for j in range(len(opts) - 1)] + ["none"],
                        "kind": kind, "acceptable": acc, "meta": {"target": None if target is None else tg[fmt][lab]["label"]},
                        "option_format": fmt, "synthetic_geometry": True}
        return out


def write_split(out: Path, n: int, seed: int, held: bool, apps: list[str], name: str) -> dict:
    g = Gen(random.Random(seed), held, apps)
    rows = {"v1": [], "v2": []}
    seen = set()
    tries = 0
    while len(rows["v2"]) < n:
        tries += 1
        x = g.row()
        if x is None or "v2" not in x:
            continue
        key = (x["v2"]["context"], tuple(x["v2"]["options"]))
        if key in seen:
            continue
        seen.add(key)
        i = len(rows["v2"])
        for fmt, row in x.items():
            row["id"], row["split"] = f"geo-{name}-{i}", name
            rows[fmt].append(row)
    for fmt, rs in rows.items():
        (out / fmt).mkdir(parents=True, exist_ok=True)
        (out / fmt / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs))
    return {fmt: len(rs) for fmt, rs in rows.items()} | {"tries": tries}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--train", type=int, default=6000)
    p.add_argument("--validation", type=int, default=500)
    p.add_argument("--test", type=int, default=1000)
    p.add_argument("--seed", type=int, default=11)
    a = p.parse_args()
    if a.output.exists() and any(a.output.rglob("*.jsonl")):
        raise SystemExit(f"{a.output} already has data: use a new --output")
    train_apps = [x for x in APPS if x not in HELDOUT_APPS]
    s = a.seed
    rep = {"train": write_split(a.output, a.train, s, False, train_apps, "train"),
           "validation": write_split(a.output, a.validation, s + 1, False, train_apps, "validation"),
           "test_iid": write_split(a.output, a.test, s + 2, False, train_apps, "test_iid"),
           "test_unseen_phrasing": write_split(a.output, a.test, s + 3, True, train_apps, "test_unseen_phrasing"),
           "test_unseen_apps": write_split(a.output, a.test, s + 4, False, sorted(HELDOUT_APPS), "test_unseen_apps")}
    code = hashlib.sha256(Path(__file__).read_bytes() + (ROOT / "android/suite/tree_targets.py").read_bytes()).hexdigest()[:12]
    (a.output / "BUILD.json").write_text(json.dumps({"argv": sys.argv, "seed": s, "counts": rep, "code_sha": code}, indent=1))
    (a.output / "policy.txt").write_text(T.POLICY_TARGETS + "\n")
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
