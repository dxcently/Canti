"""Checks wordings_llm/bank.json against the schema vocabulary and the shipped training wordings.

Run: python3 validate.py            (exits non-zero on any failure)
     python3 validate.py --info     (also lists vocab overlaps that are not failures)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from vox.schema import ACTIONS, CONTOURS, DISCRETE, PHRASES
from vox.wordings import (
    ACTION_WORDS_TRAIN,
    DISABLE_TEMPLATES_TRAIN,
    GESTURE_WORDS_TRAIN,
    GLOBAL_TEMPLATES_TRAIN,
    PHRASE_TEMPLATES_TRAIN,
    RULE_TEMPLATES_TRAIN,
)

BANK = HERE / "bank.json"

ACTION_MIN, ACTION_MAX = 30, 40
GESTURE_MIN, GESTURE_MAX = 20, 30

TEMPLATE_MIN = {
    "app_rule_templates": 40,
    "global_rule_templates": 25,
    "disable_templates": 15,
    "phrase_templates": 15,
}
TEMPLATE_PLACEHOLDERS = {
    "app_rule_templates": ({"app", "g", "a"}, {"app", "g", "a"}),
    "global_rule_templates": ({"g", "a"}, {"g", "a"}),
    "disable_templates": ({"app", "g"}, {"app", "g"}),
    "phrase_templates": ({"p", "a"}, {"p", "a"}),
}
TRAIN_TEMPLATES = {
    "app_rule_templates": RULE_TEMPLATES_TRAIN,
    "global_rule_templates": GLOBAL_TEMPLATES_TRAIN,
    "disable_templates": DISABLE_TEMPLATES_TRAIN,
    "phrase_templates": PHRASE_TEMPLATES_TRAIN,
}

EXPECTED_ACTIONS = set(ACTIONS) - {"none"}
EXPECTED_GESTURES = set(CONTOURS) | set(DISCRETE)
PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


def norm(text: str) -> str:
    """Aggressive: punctuation and case dropped. Used for wordings, where 'flick the screen up' and
    'Flick the screen up!' are the same string to a reader."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9{}]+", " ", text.lower())).strip()


def templ_key(text: str) -> str:
    """Only case and whitespace are dropped. Template notation (-> : | =) is load-bearing."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def train_vocab() -> dict[str, set[str]]:
    pools: dict[str, set[str]] = {}
    for key, words in ACTION_WORDS_TRAIN.items():
        pools.setdefault("action", set()).update(words)
    for words in GESTURE_WORDS_TRAIN.values():
        pools.setdefault("gesture", set()).update(words)
    for templs in TRAIN_TEMPLATES.values():
        pools.setdefault("template", set()).update(templs)
    return pools


def main() -> int:
    info = "--info" in sys.argv
    bank = json.loads(BANK.read_text())
    fails: list[str] = []
    notes: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    check(set(bank) == {"actions", "gestures", *TEMPLATE_MIN}, f"top-level keys wrong: {sorted(bank)}")

    actions, gestures = bank["actions"], bank["gestures"]
    check(set(actions) == EXPECTED_ACTIONS, f"action keys wrong: missing {sorted(EXPECTED_ACTIONS - set(actions))}, extra {sorted(set(actions) - EXPECTED_ACTIONS)}")
    check(set(gestures) == EXPECTED_GESTURES, f"gesture keys wrong: missing {sorted(EXPECTED_GESTURES - set(gestures))}, extra {sorted(set(gestures) - EXPECTED_GESTURES)}")

    for key, words in actions.items():
        check(ACTION_MIN <= len(words) <= ACTION_MAX, f"action {key}: {len(words)} wordings, want {ACTION_MIN}-{ACTION_MAX}")
    for key, words in gestures.items():
        check(GESTURE_MIN <= len(words) <= GESTURE_MAX, f"gesture {key}: {len(words)} wordings, want {GESTURE_MIN}-{GESTURE_MAX}")

    for name, minimum in TEMPLATE_MIN.items():
        templs = bank[name]
        check(len(templs) >= minimum, f"{name}: {len(templs)} templates, want >= {minimum}")
        need, allowed = TEMPLATE_PLACEHOLDERS[name]
        for t in templs:
            found = set(PLACEHOLDER_RE.findall(t))
            check(need <= found, f"{name}: missing placeholder(s) {sorted(need - found)} in {t!r}")
            check(found <= allowed, f"{name}: unknown placeholder(s) {sorted(found - allowed)} in {t!r}")
    for t in bank["global_rule_templates"]:
        check("{app}" not in t, f"global_rule_templates: {{app}} not allowed in {t!r}")

    seen: dict[str, str] = {}
    for section, groups in (("actions", actions), ("gestures", gestures), *((n, {n: bank[n]}) for n in TEMPLATE_MIN)):
        is_wordings = section in ("actions", "gestures")
        for key, words in groups.items():
            label = f"{section}/{key}" if is_wordings else section
            for w in words:
                check(w == w.strip() and w != "", f"{label}: blank or padded entry {w!r}")
                n = norm(w) if is_wordings else templ_key(w)
                check(n not in seen, f"duplicate: {w!r} in {label} also in {seen.get(n)}")
                seen.setdefault(n, label)

    pools = train_vocab()
    for section, group, pool_name in (("actions", actions, "action"), ("gestures", gestures, "gesture")):
        pool_exact = pools[pool_name]
        pool_norm = {norm(w) for w in pool_exact}
        for key, words in group.items():
            for w in words:
                check(w not in pool_exact, f"{section}/{key}: {w!r} is copied from wordings.py")
                check(norm(w) not in pool_norm, f"{section}/{key}: {w!r} matches a wordings.py entry after normalising")
    train_templates_norm = {templ_key(t) for templs in TRAIN_TEMPLATES.values() for t in templs}
    for name in TEMPLATE_MIN:
        for t in bank[name]:
            check(t not in TRAIN_TEMPLATES[name], f"{name}: {t!r} is copied from wordings.py")
            check(templ_key(t) not in train_templates_norm, f"{name}: {t!r} matches a wordings.py template after normalising")

    if info:
        vocab = {**{norm(v): f"schema ACTIONS[{k}]" for k, v in ACTIONS.items()},
                 **{norm(v): f"schema CONTOURS[{k}]" for k, v in CONTOURS.items()},
                 **{norm(v): f"schema DISCRETE[{k}]" for k, v in DISCRETE.items()}}
        for k, phr in PHRASES.items():
            for p in phr:
                vocab[norm(p)] = f"schema PHRASES[{k}]"
        for section, group in (("actions", actions), ("gestures", gestures)):
            for key, words in group.items():
                for w in words:
                    if norm(w) in vocab:
                        notes.append(f"INFO {section}/{key}: {w!r} textually equals {vocab[norm(w)]}")

    for key, words in actions.items():
        print(f"  actions.{key:20} {len(words):3}")
    for key, words in gestures.items():
        print(f"  gestures.{key:19} {len(words):3}")
    for name in TEMPLATE_MIN:
        print(f"  {name:24} {len(bank[name]):3}")

    for n in notes:
        print(n)
    if fails:
        print(f"\nFAIL ({len(fails)})")
        for f in fails:
            print(f"  - {f}")
        return 1
    total = sum(len(v) for v in actions.values()) + sum(len(v) for v in gestures.values()) + sum(len(bank[n]) for n in TEMPLATE_MIN)
    print(f"\nPASS: {total} entries, all checks clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
