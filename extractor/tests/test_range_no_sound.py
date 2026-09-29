"""Missed takes (the phone recorder's no_sound attempts): range_layout keeps and validates every attempt, the take is
its last heard row, and range_suite counts each missed attempt as a gate miss. SYNTHETIC audio only, sessions under
android/.state (gitignored); no device, no model API."""
from __future__ import annotations

import json

import numpy as np
import pytest

import range_layout as L
import range_suite as R
from test_range_suite_checks import CENTRE, DISCRETE, FS, opts, private, standard, tid, write_wav  # noqa: F401

CLICK = tid("discrete", "click", DISCRETE)
ARCH = tid("contours", "arch", CENTRE)
DROP = object()   # a key left out of the row


def plan_take(take_id):
    return next(t for t in L.build_plan(L.load_spec()) if t["take_id"] == take_id)


def missed(out, take_id, attempt, seconds=5.5):
    """Appends a no_sound attempt the way the app writes it: its own .a<attempt> WAV, then the row."""
    t = plan_take(take_id)
    x = np.zeros(int(FS * seconds), dtype=np.float32)
    row = dict(L.label_row(t, attempt, 0, 1000, len(x), FS), file=L.take_file(t["block"], take_id, attempt),
               no_sound=True, attempt=attempt)
    write_wav(out / row["file"], x)
    L.append_row(out / "labels.jsonl", row)
    return row


def test_a_retry_never_overwrites_a_missed_attempt(private):
    out = standard(private)
    rows = L.read_rows(out / "labels.jsonl")
    heard = next(r for r in rows if r["take_id"] == CLICK)
    before = (out / heard["file"]).read_bytes()
    # a later attempt is missed: kept beside the heard one, which stays the take
    missed(out, CLICK, 1)
    assert (out / f"takes/discrete/{CLICK}.a1.wav").exists()
    assert (out / heard["file"]).read_bytes() == before
    counts = L.validate_session(out)
    assert counts["no_sound"] == 1 and counts["takes"] == 4
    assert not L.is_no_sound(L.take_rows(out / "labels.jsonl")[CLICK])


def test_only_missed_attempts_make_the_take_the_last_missed_one(private):
    out = standard(private)
    missed(out, ARCH, 0)
    missed(out, ARCH, 1)
    take = L.take_rows(out / "labels.jsonl")[ARCH]
    assert take["attempt"] == 1 and L.is_no_sound(take)
    assert L.validate_session(out)["no_sound"] == 2
    assert [r["attempt"] for r in L.no_sound_rows(out / "labels.jsonl")] == [0, 1]


@pytest.mark.parametrize("bad", [
    dict(file=f"takes/discrete/{CLICK}.wav"),   # a missed attempt on the plain path would overwrite the take
    dict(attempt=DROP),
    dict(no_sound="yes"),
])
def test_a_malformed_missed_row_is_refused(private, bad):
    out = standard(private)
    row = missed(out, CLICK, 1)
    L.append_row(out / "labels.jsonl", {k: v for k, v in dict(row, **bad).items() if v is not DROP})
    with pytest.raises(ValueError):
        L.validate_session(out)


def test_desktop_rows_without_the_flag_stay_valid(private):
    out = standard(private)
    assert L.validate_session(out)["no_sound"] == 0
    assert L.take_rows(out / "labels.jsonl") == L.latest_rows(out / "labels.jsonl")


def test_suite_counts_missed_attempts_as_gate_misses(private):
    base = R.run_session(standard(private, name="base"), opts())
    out = standard(private, name="missed")
    missed(out, CLICK, 1)          # heard earlier, then a missed Try again
    missed(out, ARCH, 0)           # only missed
    rep = R.run_session(out, opts())
    ns = rep["no_sound"]
    assert (ns["attempts"], ns["takes"], ns["heard_later"]) == (2, 2, 1)
    assert ns["per_gesture"] == {"click": 1, "arch": 1}
    keep, keep0 = rep["gates"]["own"]["keep_rate"], base["gates"]["own"]["keep_rate"]
    # each missed attempt adds its expected sounds to the total with none kept
    assert keep["per_gesture"]["click"]["total"] == keep0["per_gesture"]["click"]["total"] + 1
    assert keep["per_gesture"]["click"]["correct"] == keep0["per_gesture"]["click"]["correct"]
    assert keep["per_gesture"]["arch"] == {"correct": 0, "total": 1, "recall": 0.0}
    misses = [t for t in rep["gates"]["own"]["per_take"] if t.get("no_sound")]
    assert sorted((t["take_id"], t["attempt"], t["kept"]) for t in misses) == sorted([(CLICK, 1, 0), (ARCH, 0, 0)])
    # the only-missed take is still analysed as the take (like the desktop), never mixed
    assert ARCH in {t["take_id"] for t in rep["labels"]["per_take"]}
    assert "no sound: 2 missed attempt(s)" in (out / "report.md").read_text()
    assert json.loads((out / "report.json").read_text())["no_sound"]["attempts"] == 2


def test_finalize_measures_the_heard_attempt_not_a_later_missed_one(private, monkeypatch):
    import range_session as S
    out = standard(private)
    heard = {}
    for t in L.build_plan(L.load_spec(), ["range"])[:2]:   # a heard hum on the plain path
        x = (0.3 * np.sin(2 * np.pi * 150 * np.arange(int(FS * 3)) / FS)).astype(np.float32)
        row = L.label_row(t, 0, 0, 1000, len(x), FS)
        write_wav(out / row["file"], x)
        L.append_row(out / "labels.jsonl", row)
        heard[t["take_id"]] = row["file"]
    for take_id in heard:
        missed(out, take_id, 5)                    # a missed Try again after each heard range take
    read = []
    real = S.sf.read
    monkeypatch.setattr(S.sf, "read", lambda f, **k: (read.append(str(f)), real(f, **k))[1])
    S.finalize_range(out, L.load_spec())
    assert sorted(read) == sorted(str(out / f) for f in heard.values())
