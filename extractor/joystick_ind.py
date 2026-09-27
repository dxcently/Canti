#!/usr/bin/env python3
"""The joystick's on-screen indicators, approved 2026-09-27 as static mockups (the drawing code is the mockups'):
  Cursor B, the chevron trail: a 13-cell pixel ring with a centre dot; while it moves, 1-3 chevrons run ahead of it
    in its heading (8 directions), more when faster; voiced but not moving = four crosshair ticks on the axes;
    stopped = the ring; snapped = corner brackets around the element.
  Face A, the bar, on the Canti badge's screen: the lit reference line; a bar growing up or down in 4 steps with a
    cap at least 2 rows off the line; [----] brackets on the line in the dead zone; an arrowhead poking out past the
    range; a small side pointer for ee (right) / oo (left); the line dashed when not voiced.
Drawn at the approved size, 4 device px per art px (a 2.625 px/dp phone), as RGBA arrays; numpy only, so the
prototype's venv runs it. The badge body comes from brand/tools/canti_sprite.py (it needs pillow and rsvg), so
its frames are rendered once into assets/joystick_badge.npz by this file's main; without that file the prototype
shows the badge's screen alone.

  cd ~/VOX && nix shell --impure --expr '(builtins.getFlake "nixpkgs").legacyPackages.x86_64-linux.python3.withPackages
      (p: [p.numpy p.pillow])' -c bash -c 'PATH=$PATH:$(nix build --no-link --print-out-paths nixpkgs#librsvg)/bin
      python3 extractor/joystick_ind.py'
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BADGES = HERE / "assets" / "joystick_badge.npz"
PX = 4                                    # device px per art px (the badge's)
DEVICE_PX_PER_DP = 2.625                  # 420 dpi
NAVY, MINT = (0x1D, 0x27, 0x57), (0xDD, 0xEB, 0xD3)
GLYPH, GHOST = (0xF2, 0xA3, 0x3A), (0x2A, 0x33, 0x5E)      # screen-only fallback: lit cells, dark (off) cells

# ============================================================================ the cursor (art-px grids)
# A cursor is drawn on a (2R+1)^2 grid of art px, centre (R, R); each cell 0 = clear, 1 = ink (navy), 2 = paper
# (mint-cream). Everything ink gets a one-cell paper outline (8-neighbour), so it reads on light and dark apps.
R = 20
ORDER = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]      # counter-clockwise from east, 45 degrees apart


def grid():
    return np.zeros((2 * R + 1, 2 * R + 1), dtype=np.uint8)


def ring(g, r=4.0, w=1.0):
    for y in range(g.shape[0]):
        for x in range(g.shape[1]):
            d = math.hypot(x - R, y - R)
            if r - w / 2 <= d < r + w / 2:
                g[y, x] = 1


def cursor_base(g):
    """A 13-cell pixel ring with a one-cell centre dot; clear inside, so the target under it shows."""
    ring(g, 6.0)
    g[R, R] = 1


def outline(g):
    ink = g == 1
    p = np.pad(ink, 1)
    o = np.zeros_like(ink)
    h, w = ink.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            o |= p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
    g[(o & ~ink) & (g == 0)] = 2
    return g


def rot(g, d):
    """g is drawn for E (orthogonal) or NE (diagonal); rotate to d (y down)."""
    k = {"E": 0, "N": 1, "W": 2, "S": 3, "NE": 0, "NW": 1, "SW": 2, "SE": 3}[d]
    return np.rot90(g, k)


def chev_E(n):
    """Orthogonal: n two-cell-thick chevrons ahead of the ring (a runway of >>>)."""
    g = grid()
    for i in range(n):
        x0 = R + 8 + 4 * i
        for j, dx in enumerate((0, 1, 2, 1, 0)):
            g[R - 2 + j, x0 + dx] = 1
            g[R - 2 + j, x0 + dx + 1] = 1
    return g


def chev_NE(n):
    """Diagonal: n corner chevrons (a top row and a right column meeting at the outer corner), two cells thick,
    stepping out along the diagonal."""
    g = grid()
    for i in range(n):
        k = 8 + 3 * i
        cx, cy = R + k, R - k
        for t in range(0, 4):
            g[cy, cx - t] = 1
            g[cy + t, cx] = 1
            g[cy + 1, cx - t] = 1 if t < 3 else g[cy + 1, cx - t]
            g[cy + t, cx - 1] = 1 if t < 3 else g[cy + t, cx - 1]
    return g


def cursor(d: str | None = None, n: int = 0, neutral: bool = False) -> np.ndarray:
    """Cursor B: heading d (one of ORDER) with n chevrons, or neutral (voiced, not moving), or plain (stopped)."""
    g = grid()
    if d is not None and n:
        g = rot(chev_NE(n) if len(d) == 2 else chev_E(n), d).copy()
    cursor_base(g)
    if neutral:                           # four notch ticks on the axes: a held crosshair
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            for k in (9, 10):
                g[R + dy * k, R + dx * k] = 1
    return outline(g)


def brackets(l, t, r, b, pad=2, arm=5):
    """Snapped: corner brackets around an element's bounds (device px), on the art grid -> (grid, x, y) with x, y
    the grid's top-left in device px."""
    L, T = (l // PX) - pad, (t // PX) - pad
    Rr, B = -(-r // PX) + pad - 1, -(-b // PX) + pad - 1
    w, h = Rr - L + 3, B - T + 3
    g = np.zeros((h, w), dtype=np.uint8)
    x0, y0, x1, y1 = 1, 1, w - 2, h - 2
    for k in range(arm):
        for (x, y) in ((x0 + k, y0), (x0, y0 + k), (x1 - k, y0), (x1, y0 + k),
                       (x0 + k, y1), (x0, y1 - k), (x1 - k, y1), (x1, y1 - k)):
            g[y, x] = 1
    for (x, y) in ((x0 + 1, y0 + 1), (x1 - 1, y0 + 1), (x0 + 1, y1 - 1), (x1 - 1, y1 - 1)):
        g[y, x] = 1                       # a 2-cell-thick corner knuckle
    outline(g)
    return g, (L - 1) * PX, (T - 1) * PX


def rgba(g: np.ndarray, ink=NAVY, paper=MINT) -> np.ndarray:
    a = np.zeros((*g.shape, 4), dtype=np.uint8)
    a[g == 1] = (*ink, 255)
    a[g == 2] = (*paper, 255)
    return a


# ============================================================================ the badge face (head cells)
H = 28                                    # the v3 badge's head (cells)
REF = 18                                  # the reference row (the middle of the screen's usable rows 13..23)
TOP, BOT = 13, 23
BX0, BX1 = 12, 15                         # the bar's columns (4 wide, on the centre line)


def blank():
    return [["." for _ in range(H)] for _ in range(H)]


def cells(g, x, y):
    if 0 <= y < H and 0 <= x < H:
        g[y][x] = "#"


def tri(g, side):
    """The vowel pointer: a 3-row triangle at the screen's side, pointing out (ee right, oo left)."""
    if side > 0:
        for y, xs in ((REF - 2, (21,)), (REF - 1, (21, 22)), (REF, (21, 22, 23)), (REF + 1, (21, 22)), (REF + 2, (21,))):
            for x in xs:
                cells(g, x, y)
    else:
        for y, xs in ((REF - 2, (6,)), (REF - 1, (5, 6)), (REF, (4, 5, 6)), (REF + 1, (5, 6)), (REF + 2, (6,))):
            for x in xs:
                cells(g, x, y)


def head(lit, ghost, s):
    """Past the range: the bar full to the edge, with a 3-row arrowhead through the edge."""
    edge = TOP if s < 0 else BOT
    for y in range(min(REF, edge), max(REF, edge) + 1):
        for x in range(BX0, BX1 + 1):
            cells(lit, x, y)
    for i, (a, b) in enumerate(((BX0 + 1, BX1 - 1), (BX0, BX1), (BX0 - 1, BX1 + 1), (BX0 - 2, BX1 + 2))):
        y = edge + i if s < 0 else edge - i
        for x in range(BX0 - 3, BX1 + 4):
            if lit[y][x] == "#" and not (a <= x <= b):
                lit[y][x] = "."
        for x in range(a, b + 1):
            cells(lit, x, y)
    y = edge + 4 if s < 0 else edge - 4    # the row under the head is cut, so the head reads apart from the shaft
    for x in range(BX0, BX1 + 1):
        lit[y][x] = "."
        cells(ghost, x, y)


def face(n: int | str | None, vowel: str = "ah") -> tuple[list[str], list[str]]:
    """Face A -> (ghost rows, lit rows). n None = not voiced; 0 = the dead zone; +-1..4 = the bar's step (+ = up);
    'off' / '-off' = past the range, up / down."""
    ghost, lit = blank(), blank()
    voiced = n is not None
    off = isinstance(n, str)
    s = 0 if not voiced or n == 0 else (-1 if (n == "off" or (not off and n > 0)) else 1)   # -1 = up
    for y in range(TOP, BOT + 1):          # ghost: the empty track, and both vowel pointers
        for x in range(BX0, BX1 + 1):
            cells(ghost, x, y)
    for side in (-1, 1):
        tri(ghost, side)
    for x in range(BX0 - 4, BX1 + 5):      # the reference line, 4 cells either side; dashed while not voiced
        if voiced or x % 2 == 0:
            cells(lit, x, REF)
    if voiced and n == 0:                  # dead zone: the line's ends turn up and down into brackets [----]
        for y in (REF - 1, REF + 1):
            for x in (BX0 - 4, BX1 + 4):
                cells(lit, x, y)
    elif voiced and off:
        head(lit, ghost, s)
    elif voiced:
        k = {1: 2, 2: 3, 3: 4, 4: 5}[abs(n)]      # the cap at least 2 rows off the line: never a thick line
        end = REF + s * k
        for y in range(min(REF, end), max(REF, end) + 1):
            for x in range(BX0, BX1 + 1):
                cells(lit, x, y)
        for x in range(BX0 - 1, BX1 + 2):         # the live marker: a cap 2 wider than the bar
            cells(lit, x, end)
    if voiced and vowel != "ah":
        tri(lit, 1 if vowel == "ee" else -1)
    return ["".join(r) for r in ghost], ["".join(r) for r in lit]


FACE_KEYS = [None, 0, 1, 2, 3, 4, -1, -2, -3, -4, "off", "-off"]


def key(n, vowel: str) -> str:
    return "idle" if n is None else f"{n}|{vowel}"


def screen_only(n, vowel: str) -> np.ndarray:
    """The fallback without the badge frames: the face's cells alone on a navy square (RGBA, H x H)."""
    ghost, lit = face(n, vowel)
    a = np.zeros((H, H, 4), dtype=np.uint8)
    a[3:26, 3:26] = (*NAVY, 255)
    for y in range(H):
        for x in range(H):
            if lit[y][x] == "#":
                a[y, x] = (*GLYPH, 255)
            elif ghost[y][x] == "#":
                a[y, x] = (*GHOST, 255)
    return a


def load_badges() -> dict[str, np.ndarray] | None:
    if not BADGES.exists():
        return None
    with np.load(BADGES) as z:
        return {k: z[k] for k in z.files}


# ============================================================================ from the mover's state

def heading(dx: float, dy: float) -> str:
    """(dx, dy) with y down -> one of 8 headings."""
    a = math.degrees(math.atan2(-dy, dx)) % 360
    return ORDER[int((a + 22.5) // 45) % 8]


def chevrons(speed: float, spec: dict) -> int:
    """1-3 chevrons: thirds of the speed ramp (start_dp_s .. max_dp_s)."""
    sp = spec["speed"]
    f = (speed - sp["start_dp_s"]) / (sp["max_dp_s"] - sp["start_dp_s"])
    return 1 + int(min(2, max(0, f * 3)))


def bar_step(off: float, dead: float, full: float, past: int = 0) -> int | str:
    """The bar's step from the real vertical offset: 0 inside the dead zone, then 4 equal steps up to full speed
    (+ = up). past = +-1 when the pitch is outside the person's range: the arrowhead, that way."""
    if past:
        return "off" if past > 0 else "-off"
    a = abs(off)
    if a < dead:
        return 0
    n = 1 + int(min(3, (a - dead) / max(1e-6, full - dead) * 4))
    return n if off > 0 else -n


# ============================================================================ images for Tk (no pillow)

def scale(a: np.ndarray, k: float) -> np.ndarray:
    """Nearest-neighbour resize by k (the prototype shows 1080 px phones at 360 px: 4 device px = 1.33 px)."""
    h, w = a.shape[:2]
    H2, W2 = max(1, round(h * k)), max(1, round(w * k))
    ys = np.minimum(h - 1, (np.arange(H2) / k).astype(int))
    xs = np.minimum(w - 1, (np.arange(W2) / k).astype(int))
    return a[ys][:, xs]


def png(a: np.ndarray) -> bytes:
    """RGBA uint8 -> PNG bytes (Tk's PhotoImage reads PNG with alpha)."""
    h, w = a.shape[:2]
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ============================================================================ the badge frames (needs pillow + rsvg)

def main() -> None:
    import sys
    sys.path.insert(0, str(HERE.parent / "brand" / "tools"))
    import canti_sprite as cs
    cs.configure("v3")
    assert cs.HEAD == H, cs.HEAD
    frames = {}
    for n in FACE_KEYS:
        for v in (("ah",) if n is None else ("ah", "ee", "oo")):
            ghost, lit = face(n, v)
            f = cs.Face((ghost, 0, 0, "off"), (lit, 0, 0, "glyph"))
            voiced = n is not None
            frames[key(n, v)] = cs.frame(f, "orange" if voiced else "dull", halo=voiced,
                                         lights="orange" if voiced else "dim", ant=(-30, 0), bead="rest")
    x0, y0, x1, y1 = cs.crop_box(list(frames.values()))
    BADGES.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(BADGES, **{k: np.ascontiguousarray(v[y0:y1, x0:x1]) for k, v in frames.items()})
    print(f"wrote {BADGES} ({len(frames)} frames, {x1 - x0} x {y1 - y0} art px)")


if __name__ == "__main__":
    main()
