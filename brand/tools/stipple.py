#!/usr/bin/env python3
"""Stipple (ordered-dither) versions of the Canti icon and wordmark.

The icon keeps canti-icon.svg's shapes and palette. Every soft gradient and blur of the original becomes flat
cel tones plus ordered-dither pixel stipple (4x4 Bayer matrix, whole grid cells, 2-3 tones per surface):

  * the flat shapes (body, recess lip, glass, brim shadow, eyes, brim, trim, crown, lamp) stay vectors;
  * each shaded surface is split into grid cells; a cell's tone comes from the ORIGINAL icon rendered at high
    resolution, averaged over the pixels of that surface inside the cell, then thresholded with the Bayer matrix
    between the surface's darker, base and lighter tone;
  * glows (eye glow, lamp halo, the shine's falloff) are analytic fields, dithered the same way in their own colour.

The dots are square cells on one global grid, so patterns line up across surfaces. `cell` is the grid pitch in
icon units (512 = the icon's width). For a raster at S px, pick cell = k * 512 / S with an integer k so every dot
is k x k device pixels (see `launcher`).

Needs python3 with numpy + pillow, and rsvg-convert. From ~/VOX:
  nix shell --impure --expr '(builtins.getFlake "nixpkgs").legacyPackages.x86_64-linux.python3.withPackages
      (p: [p.numpy p.pillow])' -c bash -c 'PATH=$PATH:$(nix build --no-link --print-out-paths nixpkgs#librsvg)/bin
      python3 brand/tools/stipple.py all'
"""
import math
import re
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = os.path.dirname(HERE)
VOX = os.path.dirname(BRAND)

BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=float)
THRESH = (BAYER4 + 0.5) / 16.0
# 8x8 Bayer (the 4x4 one, recursively): 64 levels, so dots in near-solid or near-empty areas stagger over 8 rows
BAYER8 = np.block([[4 * BAYER4 + 0, 4 * BAYER4 + 2], [4 * BAYER4 + 3, 4 * BAYER4 + 1]])
THRESH8 = (BAYER8 + 0.5) / 64.0


def column_jitter(n, spread, seed=7):
    """A fixed, seeded whole-cell offset per grid column (0..spread): breaks ruler-straight rows, stays on grid."""
    return np.random.default_rng(seed).integers(0, spread + 1, size=n)

# brand tokens
TEAL, TEAL_SHADE, MINT, NAVY, GLOW, SLATE = "#6DB8A8", "#4A9488", "#DDEBD3", "#1D2757", "#7FE0C9", "#3C4C7E"
ORANGE, YELLOW, RED, INK = "#F2A33A", "#F6C945", "#D6453D", "#16192B"
TEAL_LIGHT = "#8FCBBE"   # lit teal, the colour wordmark's top light (between teal and #9AD4C6)
TEAL_DEEP = "#3F877B"    # the colour wordmark's underside teal

HOOD = "M0 0 H512 V162 C512 202 508 232 494 232 C454 222 396 172 256 172 C116 172 58 222 18 232 C4 232 0 202 0 162 Z"
EYE_L = ('M138 340 C142 294 218 294 222 340 C220 358 200 340 180 340 C160 340 140 358 138 340 Z',
         'rotate(5 180 334) translate(180 334) scale(1.17) translate(-180 -334)')
EYE_R = ('M290 340 C294 294 370 294 374 340 C372 358 352 340 332 340 C312 340 292 358 290 340 Z',
         'rotate(-5 332 334) translate(332 334) scale(1.17) translate(-332 -334)')
TRIM = ("M508.25 212 C505.5 224.5 501 232 494 232 C454 222 396 172 256 172 C116 172 58 222 18 232 "
        "C11 232 6.5 224.5 3.75 212")
CROWN = "M0 0 H512 V112 C452 40 364 18 256 18 C148 18 60 40 0 112 Z"

# v5: the art continues past the 512 box out to the whole 108 dp launcher layer (-128..640), so no launcher mask shows
# a box edge. SRC is the canvas every source render covers (4 px per unit, as before). The brim's lower edge leaves the
# original curve at the tips' lowest points (18, 232) / (494, 232) and runs on along the curve's tangent (4 across,
# 1 down) past the layer's edge: the curl-up tips are gone and the gold trim runs off the icon's edge. The crown (the
# head turning away at the top corners) runs on along its own tangent at (0, 112) / (512, 112).
SRC = (-128.0, 768.0)
HIRES = 3072
FAR = 200.0                                    # how far past the 512 box the extended shapes reach (> 128)
BRIM_SLOPE = 0.25                              # the brim curve's slope at its tips (from 58,222 to 18,232)
CROWN_SLOPE = float(os.environ.get("CROWN_SLOPE", "1.2"))   # the crown curve's slope at (0, 112)


def fmt(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


def _line_c(x0, y0, x1, y1):
    """A straight segment written as a cubic (bezier_points reads only M and C)."""
    return (f"C{fmt(x0 + (x1 - x0) / 3)} {fmt(y0 + (y1 - y0) / 3)} {fmt(x0 + 2 * (x1 - x0) / 3)} "
            f"{fmt(y0 + 2 * (y1 - y0) / 3)} {fmt(x1)} {fmt(y1)}")


def _geometry():
    yb = 232 + BRIM_SLOPE * (18 + FAR)                 # brim edge at x = -FAR (and 512 + FAR)
    yc = 112 + CROWN_SLOPE * FAR
    L, R, T = -FAR, 512 + FAR, -FAR
    mid = "C454 222 396 172 256 172 C116 172 58 222 18 232"
    hood = f"M{fmt(L)} {fmt(T)} H{fmt(R)} V{fmt(yb)} L494 232 {mid} L{fmt(L)} {fmt(yb)} Z"
    trim = f"M{fmt(R)} {fmt(yb)} {_line_c(R, yb, 494, 232)} {mid} {_line_c(18, 232, L, yb)}"
    crown = (f"M{fmt(L)} {fmt(T)} H{fmt(R)} V{fmt(yc)} L512 112 C452 40 364 18 256 18 C148 18 60 40 0 112 "
             f"L{fmt(L)} {fmt(yc)} Z")
    return hood, trim, crown


HOOD_V4, TRIM_V4, CROWN_V4 = HOOD, TRIM, CROWN
HOOD, TRIM, CROWN = _geometry()
LIP = '<rect x="40" y="82" width="432" height="384" rx="142"/>'
GLASS = '<rect x="54" y="96" width="404" height="356" rx="128"/>'

# Dithered surfaces: name -> (tones dark..light, index of the base tone, the flat shape).
# The shape is painted in the base tone; dots are only the other tones, clipped to the shape.
SURFACES = {
    "body":  ([TEAL_SHADE, TEAL, TEAL_LIGHT], 1, '<rect x="-128" y="-128" width="768" height="768"/>'),
    "lip":   ([TEAL_DEEP, TEAL_SHADE, TEAL], 1, LIP),
    "glass": ([INK, NAVY, SLATE], 1, GLASS),
    "under": ([TEAL_DEEP, TEAL_SHADE], 1, f'<path d="{HOOD}" transform="translate(0 30)"/>'),
    "hood":  ([TEAL_SHADE, TEAL, TEAL_LIGHT], 1, f'<path d="{HOOD}"/>'),
    "crown": ([TEAL_DEEP, TEAL_SHADE], 1, f'<path d="{CROWN}"/>'),
}
# How far from the surface's reference luminance (its median in the original) a full tone step is, and a dead
# zone around the reference that stays flat (cartoon shading: flat areas, dithered transitions).
SHADE = {  # name: (luminance units per tone step down, per step up, dead zone)
    "body": (0.05, 0.045, 0.25),
    "lip": (0.07, 0.07, 0.25),
    "glass": (0.09, 0.06, 0.25),
    "under": (0.06, 1.0, 0.25),
    "hood": (0.06, 0.05, 0.20),
    "crown": (0.05, 1.0, 0.30),
}


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float) / 255.0


