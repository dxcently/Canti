"""Write app/src/test/resources/state_parity.json: random Scenes and the text generate.py's Scene.text() renders.

StateParityTest (JVM unit test) rebuilds each Scene in Kotlin and requires byte-identical text. Also checks the rule
decider against generate.py's own labels on generated rows that need no language understanding (see rows_for_rules).
"targets": rows of finetune/data/targets-v1 (intent cursor mode) split into their parts, so the Kotlin state text and
option format can be checked against the training data.

    python3 tools/state_parity.py
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANDROID = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ANDROID.parent / "finetune"))
from vox import generate as G  # noqa: E402
from vox import schema as S  # noqa: E402

OUT = ANDROID / "app/src/test/resources/state_parity.json"


def random_scene(r: random.Random, gen: G.Generator) -> G.Scene:
    app = r.choice(list(S.APPS))
    mode = r.choice(["gesture", "gesture", "cursor", "listening"])
    sc = G.Scene(mode=mode, app=app, recent=gen.recent())
    if r.random() < 0.8:
        sc.screen = gen.screen(app)
    if mode == "cursor":
        sc.cursor = r.choice(["moving right slow", "moving up fast", "stopped", "dragging, stopped"])
    if mode == "listening":
        sc.phrase = r.choice(["next", "go back", 'say "cheese"', "hmm"])
    else:
        seq = gen.random_seq()
        sc.sequence = seq
        sc.heard = [gen.deliberate_sound(g) if r.random() < 0.8 else gen.junk_sound()[0] for g in seq]
    sc.rules = gen.distractor_rules(app, (), r.randint(0, 3))
    return sc


def main() -> None:
    r = random.Random(7)
    gen = G.Generator(r, heldout_phrasing=False, apps=G.TRAIN_APPS)
    cases = []
    for _ in range(300):
        sc = random_scene(r, gen)
        cases.append({
            "mode": sc.mode, "app": sc.app, "app_name": S.APPS[sc.app], "heard": sc.heard, "sequence": list(sc.sequence),
            "rules": sc.rules, "phrase": sc.phrase, "recent": sc.recent, "cursor": sc.cursor,
            "screen": list(sc.screen) if sc.screen else None, "text": sc.text(),
        })
    # Rows whose label the rule table must reproduce: defaults, unbound, not-deliberate, plain phrases, screen phrases,
    # and cursor rows without a rule sentence. (Rows with rule sentences need language understanding: model only.)
    rows = []
    rr = random.Random(11)
    g2 = G.Generator(rr, heldout_phrasing=False, apps=G.TRAIN_APPS)
    for kind in ["default", "unbound", "not_deliberate", "phrase", "screen_phrase", "cursor"] * 200:
        row = g2.make(kind)
        ctx = row["context"]
        if "my rules: none" not in ctx:
            continue
        rows.append({"kind": row["kind"], "context": ctx, "answer": row["option_keys"][row["label"]]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # The order the options are sent in must be schema dict order (checked by CoreTest.optionOrderMatchesSchema).
    order = {"actions": list(S.ACTIONS), "cursor_actions": list(S.CURSOR_ACTIONS)}
    targets = target_rows()
    OUT.write_text(json.dumps({"scenes": cases, "rows": rows, "option_order": order, "targets": targets}, indent=0) + "\n")
    print(f"wrote {OUT}: {len(cases)} scenes, {len(rows)} labelled rows, {len(targets)} target rows")


def target_rows(n: int = 120) -> list[dict]:
    """Intent-cursor rows split into (app name, package, screen parts, utterance) and (label, role, position) per option."""
    from vox import targets as T  # noqa: PLC0415
    src = ANDROID.parent / "finetune/data/targets-v1"
    ctx_re = re.compile(r'mode: cursor\napp: (.*) \(([^()]*)\)\nscreen: (.*); media (.*); scroll (.*); keyboard (.*)\nspoken target: "(.*)"', re.S)
    opt_re = re.compile(r"(.*) \(([^,()]+), ([^,()]+)\)")
    out = []
    for name in ("test_iid.jsonl", "test_unseen_apps.jsonl"):
        for line in (src / name).read_text().splitlines()[: n // 2]:
            row = json.loads(line)
            m = ctx_re.fullmatch(row["context"])
            assert m, row["context"]
            assert row["options"][-1] == T.NONE_OPTION
            opts = []
            for o in row["options"][:-1]:
                om = opt_re.fullmatch(o)
                assert om, o
                opts.append({"option": o, "label": om[1], "role": om[2], "position": om[3]})
            out.append({"context": row["context"], "app_name": m[1], "app": m[2], "screen": [m[3], m[4], m[5], m[6]],
                        "utterance": m[7], "options": opts})
    return out


if __name__ == "__main__":
    main()
