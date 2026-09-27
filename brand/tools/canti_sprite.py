#!/usr/bin/env python3
"""The floating badge's character: a small pixel robot, the app icon's hooded-screen head on a jointed mechanical body
(inspired by Canti, not a likeness), posed per state and rendered through the stipple pipeline (tools/stipple.py).

How a frame is made:
  * The head IS the stipple icon: stipple.icon_raster() with one cell per art px (the icon's 512 units = HEAD px),
    cut to a rounded head. Hand-placed overrides where the automatic render turns to mush at this size: flat glass
    (the icon's glass dither reads as teeth), a solid lens shine, an unbroken gold trim, a bigger pixel lamp (signal
    colour, dotted halo), and the face content: crisp glyphs (crescent eyes, arrows, ...) in scanline rows (lit
    rows, dim rows), as on the icon.
  * The body is a vector rig (collar, boxy torso, shoulder blocks with lights, two angular chest plates, red waist
    trim, pelvis with hip lights, legs with knee joints, boots; arms = upper arm, elbow joint, forearm, a flat-topped
    slate mitt; an antenna on the hood's corner). A pose sets the arm angles (multiples of 45 degrees, so limbs stay
    clean pixel lines), the antenna's two joint angles (its spring / follow-through), a head bob and a hop. Each part
    is a flat fill plus a soft top-light gradient in its own coordinates, rendered supersampled; a part is the cells
    it covers more than half of, and its tones come from stipple.surface_tones (per-surface luminance -> 4x4 Bayer
    dither between 2-3 tones). Parts are composited in depth order, each with a one-cell ink outline; inset details
    (plates, lights) have none. The antenna rod is a one-cell pixel line along the rig's segments.
  * Whole cells only: no anti-aliasing, no fades, no random.

Two sizes (the same footprint on a phone, ~80 dp): "38" (38-px head, drawn at 3 device px per art px on a 2.625x
phone, the stipple icon's dot there) and "28" (28-px head at 4 device px: chunkier pixels). The rig is designed at
38 and scaled for 28; the pixel overrides and glyphs are drawn for each.
The default, "v3", is the 28 head on a chibi body (BODY_V3: squat torso, no legs, small shoulder blocks, stub arms;
34x47 frames). "v3a" is the earlier v3 body (broad shoulder blocks, 4x4 mitts; 40x47), kept to reproduce that sheet.

Outputs:
  android [SIZE]       ../ui/assets/badge/canti_badge.png + canti_badge.json (1x sheet + manifest; the Android
                       badge reads them from the APK's flutter_assets/)
  preview DIR [SIZE]   previews into DIR (contact sheet, GIFs, phone mock, silhouette, outline check)
  compare DIR OLD.png  both sizes side by side + the old sprite, at their real device pixels

From ~/VOX (needs numpy, pillow and rsvg-convert, as stipple.py):
  nix shell --impure --expr '(builtins.getFlake "nixpkgs").legacyPackages.x86_64-linux.python3.withPackages
      (p: [p.numpy p.pillow])' -c bash -c 'PATH=$PATH:$(nix build --no-link --print-out-paths nixpkgs#librsvg)/bin
      python3 brand/tools/canti_sprite.py preview /tmp/badge 38'
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stipple as st  # noqa: E402

VOX = os.path.dirname(os.path.dirname(HERE))
ASSETS = os.path.join(VOX, "ui", "assets", "badge")   # the one copy: the app header and (via flutter_assets) the badge

INK, TEAL, TEAL_SHADE, TEAL_LIGHT, TEAL_DEEP = st.INK, st.TEAL, st.TEAL_SHADE, st.TEAL_LIGHT, st.TEAL_DEEP
NAVY, SLATE, MINT, GLOW = st.NAVY, st.SLATE, st.MINT, st.GLOW
ORANGE, YELLOW, RED = st.ORANGE, st.YELLOW, st.RED
GLOW_DIM = "#58969B"
SLATE_LIGHT = "#56679A"
GOLD = "#F4C84A"
BRIM_SHADOW = "#171B33"
# body lights: they repeat the head lamp while it signals (hearing, pending, error), otherwise sit unlit
LIGHTS = {  # rim, body, highlight
    "dim": ("#5E4228", "#7A5530", "#7A5530"),
    "orange": ("#D98A22", ORANGE, "#FFF1CF"),
    "yellow": ("#D4A72C", YELLOW, "#FFF6D6"),
    "red": ("#A8312B", RED, "#FFD9D6"),
}
LAMP_COLOURS = {  # bulb, shade, highlight, specular, halo dots
    "orange": (ORANGE, "#D98A22", "#FFF1CF", "#FFFFFF", "#C9C470"),
    "yellow": (YELLOW, "#D4A72C", "#FFF6D6", "#FFFFFF", "#D6D06A"),
    "red": (RED, "#A8312B", "#FFD9D6", "#FFFFFF", "#B0806A"),
    "dull": ("#7A5530", "#5E4228", "#8E6A45", "#8E6A45", None),
}
BEADS = {  # the antenna's tip bead: neutral (never a signal colour); it brightens to screen-glow on a hum
    "rest": [MINT, MINT, MINT, "#B5C1B3"],
    "pulse": ["#F4FFFB", GLOW, GLOW, GLOW_DIM],
    "off": [SLATE, SLATE, SLATE, NAVY],
}
TEAL_TONES = ([TEAL_SHADE, TEAL, TEAL_LIGHT], 1, (0.05, 0.045, 0.25))   # stipple's "body" surface
DEEP_TONES = ([TEAL_DEEP, TEAL_SHADE, TEAL], 1, (0.06, 0.05, 0.25))
SLATE_TONES = ([NAVY, SLATE, SLATE_LIGHT], 1, (0.05, 0.05, 0.25))
MINT_TONES = (["#B5C1B3", MINT, "#F4FFFB"], 1, (0.06, 0.05, 0.25))
RED_TONES = (["#A8312B", RED], 1, (0.05, 1.0, 0.25))
HEAD_SHAPE = ("M120 0 H392 A120 120 0 0 1 512 120 V432 A80 80 0 0 1 432 512 H80 A80 80 0 0 1 0 432 V120 "
              "A120 120 0 0 1 120 0 Z")


def rgb(h):
    return st.hexrgb(h)


def glyph(s):
    return s.strip("\n").split("\n")


def fliph(g):
    return [r[::-1] for r in g]


def flipv(g):
    return g[::-1]


def transpose(g):
    return ["".join(g[j][i] for j in range(len(g))) for i in range(len(g[0]))]


# ------------------------------------------------------------------------------------------------ the two sizes

GLYPHS_38 = dict(
    EYE_L=glyph("""
..####..
.######.
###..###
##....##
.......#
"""),             # the left eye; its inner tip hangs a row lower: the icon's inward tilt
    EYE_HALF_L=glyph("""
........
........
.######.
###..###
.......#
"""),
    EYE_SHUT_L=glyph("""
........
........
........
########
"""),
    EYE_SLEEP_L=glyph("""
#......#
.######.
"""),
    EYE_ROUND=glyph("""
.####.
######
######
######
######
.####.
"""),
    EYE_SQUINT_L=glyph("""
##......
..###...
.....##.
..###...
##......
"""),
    RETICLE_WIDE=glyph("""
###...###
#.......#
#.......#
....#....
...###...
....#....
#.......#
#.......#
###...###
"""),
    RETICLE_TIGHT=glyph("""
.........
.##...##.
.#.....#.
....#....
...###...
....#....
.#.....#.
.##...##.
.........
"""),
    ARROW_UP=glyph("""
....#....
...###...
..#####..
.#######.
#########
...###...
...###...
...###...
...###...
"""),
    CHEVRON_UP=glyph("""
....#....
...###...
..##.##..
.##...##.
##.....##
"""),
    HOUSE=glyph("""
.....#.....
....###....
...#####...
..#######..
.#########.
###########
.##.....##.
.##.###.##.
.##.###.##.
.##.###.##.
"""),
    Z_BIG=glyph("""
#####
...#.
..#..
.#...
#####
"""),
    Z_SMALL=glyph("""
###
.#.
###
"""),
    EYE_FLAT_L=glyph("""
......
######
"""),       # ignored: flat, level eyes (not the blink's shut line: that sits lower)
    MOUTH_WAVY=glyph("""
.#...#.
#.#.#.#
"""),
    EYE_DROWSY_L=glyph("""
........
########
.######.
"""),       # tap-to-wake: a heavy flat lid over the lower half of the eye (drowsy, not shut: that is paused)
    TAP=glyph("""
#####..###..####.
..#...#...#.#...#
..#...#...#.#...#
..#...#####.####.
..#...#...#.#....
..#...#...#.#....
..#...#...#.#....
"""),       # tap-to-wake: the face screen asks for a tap
    DOT=["#"],
)

GLYPHS_28 = dict(
    EYE_L=glyph("""
.####.
##..##
#....#
.....#
"""),
    EYE_HALF_L=glyph("""
......
.####.
##..##
.....#
"""),
    EYE_SHUT_L=glyph("""
......
......
######
"""),
    EYE_SLEEP_L=glyph("""