def lum(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def rsvg(svg_text, size, out_png=None):
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.svg")
        dst = out_png or os.path.join(td, "out.png")
        with open(src, "w") as f:
            f.write(svg_text)
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), src, "-o", dst], check=True)
        if out_png:
            return None
        return np.asarray(Image.open(dst).convert("RGBA"), dtype=float) / 255.0


def fmt(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


def squares(cells, c, o=0.0):
    """One path of c x c squares at origin o, horizontal runs merged."""
    out = []
    rows = {}
    for (i, j) in cells:
        rows.setdefault(j, []).append(i)
    for j in sorted(rows):
        xs = sorted(rows[j])
        start = prev = xs[0]
        for x in xs[1:] + [None]:
            if x is not None and x == prev + 1:
                prev = x
                continue
            out.append(f"M{fmt(o + start * c)} {fmt(o + j * c)}h{fmt((prev - start + 1) * c)}v{fmt(c)}h{fmt(-(prev - start + 1) * c)}z")
            if x is not None:
                start = prev = x
    return "".join(out)


class Grid:
    def __init__(self, cell, origin=0.0, extent=512.0, hires=2048, src=(0.0, 512.0)):
        """A square grid of `cell`-unit cells starting at `origin` and covering [origin, origin + extent].
        The source renders cover `src` (origin, extent) at `hires` px; source pixels outside the grid are ignored.
        The icon's grids use the extended source (SRC at HIRES)."""
        self.src = src
        self.c = cell
        self.o = origin
        self.n = int(math.ceil(extent / cell - 1e-9))
        self.hires = hires
        u = src[0] + (np.arange(hires) + 0.5) * src[1] / hires
        k = np.floor((u - origin) / cell).astype(int)
        self.valid = (k >= 0) & (k < self.n)
        self.idx = np.clip(k, 0, self.n - 1)
        centers = origin + (np.arange(self.n) + 0.5) * cell
        self.cx, self.cy = np.meshgrid(centers, centers)  # [row j, col i]
        self.th = THRESH[np.arange(self.n)[:, None] % 4, np.arange(self.n)[None, :] % 4]

    def cell_mean(self, values, mask):
        """Mean of `values` (H x W) over `mask` pixels, per cell -> (n x n, counts)."""
        jj, ii = np.meshgrid(self.idx, self.idx, indexing="ij")
        mask = mask & self.valid[:, None] & self.valid[None, :]
        flat = (jj * self.n + ii)[mask]
        cnt = np.bincount(flat, minlength=self.n * self.n).reshape(self.n, self.n)
        s = np.bincount(flat, weights=values[mask], minlength=self.n * self.n).reshape(self.n, self.n)
        with np.errstate(invalid="ignore", divide="ignore"):
            return s / np.maximum(cnt, 1), cnt

    def dither(self, f):
        """Cells whose fraction f (0..1) is above the Bayer threshold."""
        return f > self.th


# ---------------------------------------------------------------------------------------------------- the icon

LABELS = ["body", "lip", "glass", "shadow", "eyes", "under", "hood", "trim", "crown", "lamp"]


def label_svg(HOOD=HOOD, TRIM=TRIM, CROWN=CROWN, view=None):
    """Flat shapes in paint order, each in a distinct colour, to know which surface each pixel shows (over SRC)."""
    col = {n: "#%02x%02x%02x" % (10 + 20 * k, 200 - 15 * k, 40 + 17 * k) for k, n in enumerate(LABELS)}
    o, e = view or SRC
    return col, f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(o)} {fmt(o)} {fmt(e)} {fmt(e)}" shape-rendering="crispEdges">
