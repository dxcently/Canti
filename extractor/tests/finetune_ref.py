"""Read-only access to the training-data generator in /home/khoa/VOX/finetune (never modified).

Bytecode writing is switched off during the import so nothing is written into finetune/.
Returns None when the directory is missing, so the extractor's tests still run elsewhere.
"""

from __future__ import annotations

import random
import sys
from functools import lru_cache
from pathlib import Path

FINETUNE = Path(__file__).resolve().parents[2] / "finetune"


@lru_cache(maxsize=1)
def load():
    if not (FINETUNE / "vox" / "schema.py").exists():
        return None
    old_path, old_dwb = sys.path[:], sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(FINETUNE))
    try:
        import vox.generate as G
        import vox.schema as S
    finally:
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_dwb
    return S, G


@lru_cache(maxsize=1)
def seen_lines(draws: int = 60000, seed: int = 0) -> frozenset[str] | None:
    """Every sound line generate.py produces (deliberate_sound, air_hiss, junk_sound), by sampling.
    The line space is small (a few thousand), so this many draws covers the support."""
    ref = load()
    if ref is None:
        return None
    S, G = ref
    gen = G.Generator(random.Random(seed), False, [])
    names = list(S.CONTOURS) + list(S.DISCRETE)
    out = set()
    for _ in range(draws):
        for g in names:
            out.add(gen.deliberate_sound(g))
        out.add(gen.air_hiss())
        out.add(gen.junk_sound()[0])
    return frozenset(out)