#....#
.####.
"""),
    EYE_ROUND=glyph("""
.##.
####
####
.##.
"""),
    EYE_SQUINT_L=glyph("""
##...
..##.
....#
..##.
##...
"""),
    RETICLE_WIDE=glyph("""
##...##
#.....#
...#...
..###..
...#...
#.....#
##...##
"""),
    RETICLE_TIGHT=glyph("""
.......
.##.##.
.#...#.
...#...
.#...#.
.##.##.
.......
"""),
    ARROW_UP=glyph("""
...#...
..###..
.#####.
#######
..###..
..###..
..###..
"""),
    CHEVRON_UP=glyph("""
...#...
..###..
.##.##.
##...##
"""),
    HOUSE=glyph("""
....#....
...###...
..#####..
.#######.
#########
.##...##.
.##.#.##.
.##.#.##.
"""),
    Z_BIG=glyph("""
####
..#.
.#..
####
"""),
    Z_SMALL=glyph("""
###
.#.
###
"""),
    EYE_FLAT_L=glyph("""
####
"""),
    MOUTH_WAVY=glyph("""
.#.#.
#.#.#
"""),
    EYE_DROWSY_L=glyph("""
......
######
.####.
"""),       # tap-to-wake: a heavy flat lid over the lower half of the eye (drowsy, not shut: that is paused)
    TAP=glyph("""
#####..###..####.
..#...#...#.#...#
..#...#...#.#...#
..#...#####.####.
..#...#...#.#....
..#...#...#.#....
..#...#...#.#....
"""),       # tap-to-wake: the face screen asks for a tap
    DOT=["#"],
)

# The body's proportions, in rig units (38-scale art px; origin at the neck: x 0 = the centre line, y 0 = the head's
# bottom edge). Each part is (y0, y1, ...) as body_layers reads it; inset parts get no ink ring of their own (on a
# short body the rings of stacked bands read as stripes); hip_over_waist draws the hip lights after the waist band.
BODY_V2 = dict(
    collar=(-2, 3), torso=(1, 14, 11, 9), plates=(4, 9), waist=(13, 16, 10), pelvis=(15, 20, 9, 7),
    hip=(-5, 18, 1.3), legs=(18, 26, -6, -2), knee=(21, 23), boots=(25, 29, -9, -1), inset=(), hip_over_waist=False,
    shoulder=(-17, 1, -9, 9), light=(-13, 5, 2.0), pivot=(-13, 5), arm=(6.0, 5.0),   # arm: upper, fore length
)
# Optional arm / shoulder sizes (rig units; the defaults are BODY_V2's): upper_w, fore_w = half widths of the upper arm
# and forearm (2.0, 1.75), elbow_r = the elbow joint's radius (2.1; 0 = none), mitt = (mitt size, thumb length,
# pointing-finger length) (6, 3, 5), shoulder_r = the shoulder blocks' corner radius (1.2).
# v3a: v1's head-to-body ratio (v1: a 10-row body under a 26-row head; here 12 rows under the 30-row head) and height:
# a squat torso, no legs (boots straight under the pelvis), stubby arms. Its shoulder blocks (5x4 cells at the 28
# head) and 4x4 mitts stick out nearly as wide as the head: bulky.
BODY_V3A = dict(
    collar=(-2, 2), torso=(0.5, 7.5, 10, 8.5), plates=(2, 5.5), waist=(7, 9.5, 9), pelvis=(9, 11.5, 7.5, 6),
    hip=(-4, 10.3, 1.0), legs=None, knee=None, boots=(11, 15, -8, -1.4), inset=("pelvis",), hip_over_waist=True,
    shoulder=(-15.5, 0.5, -8.5, 7), light=(-12, 3.75, 1.7), pivot=(-12, 3.75), arm=(3.0, 2.6),
)
# v3 (the default): v3a with smaller shoulder blocks (3x3 cells, a one-cell light) and thinner arms with 3-cell mitts,
# toward v1's chibi silhouette: the body spans 20 cells under the 30-cell head (v3a 24).
BODY_V3 = dict(
    BODY_V3A, shoulder=(-12.5, 1, -7.5, 5.5), light=(-10.18, 3.39, 0.9), pivot=(-10.18, 3.39), arm=(2.8, 2.6),
    upper_w=1.5, fore_w=1.4, elbow_r=1.5, mitt=(4.5, 2.5, 5), shoulder_r=1.0,
)

PROFILES = {
    "38": dict(
        HEAD=38, N=80, HEAD_X=21, HEAD_Y=9, U=1.0, PX=3, ART_PX_DP=8 / 7, glyphs=GLYPHS_38,
        # lamp (s socket, o bulb, d shade, h highlight, w specular), its top-left head cell and halo ring radii
        LAMP_PIX=[".sssss.", "sswhoss", "shoooos", "soooods", "sooodds", "ssoddss", ".sssss."],
        LAMP_AT=(24, 4), HALO_R=(4.5, 6.0),
        SHINE=[(16, 15, 22, MINT), (16, 18, 19, "#F4FFFB"), (17, 17, 20, GLOW_DIM)],  # row, x0, x1, colour
        TRIM_MIN_ROW=10,
        MOUNT=(1, 3, 3, 3),                 # antenna bolt: head x, y, w, h
        ANT_BASE=(2.0, 4.0), ANT_LEN=(4.6, 4.2),
        EYE_Y=21, EYE_LX=9, EYE_RX=21, EYE_W=8, FACE_CY=25, SCREEN_BOTTOM=31,
        DOTS=[(15, 29), (18, 29), (21, 29)], Z_SMALL_AT=(28, 20), Z_BIG_AT=(26, 17),
        STEP=3, STREAM=6, BARS=[5, 4],
        EYE_DY=dict(hear=-2, round=-2, reticle=-3, sleep=3, squint=-1),
        BODY=BODY_V2, ANT="corner",
    ),
    "28": dict(
        HEAD=28, N=60, HEAD_X=16, HEAD_Y=7, U=28 / 38, PX=4, ART_PX_DP=32 / 21, glyphs=GLYPHS_28,
        LAMP_PIX=[".sss.", "swhos", "shoos", "sodds", ".sss."],
        LAMP_AT=(18, 3), HALO_R=(3.4, 4.6),
        SHINE=[(12, 11, 16, MINT), (12, 13, 14, "#F4FFFB")],
        TRIM_MIN_ROW=7,
        MOUNT=(0, 2, 3, 2),
        ANT_BASE=(1.5, 3.0), ANT_LEN=(3.6, 3.2),
        EYE_Y=16, EYE_LX=7, EYE_RX=15, EYE_W=6, FACE_CY=19, SCREEN_BOTTOM=22,
        DOTS=[(10, 21), (13, 21), (16, 21)], Z_SMALL_AT=(20, 15), Z_BIG_AT=(19, 14),
        STEP=2, STREAM=5, BARS=[4, 3],
        EYE_DY=dict(hear=-2, round=-1, reticle=-2, sleep=2, squint=-1),
        BODY=BODY_V2, ANT="corner",
    ),
}
# v3 (the default): the 28 head and pixel size on v1's proportions, the antenna a mast on the crown's centre
PROFILES["v3"] = dict(PROFILES["28"], HEAD_Y=8, BODY=BODY_V3, ANT="mast",
                      POSES={"push": (90, 90, False)})   # stubby forearms: push with the mitts up beside the head
PROFILES["v3a"] = dict(PROFILES["v3"], BODY=BODY_V3A)     # the earlier v3 body, for the record
DEFAULT_SIZE = "v3"
P = {}
G = {}
N = HEAD = HEAD_X = HEAD_Y = HB = CX = 0
GB = GH = None
HIRES = 1024                 # supersampling render size for the body parts (13-17 px per art px)


def configure(size):
    """Select a size profile: sets the frame grid, the head grid and the glyph set; clears the caches."""
    global P, G, N, HEAD, HEAD_X, HEAD_Y, HB, CX, GB, GH, SHOULDER, UPPER, FORE
    P = PROFILES[size]
    SHOULDER, (UPPER, FORE) = P["BODY"]["pivot"], P["BODY"]["arm"]
    G = dict(P["glyphs"])
    G["ARROW_LEFT"] = transpose(G["ARROW_UP"])
    G["ARROW_RIGHT"] = fliph(G["ARROW_LEFT"])
    G["ARROW_DOWN"] = flipv(G["ARROW_UP"])
    N, HEAD, HEAD_X, HEAD_Y = P["N"], P["HEAD"], P["HEAD_X"], P["HEAD_Y"]
    CX = HEAD_X + HEAD // 2       # the body's centre line (a whole-cell line: the rig mirrors onto the grid)
    HB = HEAD_Y + HEAD            # the head's bottom edge
    GB = st.Grid(512.0 / N, 0.0, 512.0, hires=HIRES)       # body grid: 512 units <-> N art px
    GH = st.Grid(512.0 / HEAD, 0.0, 512.0)                 # head grid: the icon's own units
    _HEADS.clear()
    _PARTS.clear()
    STATES.clear()
    EXTRA.clear()


# ------------------------------------------------------------------------------------------------ the head

_HEADS = {}


def head_base(lamp="orange", halo=True, off=False):
    """(rgb HEAD x HEAD, mask, screen) before the face content. lamp: orange / yellow / red / dull.
    The stipple icon's head (its off render: no eye glow, no halo), then the pixel overrides."""
    key = (lamp, halo, off)
    if key in _HEADS:
        return _HEADS[key]
    if "src" not in _HEADS:
        _HEADS["src"] = st.icon_raster("off", 512.0 / HEAD, 512.0 / HEAD)
    img, owner = _HEADS["src"]
    img = img.copy()
    mask = st.cells_of(f'<path d="{HEAD_SHAPE}"/>', GH)
    screen = np.isin(owner, ["glass", "shadow"]) & mask
    # the screen: flat glass under a hard brim shadow (the icon's glass dither reads as teeth at this size)
    img[owner == "glass"] = rgb(NAVY)
    img[owner == "shadow"] = rgb(BRIM_SHADOW)
    if not off:
        for y, x0, x1, c in P["SHINE"]:
            img[y, x0:x1 + 1] = rgb(c)
    # the gold trim: one unbroken pixel line a cell above the brim's lower edge
    hood = owner == "hood"
    prev = None
    for x in range(HEAD):
        ys = np.nonzero(hood[:, x])[0]
        if not len(ys) or ys.max() < P["TRIM_MIN_ROW"] or not mask[ys.max(), x]:
            prev = None
            continue
        yb = ys.max()
        img[yb, x] = rgb(TEAL)
        img[yb - 1, x] = rgb(GOLD)
        if prev is not None and abs(prev - (yb - 1)) > 1:        # keep the line 8-connected on steep steps
            lo, hi = sorted((prev, yb - 1))
            for y in range(lo + 1, hi):
                img[y, x if prev < yb - 1 else x - 1] = rgb(GOLD)
        prev = yb - 1
    # the lamp
    lx, ly = P["LAMP_AT"]
    o, d, h, w, hc = LAMP_COLOURS["dull" if off else lamp]
    pal = {"s": TEAL_SHADE, "o": o, "d": d, "h": h, "w": w}
    pix = P["LAMP_PIX"]
    for j, row in enumerate(pix):
        for i, ch in enumerate(row):
            if ch != ".":
                img[ly + j, lx + i] = rgb(pal[ch])
    if halo and hc and not off:
        c0 = (len(pix) - 1) / 2
        r0, r1 = P["HALO_R"]
        for y in range(HEAD):
            for x in range(HEAD):
                r = math.hypot(x - lx - c0, y - ly - c0)
                if r0 <= r < r1 and (x + y) % 2 == 0 and owner[y, x] in ("hood", "crown") and mask[y, x] \
                        and not np.allclose(img[y, x], rgb(GOLD)):
                    img[y, x] = rgb(hc)
    _HEADS[key] = (img, mask, screen)
    return _HEADS[key]


