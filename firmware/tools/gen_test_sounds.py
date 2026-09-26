#!/usr/bin/env python3
"""Generate the firmware's canned test sounds from the Python reference extractor.

The Pico has no on-device extractor yet, so for BLE/app tests it sends canned sound messages. Their lines must be
exactly what the extractor produces, so this script RUNS the current extractor (extractor/vox_extract) over the
extractor's own fixed test clips (extractor/vectors/<case>.pcm, SYNTHETIC audio) and writes what comes out:

    firmware/arduino/vox_node/test_sounds.h   the C table the firmware compiles in
    firmware/tests/test_sounds.json           the same data for tools/ble_check.py

Run it with the extractor's environment (numpy etc.); it only READS extractor/:

    ~/VOX/extractor/run python ~/VOX/firmware/tools/gen_test_sounds.py           # (re)generate
    ~/VOX/extractor/run python ~/VOX/firmware/tools/gen_test_sounds.py --check   # exit 1 if lines/vocab changed

tools/build.sh runs it before every compile, so the strings cannot drift from the extractor.

Every line is checked with the extractor's strict parser (lines.parse_line) and its label. A case that no longer
yields exactly the expected labels (because the extractor changed) is an error: nothing is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
VOX = FIRMWARE.parent
EXTRACTOR = VOX / "extractor"
HEADER = FIRMWARE / "arduino" / "vox_node" / "test_sounds.h"
JSON_OUT = FIRMWARE / "tests" / "test_sounds.json"

sys.path.insert(0, str(EXTRACTOR))

import numpy as np  # noqa: E402

from vox_extract import Config  # noqa: E402
from vox_extract import vocab  # noqa: E402
from vox_extract.extractor import Extractor  # noqa: E402
from vox_extract.lines import label_consistent, parse_line  # noqa: E402

# name -> (vector case, expected labels). The single sounds, then the extractor's own two-sound clip.
SINGLES = [
    ("rise", "rise_20db", ["rise"]),
    ("fall", "fall_20db", ["fall"]),
    ("arch", "arch_20db", ["arch"]),
    ("dip", "dip_20db", ["dip"]),
    ("flat", "flat_20db", ["flat"]),
    ("pop", "pop_20db", ["pop"]),
    ("click", "click_30db", ["click"]),
    ("hiss", "hiss_20db", ["hiss"]),
]
CLIP_SEQUENCES = [
    # click then pop in ONE clip: its gap is the extractor's measured one (t_start(pop) - t_end(click))
    ("clickpop", "click_pop_30db", ["click", "pop"]),
]
# Two-sound sequences composed from the single sounds above, with a chosen device-clock gap (ms).
COMPOSED_SEQUENCES = [
    ("poppop", ["pop", "pop"], 250),       # within gap_ms (600): the phone groups them
    ("riserise", ["rise", "rise"], 900),   # beyond gap_ms: the phone must split them into two groups
]
RATE = 16000
CHUNK = 1600


def extract(case: str) -> list[dict]:
    pcm = np.fromfile(EXTRACTOR / "vectors" / f"{case}.pcm", dtype="<i2")
    x = pcm.astype(np.float32) / 32768.0          # exactly what export_vectors.py feeds the reference
    ex = Extractor(Config(), input_rate=RATE)
    events = []
    for i in range(0, x.size, CHUNK):
        events += ex.push(x[i:i + CHUNK])
    events += ex.flush()
    return [e.to_dict() for e in events if e.emit]


def check_event(case: str, e: dict, want: str) -> None:
    if e["label"] != want:
        raise SystemExit(f"{case}: extractor now says {e['label']!r}, expected {want!r}; update this script")
    parsed = parse_line(e["text"])               # strict schema parser, raises on any drift
    if not label_consistent(e["label"], parsed):
        raise SystemExit(f"{case}: label {e['label']!r} disagrees with line {e['text']!r}")
    if not e["text"].isascii() or '"' in e["text"] or "\\" in e["text"]:
        raise SystemExit(f"{case}: line has characters the firmware table does not expect: {e['text']!r}")


def build() -> dict:
    sounds: list[dict] = []          # every sound entry the firmware knows
    sequences: list[dict] = []
    stale: list[str] = []

    def vector_texts(case: str) -> list[str]:
        d = json.loads((EXTRACTOR / "vectors" / f"{case}.events.json").read_text())
        return [e["text"] for e in d["events"] if e.get("emit", True)]

    for name, case, labels in SINGLES + CLIP_SEQUENCES:
        evs = extract(case)
        if len(evs) != len(labels):
            raise SystemExit(f"{case}: extractor emitted {[e['label'] for e in evs]}, expected {labels}")
        for e, want in zip(evs, labels):
            check_event(case, e, want)
        if [e["text"] for e in evs] != vector_texts(case):
            stale.append(case)
        idx = []
        for k, e in enumerate(evs):
            idx.append(len(sounds))
            sounds.append({
                "name": name if len(evs) == 1 else f"{name}.{k + 1}",
                "label": e["label"],
                "line": e["text"],
                "dur_ms": int(e["t_end_ms"] - e["t_start_ms"]),
                "source": f"extractor/vectors/{case}.pcm",
                "extracted_t_ms": [int(e["t_start_ms"]), int(e["t_end_ms"])],
            })
        if len(evs) > 1:
            gaps = [int(evs[k + 1]["t_start_ms"] - evs[k]["t_end_ms"]) for k in range(len(evs) - 1)]
            sequences.append({"name": name, "sounds": idx, "gaps_ms": gaps,
                              "note": f"one clip, gaps as extracted from {case}"})

    by_name = {s["name"]: i for i, s in enumerate(sounds)}
    for name, parts, gap in COMPOSED_SEQUENCES:
        sequences.append({"name": name, "sounds": [by_name[p] for p in parts], "gaps_ms": [gap] * (len(parts) - 1),
                          "note": f"composed from single sounds, gap {gap} ms"})

    payload = {"sounds": sounds, "sequences": sequences}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    src = hashlib.sha256()
    for p in sorted((EXTRACTOR / "vox_extract").glob("*.py")):
        src.update(p.name.encode() + b"\0" + p.read_bytes())
    return {
        "generated_by": "firmware/tools/gen_test_sounds.py",
        "synthetic": True,
        "note": "Lines produced by running the Python extractor on its SYNTHETIC test clips. Canned, for link tests.",
        "digest": digest,
        "vocab_digest": vocab.digest(),
        "extractor_source_sha256": src.hexdigest()[:16],
        "stale_vectors": stale,
        **payload,
    }


def c_str(s: str) -> str:
    return json.dumps(s)  # ASCII-only, no quotes or backslashes (checked): a valid C string literal


def render_header(d: dict) -> str:
    out = [
        "// GENERATED by firmware/tools/gen_test_sounds.py -- do not edit. Regenerate with tools/build.sh.",
        "// Canned sound lines, produced by running the Python reference extractor (extractor/vox_extract)",
        "// on its SYNTHETIC test clips (extractor/vectors). Used only for link/app tests (serial `send`).",
        "#pragma once",
        "#include <stdint.h>",
        "",
        f'#define VOX_TEST_SOUNDS_DIGEST "{d["digest"]}"',
        f'#define VOX_VOCAB_DIGEST "{d["vocab_digest"]}"',
        f'#define VOX_EXTRACTOR_SRC_SHA "{d["extractor_source_sha256"]}"',
        "",
        "struct VoxTestSound { const char *name; const char *label; const char *line; uint16_t dur_ms; };",
        "struct VoxTestSeq { const char *name; uint8_t n; uint8_t sound[3]; uint16_t gap_ms[2]; };",
        "",
        "static const VoxTestSound VOX_TEST_SOUNDS[] = {",
    ]
    for s in d["sounds"]:
        out.append(f'    {{{c_str(s["name"])}, {c_str(s["label"])},')
        out.append(f'     {c_str(s["line"])}, {s["dur_ms"]}}},')
    out += ["};", f"static const int VOX_N_TEST_SOUNDS = {len(d['sounds'])};", "",
            "static const VoxTestSeq VOX_TEST_SEQS[] = {"]
    for q in d["sequences"]:
        idx = q["sounds"] + [0] * (3 - len(q["sounds"]))
        gaps = q["gaps_ms"] + [0] * (2 - len(q["gaps_ms"]))
        out.append(f'    {{{c_str(q["name"])}, {len(q["sounds"])}, {{{", ".join(map(str, idx))}}}, '
                   f'{{{", ".join(map(str, gaps))}}}}},  // {q["note"]}')
    out += ["};", f"static const int VOX_N_TEST_SEQS = {len(d['sequences'])};", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if the files differ from the extractor")
    a = ap.parse_args()
    d = build()
    header = render_header(d)
    js = json.dumps(d, indent=1) + "\n"
    if d["stale_vectors"]:
        print(f"note: extractor/vectors events.json are stale for {d['stale_vectors']} "
              "(the live extractor output is used)", file=sys.stderr)
    if a.check:
        # Stale = the lines/labels/durations or the vocabulary differ. A change of the extractor's source hash alone
        # (someone edited vox_extract without changing these outputs) is reported but is not stale.
        try:
            old = json.loads(JSON_OUT.read_text())
        except (OSError, ValueError):
            old = {}
        ok = (old.get("digest") == d["digest"] and old.get("vocab_digest") == d["vocab_digest"]
              and HEADER.exists() and f'VOX_TEST_SOUNDS_DIGEST "{d["digest"]}"' in HEADER.read_text())
        note = ""
        if ok and old.get("extractor_source_sha256") != d["extractor_source_sha256"]:
            note = " (extractor source changed since generation; the outputs did not)"
        print(f"test sounds {'up to date' if ok else 'STALE'} (digest {d['digest']}, file {old.get('digest')}){note}")
        sys.exit(0 if ok else 1)
    HEADER.write_text(header)
    JSON_OUT.write_text(js)
    print(f"wrote {HEADER.relative_to(VOX)} and {JSON_OUT.relative_to(VOX)}: {len(d['sounds'])} sounds, "
          f"{len(d['sequences'])} sequences, digest {d['digest']}")


if __name__ == "__main__":
    main()
