#!/usr/bin/env python3
"""Regenerates extractor/tests/fixtures/range_v1_plan.json from range_v1.json (range_layout.build_plan).

The fixture is the parity contract between the Python plan and the Kotlin RangePlan: for both profiles, one entry per
take with {take_id, block, cue, expect, cond_id, rep, bg, kind}. Run this whenever range_v1.json changes; a pytest
checks the checked-in fixture is current and a JVM test checks RangePlan against it.
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
    path = HERE / 'fixtures' / 'range_v1_plan.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build(), indent=1) + '\n')
    print(path)


if __name__ == '__main__':
    main()
