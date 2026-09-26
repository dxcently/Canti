"""The exported C test vectors must match what the current code produces (re-export after changes:
./run python export_vectors.py)."""

import json
from pathlib import Path

import numpy as np
import pytest

from export_vectors import run_case
from vox_extract import Config

VEC = Path(__file__).resolve().parents[1] / "vectors"


@pytest.mark.skipif(not (VEC / "manifest.json").exists(), reason="no vectors exported")
def test_vectors_are_current():
    man = json.loads((VEC / "manifest.json").read_text())
    cfg = Config.from_dict(man["config"])
    assert cfg == Config(), "vectors were exported with a different default config: re-export"
    for c in man["cases"]:
        pcm = np.fromfile(VEC / f"{c['name']}.pcm", dtype="<i2")
        _, _, events = run_case(pcm, c["rate"], cfg)
        assert [[e.label, e.text] for e in events] == [list(x) for x in c["expected"]], c["name"]
        ref = json.loads((VEC / f"{c['name']}.events.json").read_text())["events"]
        assert [(e.t_start_ms, e.t_end_ms) for e in events] == [(r["t_start_ms"], r["t_end_ms"]) for r in ref]