<defs><clipPath id="g">{GLASS}</clipPath></defs>
<rect x="{fmt(o)}" y="{fmt(o)}" width="{fmt(e)}" height="{fmt(e)}" fill="{col['body']}"/>
<g fill="{col['lip']}">{LIP}</g><g fill="{col['glass']}">{GLASS}</g>
<g clip-path="url(#g)" fill="{col['eyes']}"><path d="{EYE_L[0]}" transform="{EYE_L[1]}"/><path d="{EYE_R[0]}" transform="{EYE_R[1]}"/>
<path d="{HOOD}" transform="translate(0 88)" fill="{col['shadow']}"/></g>
<path d="{HOOD}" transform="translate(0 30)" fill="{col['under']}"/><path d="{HOOD}" fill="{col['hood']}"/>
<path d="{TRIM}" fill="none" stroke="{col['trim']}" stroke-width="18" stroke-linecap="round" clip-path="url(#hc)"/>
<defs><clipPath id="hc"><path d="{HOOD}"/></clipPath></defs>
<path d="{CROWN}" fill="{col['crown']}"/><circle cx="370" cy="104" r="27" fill="{col['lamp']}"/>
</svg>"""


def posterize(f, levels):
    """Cel steps for a glow: [(field above, dot density)], highest first. Regular rings, not a sparkle of lone dots."""
    out = np.zeros_like(f)
    for above, dens in reversed(levels):
        out = np.where(f > above, dens, out)
    return out


def field_eyeglow(g):
    a = np.zeros_like(g.cx)
    for cx in (180.0, 332.0):
        r = np.sqrt(((g.cx - cx) / 86.0) ** 2 + ((g.cy - 334.0) / 70.0) ** 2)
        a = np.maximum(a, np.clip(1 - r, 0, 1))
    return a


def field_halo(g):
    r = np.hypot(g.cx - 370.0, g.cy - 104.0) / 78.0
    return np.interp(r, [0, 0.25, 0.6, 1.0], [1.0, 1.0, 0.31, 0.0])


def field_shine(g):
    r = np.sqrt(((g.cx - 256.0) / 104.0) ** 2 + ((g.cy - 209.0) / 17.0) ** 2)
    return np.clip(1 - r, 0, 1)


_CACHE = {}


def extended_master(text):
    """canti-icon[-off].svg over SRC: the full-bleed body layers cover the whole layer, and the hood, the trim and the
    crown are the extended shapes. Its gradients are userSpaceOnUse and pad, so the shading carries on past the box."""
    s = text
    o, e = fmt(SRC[0]), fmt(SRC[1])

    def sub(a, b, n):
        nonlocal s
        assert s.count(a) == n, (a, s.count(a))
        s = s.replace(a, b)
    sub('viewBox="0 0 512 512" width="512" height="512"', f'viewBox="{o} {o} {e} {e}" width="{e}" height="{e}"', 1)
    sub(f'd="{HOOD_V4}"', f'd="{HOOD}"', 1)
    sub(f'd="{TRIM_V4}"', f'd="{TRIM}"', 2)
    sub(f'd="{CROWN_V4}"', f'd="{CROWN}"', 1)
    sub('<rect width="512" height="512" fill="#6DB8A8"/>', f'<rect x="{o}" y="{o}" width="{e}" height="{e}" fill="#6DB8A8"/>', 1)
    s, n = re.subn(r'<rect width="512" height="512" fill="url\(#(canti_\w+-(?:shell|bdown))\)"/>',
                   lambda m: f'<rect x="{o}" y="{o}" width="{e}" height="{e}" fill="url(#{m.group(1)})"/>', s)
    assert n == 2, n
    s, n = re.subn(r'<rect y="200" width="512" height="312" fill="url\(#(canti_\w+-bside)\)"/>',
                   lambda m: f'<rect x="{o}" y="200" width="{e}" height="{fmt(SRC[0] + SRC[1] - 200)}" fill="url(#{m.group(1)})"/>', s)
    assert n == 1, n
    # the brim's shading (a vertical gradient: light at the top, darker toward the lip) follows the lip past the box:
    # outside 0..512 it is sheared by the brim's slope, so it keeps its distance to the dropping lower edge
    m = re.search(r'<use href="#(canti_\w+)-hood" fill="url\(#(canti_\w+-brim)\)"/>', s)
    pre, grad = m.group(1), m.group(2)
    k = fmt(BRIM_SLOPE)
    sheared = (f'<g clip-path="url(#{pre}-hoodclip)">'
               f'<rect x="{o}" y="{o}" width="128" height="{e}" fill="url(#{grad})" transform="matrix(1 -{k} 0 1 0 0)"/>'
               f'<rect x="512" y="{o}" width="128" height="{e}" fill="url(#{grad})" transform="matrix(1 {k} 0 1 0 {fmt(-512 * BRIM_SLOPE)})"/>'
               f'<rect x="0" y="{o}" width="512" height="{e}" fill="url(#{grad})"/></g>')
    s = s[:m.start()] + sheared + s[m.end():]
    return s


def _sources(state):
    """The master icon over SRC (extended_master) and the flat label render. Inside the 512 box the v4 source (the
    master as drawn) is kept wherever the flat surface is the same as v4's, so the box dithers exactly as before
    except where the shapes changed (the old curled brim tips)."""
    if state not in _CACHE:
        src = os.path.join(BRAND, "canti-icon.svg" if state == "on" else "canti-icon-off.svg")
        with open(src) as f:
            text = f.read()
        col, lsvg = label_svg()
        lab = rsvg(lsvg, HIRES)
        orig = rsvg(extended_master(text), HIRES)
        box = rsvg(text, 2048)
        _, lsvg4 = label_svg(HOOD_V4, TRIM_V4, CROWN_V4, view=(0.0, 512.0))
        lab4 = rsvg(lsvg4, 2048)
        a = int(round(-SRC[0] * HIRES / SRC[1]))
        assert HIRES * 512 == 2048 * SRC[1] and a + 2048 <= HIRES
        same = np.all(np.abs(lab[a:a + 2048, a:a + 2048, :3] - lab4[..., :3]) < 1.5 / 255, axis=-1)
        win = orig[a:a + 2048, a:a + 2048]
        win[same] = box[same]
        inbox = np.zeros(lab.shape[:2], dtype=bool)
        inbox[a:a + 2048, a:a + 2048] = True
        _CACHE[state] = (orig, col, lab, inbox)
    return _CACHE[state]


EYE_ARC = (44.0, math.radians(62), 11.0, 5.5, 361.0)   # mid-line radius, half span, half thickness crown/tips, centre y
EYES = ((180.0, 5.0), (332.0, -5.0))                    # eye centre x, tilt (degrees, SVG sense) about (x, 334)


def crescent_outline(cx, rot, n=24):
    """One eye's crescent outline as a polygon in icon units (the same shape [crescents] fills)."""
    R, S, H0, H1, CY = EYE_ARC
    local = []
    ths = np.linspace(-S, S, 2 * n)
    h = lambda th: H1 + (H0 - H1) * math.cos(th / S * math.pi / 2)
    for th in ths:                                                   # outer edge, left to right
        local.append(((R + h(th)) * math.sin(th), -(R + h(th)) * math.cos(th)))
    for sgn in (1, -1):
        th = sgn * S
        c = (R * math.sin(th), -R * math.cos(th))
        nrm, tan = (math.sin(th), -math.cos(th)), (math.cos(th), math.sin(th))
        for phi in np.linspace(0, math.pi, n)[1:-1]:                  # round cap, outer to inner
            a, b = math.cos(phi), math.sin(phi) * sgn
            local.append((c[0] + H1 * (nrm[0] * a + tan[0] * b), c[1] + H1 * (nrm[1] * a + tan[1] * b)))
        if sgn == 1:
            for th2 in ths[::-1]:                                     # inner edge, right to left
                local.append(((R - h(th2)) * math.sin(th2), -(R - h(th2)) * math.cos(th2)))
    a = math.radians(rot)
    pts = []
    for ux, uy in local:
        dx, dy = 1.17 * ux, 1.17 * (uy + CY - 334.0)
        pts.append((cx + dx * math.cos(a) - dy * math.sin(a), 334.0 + dx * math.sin(a) + dy * math.cos(a)))
    return pts


def crescents(g, ss=4):
    """Cells of grid g that are more than half covered by an eye crescent (ss x ss supersampling).

    One eye, in the original eye's own frame (before its 1.17 scale and 5 degree tilt about (cx, 334)): a thick
    arc around (cx, 361) with a mid-line radius of 44, spanning 62 degrees either side of straight up. Its half
    thickness tapers from 11 at the crown to 5.5 at the ends, which are round caps. So: a domed top at y 306, an
    underside arching up to y 328 in the middle, rounded tips down at about y 346, 89 units wide."""
    R, SPAN, H0, H1, CY = EYE_ARC
    off = (np.arange(ss) + 0.5) / ss
    cov = np.zeros(g.cx.shape)
    for oy in off:
        for ox in off:
            x = g.cx + (ox - 0.5) * g.c
            y = g.cy + (oy - 0.5) * g.c
            hit = np.zeros(g.cx.shape, dtype=bool)
            for cx, rot in EYES:
                a = math.radians(-rot)    # undo the tilt, then the scale, about (cx, 334)
                dx, dy = x - cx, y - 334.0
                ux = (dx * math.cos(a) - dy * math.sin(a)) / 1.17
                uy = (dx * math.sin(a) + dy * math.cos(a)) / 1.17 + 334.0 - CY
                r = np.hypot(ux, uy)
                th = np.arctan2(ux, -uy)                      # 0 = straight up
                h = H1 + (H0 - H1) * np.cos(np.clip(th / SPAN, -1, 1) * math.pi / 2)
                band = (np.abs(th) <= SPAN) & (np.abs(r - R) <= h)
                for sgn in (-1, 1):                           # round caps
                    tx, ty = sgn * R * math.sin(SPAN), -R * math.cos(SPAN)
                    band |= np.hypot(ux - tx, uy - ty) <= H1
                hit |= band
            cov += hit
    return cov / (ss * ss) > 0.5


