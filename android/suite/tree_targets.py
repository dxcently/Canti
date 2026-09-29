"""Python port of the app's option builder (Targets.kt) and screen line (ScreenSummarizer.kt) over a `uiautomator dump`.

For phones without VOX/Canti installed (harvest_device.sh). The app's own `targets` op is the reference; this port is
checked against it on the emulator with `python3 suite/tree_targets.py --check` (run inside ./dev), which reports how
often the two option lists agree exactly.

Known gaps against the app (uiautomator XML does not carry these fields):
  - collectionItem / CollectionInfo rows/cols: absent, so "list item" is decided only by the parent's class
    (RecyclerView/ListView/GridView), and the feed-pager test cannot use `rows`;
  - canScrollForward/Backward: absent; the scroll line uses the primary scroller's position is unknown ->
    "can scroll both ways" for any scrollable (flagged `scroll_approx`);
  - editable: taken from the EditText class (plus AutoCompleteTextView / *EditText* class names);
  - visible: uiautomator only dumps nodes visible to the user, so every dumped node counts as visible;
  - the root is the window uiautomator dumps (the active window), not TreeReader.appRoot's choice;
  - window covers (Occlusion): the app uses every window above the app's; here only the other dumped roots of
    system UI / the keyboard count (`covers_for`), and the app's other windows (a floating-button layer) are not read;
  - keyboard open / music active come from dumpsys (input_method mInputShown, audio playback state).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

NONE_OPTION = "none of these (the thing I named is not on screen)"
POSITIONS = ["top left", "top", "top right", "left", "center", "right", "bottom left", "bottom", "bottom right"]
MAX_OPTIONS = 40
MAX_LABEL_CHARS = 60
CONTAINER_SHARE = 0.5
LIST_CLASSES = {"RecyclerView", "ListView", "GridView"}
INDENT_DP = 16   # Targets.INDENT_DP: the indentation threshold in dp on the app's 411-dp design width (see indent_parents)


@dataclass
class Node:
    cls: str
    id: str | None
    text: str | None
    desc: str | None
    left: int
    top: int
    right: int
    bottom: int
    scrollable: bool = False
    editable: bool = False
    focused: bool = False
    clickable: bool = False
    visible: bool = True
    focusable: bool = False
    selected: bool = False
    collection_item: bool = False
    rows: int = -1
    cols: int = -1
    drawing_order: int = 0   # AccessibilityNodeInfo.getDrawingOrder (0 = unknown: uiautomator dumps, Compose)
    pkg: str = ""
    children: list["Node"] = field(default_factory=list)

    @property
    def width(self) -> int: return max(self.right - self.left, 0)
    @property
    def height(self) -> int: return max(self.bottom - self.top, 0)
    @property
    def area(self) -> int: return self.width * self.height
    @property
    def short_cls(self) -> str: return self.cls.rsplit(".", 1)[-1]

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


_B = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_uiautomator(xml: str) -> list[Node]:
    """uiautomator XML -> the top-level nodes (one per dumped window root)."""
    root = ET.fromstring(xml)

    def conv(e) -> Node:
        m = _B.match(e.get("bounds", "[0,0][0,0]"))
        l, t, r, b = map(int, m.groups()) if m else (0, 0, 0, 0)
        cls = e.get("class", "")
        t_ = lambda k: e.get(k) == "true"  # noqa: E731
        n = Node(cls=cls, id=e.get("resource-id") or None, text=e.get("text") or None,
                 desc=e.get("content-desc") or None, left=l, top=t, right=r, bottom=b,
                 scrollable=t_("scrollable"), editable=cls.endswith("EditText") or "EditText" in cls or t_("password"),
                 focused=t_("focused"), clickable=t_("clickable"),
                 visible=e.get("visible-to-user", "true") != "false", focusable=t_("focusable"), selected=t_("selected"),
                 pkg=e.get("package", ""))
        n.children = [conv(c) for c in e if c.tag == "node"]
        return n

    return [conv(c) for c in root if c.tag == "node"]


# --- Targets.kt ------------------------------------------------------------------------------------------------------

def bucket(cx: int, cy: int, w: int, h: int) -> int:
    col = 1 if w <= 0 else min(max(cx * 3 // w, 0), 2)
    row = 1 if h <= 0 else min(max(cy * 3 // h, 0), 2)
    return row * 3 + col


def clean(s: str | None) -> str | None:
    if s is None:
        return None
    t = re.sub(r"\s+", " ", s).strip()
    if not t:
        return None
    return t if len(t) <= MAX_LABEL_CHARS else t[:MAX_LABEL_CHARS - 3].rstrip() + "..."


def _words(n: Node) -> str | None:
    return n.text if n.text and any(ch.isalpha() for ch in n.text) else None


# Targets.DESCENDANT_PASSES: a text with a letter (a title), else a description (an icon's), else any text (a count)
DESCENDANT_PASSES = (_words, lambda n: n.desc, lambda n: n.text)


def _descendant_text(n: Node, field, depth: int = 0) -> str | None:
    if depth > 8:
        return None
    for c in n.children:
        if not c.visible or c.clickable or c.focusable:
            continue
        for v in (clean(field(c)), _descendant_text(c, field, depth + 1)):
            if v:
                return v
    return None


def label(n: Node) -> str:
    # Targets.label: a row's title before its icon's description (DESCENDANT_PASSES)
    for v in (clean(n.desc), clean(n.text), *(_descendant_text(n, f) for f in DESCENDANT_PASSES), clean(id_name(n))):
        if v:
            return v
    return "unlabeled"


ID_FILLER = {"img", "imgv", "iv", "image", "imageview", "txt", "txtv", "tv", "text", "textview", "btn", "but",
             "button", "ib", "imgbtn", "sb", "seekbar", "pb", "fab", "cb", "chk", "checkbox", "sw", "switch", "et", "edittext",
             "rv", "lv", "ll", "fl", "rl", "cl", "vg", "layout", "view", "container", "holder", "wrapper", "item", "id"}
WIDGET_NOUNS = {"ImageView": "image", "ImageButton": "button", "Button": "button",
                "FloatingActionButton": "button", "SeekBar": "seek bar", "Slider": "slider", "ProgressBar": "progress bar",
                "RatingBar": "rating bar", "Switch": "switch", "SwitchCompat": "switch", "CheckBox": "checkbox",
                "RadioButton": "radio button", "ToggleButton": "toggle", "EditText": "text field",
                "TextInputEditText": "text field", "Spinner": "dropdown", "Chip": "chip"}
# Targets.ID_NAMED: a last id word that already says what the control is: no widget noun after it
ID_NAMED = {"icon", "image", "picture", "photo", "avatar", "thumbnail", "logo", "button", "slider", "switch", "toggle",
            "box", "field", "chip", "card", "dropdown"}
_ID_SPLIT = re.compile(r"[_\-.\s]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def id_name(n: Node) -> str | None:
    """Targets.idName: the view id tail's words (split at _ - . and camelCase, lowercased, ID_FILLER and bare numbers
    dropped), then the widget noun unless the words end with it or with an ID_NAMED word; no words: the noun; no id, or neither: None.
    Never the raw id."""
    if not n.id or not n.id.strip():
        return None
    tail = n.id.rsplit("/", 1)[-1]
    words = " ".join(w for w in (p.lower() for p in _ID_SPLIT.split(tail)) if w and w not in ID_FILLER and not w.isdigit())
    c = n.short_cls
    c = c[len("AppCompat"):] if c.startswith("AppCompat") else c
    c = c[len("Material"):] if c.startswith("Material") else c
    noun = WIDGET_NOUNS.get(c)
    if noun and words and not words.endswith(noun) and words.rsplit(" ", 1)[-1] not in ID_NAMED:
        return words + " " + noun
    return words or noun


def _is_tab(n: Node, parent: Node | None) -> bool:
    c = n.short_cls
    if c.endswith("$Tab") or c == "TabView" or (parent is not None and parent.short_cls == "TabWidget"):
        return True
    if parent is None:
        return False
    sibs = [s for s in parent.children if s.visible]
    if len(sibs) < 2 or not any(s.selected for s in sibs):
        return False
    return all(s.short_cls == c and abs(s.top - n.top) <= 8 and abs(s.height - n.height) <= 8 for s in sibs)


def role(n: Node, parent: Node | None) -> str:
    c = n.short_cls
    if c == "EditText" or n.editable:
        return "text field"
    if c in ("Switch", "CheckBox"):
        return "switch"
    if _is_tab(n, parent):
        return "tab"
    if c in ("Button", "ImageButton"):
        return "button"
    if n.collection_item or (parent is not None and (parent.short_cls in LIST_CLASSES or parent.rows > 0 or parent.cols > 0)):
        return "list item"
    if c == "ImageView":
        return "image"
    return "item"


def _has_target_inside(n: Node, depth: int = 0) -> bool:
    # An invisible node can still hold visible targets (Compose AndroidView holder): look through it (Targets.kt).
    return depth < 12 and ((n.visible and (n.clickable or n.focusable)) or any(_has_target_inside(c, depth + 1) for c in n.children))


def is_target(n: Node, w: int, h: int) -> bool:
    if not n.visible or not (n.clickable or n.focusable) or n.width <= 0 or n.height <= 0:
        return False
    if n.scrollable and not n.clickable:
        return False
    if not n.clickable and n.area > CONTAINER_SHARE * w * h:
        return False
    if not n.clickable and clean(n.desc) is None and clean(n.text) is None and any(_has_target_inside(c) for c in n.children):
        return False
    cx, cy = (n.left + n.right) // 2, (n.top + n.bottom) // 2
    return 0 <= cx < w and 0 <= cy < h


# --- Occlusion (Targets.kt) -----------------------------------------------------------------------------------------------

MIN_VISIBLE_SHARE = 0.25
SCRIM_SHARE = 0.5
SCRIM_LABELS = {"close navigation menu", "close drawer", "close sheet", "dismiss", "close menu", "scrim"}
Box = tuple  # (left, top, right, bottom)


def _empty(b: Box) -> bool: return b[2] <= b[0] or b[3] <= b[1]
def _area(b: Box) -> int: return 0 if _empty(b) else (b[2] - b[0]) * (b[3] - b[1])
def _isect(a: Box, b: Box) -> Box: return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def uncovered(r: Box, covers) -> list:
    parts = [] if _empty(r) else [r]
    for c in covers:
        nxt = []
        for p in parts:
            i = _isect(p, c)
            if _empty(i):
                nxt.append(p)
                continue
            nxt += [q for q in ((p[0], p[1], p[2], i[1]), (p[0], i[3], p[2], p[3]), (p[0], i[1], i[0], i[3]), (i[2], i[1], p[2], i[3]))
                    if not _empty(q)]
        parts = nxt
        if not parts:
            break
    return parts


MIN_TAP_SIDE = 40
POPUP_OVERHANG = 24


def visible_part(r: Box, covers, screen: Box):
    """Occlusion.visiblePart: None if hidden; r if its centre is uncovered; else the largest uncovered piece if it is at
    least MIN_TAP_SIDE both ways (the tap lands on what can be seen)."""
    on = _isect(r, screen)
    if _empty(on):
        return None
    if not covers:
        return r
    parts = uncovered(on, covers)
    if sum(_area(b) for b in parts) / _area(on) < MIN_VISIBLE_SHARE:
        return None
    cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
    if not any(c[0] <= cx < c[2] and c[1] <= cy < c[3] for c in covers):
        return r
    best = max(parts, key=_area) if parts else None
    return best if best is not None and best[2] - best[0] >= MIN_TAP_SIDE and best[3] - best[1] >= MIN_TAP_SIDE else None


def hidden(r: Box, covers, screen: Box) -> bool:
    return visible_part(r, covers, screen) is None


SHEET_MIN_PARTS = 2
ABOVE_FILL_TENTHS = 3


def fills(n: Node) -> bool:
    """Occlusion.fills: the visible leaf descendants' areas (clipped to n) add up to ABOVE_FILL_TENTHS tenths of n."""
    me = (n.left, n.top, n.right, n.bottom)
    if _empty(me):
        return False
    total = sum(_area(_isect((d.left, d.top, d.right, d.bottom), me)) for d in list(n.walk())[1:]
                if d.visible and not any(c.visible for c in d.children))
    return total * 10 >= _area(me) * ABOVE_FILL_TENTHS


