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


@pytest.mark.skipif(not (VEC / "manifest.json").exists(), reason="no vectors exported")
def test_long_stream_times_keep_increasing():
    """Past 134 s of stream (where 32-bit index * hop * 1000 overflowed in the C port) every loop must still give
    the first loop's events, shifted by the loop length."""
    man = json.loads((VEC / "manifest.json").read_text())
    longs = [c for c in man["cases"] if c.get("loops", 1) > 1]
    assert longs, "no long-stream case in the vectors: re-export"
    for c in longs:
        ref = json.loads((VEC / f"{c['name']}.events.json").read_text())["events"]
        loops, loop_ms = c["loops"], c["samples"] / c["loops"] * 1000.0 / c["rate"]
        assert c["samples"] / c["rate"] > 140, "long enough to cross 134.2 s"
        assert len(ref) % loops == 0 and len(ref) >= loops, c["name"]
        per = len(ref) // loops
        first = ref[:per]
        for i, e in enumerate(ref):
            f = first[i % per]
            assert (e["label"], e["text"]) == (f["label"], f["text"]), (c["name"], i)
            assert abs(e["t_start_ms"] - (f["t_start_ms"] + (i // per) * loop_ms)) <= 10, (c["name"], i)
            # the loop length is not a whole number of 10 ms frames: one frame of slack at each edge
            assert abs((e["t_end_ms"] - e["t_start_ms"]) - (f["t_end_ms"] - f["t_start_ms"])) <= 20, (c["name"], i)
