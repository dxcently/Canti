#!/usr/bin/env python3
"""Per-feature scales of fp1, for the phone matcher's std floor (FINGERPRINT.md "Scales").

  ./run python eval_real/fp_scales.py --tag fixed      # -> results/fp1_scales.json (+ a table on stdout)

The JSON has the shape of the app's android/app/src/main/assets/fp_floors.json ({"fp1": {"provisional", "source",
"names", "floor", ...}}), so the app can drop it in; "within" and "population" are
kept alongside for reference. "floor" = 0.25 x population, the app's rule, from the tune split.

The app standardises each fp1 value by the std of the user's own enrolled examples. With 3-10 examples a feature
that happens to be nearly constant (duration of five identical clicks, e35f0 of an unpitched sound) gets a tiny
std, and then its noise dominates the distance. A per-feature floor fixes that: std_used = max(std_enroll, floor).

Two scales per feature, from the TUNE split only (enroll_sim.py tests on the test split):
  within:     how much the feature varies between repetitions of the SAME sound by the SAME person: the median,
              over (dataset, speaker, sound class) groups with >= 5 clean emitted sounds (Deeply Nonverbal,
              Nonspeech7k and ESC-50 only, where a group is one person or source repeating one sound), of the population std
              inside the group (each dataset weighted equally: median per dataset, then median of those).
              Kept for reference; as a floor it is too large (see FLOOR_FRACTION below).
  population: the typical spread across many speakers and sounds: robust std (IQR / 1.349) over all clean
              emitted sounds, with an equal number drawn from each dataset.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from vox_extract.fingerprint import FP1_NAMES, FP_VERSION  # noqa: E402

# sets whose (speaker, class) groups are repetitions of ONE kind of sound (MLEnd / QBSH groups are melodies,
# MUSAN groups are whole speech or music excerpts: their spread is not "the same sound again")
WITHIN_SETS = ("nonverbal", "nonspeech7k", "esc50")
# The published floor. enroll_sim.py compared no floor, floor = within, and floor = 0.25 x population (the app's
# rule): `within` is about 2x larger on most features and raised other people's false accepts 1.5-3x for some
# classes (cat, lip pop); 0.25 x population is close to the app's provisional table. See results/real_enroll_sim.md.
FLOOR_FRACTION = 0.25


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="fixed")
    ap.add_argument("--split", default="tune")
    ap.add_argument("--out", default=str(C.RESULTS / "fp1_scales.json"))
    a = ap.parse_args()
    groups: dict[tuple, list] = defaultdict(list)
    by_ds: dict[str, list] = defaultdict(list)
    for l in (C.RESULTS / f"real_features_{a.tag}_clips.jsonl").open():
        r = json.loads(l)
        if not r.get("fp") or r.get("gate") == "unmatched" or r.get("snr", "clean") != "clean" or r["split"] != a.split:
            continue
        groups[(r["dataset"], r["speaker"], r["group"], r["label"] in ("pop", "click"))].append(r["fp"])
        by_ds[r["dataset"]].append(r["fp"])
    per_ds: dict[str, list] = defaultdict(list)
    for (ds, *_), xs in groups.items():
        if len(xs) >= 5 and ds in WITHIN_SETS:
            per_ds[ds].append(np.std(np.array(xs, float), axis=0))
    within = np.median(np.array([np.median(np.array(v), axis=0) for v in per_ds.values()]), axis=0)
    rng = random.Random(0)
    n = min(len(v) for v in by_ds.values())
    pool = np.array([x for v in by_ds.values() for x in rng.sample(v, n)], float)
    q75, q25 = np.percentile(pool, [75, 25], axis=0)
    popul = (q75 - q25) / 1.349
    popul = np.where(popul < 1e-6, pool.std(0), popul)
    w = [round(float(v), 4) for v in within]
    fl = [round(FLOOR_FRACTION * float(v), 4) for v in popul]
    entry = {"provisional": False,
             "source": f"VOX extractor real-audio eval (eval_real/fp_scales.py), tag {a.tag}, {a.split} split; floor = "
                       f"{FLOOR_FRACTION} x population, population = robust std (IQR/1.349) of {n} clean emitted sounds per "
                       f"dataset from {sorted(by_ds)}; within = median same-person same-sound std over "
                       f"{sum(len(v) for v in per_ds.values())} (dataset, speaker, class) groups in {sorted(per_ds)}",
             "names": FP1_NAMES, "floor": fl, "within": w,
             "population": [round(float(v), 4) for v in popul],
             "use": "app Personal.standardizer: std_j = max(popstd_j over all enrolled examples, floor_j); < 1e-9 -> 1"}
    out = {FP_VERSION: entry}     # the shape of android/app/src/main/assets/fp_floors.json (drop-in)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    print(C.md_table(["#", "feature", "floor (0.25 x population)", "population", "within", "within / population"],
                     [[i, f"`{nm}`", f"{f:.4g}", f"{p:.4g}", f"{w:.4g}", f"{w / p:.2f}" if p > 0 else "-"]
                      for i, (nm, f, w, p) in enumerate(zip(FP1_NAMES, fl, within, popul))]))
    print("\n" + entry["source"])
    print("wrote", a.out)


if __name__ == "__main__":
    main()