def shows_content(sheet: Node) -> bool:
    """Occlusion.showsContent: a labelled or tappable visible descendant with an area, or SHEET_MIN_PARTS visible ones.
    An empty sheet container (Instagram's childless, feed-sized bottom_sheet_..._container) covers nothing."""
    parts = 0
    for d in list(sheet.walk())[1:]:
        if not d.visible or d.area <= 0:
            continue
        if d.clickable or d.focusable or d.editable or clean(d.desc) is not None or clean(d.text) is not None:
            return True
        parts += 1
        if parts >= SHEET_MIN_PARTS:
            return True
    return False


OVERLAY_BAR = re.compile(r"action_?mode_?bar|overlay_?tool_?bar|tool_?bar_?overlay|selection_?tool_?bar|contextual_?(action_?)?bar")


def surfaces(root: Node, order: dict, w: int, h: int) -> list:
    """(start index, box, kind, end): an open DrawerLayout drawer, a bottom sheet that shows content, a contextual bar
    over the toolbar (action mode / overlay toolbar) that shows content, a snackbar, a full-screen scrim, a popup drawn in
    the window reaching outside its parent, a sibling drawn above another that shows content and fills its box
    (Occlusion.surfaces; the same order of the list). end: -1, or for a popup the last index of its subtree (it also
    covers what comes after it). under: None, or (first, last) index of the one subtree it covers ("above")."""
    out = []

    def visit(n: Node, parent: Node | None):
        for c in n.children:
            visit(c, n)
        if not n.visible:
            return
        idx = order[id(n)][0]
        box = (n.left, n.top, n.right, n.bottom)
        if n.short_cls == "DrawerLayout":
            d = next((c for c in n.children[1:] if c.visible and c.width > 0 and c.height > 0), None)
            if d is not None:
                out.append((order[id(d)][0], box, "drawer", -1, None))
        tail = (n.id or "").rsplit("/", 1)[-1].lower()
        if ("BottomSheet" in n.short_cls or "bottom_sheet" in tail) and n.area > 0 and shows_content(n):
            out.append((idx, box, "sheet", -1, None))
        if OVERLAY_BAR.search(tail) and n.area > 0 and shows_content(n):
            out.append((idx, box, "bar", -1, None))
        if tail in ("snackbar_text", "snackbar_action") and parent is not None and parent.visible and parent.area > 0:
            out.append((order[id(parent)][0], (parent.left, parent.top, parent.right, parent.bottom), "snackbar", -1, None))
        lab = (clean(n.desc if n.desc is not None else n.text) or "").lower()
        if n.clickable and n.area >= SCRIM_SHARE * w * h and (lab in SCRIM_LABELS or tail.endswith("touch_outside") or tail.endswith("scrim")):
            out.append((idx, box, "scrim", -1, None))
        if parent is not None and parent.visible and parent.area > 0 and 0 < n.area < SCRIM_SHARE * w * h and \
                max(parent.left - n.left, n.right - parent.right, parent.top - n.top, n.bottom - parent.bottom) >= POPUP_OVERHANG and \
                shows_content(n):
            out.append((idx, box, "popup", order[id(n)][1], None))
        drawn = [c for c in n.children if c.visible and c.drawing_order > 0 and c.area > 0]
        if len(drawn) >= 2:
            for s in drawn:
                sb = (s.left, s.top, s.right, s.bottom)
                lower = [b for b in drawn if b.drawing_order < s.drawing_order and not _empty(_isect((b.left, b.top, b.right, b.bottom), sb))]
                if not lower or not shows_content(s) or not fills(s):
                    continue
                for b in lower:
                    out.append((order[id(s)][0], sb, "above", -1, tuple(order[id(b)])))

    visit(root, None)
    return list(dict.fromkeys(out))


