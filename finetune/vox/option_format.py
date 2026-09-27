"""Target option text formats (the app's OptionFormat.kt / Targets.kt) for stored screens.

The format rules are NOT re-implemented here: this module imports the app's own Python port, android/suite/tree_targets.py
(byte-identical to Targets.kt on app/src/test/resources/target_format_parity.json, checked by its --selftest), read-only.

  v1  "{label} ({role}, {position})" + ", {k} of {n}" on options that are still identical (the app since 2026-09-27;
      the stored screens were captured when identical options were merged away, so they never contain the suffix).
  v2  "{label}[ · {context}] ({role}, {position}[, {rank}])" (row context and column / row rank).

Exact vs approximate (user decision 2026-09-27, option A):
  * New captures that carry the app's own options_v1 / options_v2 are used as captured (exact).
  * Old captures stored only the v1 option list, its bounds and a FLAT pre-order node list (no hierarchy, no
    visible / focusable / editable flags). reserialize() keeps their target list (so labels keep their indices), computes
    the rank EXACTLY over that list with tree_targets.decorate, and rebuilds the context from a tree nested by bounds
    (flat nodes in pre-order: a node's parent is the nearest earlier node whose box contains it), running
    tree_targets.row_text on it. Such rows are marked v2_approx=True and are never used to score v2.
  * Screens without any node list (vision-built Z Flip screens) get rank but no context (v2_approx="no_tree").
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "android" / "suite"))
import tree_targets as tt  # noqa: E402

NONE_OPTION = tt.NONE_OPTION
ROLES = ("text field", "switch", "tab", "button", "list item", "image", "item")
_V1 = re.compile(r"^(?P<label>.*) \((?P<role>" + "|".join(ROLES) + r"), (?P<pos>" + "|".join(tt.POSITIONS) + r")\)$")


def parse_v1(option: str) -> dict:
    """Old stored v1 option text -> {label, role, position}. Raises on anything else."""
    m = _V1.match(option)
    if not m:
        raise ValueError(f"not a v1 option: {option[:80]!r}")
    return {"label": m["label"], "role": m["role"], "position": m["pos"]}


def _box(b) -> tuple[int, int, int, int]:
    if isinstance(b, str):
        return tuple(int(x) for x in b.split(","))  # "l,t,r,b"
    return tuple(int(x) for x in b)


def tree_from_flat(nodes: list[dict]) -> tt.Node | None:
    """Rebuild a tree from a flat pre-order node list by box nesting. Unknown flags default to the dump's semantics:
    every dumped node is visible; focusable / editable are unknown (False)."""
    if not nodes:
        return None
    built = []
    for n in nodes:
        l, t, r, b = _box(n["bounds"])
        built.append(tt.Node(cls=n.get("cls") or "", id=n.get("id") or None, text=n.get("text") or None, desc=n.get("desc") or None,
                             left=l, top=t, right=r, bottom=b, scrollable=bool(n.get("scroll")), clickable=bool(n.get("click"))))
    root = tt.Node(cls="(root)", id=None, text=None, desc=None, left=-10**6, top=-10**6, right=10**6, bottom=10**6)
    stack = [root]

    def contains(a: tt.Node, c: tt.Node) -> bool:
        return a.left <= c.left and a.top <= c.top and a.right >= c.right and a.bottom >= c.bottom

    for n in built:
        while len(stack) > 1 and not contains(stack[-1], n):
            stack.pop()
        stack[-1].children.append(n)
        stack.append(n)
    return root


def _paths(root: tt.Node):
    """(node, ancestors root-first, excluding the synthetic root) for every node, pre-order."""
    out = []

    def visit(n, path):
        out.append((n, list(path)))
        path.append(n)
        for c in n.children:
            visit(c, path)
        path.pop()

    for c in root.children:
        visit(c, [])
    return out


def reserialize(options: list[str], bounds: list, screen_size, nodes: list[dict] | None, fmt: str,
                root: "tt.Node | None" = None) -> tuple[list[str], dict]:
    """Stored old screen -> option list in `fmt` (same targets, same order, none option last) and info
    {v2_approx, context_from_tree, n_context}. fmt "v1" returns the old text plus the repeat suffix (none occur)."""
    w, h = (int(screen_size[0]), int(screen_size[1])) if screen_size else (1080, 2400)
    assert options and options[-1] == NONE_OPTION, "last option must be the none option"
    tg = options[:-1]
    assert len(bounds) >= len(tg), "bounds must align with the options"
    kept = []
    for o, b in zip(tg, bounds):
        t = parse_v1(o)
        box = list(_box(b))
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        bk = tt.bucket(cx, cy, w, h)
        if tt.POSITIONS[bk] != t["position"]:
            raise ValueError(f"position {t['position']!r} does not match the bounds bucket {tt.POSITIONS[bk]!r}")
        kept.append({**t, "bounds": box, "_b": bk, "_row": None})
    info = {"v2_approx": fmt == "v2", "context_from_tree": False, "n_context": 0}
    if fmt == "v2":
        root = root if root is not None else tree_from_flat(nodes or [])
        if root is None:
            info["v2_approx"] = "no_tree"
        else:
            info["context_from_tree"] = True
            by_box = {}
            for n, path in _paths(root):
                by_box.setdefault((n.left, n.top, n.right, n.bottom), []).append((n, path))
            for t in kept:
                cands = by_box.get(tuple(t["bounds"]), [])
                # the target node: clickable first, then the deepest node with that box
                pick = next(((n, p) for n, p in cands if n.clickable), None) or (cands[-1] if cands else None)
                if pick is not None:
                    t["_row"] = tt.row_text(pick[0], t["label"], pick[1], w, h)
    tt.decorate(kept, w, h, fmt)
    info["n_context"] = sum(1 for t in kept if t.get("context"))
    return [t["option"] for t in kept] + [NONE_OPTION], info


def tree_from_xml(xml: str) -> "tt.Node | None":
    """A uiautomator XML dump (old Z Flip tree captures) -> one root holding the dumped window roots (full hierarchy)."""
    roots = tt.parse_uiautomator(xml)
    if not roots:
        return None
    root = tt.Node(cls="(root)", id=None, text=None, desc=None, left=-10**6, top=-10**6, right=10**6, bottom=10**6)
    root.children = roots
    return root


def flatten(root: tt.Node) -> list[dict]:
    """A tt.Node tree -> the old capture's flat pre-order node list (for measuring the approximation)."""
    out = []
    for n in root.walk():
        out.append({"id": n.id or "", "cls": n.cls, "text": n.text or "", "desc": n.desc or "", "click": n.clickable,
                    "scroll": n.scrollable, "bounds": f"{n.left},{n.top},{n.right},{n.bottom}"})
    return out