_SHAPES = {}


def coverage(shapes, g):
    """Per-cell coverage (0..1) of grid g by SVG `shapes` (icon units, rendered over g's source canvas)."""
    key = (shapes, g.src, g.hires)
    if key not in _SHAPES:
        o, e = g.src
        img = rsvg(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(o)} {fmt(o)} {fmt(e)} {fmt(e)}"><g fill="#000">{shapes}</g></svg>', g.hires)
        _SHAPES[key] = img[..., 3]
    a = _SHAPES[key]
    s, cnt = g.cell_mean(a, np.ones(a.shape, dtype=bool))
    return np.where(cnt > 0, s, 0.0)


def cells_of(shapes, g, thr=0.5):
    """Cells more than `thr` covered; a shape too small for that still gets its best-covered cell."""
    cov = coverage(shapes, g)
    m = cov > thr
    if not m.any() and cov.max() > 0:
        m = cov == cov.max()
    return m


def edge4(m, border=False):
    """Cells of m with a 4-neighbour outside m (the one-cell pixel contour). border=True: past the canvas counts as
    inside m, so a shape that runs off the canvas gets no contour along the canvas edge."""
    p = np.pad(m, 1, constant_values=border)
    inner = p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return m & ~inner


def near4(m):
    p = np.pad(m, 1, constant_values=False)
    return p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:] | m


def bezier_points(d, per=200):
    """Dense points along an absolute M/C-only path."""
    t = d.replace("M", " M ").replace("C", " C ").split()
    pts, cur, k = [], None, 0
    while k < len(t):
        if t[k] == "M":
            cur = (float(t[k + 1]), float(t[k + 2])); k += 3; pts.append(cur)
        elif t[k] == "C":
            p = [cur] + [(float(t[k + 1 + 2 * q]), float(t[k + 2 + 2 * q])) for q in range(3)]
            for s in np.linspace(0, 1, per)[1:]:
                u = 1 - s
                pts.append(tuple(u ** 3 * np.array(p[0]) + 3 * u * u * s * np.array(p[1]) + 3 * u * s * s * np.array(p[2]) + s ** 3 * np.array(p[3])))
            cur = p[3]; k += 7
        else:
            k += 1
    return np.array(pts)


def blend(img, m, color, a=1.0):
    c = hexrgb(color)
    img[m] = img[m] * (1 - a) + c * a


def surface_tones(g, L, m, ntones, base, shade, ref=None, ref_mask=None):
    """Cartoon shading of one surface on grid g: each cell's mean luminance (L over the surface's pixels m, both at
    the source resolution) against the surface's reference (its median unless given), `shade` = (luminance per tone
    step down, per step up, dead zone), dithered with the Bayer matrix into tone indices 0..ntones-1 (flat `base`
    inside the dead zone). Also used by canti_sprite.py for the badge character's body."""
    mean, cnt = g.cell_mean(L, m)
    if ref is None:   # the median over the part inside ref_mask (the 512 box: as v4) when given
        rm = m & ref_mask if ref_mask is not None and (m & ref_mask).any() else m
        ref = np.median(L[rm])
    down, upv, dz = shade
    d = mean - ref
    t = np.where(d < 0, d / down, d / upv)
    mag = np.clip((np.abs(t) - dz) / (1 - dz), 0, ntones)
    tone = np.full(g.cx.shape, base)
    for ti in range(ntones):
        if ti == base:
            continue
        steps = abs(ti - base)
        sign = -1 if ti < base else 1
        want = (cnt > 0) & (np.sign(t) == sign) & g.dither(np.clip(mag - (steps - 1), 0, 1))
        tone = np.where(want, ti, tone)
    return tone


