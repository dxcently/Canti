"""Cursor B's pixel grids (extractor/joystick_ind.py, the approved mockups' drawing code) -> the app's asset, and goldens
for the Kotlin indicator rules (heading, chevrons, bar step, brackets): JoyIndicatorsTest.

  extractor/run python /home/khoa/VOX/android/tools/gen_joystick_cursor.py
writes app/src/main/assets/joystick_cursor.json and app/src/test/resources/joystick_ind_golden.json. Deterministic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
VOX = HERE.parent.parent
sys.path.insert(0, str(VOX / "extractor"))

import joystick_core as J  # noqa: E402
import joystick_ind as I  # noqa: E402

ASSET = HERE.parent / "app" / "src" / "main" / "assets" / "joystick_cursor.json"
GOLDEN = HERE.parent / "app" / "src" / "test" / "resources" / "joystick_ind_golden.json"


def rows(g: np.ndarray) -> list[str]:
    return ["".join(str(int(v)) for v in r) for r in g]


def main() -> None:
    grids = {"plain": rows(I.cursor()), "neutral": rows(I.cursor(neutral=True))}
    for d in I.ORDER:
        for n in (1, 2, 3):
            grids[f"{d}-{n}"] = rows(I.cursor(d, n))
    ASSET.write_text(json.dumps({
        "about": "Cursor B (extractor/joystick_ind.py, approved 2026-09-27): (2R+1)^2 cells, 0 clear, 1 ink (navy), "
                 "2 paper (mint-cream); drawn at art_px_dp dp per cell. Made by android/tools/gen_joystick_cursor.py.",
        "R": I.R, "art_px_dp": I.PX / I.DEVICE_PX_PER_DP, "ink": "#%02X%02X%02X" % I.NAVY, "paper": "#%02X%02X%02X" % I.MINT,
        "grids": grids}, separators=(",", ":")))
    spec = J.load_spec()
    rng = np.random.default_rng(7)
    headings = [[float(dx), float(dy), I.heading(dx, dy)] for dx, dy in rng.uniform(-1, 1, (64, 2))]
    headings += [[1.0, 0.0, I.heading(1, 0)], [0.0, -1.0, I.heading(0, -1)], [-1.0, 0.0, I.heading(-1, 0)], [0.0, 1.0, I.heading(0, 1)]]
    sp = spec["speed"]
    chev = [[float(s), I.chevrons(s, spec)] for s in np.linspace(sp["start_dp_s"] - 10, sp["max_dp_s"] + 10, 41)]
    bars = []
    for off in np.linspace(-6, 6, 49):
        for dead, full in ((0.5, 3.0), (0.5, 1.2), (0.1, 1.0)):
            for past in (0, 1, -1):
                bars.append([float(off), dead, full, past, I.bar_step(off, dead, full, past)])
    br = []
    for l, t, r, b in ((100, 200, 300, 260), (0, 0, 1080, 2400), (37, 41, 43, 47), (500, 900, 501, 903)):
        g, x, y = I.brackets(l, t, r, b)
        br.append({"ltrb": [l, t, r, b], "x": int(x), "y": int(y), "rows": rows(g)})
    GOLDEN.write_text(json.dumps({"headings": headings, "chevrons": chev, "bars": bars, "brackets": br},
                                 separators=(",", ":")))
    print(f"wrote {ASSET} ({len(grids)} grids), {GOLDEN}")


if __name__ == "__main__":
    main()