# ------------------------------------------------------------------------------------------------ the face

class Face:
    """Screen content: (glyph, x, y, style) in head cells; style "glyph" (lit/dim scanlines) or "off" (dark)."""

    def __init__(self, *items):
        self.items = list(items)

    def __add__(self, other):
        return Face(*(self.items + other.items))


def eyes(gl, dy=0, gr=None, style="glyph"):
    gr = gr if gr is not None else fliph(gl)
    w, ew, y = len(gl[0]), P["EYE_W"], P["EYE_Y"] + dy
    return Face((gl, P["EYE_LX"] + (ew - w) // 2, y, style), (gr, P["EYE_RX"] + (ew - w) // 2, y, style))


def centred(g, dx=0, dy=0):
    return Face((g, (HEAD - len(g[0])) // 2 + dx, P["FACE_CY"] - len(g) // 2 + dy, "glyph"))


def at(g, x, y):
    return Face((g, x, y, "glyph"))


def bars(heights):
    items = []
    x0 = (HEAD - (2 * len(heights) - 1)) // 2
    for i, h in enumerate(heights):
        items.append((["#"] * h, x0 + 2 * i, P["SCREEN_BOTTOM"] - h + 1, "glyph"))
    return Face(*items)


def draw_face(img, screen, face):
    for g, gx, gy, style in face.items:
        for j, row in enumerate(g):
            for i, ch in enumerate(row):
                x, y = gx + i, gy + j
                if ch != "#" or not (0 <= x < HEAD and 0 <= y < HEAD) or not screen[y, x]:
                    continue
                if style == "off":
                    img[y, x] = rgb("#262E5E" if y % 2 == 0 else "#1A1F42")
                else:
                    img[y, x] = rgb(GLOW if y % 2 == 0 else GLOW_DIM)


# ------------------------------------------------------------------------------------------------ the body rig

def f(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


def box(x0, y0, x1, y1, r=(0.5, 0.5, 0.5, 0.5)):
    """A box with a radius per corner (top-left, top-right, bottom-right, bottom-left)."""
    a, b, c, d = r
    return (f'<path d="M{f(x0 + a)} {f(y0)} H{f(x1 - b)} Q{f(x1)} {f(y0)} {f(x1)} {f(y0 + b)} V{f(y1 - c)} '
            f'Q{f(x1)} {f(y1)} {f(x1 - c)} {f(y1)} H{f(x0 + d)} Q{f(x0)} {f(y1)} {f(x0)} {f(y1 - d)} V{f(y0 + a)} '
            f'Q{f(x0)} {f(y0)} {f(x0 + a)} {f(y0)} Z"/>')


def poly(pts, r=0.6):
    """A polygon with small rounded corners: hard edges, turned corners."""
    n = len(pts)
    d = []
    for i in range(n):
        p0, p1, p2 = np.array(pts[i - 1], float), np.array(pts[i], float), np.array(pts[(i + 1) % n], float)
        a = p1 + (p0 - p1) / np.linalg.norm(p0 - p1) * r
        b = p1 + (p2 - p1) / np.linalg.norm(p2 - p1) * r
        d.append(("M" if i == 0 else "L") + f"{f(a[0])} {f(a[1])} Q{f(p1[0])} {f(p1[1])} {f(b[0])} {f(b[1])}")
    return f'<path d="{" ".join(d)} Z"/>'


def soft(shape, base, y0, y1, x0=None, x1=None):
    """A shape in its flat base colour plus a soft top light / bottom shade (and left light / right shade), as
    gradients in the shape's own coordinates. Rendered supersampled, then stippled by surface_tones."""
    gid = f"g{abs(hash((shape, base, y0, y1, x0, x1))) % 10**9}"
    s = shape.replace("<path ", '<path fill="{}" ').replace("<circle ", '<circle fill="{}" ')
    out = (f'<defs><linearGradient id="{gid}v" gradientUnits="userSpaceOnUse" x1="0" y1="{f(y0)}" x2="0" y2="{f(y1)}">'
           f'<stop offset="0" stop-color="{MINT}" stop-opacity="0.34"/><stop offset="0.35" stop-color="{MINT}" stop-opacity="0"/>'
           f'<stop offset="0.62" stop-color="{INK}" stop-opacity="0"/><stop offset="1" stop-color="{INK}" stop-opacity="0.30"/>'
           f'</linearGradient>')
    if x0 is not None:
        out += (f'<linearGradient id="{gid}h" gradientUnits="userSpaceOnUse" x1="{f(x0)}" y1="0" x2="{f(x1)}" y2="0">'
                f'<stop offset="0" stop-color="{MINT}" stop-opacity="0.12"/><stop offset="0.3" stop-color="{MINT}" stop-opacity="0"/>'
                f'<stop offset="0.8" stop-color="{INK}" stop-opacity="0"/><stop offset="1" stop-color="{INK}" stop-opacity="0.18"/>'
                f'</linearGradient>')
    out += "</defs>" + s.format(base) + s.format(f"url(#{gid}v)")
    if x0 is not None:
        out += s.format(f"url(#{gid}h)")
    return out


def rig(svg, mirror=False):
    """Place rig-space SVG (38-scale art px, origin at the neck: centre line x 0, the head's bottom edge y 0) in the
    frame; mirror = the right-hand copy."""
    m = " scale(-1 1)" if mirror else ""
    return f'<g transform="translate({CX} {HB}) scale({f(P["U"])}){m}">{svg}</g>'


_PARTS = {}


def part(svg, tones=None, flat=None):
    """Render one part (SVG in frame art px). -> (mask N x N, rgb N x N x 3): the cells it covers more than half of,
    toned by stipple.surface_tones (tones = (colours, base index, shade)) or one flat colour."""
    key = (svg, str(tones), flat)
    if key in _PARTS:
        return _PARTS[key]
    doc = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {N} {N}">{svg}</svg>'
    im = st.rsvg(doc, HIRES)
    a = im[..., 3]
    cov, _ = GB.cell_mean(a, np.ones(a.shape, dtype=bool))
    mask = cov > 0.5
    if not mask.any() and cov.max() > 0:
        mask = cov == cov.max()
    out = np.zeros((N, N, 3))
    if flat:
        out[:] = rgb(flat)
    else:
        cols, base, shade = tones
        L = st.lum(im[..., :3])
        tone = st.surface_tones(GB, L, a > 0.5, len(cols), base, shade, ref=float(st.lum(rgb(cols[base]))))
        for ti, c in enumerate(cols):
            out[tone == ti] = rgb(c)
    _PARTS[key] = (mask, out)
    return _PARTS[key]


def shifted(p, dx, dy):
    m, c = p
    if dx == 0 and dy == 0:
        return p
    m2, c2 = np.zeros_like(m), np.zeros_like(c)
    ys, ye, xs, xe = max(0, dy), N + min(0, dy), max(0, dx), N + min(0, dx)
    m2[ys:ye, xs:xe] = m[ys - dy:ye - dy, xs - dx:xe - dx]
    c2[ys:ye, xs:xe] = c[ys - dy:ye - dy, xs - dx:xe - dx]
    return m2, c2


def light_part(x, y, r, colour, mirror=False):
    """A round body light: a pixel disc, its rim below-right, one highlight cell top-left."""
    rim, body, hi = LIGHTS[colour]
    m, _ = part(rig(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}"/>', mirror), flat=body)
    c = np.zeros((N, N, 3))
    c[m] = rgb(body)
    ys, xs = np.nonzero(m)
    if len(ys) > 4:
        for yy, xx in zip(ys, xs):
            if not m[min(yy + 1, N - 1), xx] or not m[yy, min(xx + 1, N - 1)]:
                c[yy, xx] = rgb(rim)
    top = ys.min()
    c[top, xs[ys == top].min()] = rgb(hi)
    return m, c


def body_layers(lights="dim"):
    """The static body behind the arms, back to front: (part, outline?). Rig coordinates (38-scale, whole cells),
    proportions from the profile's BODY table."""
    b = P["BODY"]
    ring = lambda name: name not in b["inset"]
    L = []
    by0, by1, bx0, bx1 = b["boots"]
    for mir in (False, True):  # boots, legs, knee joints (left, then mirrored right)
        L.append((part(rig(soft(box(bx0, by0, bx1, by1, (0.8, 0.8, 1.2, 1.2)), TEAL_DEEP, by0, by1), mir), DEEP_TONES), True))
        if b["legs"]:
            ly0, ly1, lx0, lx1 = b["legs"]
            L.append((part(rig(soft(box(lx0, ly0, lx1, ly1, (0.3,) * 4), TEAL, ly0, ly1, lx0, lx1), mir), TEAL_TONES), True))
            if b["knee"]:
                k0, k1 = b["knee"]
                L.append((part(rig(soft(box(lx0 - 1, k0, lx1 + 1, k1, (0.5,) * 4), SLATE, k0, k1), mir), SLATE_TONES),
                          ring("knee")))
    # pelvis and hip lights
    p0, p1, pw0, pw1 = b["pelvis"]
    L.append((part(rig(soft(poly([(-pw0, p0), (pw0, p0), (pw1, p1), (-pw1, p1)], 0.8), TEAL_SHADE, p0, p1)), DEEP_TONES),
              ring("pelvis")))
    hips = [(light_part(*b["hip"], lights, mir), False) for mir in (False, True)]
    if not b["hip_over_waist"]:
        L += hips
    # torso: a box, broad at the chest, narrowing to the waist
    t0, t1, tw0, tw1 = b["torso"]
    L.append((part(rig(soft(poly([(-tw0, t0), (tw0, t0), (tw1, t1), (-tw1, t1)], 1.0), TEAL, t0, t1, -tw0, tw0)), TEAL_TONES), True))
    # red waist trim
    w0, w1, ww = b["waist"]
    L.append((part(rig(soft(box(-ww, w0, ww, w1, (0.4,) * 4), RED, w0, w1)), RED_TONES), True))
    if b["hip_over_waist"]:
        L += hips
    # two small angular chest plates, split down the middle
    c0, c1 = b["plates"]
    for mir in (False, True):
        L.append((part(rig(soft(poly([(-7, c0), (-2, c0), (-2, c1), (-5, c1), (-7, c1 - 2)], 0.4), MINT, c0, c1), mir), MINT_TONES), False))
    # collar: the neck joint, a slate ring between head and torso
    k0, k1 = b["collar"]
    L.append((part(rig(soft(box(-6, k0, 6, k1, (0.6,) * 4), SLATE, k0, k1)), SLATE_TONES), True))
    return L


def shoulder_layers(lights="dim"):
    """Shoulder blocks with their lights: in front of the arms' roots."""
    x0, y0, x1, y1 = P["BODY"]["shoulder"]
    L = []
    for mir in (False, True):
        r = P["BODY"].get("shoulder_r", 1.2)
        L.append((part(rig(soft(box(x0, y0, x1, y1, (r,) * 4), TEAL, y0, y1, x0, x1), mir), TEAL_TONES), True))
        L.append((light_part(*P["BODY"]["light"], lights, mir), False))
    return L


POSES = {  # shoulder angle (0 = hanging, + = outward), elbow angle (relative), pointing finger
    "rest": (0, 0, False),
    "lift": (45, 0, False),
    "point": (90, 0, True),
    "up": (90, 45, False),      # arms out wide, forearms angled up, mitts up (home)
    "push": (45, 135, False),   # forearms raised, mitts up at the jaw (scroll up: pushing the page up)
    "shrug": (45, 45, False),    # elbows out, forearms level, mitts open at shoulder height (ignored)
}
SHOULDER = (-13, 5)           # the left arm's pivot, rig space (set per profile by configure, from BODY)
UPPER, FORE = 6.0, 5.0


def arm_parts(pose, mirror=False):
    """One arm (the left; mirror = the right): upper arm about the shoulder, an elbow joint, the forearm, a slate
    mitt. Segments are rotated SVG boxes; the mitt is drawn upright at the whole-cell wrist, flat across the wrist,
    rounded at the far end, a thumb on the inner side."""
    a1, a2, point = P.get("POSES", {}).get(pose) or POSES[pose]   # a profile may re-pose (v3's short arms)
    u = P["U"]
    sx, sy = SHOULDER
    rad = math.radians
    ex, ey = sx - UPPER * math.sin(rad(a1)), sy + UPPER * math.cos(rad(a1))
    t = a1 + a2
    wlx, wly = ex - FORE * math.sin(rad(t)), ey + FORE * math.cos(rad(t))
    B = P["BODY"]
    uw, fw, er = B.get("upper_w", 2.0), B.get("fore_w", 1.75), B.get("elbow_r", 2.1)
    upper = f'<g transform="translate({f(sx)} {f(sy)}) rotate({f(a1)})">' + \
        soft(box(-uw, -1.5, uw, UPPER + 0.5, (min(0.8, uw * 0.4),) * 4), TEAL, -1.5, UPPER + 0.5, -uw, uw) + "</g>"
    fore = f'<g transform="translate({f(ex)} {f(ey)}) rotate({f(t)})">' + \
        soft(box(-fw, 0, fw, FORE, (0.5,) * 4), TEAL, 0, FORE, -fw, fw) + "</g>"
    elbow = soft(f'<circle cx="{f(ex)}" cy="{f(ey)}" r="{f(er)}"/>', SLATE, ey - er, ey + er)
    parts = [part(rig(upper, mirror), TEAL_TONES), part(rig(fore, mirror), TEAL_TONES)]
    if er > 0:
        parts.append(part(rig(elbow, mirror), SLATE_TONES))
    # the mitt, in frame cells (left arm), then mirrored about the centre line
    wx, wy = int(round(CX + wlx * u)), int(round(HB + wly * u))
    ms, ts, fs = B.get("mitt", (6, 3, 5))
    m, h, tl, fl = round(ms * u), round(ms * u) / 2, round(ts * u), round(fs * u)
    rd, sq = 1.6 * u, 0.3
    o = 0 if t <= 45 else (90 if t < 135 else 180)
    finger = None
    if m % 2:          # an odd mitt: centre it across the arm on a cell, not a cell edge (else it loses a row / column)
        if o == 90:
            wy += 0.5
        else:
            wx += 0.5
    if o == 0:
        hand, thumb = box(wx - h, wy - 1, wx + h, wy - 1 + m, (sq, sq, rd, rd)), box(wx + h - 1, wy, wx + h + 1, wy + tl, (0.6,) * 4)
    elif o == 180:
        hand, thumb = box(wx - h, wy + 1 - m, wx + h, wy + 1, (rd, rd, sq, sq)), box(wx + h - 1, wy - tl, wx + h + 1, wy, (0.6,) * 4)
    else:
        hand, thumb = box(wx + 1 - m, wy - h, wx + 1, wy + h, (rd, sq, sq, rd)), box(wx - tl, wy - h - 2, wx, wy - h + 1, (0.6,) * 4)
        if point:
            finger = box(wx - m + 2 - fl, wy - h + 1, wx - m + 2, wy - h + 3, (0.8, 0.3, 0.3, 0.8))
    mir = (lambda s: f'<g transform="translate({2 * CX} 0) scale(-1 1)">{s}</g>') if mirror else (lambda s: s)
    parts.append(part(mir(soft(thumb, SLATE, wy - m, wy + m)), SLATE_TONES))
    if finger:
        parts.append(part(mir(soft(finger, SLATE, wy - h, wy)), SLATE_TONES))
    parts.append(part(mir(soft(hand, SLATE, wy - m, wy + m)), SLATE_TONES))
    return parts


# ------------------------------------------------------------------------------------------------ the antenna

ANT_REST = (-45, 25)          # base angle from vertical (- = out to the left), knuckle bend (+ = back toward upright)


def pixel_line(p0, p1):
    """Whole cells along p0 -> p1, one cell thick, pixel-perfect (no doubled stair corners)."""
    n = int(max(abs(p1[0] - p0[0]), abs(p1[1] - p0[1])) * 4) + 2
    cells = []
    for t in np.linspace(0, 1, n):
        c = (int(math.floor(p0[0] + (p1[0] - p0[0]) * t)), int(math.floor(p0[1] + (p1[1] - p0[1]) * t)))
        if not cells or cells[-1] != c:
            cells.append(c)
    out = []
    for i, c in enumerate(cells):
        if 0 < i < len(cells) - 1 and out:
            a, b = out[-1], cells[i + 1]
            if abs(a[0] - b[0]) == 1 and abs(a[1] - b[1]) == 1 and (c[0] == a[0] or c[1] == a[1]):
                continue
        out.append(c)
    return out


def antenna(a0, a1, hy):
    """The antenna: two rod segments rotated about the base (a0) and the knuckle (a1). -> rod cells, knuckle cell,
    the 2x2 bead's cells (top-left, top-right, bottom-left, bottom-right)."""
    bx, by = HEAD_X + P["ANT_BASE"][0], hy + P["ANT_BASE"][1]
    d = lambda deg: (math.sin(math.radians(deg)), -math.cos(math.radians(deg)))
    l0, l1 = P["ANT_LEN"]
    k = (bx + d(a0)[0] * l0, by + d(a0)[1] * l0)
    t = (k[0] + d(a0 + a1)[0] * l1, k[1] + d(a0 + a1)[1] * l1)
    rod = pixel_line((bx, by), k) + pixel_line(k, t)
    tx, ty = int(math.floor(t[0] - 0.5)), int(math.floor(t[1] - 0.5))
    return rod, (int(math.floor(k[0])), int(math.floor(k[1]))), [(tx, ty), (tx + 1, ty), (tx, ty + 1), (tx + 1, ty + 1)]


MAST_BEAD = [".##.", "####", ".##."]      # the crown mast's bead: 4 x 3, rounded
MAST_BEADS = {  # highlight, body, shade: neutral at rest; teal screen-glow while the lamp is orange (a hum)
    "rest": ("#F4FFFB", MINT, "#B5C1B3"),
    "pulse": ("#F4FFFB", GLOW, GLOW_DIM),
    "glow": (GLOW, GLOW_DIM, TEAL_DEEP),
    "off": (SLATE_LIGHT, SLATE, NAVY),
}
MAST_REACH = 3.5              # hinge -> the bead's centre, cells


def mast_bead(lamp, bead, off):
    """The mast bead's colours for a frame: glowing (pulsing bright/dim as the states ask) only while the lamp is
    orange, neutral otherwise (pending's pulse too), slate when off."""
    if off:
        return "off"
    if lamp == "orange":
        return "pulse" if bead == "pulse" else "glow"
    return "rest"


def mast_lean(ant):
    """The mast's lean in degrees (- = left) for a state's antenna angles (base, knuckle): the jointed antenna's tip
    direction relative to its rest, so every state keeps its antenna motion. Under 12 degrees it stands straight
    (a stiff mast, no one-pixel flicker); past 80 it lies on the crown (limp)."""
    d = (ant[0] + ant[1]) - (ANT_REST[0] + ANT_REST[1])
    return 0.0 if abs(d) < 12 else max(-80.0, min(80.0, float(d)))


def mast(ant, hy, key):
    """The crown mast as a part (mask, rgb): a 4-cell slate foot on the crown's top row (row hy), a 2-cell rod hinged
    at the foot's top centre and leaning by mast_lean, the bead at its end. Symmetric about the centre line when
    upright (the line falls between two cells, so the rod is two cells wide)."""
    m = np.zeros((N, N), dtype=bool)
    c = np.zeros((N, N, 3))
    th = math.radians(mast_lean(ant))
    sx, sy = math.sin(th), -math.cos(th)
    flat = abs(th) > math.radians(45)
    hi, mid, lo = MAST_BEADS[key]

    def cell(x, y, col):
        m[y, x] = True
        c[y, x] = rgb(col)

    reach = MAST_REACH + (1 if flat else 0)               # lying down, the rod shows between foot and bead
    for t in ((0.5, 1.5, 2.5) if flat else (0.5, 1.5)):   # the rod: lit side, shaded side
        x, y = CX + t * sx, hy + t * sy
        if flat:
            r = math.floor(y)
            cell(math.floor(x), r - 1, SLATE_LIGHT)
            cell(math.floor(x), r, SLATE)
        else:
            q = int(round(x))
            cell(q - 1, math.floor(y), SLATE_LIGHT)
            cell(q, math.floor(y), SLATE)
    bx, by = CX + reach * sx, hy + reach * sy
    left, top = int(round(bx)) - 2, int(round(by - 1.5))
    if flat:
        top = min(top, hy - 3)                            # lying down: on the crown, not in it
    for j, row in enumerate(MAST_BEAD):
        for i, ch in enumerate(row):
            if ch == "#":
                cell(left + i, top + j, hi if (i, j) in ((1, 0), (0, 1)) else lo if (j == 2 or i == 3) else mid)
    for i in range(4):                                    # the foot, on the crown's top row
        cell(CX - 2 + i, hy, NAVY if i == 3 else SLATE)
    return m, c


# ------------------------------------------------------------------------------------------------ frames

def frame(face, lamp="dull", halo=False, arms=("rest", "rest"), head_dy=0, hop=0, off=False, lights="dim",
          ant=ANT_REST, bead=None, outline=INK, shrug=0):
    """One frame as RGBA (N x N x 4, uint8). Depth order: body, antenna, head, arms, shoulder blocks, antenna bolt.
    shrug lifts the arms and shoulder blocks that many cells (the body and legs stay put)."""
    img = np.zeros((N, N, 3))
    alpha = np.zeros((N, N), dtype=bool)
    ink = rgb(outline)

    def put(p, ol=True):
        m, c = p
        if ol:
            o = st.near4(m) & ~m
            img[o] = ink
            alpha[o] = True
        img[m] = c[m]
        alpha[m] = True

    for p, ol in body_layers(lights):
        put(shifted(p, 0, -hop), ol)
    hy = HEAD_Y + head_dy - hop
    corner = P["ANT"] == "corner"
    if not corner:                       # the crown mast, behind the head; drawn again over its top edge below
        mast_part = mast(ant, hy, mast_bead(lamp, bead, off))
        put(mast_part)
    # the corner antenna, behind the head (its root tucks under the bolt)
    rod, knuckle, bead_cells = antenna(ant[0], ant[1], hy) if corner else ([], None, [])
    bm = np.zeros((N, N), dtype=bool)
    for x, y in bead_cells:
        bm[y, x] = True
    o = st.near4(bm) & ~bm
    img[o] = ink
    alpha[o] = True
    for x, y in rod:                     # mid teal, not ink: it has to read over dark apps too
        img[y, x] = rgb(TEAL_DEEP)
        alpha[y, x] = True
    if knuckle:
        img[knuckle[1], knuckle[0]] = rgb(SLATE_LIGHT)
    for (x, y), c in zip(bead_cells, BEADS[bead or ("off" if off else "rest")]):
        img[y, x] = rgb(c)
    # the head
    himg, hmask, screen = head_base(lamp, halo, off)
    himg = himg.copy()
    if face is not None:
        draw_face(himg, screen, face)
    hm = np.zeros((N, N), dtype=bool)
    hc = np.zeros((N, N, 3))
    hm[hy:hy + HEAD, HEAD_X:HEAD_X + HEAD] = hmask
    hc[hy:hy + HEAD, HEAD_X:HEAD_X + HEAD] = himg
    put((hm, hc))
    if not corner:                       # the mast's foot on the crown, its rod over the head's top outline
        put(mast_part, ol=False)
    # arms in front of the head (raised mitts cross its lower corners), shoulder blocks over the arms' roots
    for side, pose in enumerate(arms):
        for p in arm_parts(pose, mirror=side == 1):
            put(shifted(p, 0, -hop - shrug))
    for p, ol in shoulder_layers(lights):
        put(shifted(p, 0, -hop - shrug), ol)
    # the antenna's bolt on the hood's corner
    mx, my, mw, mh = P["MOUNT"] if corner else (0, 0, 0, 0)
    mb = np.zeros((N, N), dtype=bool)
    mb[hy + my:hy + my + mh, HEAD_X + mx:HEAD_X + mx + mw] = True
    mc = np.zeros((N, N, 3))
    mc[mb] = rgb(SLATE)
    mc[hy + my, HEAD_X + mx:HEAD_X + mx + mw - 1] = rgb(SLATE_LIGHT)
    mc[hy + my + mh - 1, HEAD_X + mx + 1:HEAD_X + mx + mw] = rgb(NAVY)
    put((mb, mc))
    out = np.zeros((N, N, 4), dtype=np.uint8)
    out[..., :3] = np.round(img * 255).astype(np.uint8)
    out[..., 3] = np.where(alpha, 255, 0)
    return out


# ------------------------------------------------------------------------------------------------ states

STATES = {}      # name -> dict(about, loop, frames=[(rgba, ms)], still)
EXTRA = {}       # preview-only alternatives


def state(name, about, frames, loop=True, still=0, into=None):
    (STATES if into is None else into)[name] = dict(about=about, loop=loop, frames=frames, still=still)


def build_states():
    """Every state's frames. Antenna angles (base, knuckle) give it spring: it lags the head, whips against a
    move and settles."""
    OPEN, HALF, SHUT = eyes(G["EYE_L"]), eyes(G["EYE_HALF_L"]), eyes(G["EYE_SHUT_L"])
    dy = P["EYE_DY"]
    s1 = P["STEP"]

    def idle(lamp):
        fr = lambda face, hdy, a1: frame(face, lamp, head_dy=hdy, ant=(-45, a1))
        # the head bobs on frames 1, 3, 8; the antenna follows a frame late (up as the head drops, back as it rises)
        return [(fr(OPEN, 0, 25), 700), (fr(OPEN, 1, 25), 700), (fr(OPEN, 0, 40), 700), (fr(OPEN, 1, 12), 700),
                (fr(OPEN, 0, 38), 700), (fr(HALF, 0, 25), 60), (fr(SHUT, 0, 25), 90), (fr(HALF, 0, 25), 60),
                (fr(OPEN, 1, 25), 700)]

    state("idle", "Armed, waiting for a hum: calm crescent eyes, a slow blink, the head bobbing a pixel on its collar "
          "with the antenna swaying a beat behind. Lamp dull (it lights orange only while hearing); body lights unlit.",
          idle("dull"))

    hear_eyes = eyes(G["EYE_L"], dy=dy["hear"])
    hi, lo = P["BARS"]
    meters = [[1, 3, 2, lo, hi, lo, 2, 3, 1], [2, lo, 3, 2, lo, hi, 3, 2, 2], [3, 2, hi, 3, 3, lo, 2, lo, 1],
              [2, 3, lo, hi, 2, 3, lo, 2, 3]]
    hear = [(frame(hear_eyes + bars(h), "orange", halo=(i % 2 == 0), lights="orange", ant=(-45, 25 + 8 * (i % 2)),
                   bead="pulse" if i % 2 == 0 else "rest"), 110) for i, h in enumerate(meters)]
    state("hearing", "A hum in progress: eyes up, a level meter, the lamp's halo pulsing, shoulder and hip lights lit, "
          "the antenna quivering with its tip bead pulsing.", hear)
    state("hearing_once", "A sound that caused no action (one-shot): one beat of the meter.", hear, loop=False)

    pend_eyes = eyes(G["EYE_ROUND"], dy=dy["round"])
    dots = [at(G["DOT"], x, y) for x, y in P["DOTS"]]
    tilt = [(-40, 22), (-34, 20), (-30, 18), (-36, 22)]
    pend = [(frame(pend_eyes + Face(*sum((d.items for d in dots[:k]), [])), "yellow", halo=(k % 2 == 1), lights="yellow",
                   ant=tilt[k - 1], bead="pulse" if k == 3 else "rest"), 220) for k in (1, 2, 3)]
    pend.append((frame(pend_eyes, "yellow", lights="yellow", ant=tilt[3]), 220))
    state("pending", "Waiting for the second sound: round expectant eyes, dots counting, lamp and body lights yellow, "
          "the antenna tilting up to listen.", pend, still=2)

    def scroll(up):
        g = G["ARROW_UP"] if up else G["ARROW_DOWN"]
        s = -1 if up else 1
        arms = ("push", "push") if up else ("rest", "rest")
        whip = [25, -10, 5, 32, 22] if up else [25, 50, 40, 16, 27]   # head up: tip lags down; head down: tip lags up
        return [(frame(centred(g, dy=-s * s1), ant=(-45, whip[0])), 80),
                (frame(centred(g), arms=arms, head_dy=s, ant=(-45, whip[1])), 110),
                (frame(centred(g, dy=s * s1), arms=arms, head_dy=s, ant=(-45, whip[2])), 110),
                (frame(centred(g, dy=2 * s * s1), arms=arms, head_dy=s, ant=(-45, whip[3])), 90),
                (frame(centred(g, dy=3 * s * s1 + s), ant=(-45, whip[4])), 80)]

    state("scroll_up", "One-shot after a scroll up: an arrow runs up the screen, the forearms push up, the head lifts, "
          "the antenna whips back and settles.", scroll(True), loop=False, still=1)
    state("scroll_down", "One-shot after a scroll down: an arrow runs down the screen, the head dips, the antenna "
          "flicks up and settles.", scroll(False), loop=False, still=1)

    def stream(up, phase):
        g = G["CHEVRON_UP"] if up else flipv(G["CHEVRON_UP"])
        sp = P["STREAM"]
        items = []
        for k in range(-1, 4):
            off = (-phase if up else phase) % sp
            items += centred(g, dy=k * sp + off - sp - 2).items
        return Face(*items)

    for d, up in (("up", True), ("down", False)):
        wob = [0, -8, 0, 8, 0, -8] if up else [45, 52, 45, 38, 45, 52]
        state(f"hold_scroll_{d}", f"Scrolling {d} while the hum is held: chevrons stream {d}, the head leans into it, "
              "the antenna streams with a steady wobble. BadgeState.HOLD_SCROLL plays the last scroll's direction.",
              [(frame(stream(up, p % P["STREAM"]), "orange", halo=(p < 3), head_dy=-1 if up else 1,
                      arms=("push", "push") if up else ("rest", "rest"), lights="orange", ant=(-45, wob[p])), 70)
               for p in range(6)])

    def point(left):
        g = G["ARROW_LEFT"] if left else G["ARROW_RIGHT"]
        s = -1 if left else 1
        pose = (lambda p: (p, "rest")) if left else (lambda p: ("rest", p))
        # the tip trails the arm's swing: pushed right as the arm swings left, left as it swings right
        trail = [(-45, 25), (-32, 38), (-38, 32), (-47, 22), (-45, 25)] if left else \
                [(-45, 25), (-58, 8), (-52, 16), (-43, 28), (-45, 25)]
        return [(frame(centred(g, dx=-s * s1), arms=pose("lift"), ant=trail[0]), 90),
                (frame(centred(g), arms=pose("point"), ant=trail[1]), 140),
                (frame(centred(g, dx=s * s1), arms=pose("point"), ant=trail[2]), 140),
                (frame(centred(g, dx=2 * s * s1), arms=pose("point"), ant=trail[3]), 110),
                (frame(OPEN, arms=pose("lift"), ant=trail[4]), 80)]

    state("back", "One-shot after Back: the left arm points left, an arrow runs left on the screen, the antenna "
          "trails the swing.", point(True), loop=False, still=1)
    state("forward", "One-shot after Forward: the right arm points right, an arrow runs right, the antenna trails.",
          point(False), loop=False, still=1)
    house = G["HOUSE"]
    state("home", "One-shot after Home: a crouch, a hop with both mitts up, a house on the screen; the antenna "
          "bounces on the hop.",
          [(frame(centred(house, dy=1), head_dy=1, arms=("lift", "lift"), ant=(-45, 42)), 90),
           (frame(centred(house), arms=("up", "up"), hop=2, ant=(-45, -8)), 160),
           (frame(centred(house), arms=("up", "up"), hop=1, ant=(-45, 12)), 90),
           (frame(centred(house), arms=("up", "up"), ant=(-45, 40)), 180),
           (frame(OPEN, arms=("lift", "lift"), head_dy=1, ant=(-45, 22)), 80)], loop=False, still=3)
    state("cursor", "Cursor mode: reticle eyes that lock in and out; the antenna stiff and straight, pointing.",
          [(frame(eyes(G["RETICLE_WIDE"], dy=dy["reticle"], gr=G["RETICLE_WIDE"]), ant=(-30, 0)), 420),
           (frame(eyes(G["RETICLE_TIGHT"], dy=dy["reticle"], gr=G["RETICLE_TIGHT"]), ant=(-30, 0)), 420)])
    sleep = eyes(G["EYE_SLEEP_L"], dy=dy["sleep"])
    zs, zb = P["Z_SMALL_AT"], P["Z_BIG_AT"]
    state("paused", "Paused: eyes shut, a pixel z drifting up the screen, lamp dull, a slow breath; the antenna "
          "drooping.",
          [(frame(sleep + at(G["Z_SMALL"], *zs), "dull", ant=(-80, -45)), 700),
           (frame(sleep + at(G["Z_BIG"], *zb), "dull", head_dy=1, ant=(-80, -55)), 700),
           (frame(sleep + at(G["Z_BIG"], *zb), "dull", head_dy=1, ant=(-80, -55)), 700),
           (frame(sleep, "dull", ant=(-80, -45)), 700)], still=1)
    state("off", "Off / disconnected: the off icon's face (dark eyes, lamp unlit), head sunk on the collar, antenna "
          "limp, still.",
          [(frame(eyes(G["EYE_L"], style="off"), "dull", off=True, head_dy=1, ant=(-100, -60)), 1000)])
    sq = eyes(G["EYE_SQUINT_L"], dy=dy["squint"], gr=fliph(G["EYE_SQUINT_L"]))
    jit = [(-40, 18), (-50, 32), (-41, 30), (-49, 20)]
    flash = [(frame(sq, "red", halo=True, lights="red", ant=jit[0]), 110), (frame(sq, "dull", ant=jit[1]), 80),
             (frame(sq, "red", halo=True, lights="red", ant=jit[2]), 110), (frame(sq, "dull", ant=jit[3]), 80)]
    state("error", "Stop / error (held): the lamp and body lights flash red twice, then stay red; eyes squint, the "
          "antenna jitters.", flash + [(frame(sq, "red", halo=True, lights="red"), 1600)], still=4)
    state("error_once", "A failed action (one-shot): the lamp and body lights flash red twice, eyes squint, the "
          "antenna jitters.", flash + [(frame(sq, "red", halo=True, lights="red"), 160)], loop=False)

    # heard, not acting: flat level eyes and a wavy mouth, a shrug (shoulders up, head sunk, forearms out), a glance aside;
    # lamp dull, body lights unlit, no meter: nothing like hearing's lit lamp and bars
    def meh(dx=0, mouth=True):
        g, ew, y = G["EYE_FLAT_L"], P["EYE_W"], P["EYE_Y"] + 1
        items = [(g, P["EYE_LX"] + (ew - len(g[0])) // 2 + dx, y, "glyph"), (g, P["EYE_RX"] + (ew - len(g[0])) // 2 + dx, y, "glyph")]
        return Face(*items) + (centred(G["MOUTH_WAVY"], dy=2) if mouth else Face())

    shrug = ("shrug", "shrug")
    state("ignored_once", "A sound heard but not acted on (one-shot, rate-limited by the service): flat eyes, a wavy "
          "mouth, a quick shrug with a glance aside; lamp dull, no meter.",
          [(frame(meh(mouth=False), ant=(-45, 30)), 70),
           (frame(meh(), arms=shrug, shrug=1, head_dy=1, ant=(-45, 42)), 120),
           (frame(meh(dx=1), arms=shrug, shrug=1, head_dy=1, ant=(-50, 20)), 140),
           (frame(meh(dx=1, mouth=False), ant=(-45, 30)), 90),
           (frame(OPEN, ant=(-45, 25)), 60)], loop=False, still=1)

    # the Pico paused itself after a link drop and waits for a tap on the badge (the app sends the arm command): the
    # face screen alternates drowsy eyes (lids half down: not paused's shut eyes) and a glowing TAP; lamp dull, body
    # lights unlit, the antenna half-drooped. Still frame: TAP (the message, with reduced motion).
    drowsy = eyes(G["EYE_DROWSY_L"], dy=1)
    state("tap_to_wake", "Asleep after a link drop, a tap wakes it (the app arms the Pico): drowsy half-lidded eyes, "
          "then TAP glowing on the face screen, alternating slowly; lamp dull, antenna half-drooped.",
          [(frame(drowsy, "dull", ant=(-45, -20)), 1200),
           (frame(centred(G["TAP"], dy=-2), "dull", ant=(-45, -20)), 800)], still=1)

    # The voice joystick's Face A (extractor/joystick_ind.py, approved 2026-09-27; its face() is the one drawing):
    # one still frame per bar step and vowel side, shown by the app while cursor mode runs on the joystick.
    # Named joy_idle, joy_<step>_<vowel> with step 0, up1..up4, down1..down4, upoff, downoff; vowel ah / ee / oo.
    # Appended last, so every older frame keeps its sheet index.
    sys.path.insert(0, os.path.join(VOX, "extractor"))
    import joystick_ind as JI
    for n in JI.FACE_KEYS:
        for v in (("ah",) if n is None else ("ah", "ee", "oo")):
            ghost, lit = JI.face(n, v)
            voiced = n is not None
            fr = frame(Face((ghost, 0, 0, "off"), (lit, 0, 0, "glyph")), "orange" if voiced else "dull", halo=voiced,
                       lights="orange" if voiced else "dim", ant=(-30, 0), bead="rest")
            state(joy_state_name(n, v), "Voice joystick (cursor mode, Face A): the pitch bar's step and the vowel "
                  "pointer; a still frame the service picks per tick.", [(fr, 1000)])


def joy_state_name(n, vowel):
    """joystick_ind.FACE_KEYS entry + vowel -> the manifest state name (JoyFace.stateName in the app)."""
    if n is None:
        return "joy_idle"
    if isinstance(n, str):
        step = "upoff" if n == "off" else "downoff"
    else:
        step = "0" if n == 0 else (f"up{n}" if n > 0 else f"down{-n}")
    return f"joy_{step}_{vowel}"


# ------------------------------------------------------------------------------------------------ outputs

def crop_box(frames):
    a = np.zeros((N, N), dtype=bool)
    for fr in frames:
        a |= fr[..., 3] > 0
    ys, xs = np.nonzero(a)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def build_sheet():
    everything = [fr for s in list(STATES.values()) + list(EXTRA.values()) for fr, _ in s["frames"]]
    x0, y0, x1, y1 = crop_box(everything)
    fw, fh = x1 - x0, y1 - y0
    uniq, index, states = [], {}, {}
    for name, s in STATES.items():
        idx = []
        for fr, ms in s["frames"]:
            k = fr[y0:y1, x0:x1].tobytes()
            if k not in index:
                index[k] = len(uniq)
                uniq.append(fr[y0:y1, x0:x1])
            idx.append(index[k])
        states[name] = dict(loop=s["loop"], frames=idx, ms=[ms for _, ms in s["frames"]], still=s["still"],
                            about=s["about"])
    cols = 8
    rows = (len(uniq) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * fw, rows * fh), (0, 0, 0, 0))
    for i, fr in enumerate(uniq):
        sheet.paste(Image.fromarray(fr, "RGBA"), ((i % cols) * fw, (i // cols) * fh))
    manifest = {
        "name": "canti_badge", "version": 2,
        "about": "The floating badge's pixel Canti: the icon's head on a jointed robot body. Made by "
                 "brand/tools/canti_sprite.py; don't edit by hand.",
        "sheet": "canti_badge.png", "frameWidth": fw, "frameHeight": fh, "columns": cols, "frameCount": len(uniq),
        "artPxDp": round(P["ART_PX_DP"], 4),
        "scale": f"Draw each art px as n x n device px, n = max(1, round(density x artPxDp)) ({P['PX']} px at density "
                 "2.625), nearest neighbour, at whole-pixel positions.",
        "states": states,
    }
    return sheet, manifest, (x0, y0, x1, y1), uniq


def write_android():
    sheet, manifest, _box, uniq = build_sheet()
    os.makedirs(ASSETS, exist_ok=True)
    sheet.save(os.path.join(ASSETS, "canti_badge.png"), optimize=True)
    with open(os.path.join(ASSETS, "canti_badge.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
        fh.write("\n")
    print(f"sheet {sheet.size[0]}x{sheet.size[1]}, {len(uniq)} frames of {manifest['frameWidth']}x{manifest['frameHeight']}")


LIGHT_BG, DARK_BG, BLACK_BG = (0xDD, 0xEB, 0xD3, 255), (0x1E, 0x1F, 0x24, 255), (0x00, 0x00, 0x00, 255)
PAPER = (250, 250, 247, 255)


def big(fr, bx, s, bg):
    x0, y0, x1, y1 = bx
    im = Image.fromarray(fr[y0:y1, x0:x1], "RGBA")
    base = Image.new("RGBA", im.size, bg)
    base.alpha_composite(im)
    return base.resize((im.size[0] * s, im.size[1] * s), Image.NEAREST)


def solid(fr):
    out = fr.copy()
    out[..., :3] = np.where(out[..., 3:] > 0, np.array([0x16, 0x19, 0x2B], dtype=np.uint8), 255)
    out[..., 3] = 255
    return out


def write_preview(out):
    os.makedirs(out, exist_ok=True)
    sheet, manifest, bx, uniq = build_sheet()
    sheet.save(os.path.join(out, "canti_badge@1.png"))
    with open(os.path.join(out, "canti_badge.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    fw, fh_ = manifest["frameWidth"], manifest["frameHeight"]
    S = 4 if HEAD == 38 else 5
    allst = dict(STATES)
    allst.update({k + " (alt)": v for k, v in EXTRA.items()})
    maxf = max(len(s["frames"]) for s in allst.values())
    cw, ch = fw * S + 4, fh_ * S + 16
    lw = 130
    im = Image.new("RGBA", (lw + maxf * cw * 2 + 24, len(allst) * ch + 10), PAPER)
    d = ImageDraw.Draw(im)
    for r, (name, s) in enumerate(allst.items()):
        y = 5 + r * ch
        d.text((6, y + 4), name, fill=(20, 20, 30, 255))
        d.text((6, y + 18), "loop" if s["loop"] else "one-shot", fill=(90, 90, 100, 255))
        d.text((6, y + 32), f"{sum(ms for _, ms in s['frames'])} ms", fill=(90, 90, 100, 255))
        for i, (fr, ms) in enumerate(s["frames"]):
            for k, bg in enumerate((LIGHT_BG, DARK_BG)):
                x = lw + (k * maxf + i) * cw + k * 24
                im.paste(big(fr, bx, S, bg), (x, y))
                d.text((x, y + fh_ * S + 1), f"{ms}" + (" still" if i == s["still"] else ""), fill=(60, 60, 70, 255))
    im.save(os.path.join(out, f"contact-{S}x.png"))
    # GIFs (light and dark app behind), one-shots followed by idle
    allframes, alldur = [], []
    idle0 = STATES["idle"]["frames"][0][0]
    for name, s in allst.items():
        frames, durs = [], []
        seq = list(s["frames"]) + ([] if s["loop"] else [(idle0, 900)])
        for fr, ms in seq:
            g = Image.new("RGBA", (fw * S * 2 + 12, fh_ * S), LIGHT_BG)
            g.paste(big(fr, bx, S, LIGHT_BG), (0, 0))
            g.paste(big(fr, bx, S, DARK_BG), (fw * S + 12, 0))
            frames.append(g.convert("RGB"))
            durs.append(ms)
        fn = name.replace(" (alt)", "")
        frames[0].save(os.path.join(out, f"state-{fn}.gif"), save_all=True, append_images=frames[1:], duration=durs,
                       loop=0)
        total = 0
        while total < 2400:
            for g, ms in zip(frames, durs):
                hh = Image.new("RGB", (g.size[0], g.size[1] + 20), PAPER[:3])
                hh.paste(g, (0, 20))
                ImageDraw.Draw(hh).text((4, 4), name, fill=(20, 20, 30))
                allframes.append(hh)
                alldur.append(ms)
                total += ms
    allframes[0].save(os.path.join(out, "all-states.gif"), save_all=True, append_images=allframes[1:],
                      duration=alldur, loop=0)
    # silhouette check: poses in solid ink (a small robot, not a plush toy)
    picks = [("idle", 0), ("back", 1), ("home", 1), ("scroll_up", 1), ("paused", 1)]
    sil = [Image.fromarray(solid(STATES[n]["frames"][i][0])[bx[1]:bx[3], bx[0]:bx[2]], "RGBA") for n, i in picks]
    im = Image.new("RGB", (len(sil) * (fw * S + 12), fh_ * S + 18), (255, 255, 255))
    for k, p in enumerate(sil):
        im.paste(p.resize((fw * S, fh_ * S), Image.NEAREST), (k * (fw * S + 12), 18))
        ImageDraw.Draw(im).text((k * (fw * S + 12) + 4, 3), picks[k][0], fill=(20, 20, 30))
    im.save(os.path.join(out, "silhouette.png"))
    # outline on dark apps: ink (as shipped) vs a mint outline
    variants = [("ink outline", frame(eyes(G["EYE_L"]))), ("mint outline", frame(eyes(G["EYE_L"]), outline=MINT))]
    im = Image.new("RGBA", (2 * (fw * S + 16) + 16, 2 * (fh_ * S + 10) + 30), PAPER)
    dd = ImageDraw.Draw(im)
    for k, (label, v) in enumerate(variants):
        dd.text((10 + k * (fw * S + 16), 6), label, fill=(20, 20, 30, 255))
        for j, bg in enumerate((DARK_BG, BLACK_BG)):
            im.paste(big(v, bx, S, bg), (10 + k * (fw * S + 16), 24 + j * (fh_ * S + 10)))
    im.save(os.path.join(out, "outline-on-dark.png"))
    phone_mock(out, bx)
    print(f"preview -> {out}: {sheet.size[0]}x{sheet.size[1]} sheet, {len(uniq)} frames of {fw}x{fh_}")


def phone_mock(out, bx, name="phone-mock-zflip-real-px.png"):
    """A Z Flip screen at its real pixels (1080 px wide, density 2.625), the badge at PX device px per art px over a
    light app and a dark app."""
    x0, y0, x1, y1 = bx
    dens, px = 2.625, P["PX"]
    pw, ph = 1080, int(560 * dens)
    dp = lambda v: int(v * dens)
    im = Image.new("RGB", (pw * 2 + 60, ph + 40), (60, 60, 60))
    d = ImageDraw.Draw(im)
    shots = [STATES["idle"]["frames"][0][0], STATES["back"]["frames"][1][0], STATES["hearing"]["frames"][0][0]]
    for panel, (paper, ink_c, card) in enumerate((((250, 250, 250), (40, 40, 40), (226, 229, 234)),
                                                  ((24, 26, 30), (230, 230, 230), (44, 47, 54)))):
        ox = 20 + panel * (pw + 20)
        d.rectangle([ox, 20, ox + pw - 1, 20 + ph - 1], fill=paper)
        d.rectangle([ox, 20, ox + pw - 1, 20 + dp(64)], fill=card)
        d.text((ox + dp(16), 20 + dp(28)), "Feed  (text here is the mock's, not to scale)", fill=ink_c)
        y = 20 + dp(80)
        while y < 20 + ph - dp(80):
            d.ellipse([ox + dp(16), y, ox + dp(56), y + dp(40)], fill=card)
            d.rectangle([ox + dp(68), y + dp(4), ox + dp(300), y + dp(16)], fill=card)
            d.rectangle([ox + dp(68), y + dp(24), ox + dp(220), y + dp(34)], fill=card)
            y += dp(64)
        for k, fr in enumerate(shots):
            spr = Image.fromarray(fr[y0:y1, x0:x1], "RGBA")
            spr = spr.resize((spr.size[0] * px, spr.size[1] * px), Image.NEAREST)
            im.paste(spr, (ox + pw - spr.size[0] - dp(8) - k * dp(110) if k else ox + pw - spr.size[0] - dp(8),
                           20 + dp(90 + 150 * k)), spr)
        d.rectangle([ox + dp(16), 20 + ph - dp(64), ox + dp(64), 20 + ph - dp(16)], outline=ink_c)
        d.text((ox + dp(70), 20 + ph - dp(46)), "a 48 dp square", fill=ink_c)
    im.save(os.path.join(out, name))


def compare(out, old_sheet):
    """Old sprite (38x38 at 5 px) vs the two new sizes (38 head at 3 px, 28 head at 4 px), at real device pixels."""
    os.makedirs(out, exist_ok=True)
    shots = []
    for size in ("38", "28"):
        configure(size)
        build_states()
        _s, man, bx, _u = build_sheet()
        x0, y0, x1, y1 = bx
        picks = [STATES["idle"]["frames"][0][0], STATES["back"]["frames"][1][0], STATES["home"]["frames"][3][0]]
        shots.append((f"NEW {size}-px head, {x1 - x0}x{y1 - y0} art px @{P['PX']} dev px "
                      f"= {round((x1 - x0) * P['PX'] / 2.625)}x{round((y1 - y0) * P['PX'] / 2.625)} dp",
                      [Image.fromarray(p[y0:y1, x0:x1], "RGBA").resize(((x1 - x0) * P["PX"], (y1 - y0) * P["PX"]),
                                                                        Image.NEAREST) for p in picks]))
        phone_mock(out, bx, f"phone-mock-{size}.png")
    old = Image.open(old_sheet).convert("RGBA")
    old_frames = [old.crop((c * 38, 0, c * 38 + 38, 38)).resize((190, 190), Image.NEAREST) for c in (0,)]
    shots.insert(0, ("OLD 38x38 @5 dev px = 72 dp", old_frames))
    W = 30 + sum(max(sum(i.size[0] + 16 for i in imgs), 300) for _l, imgs in shots) + 20
    H = max(i.size[1] for _l, imgs in shots for i in imgs) + 50
    for bgname, bg, txt in (("light", (250, 250, 250, 255), (20, 20, 30, 255)), ("dark", (24, 26, 30, 255), (230, 230, 230, 255))):
        im = Image.new("RGBA", (W, H), bg)
        d = ImageDraw.Draw(im)
        x = 20
        for label, imgs in shots:
            d.text((x, 8), label, fill=txt)
            xx = x
            for i in imgs:
                im.alpha_composite(i, (xx, H - 10 - i.size[1]))
                xx += i.size[0] + 16
            x += max(xx - x, 300) + 10
        im.save(os.path.join(out, f"old-vs-new-{bgname}.png"))
    print("compare ->", out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "android"
    if cmd == "android":
        configure(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SIZE)
        build_states()
        write_android()
    elif cmd == "preview":
        configure(sys.argv[3] if len(sys.argv) > 3 else DEFAULT_SIZE)
        build_states()
        write_preview(sys.argv[2])
    elif cmd == "compare":
        compare(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
