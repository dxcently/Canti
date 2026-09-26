"""Regression cases from the user's own live recordings (tests/live_regressions.json).

The recordings are private and not in the repo: a case whose session.wav is missing is skipped. A case with
"status": "open" is a known failure (xfail, not strict), kept so a fix shows up as XPASS.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REC = HERE.parent / "recordings"
CASES = json.loads((HERE / "live_regressions.json").read_text())["cases"]
_cache: dict[str, list] = {}


def _events(session: str) -> list[dict]:
    if session not in _cache:
        import soundfile as sf
        from vox_extract.config import Config
        from vox_extract.extractor import Extractor
        x, sr = sf.read(REC / f"live-20260926-{session}" / "session.wav", dtype="float32")
        ex = Extractor(Config(), input_rate=sr)
        evs = []
        for i in range(0, len(x), 4800):          # 100 ms chunks, as record.py streams them
            evs += ex.push(x[i:i + 4800])
        evs += ex.flush()
        _cache[session] = [e if isinstance(e, dict) else e.__dict__ for e in evs]
    return _cache[session]


def _params():
    for c in CASES:
        marks = [pytest.mark.xfail(reason=c.get("why_open", "open"), strict=False)] if c.get("status") == "open" else []
        yield pytest.param(c, id=f"{c['session']}@{c['t_start_ms']}-{c['expected_label']}", marks=marks)


@pytest.mark.parametrize("case", list(_params()))
def test_live_case(case):
    wav = REC / f"live-20260926-{case['session']}" / "session.wav"
    if not wav.exists():
        pytest.skip(f"private recording not present: {wav}")
    best, overlap = None, 0
    for e in _events(case["session"]):
        o = min(case["t_end_ms"], e["t_end_ms"]) - max(case["t_start_ms"], e["t_start_ms"])
        if o > overlap:
            best, overlap = e, o
    assert best is not None, "no event overlaps the case"
    assert best["label"] == case["expected_label"], (best["t_start_ms"], best["label"], best.get("sounds_like"))