def icon_raster(state="on", cell=8.0, fine=4.0, origin=0.0, extent=512.0):
    """The stipple icon as pixels: an RGB image on the fine grid (pitch `fine`, `cell` / fine an integer) plus the
    owner map (which surface each fine cell belongs to). Every edge is a fine-cell edge; dither dots are whole cells
    of the stipple grid (pitch `cell`)."""
    on = state == "on"
    k = int(round(cell / fine))
    assert abs(k * fine - cell) < 1e-6, (cell, fine)
    orig, col, lab, inbox = _sources(state)
    g = Grid(cell, origin, extent, HIRES, SRC)    # stipple dots
    f = Grid(fine, origin, extent, HIRES, SRC)    # shape edges, eyes, lamp, trim
    L = lum(orig[..., :3])
    px = np.round(lab[..., :3] * 255).astype(int)

    def mask_of(name):
        c = hexrgb(col[name]) * 255
        return np.all(np.abs(px - c) < 1.5, axis=-1)

    # owner of each fine cell: the surface covering most of it in the flat label render (outside the icon: body)
    ones = np.ones(L.shape)
    counts = np.stack([f.cell_mean(ones, mask_of(n))[1] for n in LABELS])
    owner_names = [{"eyes": "glass", "trim": "hood", "lamp": "hood"}.get(n, n) for n in LABELS]
    owner = np.array(owner_names, dtype=object)[np.argmax(counts, axis=0)]
    owner[counts.sum(axis=0) == 0] = "body"
    is_ = lambda *names: np.isin(owner, names)

    def up(a):                                # stipple grid -> fine grid
        return np.repeat(np.repeat(a, k, 0), k, 1)[:f.n, :f.n]

    # v5b: the crown (the dome's outline) is snapped to whole stipple dots, so its long steep edge steps visibly
    # (a fine-cell staircase at that slope reads as a smooth line at launcher sizes)
    crown_g = cells_of(f'<path d="{CROWN}"/>', g)
    crown_f = up(crown_g)
    owner[(owner == "crown") & ~crown_f] = "hood"
    owner[(owner == "hood") & crown_f] = "crown"

    img = np.zeros((f.n, f.n, 3))
    # surfaces: base tone, dither dots of the lighter/darker tones (from the original's shading, as before)
    for name, (tones, base, _shape) in SURFACES.items():
        tone = surface_tones(g, L, mask_of(name), len(tones), base, SHADE[name], ref_mask=inbox)
        own = is_(name) if name != "glass" else is_("glass")
        tf = up(tone)
        for ti, c in enumerate(tones):
            blend(img, own & (tf == ti), c)

    # crown shading (v5b): ordered dither by distance to the dome's edge, one lighter and one darker tone (teal /
    # teal-deep over the teal-shade base): a dithered transition band along the edge, deeper toward the far corners
    blend(img, crown_dither(g, crown_g, up, TEAL, lighter=True) & is_("crown"), TEAL)
    blend(img, crown_dither(g, crown_g, up, TEAL_DEEP, lighter=False) & is_("crown"), TEAL_DEEP)

    glass = is_("glass", "shadow")
    # deep brim shadow: a hard cel shadow
    blend(img, is_("shadow"), "#171B33")
    # eyes: rounded crescents on the fine grid, lit/dim scanline rows; on: a one-cell dim halo hugging them
    eye = crescents(f) & glass
    rows = np.arange(f.n)[:, None] % 2 == 0
    lit_c, dim_c = (GLOW, "#58969B") if on else ("#262E5E", "#1A1F42")
    if on:
        halo = np.zeros_like(eye)
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                halo |= np.roll(np.roll(eye, dj, 0), di, 1)
        blend(img, halo & ~eye & glass, "#355573")
    blend(img, eye & rows, lit_c)
    blend(img, eye & ~rows, dim_c)
    # shine: a pixel lens under the brim; stipple falloff (screen-glow, then mint) around stepped solid cores
    sh = field_shine(g)
    blend(img, glass & up(g.dither(np.clip(sh * 1.6, 0, 1)) & (sh < 0.62) & (sh > 0)), GLOW, 0.5)
    blend(img, glass & up(g.dither(np.clip((sh - 0.25) * 2.2, 0, 1)) & (sh > 0.25)), MINT, 0.8)
    blend(img, glass & cells_of('<path d="M214 211.5 Q256 199 298 211.5 Q256 215 214 211.5 Z"/>', f, 0.4), "#DDEBD3", 0.85)
    blend(img, glass & cells_of('<path d="M234 209.8 Q256 203 278 209.8 Q256 212.2 234 209.8 Z"/>', f, 0.4), "#F4FFFB")
    blend(img, glass & cells_of('<ellipse cx="256" cy="208.6" rx="7" ry="1.5"/>', f, 0.4), "#FFFFFF")

    # gold trim on the brim's lip: two one-cell pixel contours of the brim along its lower edge (teal, then gold)
    hood = is_("hood")
    # the trim's contour: the lower silhouette of everything above the lip (hood, lamp, crown), so it stays one clean
    # stepped line where the crown comes down to meet the brim at the layer's edge
    above = is_("hood", "crown")
    trim_pts = bezier_points(TRIM)
    band = np.zeros(f.cx.shape, dtype=bool)
    cand = above & (f.cy > 150)
    jj, ii = np.nonzero(cand)
    if len(jj):
        dx = f.cx[jj, ii][:, None] - trim_pts[None, :, 0]
        dy = f.cy[jj, ii][:, None] - trim_pts[None, :, 1]
        d2 = dx * dx + dy * dy
        near = np.argmin(d2, axis=1)
        keep = (np.sqrt(d2[np.arange(len(jj)), near]) < max(14.0, 3 * fine)) & (near > 0) & (near < len(trim_pts) - 1)
        band[jj[keep], ii[keep]] = True
    ring1 = edge4(above, True) & band
    ring2 = edge4(above & ~ring1, True) & near4(ring1) & band & ~ring1
    blend(img, ring1, TEAL)
    blend(img, ring2, "#F4C84A")

    # lamp: pixel discs (socket ring, bulb), a stepped highlight and shade, one-cell specular; on: dotted halo
    lamp_socket = cells_of('<circle cx="370" cy="104" r="27"/>', f)
    bulb = cells_of('<circle cx="370" cy="104" r="19"/>', f)
    if on:
        hf = posterize(field_halo(g), [(0.75, 0.5), (0.3, 0.25)])
        blend(img, up(g.dither(hf)) & is_("hood", "crown") & ~lamp_socket, "#C9C470")
    blend(img, lamp_socket, TEAL_SHADE)
    if on:
        blend(img, bulb, ORANGE)
        blend(img, bulb & cells_of('<path d="M370 123 A19 19 0 0 0 389 104 A19 19 0 0 1 376 117 Z"/>', f, 0.35), "#D98A22")
        blend(img, bulb & cells_of('<path d="M357 104 A13 13 0 0 1 370 91 A17 17 0 0 0 357 104 Z"/>'
                                   '<path d="M361 101 A10 10 0 0 1 373 92 A12.5 12.5 0 0 0 361 101 Z"/>', f, 0.2), "#FFF1CF")
        blend(img, bulb & cells_of('<ellipse cx="364" cy="97" rx="4" ry="3" transform="rotate(-40 364 97)"/>', f), "#FFFFFF")
    else:
        blend(img, bulb, "#7A5530")
        blend(img, edge4(bulb), "#5E4228")
        blend(img, bulb & cells_of('<ellipse cx="364" cy="97" rx="3.5" ry="2.5" transform="rotate(-40 364 97)"/>', f), MINT, 0.35)
    return img, owner


# (distance to the dome's edge in dots, density), nearest first: the edge row of dots stays solid so the stepped
# outline stays crisp, then a checker, then thinning dots (like the hood's own band above the brim)
CROWN_LIGHT = [(0.5, 0.0), (1.5, 0.5), (2.5, 0.25), (3.5, 0.0625)]
CROWN_DARK = [(56.0, 0.0), (96.0, 0.125), (144.0, 0.25), (1e9, 0.5)]   # (units from the edge, density)


def crown_dither(g, crown_g, up, _color, lighter):
    """Cells (fine grid) of one crown tone: posterised density by each dot's distance to the dome's edge (the crown's
    dot cells next to a non-crown cell, not counting the canvas border), 4x4 Bayer on the dot grid."""
    edge = edge4(crown_g, True)
    ej, ei = np.nonzero(edge)
    cj, ci = np.nonzero(crown_g)
    d = np.full(crown_g.shape, np.inf)
    if len(ej):
        for s0 in range(0, len(cj), 4096):
            a, b = cj[s0:s0 + 4096], ci[s0:s0 + 4096]
            dd = np.min((a[:, None] - ej[None, :]) ** 2 + (b[:, None] - ei[None, :]) ** 2, axis=1)
            d[a, b] = np.sqrt(dd) * g.c
    dens = np.zeros(crown_g.shape)
    if lighter:
        for lim, v in reversed(CROWN_LIGHT):
            dens = np.where(d / g.c < lim, v, dens)
    else:
        for lim, v in reversed(CROWN_DARK):
            dens = np.where(d < lim, v, dens)
    return up(crown_g & g.dither(dens))


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in rgb)