SYSTEM_PKGS = ("com.android.systemui", "com.samsung.android.honeyboard", "com.google.android.inputmethod")


def covers_for(roots: list[Node], root: Node | None) -> list:
    """Window covers for the port: the dumped system UI / keyboard roots (always above the app)."""
    return [(r.left, r.top, r.right, r.bottom) for r in roots if r is not root and r.pkg.startswith(SYSTEM_PKGS)]


def keep_rank(t: dict) -> int:
    if t["label"] == "unlabeled":
        return 3
    if t["role"] in ("item", "image"):
        return 2
    if t["role"] == "list item":
        return 1
    return 0


# --- option format (Targets.kt OPTION FORMAT; the same bytes) -----------------------------------------------------------
#   {label}[ · {context}] ({role}, {position}[, {rank}])
# context: row text for a switch, a generic label or a label two kept targets share; rank: "{k} of {n} down" (column),
# "{k} of {n} from left" (row), "far left" / "far right" (edge of a shared bucket), plus "{k} of {n}" in reading order
# for options that are still identical. The full rules are in Targets.kt; target_format_parity.json checks both.

MAX_CONTEXT_CHARS = 30
ROW_CLIMB = 3
GENERIC_LABELS = {"unlabeled", "more", "more options", "more actions", "onoff", "on off", "toggle", "switch", "checkbox",
                  "play or pause", "media image", "channel image", "image", "icon", "button", "menu", "options", "overflow menu",
                  "expand", "collapse"}


