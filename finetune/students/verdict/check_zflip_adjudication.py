"""Check that a Z Flip label-pass adjudication (zflip/labels_adjudicated*.jsonl) reaches the built rows.

    PYTHONPATH=. python students/verdict/check_zflip_adjudication.py

Builds the Z Flip rows twice from a temporary data root whose zflip/ links to the real screens / phrases / labels:
once as-is, once with a synthetic labels_adjudicated_check.jsonl that flips one row's gold (target -> "none", or
"none" -> another option) and drops a second row. Asserts exactly those two rows change. Nothing is written under
data/, and no screen content is printed (aggregates only).
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vox import real_targets_v2 as rt  # noqa: E402


def rows_by_pid(root: Path) -> dict:
    old = rt.D
    rt.D = root
    try:
        return {r["meta"]["pid"]: r for r in rt.build_zflip()}
    finally:
        rt.D = old


def main():
    real = rt.D / "zflip"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "zflip").mkdir()
        for f in ("screens.jsonl", "phrases.jsonl", "labels.jsonl"):
            (root / "zflip" / f).symlink_to(real / f)
        base = rows_by_pid(root)
        assert base, "no Z Flip rows built"
        pids = sorted(base)
        flip, drop = base[pids[0]], pids[1]
        none_i = len(flip["options"]) - 1
        new_gold = 0 if flip["label"] == none_i else "none"
        adj = [{"pid": flip["meta"]["pid"], "screen_id": flip["screen_id"], "phrase": flip["phrase"], "gold": new_gold,
                "acceptable": [new_gold], "confidence": "med", "note": "check", "ambiguous": False, "adjudicated": True},
               {"pid": drop, "drop": True, "note": "check"}]
        (root / "zflip" / "labels_adjudicated_check.jsonl").write_text("".join(json.dumps(x) + "\n" for x in adj))
        after = rows_by_pid(root)
    want = none_i if new_gold == "none" else 0
    got = after[flip["meta"]["pid"]]["label"]
    assert got == want, f"adjudicated gold did not reach the row: {got} != {want}"
    assert drop not in after, "adjudicated drop did not remove the row"
    changed = [p for p in after if p in base and after[p]["label"] != base[p]["label"]]
    assert changed == [flip["meta"]["pid"]], f"unexpected label changes: {len(changed)}"
    assert len(after) == len(base) - 1
    print(f"ok: {len(base)} Z Flip rows; the adjudicated gold reached its row, the adjudicated drop removed one, nothing else changed")


if __name__ == "__main__":
    main()