def icon_svg(state="on", cell=8.0, origin=0.0, extent=512.0, parts="all", size=None, eye_cell=None):
    """The stipple icon as SVG: nothing but squares on the pixel grid (runs merged per colour). `origin`/`extent` set
    the canvas in icon units; parts: "all", "bg" (the body only) or "fg" (everything but the body)."""
    fine = eye_cell or cell / 2
    img, owner = icon_raster(state, cell, fine, origin, extent)
    on = state == "on"
    body_only = parts == "bg"
    if body_only:
        # the body continues under everything else
        img2, _ = icon_raster(state, cell, fine, origin, extent)
    alpha = np.ones(owner.shape, dtype=bool)
    if parts == "fg":
        alpha = owner != "body"
    q = np.round(img * 255).astype(int)
    key = (q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]
    vals, counts = np.unique(key[alpha], return_counts=True)
    bgk = vals[np.argmax(counts)]
    out = []
    if parts != "fg":
        out.append(f'<rect x="{fmt(origin)}" y="{fmt(origin)}" width="{fmt(extent)}" height="{fmt(extent)}" fill="#{bgk:06X}"/>')
    for v in vals:
        if v == bgk and parts != "fg":
            continue
        jj, ii = np.nonzero(alpha & (key == v))
        out.append(f'<path fill="#{v:06X}" d="{squares(list(zip(ii, jj)), fine, origin)}"/>')
    what = ("ON state (default; shown while paired/connected): eyes lit, lamp lit with a dotted halo"
            if on else "OFF state (not paired/connected): eyes dark, lamp unlit")
    wh = size or int(extent)
    body = "\n  ".join(out)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(origin)} {fmt(origin)} {fmt(extent)} {fmt(extent)}" width="{wh}" height="{wh}" shape-rendering="crispEdges">
  <title>Canti</title>
  <!-- Stipple app icon, {what}.
       Same design and palette as canti-icon{'' if on else '-off'}.svg, as pixel art: every edge, line and highlight
       is whole cells of a {fmt(fine)}-unit grid, and the shading is ordered-dither stipple (4x4 Bayer) in whole
       {fmt(cell)}-unit dots (2 x 2 cells) between 2-3 cel tones per surface. Only squares: no curves, filters,
       gradients or masks. Generated by tools/stipple.py. -->
  {body}
</svg>
"""


def sub_px(dot_px):
    """Fine-grid pitch in device px for a dot of dot_px: half the dot when that is a whole pixel, else 1 px."""
    return dot_px // 2 if dot_px % 2 == 0 else 1



# ------------------------------------------------------------------------------------------------ the wordmark

LETTERS = [
    "M 86 0 H 44 A 44 44 0 0 0 0 44 V 56 A 44 44 0 0 0 44 100 H 66 V 74 H 44 A 18 18 0 0 1 26 56 V 44 A 18 18 0 0 1 44 26 H 69.35 A 50 50 0 0 1 86 4 V 0 Z",
    "M 72 100 V 44 A 44 44 0 0 1 116 0 H 120 A 44 44 0 0 1 164 44 V 100 H 138 V 44 A 18 18 0 0 0 120 26 H 116 A 18 18 0 0 0 98 44 V 100 Z",
    "M 170 100 V 32 H 210 A 44 44 0 0 1 254 76 V 100 H 228 V 76 A 18 18 0 0 0 210 58 H 196 V 100 Z",
    "M 220 0 H 304 V 26 H 286 V 100 H 260 V 26 H 220 Z",
    "M 310 0 h 26 v 100 h -26 Z",
]
BAR = "M 104 58 h 28 v 18 h -28 Z"
WM_VIEW = (-10.0, -10.0, 356.0, 163.5)


def subtitle(fill):
    """The [ HUM · SING · SWIPE ] paths, verbatim from canti-wordmark.svg, recoloured."""
    with open(os.path.join(BRAND, "canti-wordmark.svg")) as f:
        src = f.read()
    a = src.index("<path d=\"M 41.1 121.5")
    b = src.index("</g>", a)
    filled = src[a:b].strip()
    c = src.index('<g fill="none"', b)
    d = src.index("</g>", c) + 4
    stroked = src[c:d].replace("#16192B", fill)
    return f'<g fill="{fill}">{filled}</g>\n  {stroked}'


FALLOFF = [15, 14, 13, 12, 11, 10, 9, 8]  # sixteenths per cell row under the solid tops; then 8/16 to the baseline
HANG = [10, 6, 3, 1]                      # sixteenths per cell row hanging under a top stroke's underside (v5: shorter, sparser)


def wordmark_svg(fill=INK, cell=4.0, depth=10.0, solid_to=50.0, light=False):
    """Solid letter tops over an ordered-dither lower part, standing on dithered pillars that dissolve.

    Face: solid down to y = `solid_to` (a cell edge) plus a seeded 0-2 cell offset per column, then one density
    per cell row from FALLOFF (15/16, 14/16 ... 8/16, held to the baseline), thresholded with the 8x8 Bayer matrix so
    the first holes stagger over several rows instead of lining up. Dots are whole cells clipped to the letters.
    Hang: under the undersides of the top strokes (the C's arm, the A's arch, the T's bar, the n's shoulder) the
    ink crumbles a little into the counters: HANG densities per row (10/16, 6/16, 3/16, 1/16), each column's run
    lengthened by a seeded 0-1 cell, 8x8 Bayer.
    Pillar: the letters swept `depth` units straight down; 6/16 dots for the first half, 3/16 for the rest, then a
    few 1/16 dots below the baseline, so the bottom edge dissolves. The A's floating bar stays solid."""
    ox, oy, w, h = WM_VIEW
    hires = 8  # px per unit for the coverage tests
    W, H = int(w * hires), int(h * hires)
    letters = "".join(f'<path d="{d}"/>' for d in LETTERS)
    face_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{ox} {oy} {w} {h}" width="{W}" height="{H}">'
                f'<g fill="#000">{letters}<path d="{BAR}"/></g></svg>')
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "f.svg")
        pp = os.path.join(td, "f.png")
        open(sp, "w").write(face_svg)
        subprocess.run(["rsvg-convert", sp, "-o", pp], check=True)
        face = np.asarray(Image.open(pp).convert("RGBA"))[..., 3] > 127

    nx, ny = int(math.ceil(w / cell)), int(math.ceil(h / cell))
    xs = ox + (np.arange(nx) + 0.5) * cell
    ys = oy + (np.arange(ny) + 0.5) * cell
    CX, CY = np.meshgrid(xs, ys)

    def inside(x, y):
        px = np.clip(((x - ox) * hires).astype(int), 0, W - 1)
        py = np.clip(((y - oy) * hires).astype(int), 0, H - 1)
        ok = (x >= ox) & (x < ox + w) & (y >= oy) & (y < oy + h)
        return face[py, px] & ok

    th = THRESH[np.arange(ny)[:, None] % 4, np.arange(nx)[None, :] % 4]
    th8 = THRESH8[np.arange(ny)[:, None] % 8, np.arange(nx)[None, :] % 8]
    infc = inside(CX, CY)
    jit = column_jitter(nx, 2)[None, :]
    row = np.floor((CY - solid_to) / cell) - jit
    seq = np.array(FALLOFF, dtype=float) / 16.0
    dens = np.where(row < 0, 1.0, seq[np.clip(row, 0, len(seq) - 1).astype(int)])
    face_dots = infc & (CY > solid_to) & (dens > th8)   # rows above a column's falloff start are solid (1.0)
    # depth below the nearest face straight above (units)
    dep = np.full(CX.shape, np.inf)
    for k in np.arange(0.5, 60.0, 0.5)[::-1]:
        dep = np.where(inside(CX, CY - k), k, dep)
    free = ~infc
    edge_y = CY - dep                      # where the ink above ends
    # a counter or gap: ink further below, or ink on both sides within 30 units (not the open outside of a letter)
    below = np.zeros(CX.shape, dtype=bool)
    for k in np.arange(2.0, 80.0, 2.0):
        below |= inside(CX, CY + k)
    left = np.zeros(CX.shape, dtype=bool)
    right = np.zeros(CX.shape, dtype=bool)
    for k in np.arange(2.0, 30.0, 2.0):
        left |= inside(CX - k, CY)
        right |= inside(CX + k, CY)
    enclosed = below | (left & right)
    top_stroke = free & np.isfinite(dep) & (edge_y < 60) & enclosed
    hrow = np.floor(dep / cell) - column_jitter(nx, 1, seed=11)[None, :]
    hseq = np.array(HANG, dtype=float) / 16.0
    hd = np.where(hrow < 0, hseq[0], hseq[np.clip(hrow, 0, len(hseq) - 1).astype(int)])
    hd = np.where(hrow >= len(hseq), 0.0, hd)
    hang = top_stroke & (hd > th8)
    # pillars under the letters' feet (unchanged): the rest of the free cells below ink
    feet = free & np.isfinite(dep) & ~top_stroke & (dep <= depth + 8)
    pd = np.where(dep <= depth * 0.5, 0.375, np.where(dep <= depth, 0.1875, np.where(dep <= depth + 8, 1 / 16.0, 0)))
    pd = np.where(CY > 100 + depth, np.where(dep <= depth + 8, 1 / 16.0, 0), pd)
    pillar = (feet & (pd > th)) | hang
    # the A bar sits in front, solid: no pillar under it inside the A's counter
    pillar &= ~((CX > 100) & (CX < 136) & (CY > 76) & (CY < 100))

    def cells(mask):
        return [(i, j) for j, i in zip(*np.nonzero(mask))]

    def sq(cs):
        out = []
        rows = {}
        for i, j in cs:
            rows.setdefault(j, []).append(i)
        for j in sorted(rows):
            xs_ = sorted(rows[j])
            start = prev = xs_[0]
            for x in xs_[1:] + [None]:
                if x is not None and x == prev + 1:
                    prev = x
                    continue
                out.append(f"M{fmt(ox + start * cell)} {fmt(oy + j * cell)}h{fmt((prev - start + 1) * cell)}v{fmt(cell)}h{fmt(-(prev - start + 1) * cell)}z")
                if x is not None:
                    start = prev = x
        return "".join(out)

    uid = "wml" if light else "wm"
    name = "canti-wordmark-stipple-light.svg" if light else "canti-wordmark-stipple.svg"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(ox)} {fmt(oy)} {fmt(w)} {fmt(h)}" width="{int(w * 2)}" height="{int(h * 2)}">
  <title>Canti</title>
  <!-- {name}: the Canti wordmark (same letterforms as canti-wordmark.svg) in ordered-dither stipple, {fill} on
       transparent{', for dark backgrounds' if light else ''}. Solid tops that fall off into a regular dot grid toward
       the baseline (15/16 ... 8/16 per cell row, 8x8 Bayer, staggered per column), ink crumbling off the undersides of
       the top strokes, and dithered pillars that dissolve below the baseline (4x4 Bayer). Square dots on a
       {fmt(cell)}-unit grid, whole cells, clipped to the letters. The A's floating bar
       and the subtitle stay solid. Paths only. Generated by tools/stipple.py. -->
  <defs>
    <clipPath id="{uid}-face">{letters}<path d="{BAR}"/></clipPath>
    <clipPath id="{uid}-top"><rect x="{fmt(ox)}" y="{fmt(oy)}" width="{fmt(w)}" height="{fmt(solid_to - oy)}"/></clipPath>
  </defs>
  <g fill="{fill}">
    <g clip-path="url(#{uid}-top)">{letters}</g>
    <path d="{BAR}"/>
    <path clip-path="url(#{uid}-face)" d="{sq(cells(face_dots))}"/>
    <path d="{sq(cells(pillar))}"/>
  </g>
  {subtitle(fill)}