def _v_overlap(a_top: int, a_bottom: int, b_top: int, b_bottom: int) -> bool:
    ov = min(a_bottom, b_bottom) - max(a_top, b_top)
    return ov > 0 and 2 * ov >= min(a_bottom - a_top, b_bottom - b_top)


def row_text(n: Node, lab: str, path: list, w: int, h: int) -> str | None:
    """Targets.rowText: the first text in pre-order under the nearest of ROW_CLIMB ancestors that shares n's line."""
    own = lab.lower()

    def find(p: Node, depth: int, field):
        if depth > 8:
            return None
        for c in p.children:
            if c is n or not c.visible or c.clickable or c.focusable:
                continue
            t = clean(field(c))
            if t is not None and t.lower() != own and _v_overlap(c.top, c.bottom, n.top, n.bottom):
                return t
            v = find(c, depth + 1, field)
            if v is not None:
                return v
        return None

    near = []
    for a in list(reversed(path))[:ROW_CLIMB]:
        if a.area > CONTAINER_SHARE * w * h:
            break
        near.append(a)
    for field in DESCENDANT_PASSES:   # a row's title before its icons' descriptions, a bare number last
        for a in near:
            t = find(a, 0, field)
            if t is not None:
                return t if len(t) <= MAX_CONTEXT_CHARS else t[:MAX_CONTEXT_CHARS - 3].rstrip() + "..."
    return None


def ordinal(k: int, n: int) -> str:
    if k == n:
        return "last"
    suf = "th" if k % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suf}"


def option_text(t: dict) -> str:
    ctx = f" · {t['context']}" if t.get("context") else ""
    rank = f", {t['rank']}" if t.get("rank") else ""
    return f"{t['label']}{ctx} ({t['role']}, {t['position']}{rank})"


def cap_context(s: str) -> str:
    """Cap a context the same way row_text does (MAX_CONTEXT_CHARS, ellipsis)."""
    return s if len(s) <= MAX_CONTEXT_CHARS else s[:MAX_CONTEXT_CHARS - 3].rstrip() + "..."


def indent_parents(kept: list[dict], w: int) -> dict:
    """jl10 (mirror of Targets.indentParents / vox.option_format.indent_context): index -> parent label for indented
    list rows. Only a "list item" may take a parent, and the parent must also be a "list item" (a). The parent is the
    nearest preceding kept row in reading order (top, then left) in the SAME immediate parent node, indented at least
    round(16 * w / 411) px and strictly above it (b, d). The immediate parent must pass the list test (class / rows /
    cols, or the child is a collection item), falling back to >= 3 kept list items (b); a grid container gets none (i).
    A parent whose label is generic or equals the child's is skipped, taking the next nearest (c)."""
    indent = round(INDENT_DP * w / 411)
    is_row = [t["role"] == "list item" for t in kept]

    def container_ok(i):
        p = kept[i].get("_parent")
        if p is None:
            return False
        if kept[i].get("_collection_item"):
            return True
        if p.short_cls in LIST_CLASSES or p.rows > 0 or p.cols > 0:
            return True
        return sum(1 for j in range(len(kept)) if is_row[j] and kept[j].get("_parent") is p) >= 3

    def is_grid(i):
        p = kept[i].get("_parent")
        if p is None:
            return False
        rows = [j for j in range(len(kept)) if is_row[j] and kept[j].get("_parent") is p]
        for a in range(len(rows)):
            for b in range(a + 1, len(rows)):
                ia, ib = kept[rows[a]], kept[rows[b]]
                if _v_overlap(ia["bounds"][1], ia["bounds"][3], ib["bounds"][1], ib["bounds"][3]) and ia["bounds"][0] != ib["bounds"][0]:
                    return True
        return False

    order = sorted(range(len(kept)), key=lambda i: (kept[i]["bounds"][1], kept[i]["bounds"][0], i))
    pos = {i: k for k, i in enumerate(order)}
    out = {}
    for i, t in enumerate(kept):
        if not is_row[i] or not container_ok(i) or is_grid(i):
            continue
        p = kept[i].get("_parent")
        if p is None:
            continue
        left = t["bounds"][0]
        parent_row = None
        for k in range(pos[i] - 1, -1, -1):
            j = order[k]
            if not is_row[j] or kept[j].get("_parent") is not p:
                continue
            u = kept[j]
            if u["bounds"][0] <= left - indent and u["bounds"][1] < t["bounds"][1]:
                lbl = u["label"].lower()
                if lbl in GENERIC_LABELS or lbl == t["label"].lower():
                    continue
                parent_row = j
                break
        if parent_row is not None:
            out[i] = cap_context(kept[parent_row]["label"])
    return out


