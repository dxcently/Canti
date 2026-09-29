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

# jl10: the app's spoken picking now fills Target.context for rows of indented lists from the parent row's label (the
# app code is in flight elsewhere; implemented here from the spec). Opt-in: True applies the rule to every v2
# re-serialisation; real_targets_v2 sets it False for plain `--option-format v2` and True for `v2i`.
INDENT_CONTEXT = True


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
    paths = None
    if fmt == "v2":
        root = root if root is not None else tree_from_flat(nodes or [])
        if root is None:
            info["v2_approx"] = "no_tree"
        else:
            info["context_from_tree"] = True
            paths = _paths(root)
            by_box = {}
            for n, path in paths:
                by_box.setdefault((n.left, n.top, n.right, n.bottom), []).append((n, path))
            for t in kept:
                cands = by_box.get(tuple(t["bounds"]), [])
                # the target node: clickable first, then the deepest node with that box
                pick = next(((n, p) for n, p in cands if n.clickable), None) or (cands[-1] if cands else None)
                if pick is not None:
                    t["_row"] = tt.row_text(pick[0], t["label"], pick[1], w, h)
    tt.decorate(kept, w, h, fmt)
    if INDENT_CONTEXT and fmt == "v2" and paths is not None:
        _apply_indent(kept, paths, w, h)
    info["n_context"] = sum(1 for t in kept if t.get("context"))
    return [t["option"] for t in kept] + [NONE_OPTION], info


INDENT_DP = 16   # jl10: indentation threshold in dp on the app's 411-dp design width


def _cap_context(s: str) -> str:
    """Cap a context the same way tt.row_text does (MAX_CONTEXT_CHARS, ellipsis)."""
    return s if len(s) <= tt.MAX_CONTEXT_CHARS else s[:tt.MAX_CONTEXT_CHARS - 3].rstrip() + "..."


_IDENT_SUFFIX = re.compile(r"^(?:\d+(?:st|nd|rd|th)|last) of \d+$")


def _strip_identical_rank(rank):
    """Undo tt.decorate's final identical-option suffix (", k of n") so the pass can be re-run after the indent rule."""
    if not rank:
        return None
    parts = rank.split(", ")
    if _IDENT_SUFFIX.match(parts[-1]):
        parts = parts[:-1]
        return ", ".join(parts) or None
    return rank


def _identical_pass(kept: list[dict]) -> None:
    """tt.decorate's final identical-option pass, re-run after the indent context is applied (so a now-distinct option
    does not keep a redundant ", k of n"): group by option_text, append "k of n" to identical groups, re-render."""
    groups: dict = {}
    for i, t in enumerate(kept):
        groups.setdefault(tt.option_text(t), []).append(i)
    for g in groups.values():
        if len(g) < 2:
            continue
        for k, i in enumerate(g):
            kept[i]["rank"] = ", ".join(x for x in (kept[i]["rank"], f"{tt.ordinal(k + 1, len(g))} of {len(g)}") if x)
    for t in kept:
        t["option"] = tt.option_text(t)


def _apply_indent(kept: list[dict], root_paths, w: int, h: int) -> None:
    """jl10: strip the identical-option suffix, apply the indent context, then re-run the identical-option pass
    (mirrors tt.decorate's ordering so the indent context participates in the "k of n" grouping)."""
    for t in kept:
        t["rank"] = _strip_identical_rank(t["rank"])
    indent_context(kept, root_paths, w, h)
    _identical_pass(kept)