</svg>
"""


def icon_png(state, size, dot_px, out_png, parts="all", canvas=(0.0, 512.0)):
    """The stipple icon at `size` px, pixel-exact (no resampling): dots of `dot_px` device px, edges on a grid of
    sub_px(dot_px) px."""
    origin, extent = canvas
    sp = sub_px(dot_px)
    img, owner = icon_raster(state, dot_px * extent / size, sp * extent / size, origin, extent)
    a = np.ones(owner.shape) if parts != "fg" else (owner != "body").astype(float)
    if parts == "bg":
        img = img.copy()
    rgba = np.concatenate([img, a[..., None]], axis=-1)
    rgba = np.repeat(np.repeat(rgba, sp, 0), sp, 1)[:size, :size]
    Image.fromarray(np.round(rgba * 255).astype(np.uint8), "RGBA").save(out_png, optimize=True)


# Android adaptive launcher icon: 108 dp layers; the icon's 512 units are the 72 dp a launcher shows, so the layer
# canvas is -128..640. Dot size per density, in device px: the brand grid (8 units = 1.125 dp) rounded to whole pixels.
DENSITIES = [("mdpi", 1.0, 1), ("hdpi", 1.5, 2), ("xhdpi", 2.0, 2), ("xxhdpi", 3.0, 3), ("xxxhdpi", 4.0, 4)]
ADAPTIVE = (-128.0, 768.0)


def launcher(res_dir):
    for name, dens, dot in DENSITIES:
        size = int(round(108 * dens))
        d = os.path.join(res_dir, f"mipmap-{name}")
        os.makedirs(d, exist_ok=True)
        icon_png("on", size, dot, os.path.join(d, "ic_launcher_bg.png"), parts="bg", canvas=ADAPTIVE)
        for st in ("on", "off"):
            icon_png(st, size, dot, os.path.join(d, f"ic_launcher_{st}_fg.png"), parts="fg", canvas=ADAPTIVE)
        # optimise the PNGs losslessly (palette where it fits)
        for f in os.listdir(d):
            if f.startswith("ic_launcher_") and f.endswith(".png"):
                fp = os.path.join(d, f)
                im = Image.open(fp)
                im.save(fp, optimize=True)
        print("wrote", d, size, "px, dots", dot, "px")
    launcher_xml(res_dir)


def rrect_path(x, y, w, h, r):
    return (f"M{fmt(x + r)} {fmt(y)} H{fmt(x + w - r)} A{fmt(r)} {fmt(r)} 0 0 1 {fmt(x + w)} {fmt(y + r)} V{fmt(y + h - r)} "
            f"A{fmt(r)} {fmt(r)} 0 0 1 {fmt(x + w - r)} {fmt(y + h)} H{fmt(x + r)} A{fmt(r)} {fmt(r)} 0 0 1 {fmt(x)} "
            f"{fmt(y + h - r)} V{fmt(y + r)} A{fmt(r)} {fmt(r)} 0 0 1 {fmt(x + r)} {fmt(y)} Z")


def circle_path(cx, cy, r):
    return (f"M{fmt(cx - r)} {fmt(cy)} A{fmt(r)} {fmt(r)} 0 1 1 {fmt(cx + r)} {fmt(cy)} "
            f"A{fmt(r)} {fmt(r)} 0 1 1 {fmt(cx - r)} {fmt(cy)} Z")


# The part of the icon below the hood's lip (the glass shows only there).
BELOW_HOOD = "M0 162 C0 202 4 232 18 232 C58 222 116 172 256 172 C396 172 454 222 494 232 C508 232 512 202 512 162 V512 H0 Z"


def mono_paths(state):
    """The themed (monochrome) icon: one colour, shape only. The screen (below the brim) with the two crescent eyes cut
    out, and the lamp: a disc when on, a ring when off. Icon units; even-odd fills."""
    eyes = " ".join("M" + " L".join(f"{fmt(x)} {fmt(y)}" for x, y in crescent_outline(cx, rot)) + " Z" for cx, rot in EYES)
    screen = rrect_path(54, 96, 404, 356, 128) + " " + eyes
    lamp = circle_path(370, 104, 27) + ("" if state == "on" else " " + circle_path(370, 104, 16))
    return screen, lamp


def mono_xml(state):
    screen, lamp = mono_paths(state)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by brand/tools/stipple.py (launcher): the themed-icon layer, {state} state. Do not edit. -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp" android:viewportWidth="768" android:viewportHeight="768">
    <group android:translateX="128" android:translateY="128">
        <clip-path android:pathData="{BELOW_HOOD}"/>
        <path android:fillColor="#FFFFFFFF" android:fillType="evenOdd" android:pathData="{screen}"/>
    </group>
    <group android:translateX="128" android:translateY="128">
        <path android:fillColor="#FFFFFFFF" android:fillType="evenOdd" android:pathData="{lamp}"/>
    </group>
</vector>
"""