def decorate(kept: list[dict], w: int, h: int, fmt: str = "v1") -> None:
    """Targets.decorate: context, rank, the tree parent and the last-resort repeat number, in place (kept: reading
    order). "v1" (default): no context or rank, only the repeat number on identical options. "v2": row context and rank.
    "v2i": v2 plus the indented-list tree context (a sub-row's parent), which also stays on `parent` for every format."""
    counts: dict = {}
    for t in kept:
        counts[t["label"].lower()] = counts.get(t["label"].lower(), 0) + 1
    cx = lambda t: (t["bounds"][0] + t["bounds"][2]) // 2  # noqa: E731
    v2 = fmt in ("v2", "v2i")
    parents = indent_parents(kept, w)   # the tree parent, always available (even v1)
    for t in kept:
        t["context"], t["rank"] = None, None
    for i, t in enumerate(kept if v2 else []):
        l, tp, r, b = t["bounds"]
        low = t["label"].lower()
        existing = t["_row"] if (t["role"] == "switch" or low in GENERIC_LABELS or counts[low] >= 2) else None
        t["context"] = existing
        if fmt == "v2i" and not existing:   # the existing v2 rule wins over the tree parent
            t["context"] = parents.get(i)
        col = [j for j, u in enumerate(kept) if u["role"] == t["role"] and
               (min(r, u["bounds"][2]) - max(l, u["bounds"][0])) > 0 and
               2 * (min(r, u["bounds"][2]) - max(l, u["bounds"][0])) >= min(r - l, u["bounds"][2] - u["bounds"][0])]
        col.sort(key=lambda j: (kept[j]["bounds"][1], kept[j]["bounds"][0], j))
        row = [j for j, u in enumerate(kept) if u["role"] == t["role"] and _v_overlap(tp, b, u["bounds"][1], u["bounds"][3])]
        row.sort(key=lambda j: (kept[j]["bounds"][0], kept[j]["bounds"][1], j))
        others = [u for j, u in enumerate(kept) if j != i and u["_b"] == t["_b"]]
        if len(col) >= 2 and (len(col) > len(row) or (len(col) == len(row) and t["role"] != "tab")):
            rank = f"{ordinal(col.index(i) + 1, len(col))} of {len(col)} down"
        elif len(row) >= 2:
            rank = f"{ordinal(row.index(i) + 1, len(row))} of {len(row)} from left"
        elif others and t["_b"] % 3 == 0 and all(cx(u) > cx(t) for u in others):
            rank = "far left"
        elif others and t["_b"] % 3 == 2 and all(cx(u) < cx(t) for u in others):
            rank = "far right"
        else:
            rank = None
        t["rank"] = rank
    for i, t in enumerate(kept):
        t["parent"] = parents.get(i)
    groups: dict = {}
    for i, t in enumerate(kept):
        groups.setdefault(option_text(t), []).append(i)
    for g in groups.values():
        if len(g) < 2:
            continue
        for k, i in enumerate(g):
            kept[i]["rank"] = ", ".join(x for x in (kept[i]["rank"], f"{ordinal(k + 1, len(g))} of {len(g)}") if x)
    for t in kept:
        t["option"] = option_text(t)


def _same_element(a: dict, b: dict) -> bool:
    """Targets.sameElement: same label and role, one's centre inside the other's box."""
    if a["label"] != b["label"] or a["role"] != b["role"]:
        return False
    def inside(box, o):
        x, y = (o[0] + o[2]) // 2, (o[1] + o[3]) // 2
        return box[0] <= x < box[2] and box[1] <= y < box[3]
    return inside(a["bounds"], b["bounds"]) or inside(b["bounds"], a["bounds"])