def indent_context(kept: list[dict], root_paths, w: int, h: int) -> None:
    """jl10 (in place): fill Target.context for kept rows of an INDENTED list from the parent row's label.

    Only a "list item" target may take a parent, and the parent row must also be a "list item" (a). The parent is the
    nearest PRECEDING kept row in reading order (sorted by top, then left) in the SAME immediate-parent container node,
    whose left edge is at least INDENT px smaller and whose row is strictly ABOVE the target. The container must be a
    list container by the port's own test (parent short_cls in LIST_CLASSES / rows>0 / cols>0, or the child
    collection_item); if a flat dump carries no list-class info for it, fall back to >= 3 kept list items (b). A parent
    whose label is generic/unlabeled or equals the child's label is skipped (c). A GRID container (>= 2 kept list items
    in the same row with different lefts) gets no indent context (i). INDENT = INDENT_DP dp =
    round(16 * w / 411) px (42 px at 1080 wide: the app's 411-dp design width, stated assumption). Flat lists are
    untouched, so their text stays byte-identical to v2.

    Sets only `context` (no option render): callers run `_identical_pass` afterwards. `not t.get("context")` means
    "no context from the existing v2 rule" (decorate already filled switch/generic/duplicate contexts)."""
    INDENT = round(INDENT_DP * w / 411)
    by_box: dict = {}
    for n, path in root_paths:
        by_box.setdefault((n.left, n.top, n.right, n.bottom), []).append((n, path))
    node_of, parent_of = [None] * len(kept), [None] * len(kept)
    for i, t in enumerate(kept):
        cands = by_box.get(tuple(t["bounds"]), [])
        pick = next(((n, p) for n, p in cands if n.clickable), None) or (cands[-1] if cands else None)
        if pick is not None:
            node_of[i] = pick[0]
            parent_of[i] = pick[1][-1] if pick[1] else None

    is_row = [t["role"] == "list item" for t in kept]   # (a) only list rows take an indent parent
    container_count: dict = {}
    for i in range(len(kept)):
        if is_row[i] and parent_of[i] is not None:
            container_count[id(parent_of[i])] = container_count.get(id(parent_of[i]), 0) + 1

    def container_ok(i) -> bool:
        n, p = node_of[i], parent_of[i]
        if p is None:
            return False
        if n is not None and n.collection_item:                       # child collection_item: a list row by itself
            return True
        if p.short_cls in tt.LIST_CLASSES or p.rows > 0 or p.cols > 0:   # the port's list-container test
            return True
        return container_count.get(id(p), 0) >= 3                     # (b) flat dump, no list-class info

    grid_container: set = set()   # (i) a container whose kept list items form a multi-column grid
    by_cont: dict = {}
    for i in range(len(kept)):
        if is_row[i] and parent_of[i] is not None:
            by_cont.setdefault(id(parent_of[i]), []).append(i)
    for cid, idxs in by_cont.items():
        for a in range(len(idxs)):
            ia = idxs[a]
            for b in range(a + 1, len(idxs)):
                ib = idxs[b]
                if tt._v_overlap(kept[ia]["bounds"][1], kept[ia]["bounds"][3], kept[ib]["bounds"][1], kept[ib]["bounds"][3]) \
                        and kept[ia]["bounds"][0] != kept[ib]["bounds"][0]:   # same row, different lefts -> a grid column
                    grid_container.add(cid)
                    break
            if cid in grid_container:
                break

    order = sorted(range(len(kept)), key=lambda i: (kept[i]["bounds"][1], kept[i]["bounds"][0], i))
    pos = {i: k for k, i in enumerate(order)}
    for i, t in enumerate(kept):
        if not is_row[i] or t.get("context") or not container_ok(i):
            continue
        if parent_of[i] is not None and id(parent_of[i]) in grid_container:   # (i) no indent inside a grid
            continue
        p = parent_of[i]
        left = t["bounds"][0]
        candidates = []
        for j in order[:pos[i]]:   # preceding kept rows in reading order
            if not is_row[j] or p is None or parent_of[j] is not p:   # same immediate container node only (b)
                continue
            if kept[j]["bounds"][0] <= left - INDENT and kept[j]["bounds"][1] < t["bounds"][1]:   # INDENT less indented, row above
                candidates.append(j)
        parent_row = None
        for j in reversed(candidates):   # nearest first
            lbl = kept[j]["label"].lower()
            if lbl in tt.GENERIC_LABELS or lbl == t["label"].lower():   # (c) skip generic/unlabeled/equal labels
                continue
            parent_row = j
            break
        if parent_row is not None:
            t["context"] = _cap_context(kept[parent_row]["label"])


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
    reported. 3. The jl10 indent rule on vox/fixtures/indent_parity.json (v2i expected byte-for-byte, plain v2 unchanged)
    and the existing flat parity fixture (indent ON vs OFF byte-identical, so flat screens are untouched)."""
    import json
    global INDENT_CONTEXT
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

    # jl10 indent rule: the parity fixture is flat (no indentation), so indent ON/OFF must be byte-identical
    saved = INDENT_CONTEXT
    try:
        INDENT_CONTEXT = False
        flat_off, _ = reserialize(old, [t["bounds"] for t in v1t], (fx["w"], fx["h"]), flatten(root), "v2")
    finally:
        INDENT_CONTEXT = saved
    assert got == flat_off, "indent rule changed a flat screen:\n" + \
        "\n".join(f"  {g!r} | {o!r}" for g, o in zip(got, flat_off) if g != o)

    # jl10 indent fixture: v2i expected byte-for-byte, and plain v2 (indent off) reproduces options_v2
    ifx = json.loads((Path(__file__).resolve().parent / "fixtures" / "indent_parity.json").read_text())
    iroot = node(ifx["root"])
    got_v2i = reserialize_exact(iroot, ifx["w"], ifx["h"])
    assert got_v2i == ifx["options"], "indent_parity v2i mismatch:\n" + \
        "\n".join(f"{'  ' if g == x else '!='} {g!r} | {x!r}" for g, x in zip(got_v2i + [''] * len(ifx["options"]), ifx["options"] + [''] * len(got_v2i)))
    saved = INDENT_CONTEXT
    try:
        INDENT_CONTEXT = False
        got_v2 = reserialize_exact(iroot, ifx["w"], ifx["h"])
    finally:
        INDENT_CONTEXT = saved
    assert got_v2 == ifx["options_v2"], "indent_parity v2 mismatch:\n" + \
        "\n".join(f"{'  ' if g == x else '!='} {g!r} | {x!r}" for g, x in zip(got_v2 + [''] * len(ifx["options_v2"]), ifx["options_v2"] + [''] * len(got_v2)))

    return {"tree_targets_parity": "ok", "fixture_options": len(exact_v2), "approx_equal": same, "rank_equal": rank_same,
            "diffs": [(g, x) for g, x in zip(got, exact_v2) if g != x], "info": info,
            "indent_parity": "ok", "indent_fixture_options": len(ifx["options"]), "flat_unchanged": True}


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


def reserialize_exact(root: "tt.Node | None", w: int, h: int, covers=()) -> list[str]:
    """jl10: the app's raw_tree -> v2i option list. tt.build(fmt="v2") re-derives the targets (the port), then the
    indent rule is applied; the result is marked v2_approx "port+indent" by the caller (never the app's own text).
    Used for single-format ("port") exact captures, whose target list is already the port's tt.build output."""
    targets = tt.build(root, w, h, covers, fmt="v2")
    if INDENT_CONTEXT:
        _apply_indent(targets, _paths(root), w, h)
    return tt.options(targets)


def v2i_from_targets(targets: list[dict], root: "tt.Node | None", w: int, h: int) -> list[str]:
    """jl10: the app's own targets_v2 (label/role/position/bounds[, context, rank, option]) -> v2i option list, KEEPING
    the app's target list (so label/gold indices stay valid) and only adding the indent rule's context. Used for
    "app" exact captures, whose target list the port must not re-derive (tt.build has known gaps there)."""
    kept = []
    for t in targets:
        kept.append({"label": t["label"], "role": t["role"], "position": t["position"], "bounds": list(_box(t["bounds"])),
                     "context": t.get("context"), "rank": t.get("rank"), "option": t.get("option")})
    if INDENT_CONTEXT and root is not None:
        _apply_indent(kept, _paths(root), w, h)
    return [t["option"] for t in kept] + [NONE_OPTION]


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


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="run the parity + jl10 indent selftests")
    ap.parse_args()
    print(json.dumps(selftest(), indent=1, ensure_ascii=False))
