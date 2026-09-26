"""Push enrollment examples (personalization) to the app over the debug socket.

Enrollment is recorded on the PC for now. Each example is one JSON line:
    {"kind": "custom" | "ignore" | "gesture", "name": "meow", "fp": [...], "fp_version": "fp1", "pitch16": [...16 or []]}
Examples go to the app's *active* profile (the profile's "name", default "default").

    python3 suite/enroll.py push examples.jsonl [more.jsonl ...]   # enroll_add, one call per class
    python3 suite/enroll.py list                                   # classes, example counts, thresholds
    python3 suite/enroll.py delete NAME [--index I]                 # a class, or one example of it
    python3 suite/enroll.py clear                                  # every class of the active profile

Needs `adb forward tcp:7788 localabstract:vox-debug` (voxlib does it).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voxlib import Vox  # noqa: E402


def read_examples(paths: list[str]) -> dict[tuple[str, str], list[dict]]:
    classes: dict[tuple[str, str], list[dict]] = {}
    for path in paths:
        for n, line in enumerate(Path(path).read_text().splitlines(), 1):
            if not line.strip():
                continue
            d = json.loads(line)
            for k in ("kind", "name", "fp", "fp_version"):
                if k not in d:
                    raise SystemExit(f"{path}:{n}: missing {k}")
            classes.setdefault((d["kind"], d["name"]), []).append(
                {"fp": d["fp"], "fp_version": d["fp_version"], "pitch16": d.get("pitch16", [])})
    return classes


def push(vox: Vox, classes: dict[tuple[str, str], list[dict]]) -> dict:
    reply: dict = {}
    for (kind, name), examples in classes.items():
        reply = vox.control("enroll_add", kind=kind, name=name, examples=examples)
        if not reply.get("ok"):
            raise SystemExit(f"{kind} '{name}': {reply.get('error')}")
        print(f"enrolled {kind} '{name}': +{len(examples)}")
    return reply


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("push").add_argument("files", nargs="+")
    sub.add_parser("list")
    d = sub.add_parser("delete")
    d.add_argument("name")
    d.add_argument("--index", type=int)
    sub.add_parser("clear")
    a = ap.parse_args()
    vox = Vox()
    if a.cmd == "push":
        r = push(vox, read_examples(a.files))
    elif a.cmd == "list":
        r = vox.control("enroll_list")
    elif a.cmd == "delete":
        r = vox.control("enroll_delete", name=a.name, **({"index": a.index} if a.index is not None else {}))
    else:
        r = vox.control("enroll_delete", all=True)
    print(json.dumps(r.get("enrollment", r), indent=1))
    vox.close()


if __name__ == "__main__":
    main()