def build(root: Node | None, w: int, h: int, covers=(), fmt: str = "v1") -> list[dict]:
    """Targets in the app's reading order: [{label, role, position, context, rank, parent, bounds, option}]. fmt: the
    option format (OptionFormat.kt), "v1" (default, the original text), "v2" (row context and rank) or "v2i" (v2 plus
    the indented-list tree context)."""
    if root is None:
        return []
    found = []
    order: dict = {}
    counter = [0]

    def index(n: Node):
        me = [counter[0], 0]
        order[id(n)] = me
        counter[0] += 1
        for c in n.children:
            index(c)
        me[1] = counter[0] - 1

    index(root)
    surf = surfaces(root, order, w, h)
    screen = (0, 0, w, h)
    path: list = []   # ancestors of the node being visited, root first

    def visit(n: Node):
        start, end = order[id(n)]
        me = (n.left, n.top, n.right, n.bottom)
        over = list(covers) + [b for (s, b, _, e, u) in surf if (u[0] <= start <= u[1] if u else (s > end or (e >= 0 and start > e)))
                               and not _empty(_isect(b, me))]
        v = visible_part(me, over, screen) if is_target(n, w, h) else None
        if v is not None:
            cx, cy = (v[0] + v[2]) // 2, (v[1] + v[3]) // 2
            parent = path[-1] if path else None
            lab, rl, pos = label(n), role(n, parent), POSITIONS[bucket(cx, cy, w, h)]
            found.append({"label": lab, "role": rl, "position": pos, "bounds": list(v),
                          "_b": bucket(cx, cy, w, h), "_row": row_text(n, lab, path, w, h),
                          "_parent": parent, "_collection_item": n.collection_item})
        path.append(n)
        for c in n.children:
            visit(c)
        path.pop()

    visit(root)
    found.sort(key=lambda t: (t["_b"] // 3, t["_b"] % 3, t["bounds"][1], t["bounds"][0]))  # stable, like sortedWith
    out: list = []
    for t in found:   # the same element twice keeps the first; repeated identical controls all stay
        if not any(_same_element(u, t) for u in out):
            out.append(t)
    if len(out) > MAX_OPTIONS - 1:   # the least useful go first (Targets.keepRank), then back to reading order
        keep = {id(t) for _, t in sorted(enumerate(out), key=lambda it: (keep_rank(it[1]), it[0]))[:MAX_OPTIONS - 1]}
        out = [t for t in out if id(t) in keep]
    decorate(out, w, h, fmt)
    for t in out:
        t.pop("_b")
        t.pop("_row")
        t.pop("_parent", None)
        t.pop("_collection_item", None)
    return out


def options(targets: list[dict]) -> list[str]:
    return [t["option"] for t in targets] + [NONE_OPTION]


# --- ScreenSummarizer.kt ------------------------------------------------------------------------------------------------

VIDEO_SURFACES = ["SurfaceView", "TextureView", "VideoView", "PlayerView", "StyledPlayerView"]
WEB = ["WebView", "GeckoView"]
CAMERA_PKGS = {"com.android.camera2", "com.google.android.GoogleCamera", "org.lineageos.aperture", "net.sourceforge.opencamera",
               "com.simplemobiletools.camera", "org.fossify.camera", "com.sec.android.app.camera"}
MAP_PKGS = {"com.google.android.apps.maps", "app.organicmaps", "net.osmand", "net.osmand.plus"}


def screen_line(root: Node | None, pkg: str, w: int, h: int, keyboard_open: bool, launcher_pkgs: set[str],
                music_active: bool) -> str:
    """The `screen:` line. Scroll direction is unknown from uiautomator: a scrollable screen says "can scroll both ways"."""
    kb = "open" if keyboard_open else "hidden"
    if root is None:
        return f"screen: other; media {'playing' if music_active else 'none'}; scroll not scrollable; keyboard {kb}"
    nodes = [n for n in root.walk() if n.visible]
    area = w * h
    frac = lambda n: 0.0 if area == 0 else n.area / area  # noqa: E731
    lab = lambda n: ((n.desc or "") + " " + (n.text or "")).strip().lower()  # noqa: E731
    scrollers = [n for n in nodes if n.scrollable]
    primary = max(scrollers, key=lambda n: n.area) if scrollers else None
    scroll = "not scrollable" if primary is None else "can scroll both ways"
    big_surface = any(any(n.cls.endswith(s) for s in VIDEO_SURFACES) and n.width >= w * .9 and n.height >= h * .2 for n in nodes)
    seek = any(n.cls.endswith("SeekBar") or n.cls.endswith("Slider") or "seek" in (n.id or "").lower()
               or ("progress" in (n.id or "").lower() and n.width > w / 2) for n in nodes)
    pause = any((l := lab(n)) == "pause" or l.startswith("pause ") or l.startswith("pause video") for n in nodes)
    play = any((l := lab(n)) == "play" or (l.startswith("play ") and not l.startswith("play all")) or l.startswith("play video") for n in nodes)
    pager = next((n for n in nodes if n.scrollable and frac(n) >= .6 and n.rows != 0
                  and 1 <= sum(1 for c in n.children if c.visible and c.area > 0) <= 2
                  and any(c.visible and c.area >= n.area * .8 for c in n.children)), None)
    page = max((c for c in pager.children if c.visible), key=lambda c: c.area, default=None) if pager else None
    page_list = page is not None and any(d.scrollable for d in page.walk())
    page_video = (page is not None and any(any(d.cls.endswith(s) for s in VIDEO_SURFACES) for d in page.walk())) or \
        (pager is not None and (pause or play))
    page_image = page is not None and any(d.cls.endswith("ImageView") and d.area >= page.area * .5 for d in page.walk())
    vertical = pager is not None and pager.rows > 1 and pager.cols <= 1
    feed = pager if pager is not None and not page_list and (page_video or (vertical and not page_image)) else None
    if keyboard_open and any(n.editable and n.focused for n in nodes):
        kind = "text entry"
    elif pkg in launcher_pkgs:
        kind = "home screen"
    elif 1 <= root.area < area * .6 and root.width < w:
        kind = "dialog"
    elif pkg in CAMERA_PKGS:
        kind = "camera viewfinder"
    elif pkg in MAP_PKGS or any(frac(n) >= .4 and ("map" in (n.id or "").split("/", 1)[-1].lower() or "MapView" in n.short_cls) for n in nodes):
        kind = "map"
    elif any(any(n.cls.endswith(s) for s in WEB) and frac(n) >= .4 for n in nodes):
        kind = "web page"
    elif feed is not None:
        kind = "video feed"
    elif big_surface or (seek and (pause or play)):
        kind = "video player"
    elif page_image or any(n.cls.endswith("ImageView") and frac(n) >= .5 for n in nodes) or \
            any("photo" in (n.id or "").lower() and frac(n) >= .5 for n in nodes):
        kind = "photo viewer"
    elif any(not n.editable and len(n.text or "") >= 600 and frac(n) >= .3 for n in nodes):
        kind = "document"
    elif primary is not None and frac(primary) >= .3:
        kind = "scrolling list"
    else:
        kind = "other"
    media_ui = kind in ("video player", "video feed")
    media = "playing" if music_active or (pause and (media_ui or big_surface)) else \
        "paused" if play and (media_ui or big_surface) else "none"
    return f"screen: {kind}; media {media}; scroll {scroll}; keyboard {kb}"


def state_template(app_name: str, pkg: str, screen: str) -> str:
    """Targets.stateText with {UTTERANCE} for the phrase."""
    return f"mode: cursor\napp: {app_name} ({pkg})\n{screen}\nspoken target: \"{{UTTERANCE}}\""


def pick_root(roots: list[Node], w: int, h: int) -> Node | None:
    """The app window among the dumped roots: skip systemui/IME/overlays, prefer the largest remaining."""
    skip = ("com.android.systemui", "com.samsung.android.honeyboard", "com.google.android.inputmethod", "ai.vox.companion")
    cand = [r for r in roots if not r.pkg.startswith(skip)]
    return max(cand or roots, key=lambda r: r.area) if (cand or roots) else None


# --- check against the app on the emulator ------------------------------------------------------------------------------

def _check(n: int, settle: float, fmt: str | None = None) -> None:
    """Compare the port with the app's `targets` op on the screens listed in the real-targets screens.jsonl... simpler:
    walk a few apps and compare on each current screen (uiautomator disturbs the a11y service, so wait `settle`)."""
    import json
    import time
    from voxlib import Vox, adb
    vox = Vox()
    t = vox.control("targets")
    xml = adb("exec-out", "uiautomator", "dump", "/dev/tty", check=False, timeout=30)
    xml = xml[: xml.rfind("</hierarchy>") + len("</hierarchy>")]
    time.sleep(settle)
    roots = parse_uiautomator(xml)
    root = pick_root(roots, 1080, 2400)
    fmt = fmt or "v1"
    mine = options(build(root, 1080, 2400, covers_for(roots, root), fmt=fmt))
    # newer apps send every format (options_v1 / options_v2); older ones only the live one
    app = t.get("options_" + fmt) or (t["options"] if t.get("option_format", "v1") == fmt else None)
    print(json.dumps({"app": app, "port": mine, "option_format": fmt, "app_option_format": t.get("option_format", "v1"),
                      "equal": app == mine}, ensure_ascii=False))


def _selftest() -> None:
    """The occlusion cases of TargetOcclusionTest.kt on synthetic uiautomator XML (no device): an empty bottom-sheet
    container hides nothing, one with content does; a search-mode bar, an overlay toolbar and a snackbar hide what is
    under them; a later tappable node alone does not."""
    def n(cls, b, *kids, rid="", text="", desc="", click=False):
        return (f'<node class="{cls}" resource-id="{rid}" text="{text}" content-desc="{desc}" clickable="{str(click).lower()}" '
                f'bounds="[{b[0]},{b[1]}][{b[2]},{b[3]}]">' + "".join(kids) + "</node>")

    def btn(label, b):
        return n("android.widget.Button", b, text=label, click=True)

    def labels(xml):
        root = parse_uiautomator("<hierarchy>" + xml + "</hierarchy>")[0]
        return {t["label"] for t in build(root, 1080, 2400)}

    W, H = 1080, 2400
    def feed(*sheet_kids):
        return n("android.widget.FrameLayout", (0, 0, W, H),
                 n("androidx.recyclerview.widget.RecyclerView", (0, 94, W, 2200), btn("Like", (0, 900, 150, 1020)),
                   btn("Comment", (150, 900, 300, 1020)), btn("Share", (300, 900, 450, 1020)),
                   n("android.widget.ImageView", (0, 200, W, 880), desc="Photo by someone", click=True)),
                 n("android.widget.LinearLayout", (0, 2200, W, H), btn("Home", (0, 2200, 216, H)), btn("Search", (216, 2200, 432, H)),
                   btn("Profile", (864, 2200, W, H))),
                 n("android.widget.FrameLayout", (0, 94, W, H), *sheet_kids, rid="com.example.feed:id/bottom_sheet_container"))
    everything = {"Like", "Comment", "Share", "Photo by someone", "Home", "Search", "Profile"}
    assert labels(feed()) == everything, labels(feed())
    assert labels(feed(n("android.widget.FrameLayout", (0, 94, W, H)))) == everything
    assert labels(feed(n("android.widget.FrameLayout", (0, 94, W, H), btn("Close", (0, 100, 200, 220))))) == {"Close"}

    toolbar = n("android.view.ViewGroup", (0, 128, W, 296), n("android.widget.TextView", (42, 169, 216, 254), text="Saved"),
                btn("Filter", (699, 148, 826, 274)), btn("Collections", (826, 148, 953, 274)), btn("More options", (953, 148, W, 274)))
    page = n("android.widget.FrameLayout", (0, 296, W, H), btn("First article", (0, 300, W, 500)))
    def screen(*bar):
        return n("android.widget.FrameLayout", (0, 0, W, H), n("android.widget.FrameLayout", (0, 0, W, H), toolbar, page), *bar)
    assert labels(screen()) == {"Filter", "Collections", "More options", "First article"}
    search = n("android.view.ViewGroup", (0, 0, W, 296), n("android.widget.ImageView", (0, 149, 147, 275), desc="Done", click=True),
               n("android.widget.AutoCompleteTextView", (189, 163, 1059, 258), rid="com.example:id/search_src_text",
                 text="Search saved articles", click=True), rid="com.example:id/action_mode_bar")
    assert labels(screen(search)) == {"Done", "Search saved articles", "First article"}, labels(screen(search))
    selection = n("android.view.ViewGroup", (0, 128, W, 296), n("android.widget.ImageButton", (21, 138, 168, 285), desc="Clear selection", click=True),
                  btn("Delete", (822, 148, 949, 274)), rid="com.example:id/overlayToolbar")
    assert labels(screen(selection)) == {"Clear selection", "Delete", "First article"}
    assert labels(screen(n("android.view.ViewGroup", (0, 0, W, 296), rid="com.example:id/action_mode_bar"))) == \
        {"Filter", "Collections", "More options", "First article"}

    snack = n("android.widget.FrameLayout", (21, 2049, 1059, 2253), n("android.widget.LinearLayout", (42, 2049, 1038, 2253),
              n("android.widget.TextView", (63, 2049, 845, 2253), text="Nothing nearby", rid="com.example:id/snackbar_text"),
              n("android.widget.Button", (866, 2088, 1038, 2214), text="Close", click=True, rid="com.example:id/snackbar_action")))
    assert labels(n("android.widget.FrameLayout", (0, 0, W, H), btn("Search places", (147, 139, 933, 265)),
                    n("android.widget.Button", (891, 2085, 1038, 2232), desc="My location", click=True), snack)) == {"Search places", "Close"}

    player = n("android.widget.FrameLayout", (0, 128, W, 735), n("android.widget.ImageView", (21, 150, 147, 276), desc="Close player", click=True),
               desc="Show player controls", click=True)
    got = labels(n("android.widget.FrameLayout", (0, 0, W, H), player,
                   n("android.view.ViewGroup", (0, 128, W, 296), btn("Search", (848, 148, 975, 274))),
                   n("android.widget.FrameLayout", (0, 296, W, 2105), n("android.view.ViewGroup", (0, 422, W, 936), desc="A video", click=True))))
    assert {"Close player", "Show player controls"} <= got, got
    _format_parity()
    _gaps()
    print("tree_targets selftest: ok (occlusion: empty sheet, search bar, overlay toolbar, snackbar, later tappable node; "
          "option format v1 + v2: target_format_parity.json byte-identical to Targets.kt; harvest gaps: target_gaps.json)")


def _gaps() -> None:
    """app/src/test/resources/target_gaps.json (TargetGapsTest.kt): a floating button half under the navigation bar
    (tapped on its visible part), a Request button per row, rows named by their title, a menu drawn in the window."""
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "test", "resources", "target_gaps.json")
    with open(path, encoding="utf-8") as f:
        fx = json.load(f)
    for c in fx["cases"]:
        root, covers = _fixture_node(c["root"]), [tuple(b) for b in c["covers"]]
        v1 = build(root, c["w"], c["h"], covers, fmt="v1")
        assert options(v1) == c["options_v1"], (c["name"], options(v1))
        assert [t["bounds"] for t in v1] == c["bounds"], (c["name"], [t["bounds"] for t in v1])
        v2 = options(build(root, c["w"], c["h"], covers, fmt="v2"))
        assert v2 == c["options_v2"], (c["name"], v2)


def _fixture_node(o: dict) -> Node:
    """A node of the shared JSON fixtures (keys: cls, id, text, desc, b, click, focus, selected, scroll, rows, draw, kids)."""
    b = o["b"]
    return Node(cls=o["cls"], id=o.get("id") or None, text=o.get("text") or None, desc=o.get("desc") or None,
                left=b[0], top=b[1], right=b[2], bottom=b[3], scrollable=o.get("scroll", False),
                clickable=o.get("click", False), focusable=o.get("focus", False), selected=o.get("selected", False),
                rows=o.get("rows", -1), drawing_order=o.get("draw", 0), children=[_fixture_node(k) for k in o.get("kids", [])])


def _format_parity() -> None:
    """The option format on the synthetic screen of app/src/test/resources/target_format_parity.json (TargetFormatTest.kt
    asserts the same list): row context, column / row ordinals, far left, repeated controls kept, identical twins."""
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "test", "resources", "target_format_parity.json")
    with open(path, encoding="utf-8") as f:
        fx = json.load(f)

    def node(o: dict) -> Node:
        b = o["b"]
        return Node(cls=o["cls"], id=o.get("id") or None, text=o.get("text") or None, desc=o.get("desc") or None,
                    left=b[0], top=b[1], right=b[2], bottom=b[3], scrollable=o.get("scroll", False),
                    clickable=o.get("click", False), focusable=o.get("focus", False), selected=o.get("selected", False),
                    rows=o.get("rows", -1), children=[node(k) for k in o.get("kids", [])])

    for fmt, key in (("v2", "options"), ("v1", "options_v1")):
        got = options(build(node(fx["root"]), fx["w"], fx["h"], fmt=fmt))
        want = fx[key]
        assert got == want, fmt + "\n" + "\n".join(f"{'  ' if g == x else '!='} {g!r} | {x!r}" for g, x in zip(got + [''] * len(want), want + [''] * len(got)))
        assert len(set(got)) == len(got)
    assert options(build(node(fx["root"]), fx["w"], fx["h"])) == fx["options_v1"], "v1 is the default"
    assert [ordinal(k, 200) for k in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111)] + [ordinal(5, 5)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th", "last"]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare with the app's targets op on the current screen")
    ap.add_argument("--selftest", action="store_true", help="run the synthetic occlusion checks (no device)")
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--option-format", choices=["v1", "v2", "v2i"], default="v1",
                    help="target option format (OptionFormat.kt): v1 (default), v2 (row context and rank) or v2i (v2 + indented-list tree context)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
    if a.check:
        _check(1, a.settle, a.option_format)
