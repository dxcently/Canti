#!/usr/bin/env python3
"""Regenerates extractor/tests/fixtures/range_<version>_plan.json from a range spec (range_layout.build_plan).

The fixture is the parity contract between the Python plan and the Kotlin RangePlan: for both profiles, one entry per
take with {take_id, block, cue, expect, cond_id, rep, bg, kind}. Run `make_range_plan_fixture.py prompts/range_v2.json`
whenever a spec changes; a pytest checks each checked-in fixture is current and a JVM test checks RangePlan against it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import range_layout as L  # noqa: E402


def build(spec=None):
    spec = spec or L.load_spec()
    out = {}
    for profile in ('short', 'full'):
        out[profile] = [
            dict(take_id=t['take_id'], block=t['block'], cue=t['cue'],
                 expect=t.get('expect', []), cond_id=t.get('cond_id'), rep=t['rep'],
                 bg=t.get('bg'), kind=t['kind'])
            for t in L.build_plan(spec, profile=profile)
        ]
    return out


def main():
    spec = L.load_spec(sys.argv[1]) if len(sys.argv) > 1 else L.load_spec()
    path = HERE / 'fixtures' / f'{spec["version"]}_plan.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build(spec), indent=1) + '\n')
    print(path)


if __name__ == '__main__':
    main()
