"""Merge the LLM-written wording bank (wordings_llm/bank.json) into the training banks, safely.

The bank was written blind to the held-out lists (on purpose), so it is filtered here, where both
are visible:
  - exact, substring or near-duplicate (token Jaccard >= JACCARD) matches to any held-out wording
    or template are dropped: they would leak test phrasing into training;
  - held-out spoken phrases are dropped;
  - entries AMBIGUITY.md marks as readable as a *different* option are dropped: a wrong label
    teaches more than a missing wording.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

JACCARD = 0.6


def norm(s: str) -> str:
    s = re.sub(r"\{\w+\}", " ", s.lower())
    return " ".join(re.findall(r"[a-z0-9]+", s))


def near(a: str, b: str) -> bool:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb or f" {nb} " in f" {na} " or f" {na} " in f" {nb} ":
        return True
    ta, tb = set(na.split()), set(nb.split())
    return len(ta & tb) / len(ta | tb) >= JACCARD


def ambiguous(md: Path) -> set[str]:
    """Wordings whose 'could also be read as' column names a key other than the one it is filed under."""
    out = set()
    for line in md.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in ("wording", "phrase") or set(cells[0]) <= set("-"):
            continue
        wording, filed, other = cells[0], cells[1], {x.strip().split(" ")[0] for x in cells[2].split(",")}
        if other - {filed}:
            out.add(norm(wording))
    return out


def load(path: Path, held: dict, heldout_phrases: set[str]) -> tuple[dict, dict[str, list[str]]]:
    """held: {'actions': {key: [held-out wordings]}, 'gestures': {...}, '<template kind>': [held-out templates]}."""
    bank = json.loads(path.read_text())
    amb = ambiguous(path.with_name("AMBIGUITY.md"))
    every_held = [w for v in held.values() for w in (v if isinstance(v, list) else [x for ws in v.values() for x in ws])]
    dropped: dict[str, list[str]] = {}
    out = {}
    for sec, val in bank.items():
        def keep(w: str, sec=sec) -> bool:
            why = ("heldout" if any(near(w, h) for h in every_held) else
                   "heldout_phrase" if norm(w) in heldout_phrases else
                   "ambiguous" if norm(w) in amb else None)
            if why:
                dropped.setdefault(why, []).append(f"{sec}: {w}")
            return why is None
        out[sec] = {k: [w for w in ws if keep(w)] for k, ws in val.items()} if isinstance(val, dict) else [w for w in val if keep(w)]
    return out, dropped
