"""Deleting takes from a range session (contract T): soft delete, undo, trash, purge, redo numbering.

SYNTHETIC audio only, sessions under android/.state (gitignored); no device, no model API."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import range_layout as L
import range_session as D
import range_suite as R
from test_range_suite_checks import CENTRE, DISCRETE, FS, opts, private, standard, tid, write_wav  # noqa: F401

CLICK = tid("discrete", "click", DISCRETE)


def plan_take(take_id):
    return next(t for t in L.build_plan(L.load_spec()) if t["take_id"] == take_id)


def missed(out, take_id, attempt, seconds=2.0):
    """A no_sound attempt the way the phone app writes it (its own .a<attempt> WAV, then the row)."""
    t = plan_take(take_id)
    x = np.zeros(int(FS * seconds), dtype=np.float32)
    row = dict(L.label_row(t, attempt, 0, 1000, len(x), FS), file=L.take_file(t["block"], take_id, attempt),
               no_sound=True, attempt=attempt)
    write_wav(out / row["file"], x)
    L.append_row(out / "labels.jsonl", row)
    return row


def complete_session(root, name="complete"):
    """A complete short-profile session (42 takes, no backgrounds), so complete=True passes."""
    spec = L.load_spec()
    out = root / name
    L.open_session(out, spec, "desktop", "synthetic", FS, 1, True, profile="short", speaker="self")
    meta = json.loads((out / "session.json").read_text())
    meta["range"] = dict(bottom_hz=100, home_hz=150, top_hz=200, whistle_home_hz=1000, below_f0_min=False)
    L.write_json(out / "session.json", meta)
    x = np.zeros(int(FS * 2), dtype=np.float32)
    for t in L.build_plan(spec, profile="short"):
        if t["kind"] != "takes":
            continue
        row = L.label_row(t, 0, 0, 1000, len(x), FS)
        write_wav(out / row["file"], x)
        L.append_row(out / "labels.jsonl", row)
    for block in ("range", "room", "contours", "discrete", "combos"):
        L.append_row(out / "ratings.jsonl", dict(block=block, rating=3, note="", seconds=0, redos=0))
    return out


# ---------------------------------------------------------------------------------- the parity fixture


def test_tombstone_fixture_effective_rows():
    fx = json.loads((Path(__file__).parent / "fixtures" / "range_tombstones.json").read_text())
    assert len(fx["cases"]) >= 8
    for case in fx["cases"]:
        journal = case["journal"]
        eff, in_force, restorable = L.effective_rows(journal)
        assert in_force == case["in_force"], case["about"]
        assert restorable == case["restorable"], case["about"]
        if any("take_id" in r for r in journal if "op" not in r):
            assert L.take_rows(journal) == case["take_rows"], case["about"]
            assert L.no_sound_rows(journal) == case["no_sound"], case["about"]


# ---------------------------------------------------------------------------------- the three scopes


def test_delete_scope_take_moves_every_file(private):
    out = standard(private)
    heard = L.take_rows(out / "labels.jsonl")[CLICK]
    missed(out, CLICK, 1)
    del_id = L.delete_take(out, CLICK, "take")
    assert not (out / heard["file"]).exists() and not (out / f"takes/discrete/{CLICK}.a1.wav").exists()
    assert (out / "trash" / del_id / heard["file"]).exists()
    assert (out / "trash" / del_id / f"takes/discrete/{CLICK}.a1.wav").exists()
    assert CLICK not in L.take_rows(out / "labels.jsonl")
    counts = L.validate_session(out)
    assert counts["takes"] == 3 and counts["deleted"] == 1


def test_delete_scope_attempt_moves_only_that_missed_file(private):
    out = standard(private)
    heard = L.take_rows(out / "labels.jsonl")[CLICK]
    missed(out, CLICK, 1)
    del_id = L.delete_take(out, CLICK, "attempt", 1)
    assert (out / heard["file"]).exists()
    assert not (out / f"takes/discrete/{CLICK}.a1.wav").exists()
    assert (out / "trash" / del_id / f"takes/discrete/{CLICK}.a1.wav").exists()
    assert not L.is_no_sound(L.take_rows(out / "labels.jsonl")[CLICK])
    counts = L.validate_session(out)
    assert counts["takes"] == 4 and counts["no_sound"] == 0 and counts["deleted"] == 1


def test_delete_scope_attempt_null_moves_the_heard_file(private):
    out = standard(private)
    heard = L.take_rows(out / "labels.jsonl")[CLICK]
    missed(out, CLICK, 1)
    del_id = L.delete_take(out, CLICK, "attempt", None)
    assert not (out / heard["file"]).exists() and (out / f"takes/discrete/{CLICK}.a1.wav").exists()
    assert (out / "trash" / del_id / heard["file"]).exists()
    assert L.is_no_sound(L.take_rows(out / "labels.jsonl")[CLICK])
    counts = L.validate_session(out)
    assert counts["takes"] == 4 and counts["no_sound"] == 1 and counts["deleted"] == 1


# ---------------------------------------------------------------------------------- restore / purge


def test_restore_moves_files_back(private):
    out = standard(private)
    heard = L.take_rows(out / "labels.jsonl")[CLICK]
    del_id = L.delete_take(out, CLICK, "take")
    assert L.restore(out, del_id) == CLICK
    assert (out / heard["file"]).exists() and CLICK in L.take_rows(out / "labels.jsonl")
    assert L.validate_session(out)["deleted"] == 0
    assert not (out / "trash" / del_id).exists()


def test_restore_refused_after_a_rerecord(private):
    out = standard(private)
    del_id = L.delete_take(out, CLICK, "take")
    t = plan_take(CLICK)
    x = np.zeros(int(FS * 2), dtype=np.float32)
    row = L.label_row(t, L.next_redo(L.read_rows(out / "labels.jsonl"), CLICK), 0, 1000, len(x), FS)
    write_wav(out / row["file"], x)
    L.append_row(out / "labels.jsonl", row)
    with pytest.raises(ValueError, match="exists now"):
        L.restore(out, del_id)


def test_purge_removes_trash_and_blocks_restore(private):
    out = standard(private)
    del_id = L.delete_take(out, CLICK, "take")
    assert L.purge_trash(out) == [del_id]
    assert not (out / "trash" / del_id).exists()
    assert L.validate_session(out)["deleted"] == 1   # still in force
    with pytest.raises(ValueError, match="purged"):
        L.restore(out, del_id)


def test_next_redo_counts_excluded_rows(private):
    out = standard(private)
    journal = L.read_rows(out / "labels.jsonl")
    assert L.next_redo(journal, CLICK) == 1          # one heard row, redo 0
    L.delete_take(out, CLICK, "take")
    assert L.next_redo(L.read_rows(out / "labels.jsonl"), CLICK) == 1   # the deleted row still counts
    t = plan_take(CLICK)
    x = np.zeros(int(FS * 2), dtype=np.float32)
    row = L.label_row(t, L.next_redo(L.read_rows(out / "labels.jsonl"), CLICK), 0, 1000, len(x), FS)
    write_wav(out / row["file"], x)
    L.append_row(out / "labels.jsonl", row)
    assert L.next_redo(L.read_rows(out / "labels.jsonl"), CLICK) == 2


def test_complete_requires_a_deleted_take_again(private):
    out = complete_session(private)
    take_id = L.build_plan(L.load_spec(), profile="short")[0]["take_id"]
    assert L.validate_session(out, complete=True)["takes"] == 42
    L.delete_take(out, take_id, "take")
    with pytest.raises(ValueError, match="incomplete"):
        L.validate_session(out, complete=True)
    t = plan_take(take_id)
    x = np.zeros(int(FS * 2), dtype=np.float32)
    row = L.label_row(t, L.next_redo(L.read_rows(out / "labels.jsonl"), take_id), 0, 1000, len(x), FS)
    write_wav(out / row["file"], x)
    L.append_row(out / "labels.jsonl", row)
    assert L.validate_session(out, complete=True)["takes"] == 42


# ---------------------------------------------------------------------------------- operate (d / u keys)


def test_operate_delete_then_undo():
    items = L.build_plan(L.load_spec(), ["range"])
    actions = iter(["\n", "d", "y", "u", "\n", "\n", "\n", "\n"])
    captured, deleted = [], []

    def delete(t):
        deleted.append(t["take_id"])
        return "d1"

    def undo(del_id):
        return deleted.pop()

    complete, redos = L.operate(items, set(), lambda t: captured.append(t["take_id"]),
                               key=lambda _: next(actions), delete=delete, undo=undo, count=lambda t: 1)
    assert complete and redos == 0
    assert captured == [t["take_id"] for t in items]   # the deleted take was restored, not re-recorded
    assert deleted == []


def test_operate_delete_prompts_the_take_again():
    items = L.build_plan(L.load_spec(), ["range"])
    actions = iter(["\n", "d", "y", "\n", "\n", "\n", "\n", "\n"])
    captured = []

    def delete(t):
        return "d1"

    complete, redos = L.operate(items, set(), lambda t: captured.append(t["take_id"]),
                               key=lambda _: next(actions), delete=delete, undo=lambda d: None, count=lambda t: 1)
    assert complete and redos == 0
    assert captured == [items[0]["take_id"], items[0]["take_id"], items[1]["take_id"],
                        items[2]["take_id"], items[3]["take_id"]]


# ---------------------------------------------------------------------------------- range_suite + CLI


def test_suite_excludes_deleted_rows(private):
    out = standard(private)
    L.delete_take(out, CLICK, "take")
    rep = R.run_session(out, opts())
    assert CLICK not in {t["take_id"] for t in rep["labels"]["per_take"]}
    assert rep["layout"]["deleted"] == 1


def test_cli_delete_restore_clear_trash(private, capsys):
    out = standard(private)
    assert L.validate_session(out)["takes"] == 4
    assert D.run_command("delete", ["--out", str(out), "--yes", CLICK]) == 0
    assert L.validate_session(out)["takes"] == 3
    assert D.run_command("list-takes", ["--out", str(out), "--block", "discrete"]) == 0
    assert "missing" in capsys.readouterr().out
    del_id = next(r for r in L.read_rows(out / "labels.jsonl") if r.get("op") == "delete")["del_id"]
    assert D.run_command("restore", ["--out", str(out), del_id]) == 0
    assert L.validate_session(out)["takes"] == 4 and L.validate_session(out)["deleted"] == 0
    D.run_command("delete", ["--out", str(out), "--yes", CLICK])
    assert D.run_command("clear-trash", ["--out", str(out), "--yes"]) == 0
    assert not (out / "trash").exists() or not list((out / "trash").iterdir())


def test_purged_background_cannot_be_restored(tmp_path):
    out = L.HERE / 'recordings' / '_pytest' / tmp_path.name / 'bgpurge'
    out.mkdir(parents=True)
    (out / 'bg.wav').write_bytes(b'x')
    L.append_row(out / 'backgrounds.jsonl', dict(name='fan', file='bg.wav'))
    did = L.delete_background(out, 'fan')
    assert L.purge_trash(out) == [did]
    assert L.effective_rows(L.read_rows(out / 'backgrounds.jsonl'))[2] == []
    with pytest.raises(ValueError, match='purged'):
        L.restore(out, did)