def selftest() -> dict:
    """1. tree_targets' own parity selftest (Kotlin == Python, v1 and v2). 2. The approximate path on the parity fixture:
    v1 targets as an old capture would store them + the flattened tree -> v2; rank must match exactly, context is
    reported. 3. parse_v1 round-trips every stored v1 option."""
    import json
    tt._format_parity()
    fx = json.loads((ROOT / "android/app/src/test/resources/target_format_parity.json").read_text())

    def node(o: dict) -> tt.Node:
        b = o["b"]
        return tt.Node(cls=o["cls"], id=o.get("id") or None, text=o.get("text") or None, desc=o.get("desc") or None,
                       left=b[0], top=b[1], right=b[2], bottom=b[3], scrollable=o.get("scroll", False),
                       clickable=o.get("click", False), focusable=o.get("focus", False), selected=o.get("selected", False),
                       rows=o.get("rows", -1), children=[node(k) for k in o.get("kids", [])])

    root = node(fx["root"])
    v1t = tt.build(root, fx["w"], fx["h"], fmt="v1")
    exact_v2 = tt.options(tt.build(root, fx["w"], fx["h"], fmt="v2"))
    # an old capture: identical options merged away, the suffix absent -> use the targets' bare v1 text
    old = [f"{t['label']} ({t['role']}, {t['position']})" for t in v1t] + [NONE_OPTION]
    got, info = reserialize(old, [t["bounds"] for t in v1t], (fx["w"], fx["h"]), flatten(root), "v2")
    rank = lambda o: o.rsplit(", ", 1)[-1] if o.count(",") >= 2 else ""  # noqa: E731
    same = sum(g == x for g, x in zip(got, exact_v2))
    rank_same = sum(rank(g) == rank(x) for g, x in zip(got, exact_v2))
    return {"tree_targets_parity": "ok", "fixture_options": len(exact_v2), "approx_equal": same, "rank_equal": rank_same,
            "diffs": [(g, x) for g, x in zip(got, exact_v2) if g != x], "info": info}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=1, ensure_ascii=False))


# --- exact captures (raw_tree from the app's fuller rawDump) -----------------------------------------------------------

EMU_BARS = [(0, 0, 1080, 128), (0, 2274, 1080, 2400)]   # emulator-5580 status / navigation bars (the app agent's measure)


def tree_from_raw(raw: list[dict]) -> "tt.Node | None":
    """The app's raw_tree (pre-order, depth 'd', full flags) -> a tt.Node tree (the first depth-0 node is the root)."""
    if not raw:
        return None
    stack, root = [], None
    for x in raw:
        l, t, r, b = _box(x["bounds"])
        n = tt.Node(cls=x.get("cls") or "", id=x.get("id") or None, text=x.get("text") or None, desc=x.get("desc") or None,
                    left=l, top=t, right=r, bottom=b, scrollable=bool(x.get("scrollable")), editable=bool(x.get("editable")),
                    focused=bool(x.get("focused")), clickable=bool(x.get("click")), visible=bool(x.get("vis", True)),
                    focusable=bool(x.get("focusable")), selected=bool(x.get("selected")),
                    collection_item=bool(x.get("collection_item")), rows=int(x.get("rows", -1)), cols=int(x.get("cols", -1)))
        d = int(x["d"])
        del stack[d:]
        if d == 0:
            if root is None:
                root = n
            else:   # a second window root: not expected in raw_tree
                return root
        else:
            stack[-1].children.append(n)
        stack.append(n)
    return root


def parity(screen: dict, covers=None) -> dict:
    """Does the Python port rebuild the capture's own options_v1 / options_v2 from its raw_tree? (exact-capture check)"""
    w, h = (json_list(screen["screen_size"]) if screen.get("screen_size") else (1080, 2400))
    root = tree_from_raw(screen.get("raw_tree") or [])
    covers = EMU_BARS if covers is None else covers
    out = {}
    for fmt in ("v1", "v2"):
        got = tt.options(tt.build(root, w, h, covers, fmt=fmt))
        want = screen.get("options_" + fmt)
        out[fmt] = None if want is None else (got == want)
        if want is not None and got != want:
            out[fmt + "_diff"] = [(g, x) for g, x in zip(got, want) if g != x][:3] + ([("len", len(got), len(want))] if len(got) != len(want) else [])
    return out


def json_list(v):
    import json
    v = json.loads(v) if isinstance(v, str) else v
    return int(v[0]), int(v[1])