def mono_svg(state):
    screen, lamp = mono_paths(state)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-128 -128 768 768">
<clipPath id="b"><path d="{BELOW_HOOD}"/></clipPath>
<rect x="-128" y="-128" width="768" height="768" fill="#DCE8E4"/>
<path clip-path="url(#b)" fill="#1B3A35" fill-rule="evenodd" d="{screen}"/>
<path fill="#1B3A35" fill-rule="evenodd" d="{lamp}"/></svg>"""


def adaptive_xml(state):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by brand/tools/stipple.py (launcher): the {state} launcher icon (activity-alias .Launcher{state.capitalize()}). -->
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_bg"/>
    <foreground android:drawable="@mipmap/ic_launcher_{state}_fg"/>
    <monochrome android:drawable="@drawable/ic_launcher_mono_{state}"/>
</adaptive-icon>
"""


def launcher_xml(res_dir):
    for sub in ("drawable", "mipmap-anydpi-v26"):
        os.makedirs(os.path.join(res_dir, sub), exist_ok=True)
    for st in ("on", "off"):
        with open(os.path.join(res_dir, "drawable", f"ic_launcher_mono_{st}.xml"), "w") as f:
            f.write(mono_xml(st))
        with open(os.path.join(res_dir, "mipmap-anydpi-v26", f"ic_launcher_{st}.xml"), "w") as f:
            f.write(adaptive_xml(st))
    print("wrote adaptive icon and monochrome XML in", res_dir)


APP_ICON_SCALES = range(1, 5)   # device px per icon dot: the app draws n = round(devicePixelRatio), 48 dots across
APP_WM_SCALES = range(1, 9)     # device px per wordmark cell: the kit's art pixel k = round(2 x devicePixelRatio)


def app_assets(out_dir):
    """Pixel-exact PNGs for the Flutter app (ui/assets/brand), one per whole-pixel scale, so the app draws each 1:1
    at a size that is a whole number of device pixels per dot (ui/lib/src/theme/assets.dart, BrandArt) and nothing is
    resampled:
      * canti-icon-on|off@n.png: the icon, 48 dots across, dots of n device px (48n px square), n = 1..4;
      * canti-wordmark[-light]@k.png: the stipple wordmark, 89 x 41 cells (a 4-unit cell; the viewBox is 356 x 164),
        cells of k device px (89k x 41k px), k = 1..8. One cell is one art pixel of the app's pixel kit."""
    os.makedirs(out_dir, exist_ok=True)
    for n in APP_ICON_SCALES:
        for st in ("on", "off"):
            icon_png(st, 48 * n, n, os.path.join(out_dir, f"canti-icon-{st}@{n}.png"))
    ox, oy, w, h = WM_VIEW
    for light in (False, True):
        svg = wordmark_svg(MINT if light else INK, light=light)
        # a whole number of cells tall (164 units = 41 cells), and the document size set to exactly 89k x 41k px: with
        # the viewBox and the size in the same ratio the scale is k/4 px per unit on both axes and every cell lands on
        # whole pixels (a mismatch would letterbox the viewBox and shift the cells by a fraction of a pixel)
        view = f'viewBox="{fmt(ox)} {fmt(oy)} {fmt(w)} {fmt(h)}" width="{int(w * 2)}" height="{int(h * 2)}"'
        assert view in svg
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "wm.svg")
            for k in APP_WM_SCALES:
                with open(src, "w") as f:
                    f.write(svg.replace(view, f'viewBox="{fmt(ox)} {fmt(oy)} {fmt(w)} 164" width="{89 * k}" height="{41 * k}"', 1))
                dst = os.path.join(out_dir, f"canti-wordmark{'-light' if light else ''}@{k}.png")
                subprocess.run(["rsvg-convert", src, "-o", dst], check=True)
                Image.open(dst).save(dst, optimize=True)
    print("wrote", out_dir)


def main(argv):
    what = argv[1] if len(argv) > 1 else "all"
    out = argv[2] if len(argv) > 2 else BRAND
    if what in ("icon", "all"):
        for st in ("on", "off"):
            name = "canti-icon-stipple.svg" if st == "on" else "canti-icon-stipple-off.svg"
            with open(os.path.join(out, name), "w") as f:
                f.write(icon_svg(st))
            print("wrote", name)
    if what == "launcher":
        launcher(out if len(argv) > 2 else os.path.join(VOX, "android/app/src/main/res"))
    if what == "app":
        app_assets(out if len(argv) > 2 else os.path.join(VOX, "ui/assets/brand"))
    if what == "mono":  # preview of the themed-icon layer
        for st in ("on", "off"):
            rsvg(mono_svg(st), 216, os.path.join(out, f"mono-{st}.png"))
    if what == "preview":  # icon at 48 and 192 px on their own pixel grids
        for st in ("on", "off"):
            icon_png(st, 192, 3, os.path.join(out, f"icon-{st}-192.png"))
            icon_png(st, 48, 1, os.path.join(out, f"icon-{st}-48.png"))
    if what in ("wordmark", "all"):
        for light in (False, True):
            name = "canti-wordmark-stipple-light.svg" if light else "canti-wordmark-stipple.svg"
            with open(os.path.join(out, name), "w") as f:
                f.write(wordmark_svg(MINT if light else INK, light=light))
            print("wrote", name)


if __name__ == "__main__":
    main(sys.argv)
