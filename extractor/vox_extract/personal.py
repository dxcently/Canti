"""Python mirror of the phone-side enrollment matcher (android Personal.kt `Matcher`), for offline checks.

Used by record.py --enroll (to show the new class's reject threshold) and eval_real/enroll_sim.py (the
feasibility simulation). Keep it in step with Personal.kt; android/PROTOCOL.md "Personalization" is the spec:

  1. standardise every fp by the per-feature mean and population std of ALL enrolled examples, the std raised to the
     fp_version's floor (android assets/fp_floors.json, same shape as results/fp1_scales.json); std < 1e-9 -> 1;
  2. nearest example (Euclidean) over the active classes (3+ examples) picks the class; a contour-gesture class
     (rise/fall/arch/dip/flat) is a candidate only for a sound with a 16-point pitch16 and must also pass banded DTW;
  3. reject threshold per class = within-class distance x reject_mult, where the within-class distance is the
     leave-one-out one at every class size: the largest distance from an example to the nearest other example
     (the app changed from "pairwise max for 4+" on 2026-09-26); the DTW threshold is made the same way on pitch16;
  4. result: the class kind (custom / ignore / gesture), "none" (beyond the threshold) or "skipped".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

KINDS = ("custom", "ignore", "gesture")
CONTOUR_GESTURES = ("rise", "fall", "arch", "dip", "flat")
MIN_EXAMPLES, MAX_EXAMPLES = 3, 10
DTW_BAND = 3
NAME_RE = r"[a-z0-9][a-z0-9 -]{0,23}"


def standardizer(xs: list[list[float]], floor: list[float] | None = None) -> tuple[list[float], list[float]]:
    if not xs:
        return [], []
    d, n = len(xs[0]), len(xs)
    mean = [sum(x[j] for x in xs) / n for j in range(d)]
    std = []
    for j in range(d):
        s = max(math.sqrt(sum((x[j] - mean[j]) ** 2 for x in xs) / n), floor[j] if floor else 0.0)
        std.append(1.0 if s < 1e-9 else s)
    return mean, std


def load_floors(path, fp_version: str = "fp1") -> list[float] | None:
    """The floor of one fp_version from a floors JSON ({"<fp_version>": {"floor": [...], ...}}), or None."""
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return None
    e = json.loads(p.read_text()).get(fp_version)
    return list(e["floor"]) if e and e.get("floor") else None


def standardize(x, mean, std) -> list[float]:
    return [(x[i] - mean[i]) / std[i] for i in range(len(x))]


def euclid(a, b) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(len(a))))


def dtw(a, b, band: int = DTW_BAND) -> float:
    n, m = len(a), len(b)
    w = max(band, abs(n - m))
    inf = float("inf")
    d = [[inf] * (m + 1) for _ in range(n + 1)]
    d[0][0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(1, i - w), min(m, i + w) + 1):
            d[i][j] = abs(a[i - 1] - b[j - 1]) + min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1])
    return d[n][m]


def within_class(xs, dist) -> float:
    """Leave-one-out: the largest distance from an example to the nearest other example."""
    if len(xs) < 2:
        raise ValueError("need 2+ examples")
    return max(min(dist(xs[i], xs[j]) for j in range(len(xs)) if j != i) for i in range(len(xs)))


@dataclass
class EnrollClass:
    kind: str
    name: str
    examples: list[dict] = field(default_factory=list)   # {"fp": [...], "pitch16": [...]}

    @property
    def active(self) -> bool:
        return len(self.examples) >= MIN_EXAMPLES

    @property
    def contour(self) -> bool:
        return self.kind == "gesture" and self.name in CONTOUR_GESTURES


@dataclass
class Match:
    result: str                   # custom / ignore / gesture / none / skipped
    cls: str | None = None        # accepted class
    nearest: str | None = None
    distance: float | None = None
    threshold: float | None = None
    dtw: float | None = None
    dtw_threshold: float | None = None
    reason: str = ""


class Matcher:
    def __init__(self, classes: list[EnrollClass], reject_mult: float = 1.4, std_floor: list[float] | None = None) -> None:
        self.classes = classes
        fps = [e["fp"] for c in classes for e in c.examples]
        if std_floor and fps and len(std_floor) != len(fps[0]):
            std_floor = None      # the app logs a length mismatch and uses no floor
        self.mean, self.std = standardizer(fps, std_floor)
        self.prepared = []
        for c in classes:
            if not c.active:
                continue
            z = [standardize(e["fp"], self.mean, self.std) for e in c.examples]
            thr = within_class(z, euclid) * reject_mult
            dthr = within_class([e["pitch16"] for e in c.examples], dtw) * reject_mult if c.contour else None
            self.prepared.append((c, z, thr, dthr))

    def thresholds(self) -> dict[str, tuple[float, float | None]]:
        return {c.name: (t, d) for c, _, t, d in self.prepared}

    def match(self, fp: list[float], pitch16: list[float]) -> Match:
        if not self.prepared:
            return Match("skipped", reason="no active class")
        if len(fp) != len(self.mean):
            return Match("skipped", reason="fp length differs")
        q = standardize(fp, self.mean, self.std)
        pitched = len(pitch16) == 16
        cands = [p for p in self.prepared if not p[0].contour or pitched]
        if not cands:
            return Match("none", reason="only contour classes and the sound has no pitch track")
        best, best_d = None, float("inf")
        for p in cands:
            for z in p[1]:
                d = euclid(q, z)
                if d < best_d:
                    best, best_d = p, d
        c, _, thr, dthr = best
        if best_d > thr:
            return Match("none", nearest=c.name, distance=best_d, threshold=thr, reason="fp distance above the threshold")
        if c.contour:
            dd = min(dtw(pitch16, e["pitch16"]) for e in c.examples)
            if dd > dthr:
                return Match("none", nearest=c.name, distance=best_d, threshold=thr, dtw=dd, dtw_threshold=dthr,
                             reason="pitch track DTW above the threshold")
            return Match(c.kind, c.name, c.name, best_d, thr, dd, dthr, "matched")
        return Match(c.kind, c.name, c.name, best_d, thr, reason="matched")
