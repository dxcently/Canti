"""Synthetic WHAT choices, without training or screen-element resolution.

The oracle reads only the visible transcript and completed steps, never the source
plan or candidate list. Counts stay open until a connector/final boundary. Search,
type and symbolic taps are final-only; a typed outward intent is not permission to
execute it (the runtime confirmation gate still applies). Restarts cancel only
pending work. Quoted payloads protect literal connectors/restart words.

Utterances are ASR-like: payloads are spoken unquoted (ASR never emits quote marks).
The oracle still accepts quoted payloads, but no generated utterance contains them.

Class balance: every word boundary is a row, so `wait` dominates. Train/validation keep
all non-wait rows and every wait row next to a label change (the last wait before a
commit, the first after one), plus --wait-keep of the remaining interior waits. The test
splits keep every boundary: they are the runtime stream.

Run: python -m vox.whatgen --out data/what-v1 --seed 7 --rows 2000
--rows is a minimum: complete utterance trajectories are never truncated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import generate as V5, wordings as W
from .schema import APPS, PHRASES
from .targets import ELEMENTS, FUNC, ITEMS

SPLITS = ("train", "validation", "test_iid", "test_unseen_phrasing", "test_unseen_apps")
CONNECTORS = (" and ", " then ", " after that ", " and then ", ", ")
COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4}
MOVES = ("scroll_up", "scroll_down", "swipe_up", "swipe_down", "swipe_left", "swipe_right")
SIMPLE = ("back", "home", "volume_up", "volume_down")
FILLER = re.compile(r"^(?:uh\b[ ,]*)+", re.I)
# v5's synthetic unrelated speech (generate.Generator.make, phrase kind): always none.
UNRELATED = ("uh what was that", "hmm", "no I'm talking to someone", "what time is it")
# The user trails off and ASR finalizes on a connector or a bare restart: the tail is none.
TRAILING = (" and", " then", " and then", " no wait,")
# A typed step and a tap on the element that does the same thing are synonyms, not
# negatives ("send it" vs tap "send button"). Never offer one as a distractor for the other.
SYNONYM_ELEMENTS = ("like", "send", "play", "pause", "back", "home_tab")
POLICY = (
    "Choose the next uncompleted typed step from heard so far and done steps, in order. "
    "Wait for an unambiguous complete step; counts need a connector or final boundary. "
    "Open app, back, home, scrolling, swiping, playback and volume may commit on partials. "
    "Search, typing, symbolic taps and outward actions wait for final words. "
    "A no wait restart cancels pending steps, retaining completed steps. "
    "After all steps are completed choose done only on final, otherwise wait. "
    "Unrecognized final speech, or final words that end on a connector or restart, is none. "
    "Outward actions still require runtime confirmation."
)


def quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


@dataclass(frozen=True)
class Phrase:
    text: str
    step: str
    source: str


def vocabulary(held: bool, apps: list[str]) -> list[Phrase]:
    """Reuse v5 wording partitions and targets' symbolic nouns and slot payloads.

    Only composition syntax is new: app/query/text slots, counts and connectors.
    The camera wording supplies the app-opening templates. Payloads are synthetic
    list titles already in targets.py, not device data.
    """
    h = int(held)
    out = []

    def add(text, step, source):
        out.append(Phrase(text, step, source))

    for key in SIMPLE + MOVES + ("play_pause", "like", "take_photo"):
        words = V5.ACTION_WORDS[key][1] if held else W.ACTION_WORDS_TRAIN[key] + PHRASES.get(key, [])
        for word in dict.fromkeys(words):
            if word == "keep scrolling down":
                continue  # continuous, never a one-shot scroll
            step = {"pause": "pause", "play": "play", "resume": "play", "resume playing": "play"}.get(word, key)
            if word.startswith("tap "):
                step = "tap " + quoted(word.removeprefix("tap "))
            if key in MOVES:
                add(word, key + " 1", f"action:{word}")
                # Bare directional forms accept a natural count suffix. Do not
                # append 'three times' to 'a little' or 'one' wordings.
                if word in V5.ACTION_WORDS[key][h]:
                    for count, n in COUNTS.items():
                        add(f"{word} {count} {'time' if n == 1 else 'times'}", f"{key} {n}", f"action:{word}")
            else:
                add(word, step, f"action:{word}")
    for package in apps:
        name = APPS[package]
        words = V5.ACTION_WORDS["open_camera"][1] if held else W.ACTION_WORDS_TRAIN["open_camera"]
        for word in words:
            add(word.replace("camera", name), "open_app " + name.lower(), f"open:{word}")
            if not held and "the camera" in word:
                add(word.replace("the camera", name), "open_app " + name.lower(), f"open:{word}")
    for key, element in ELEMENTS.items():
        for noun in element[4 if held else 3]:
            # NAME_T supplies tap/select in train and go-for in held-out.
            text = f"go for {noun}" if held else f"tap {noun}"
            add(text, "tap " + quoted(noun), f"target:{text}")
    for payload in ITEMS["scrolling list"][h]:
        q = quoted(payload)
        # Slot-bearing adaptations of FUNC search/message_box, whose banks have
        # no arbitrary string arguments in v5.
        for template in [w.replace("something", "{q}") for w in FUNC["search"][h]]:
            add(template.format(q=payload), "search " + q, "query:" + template)
        text_templates = [w.replace("something", "{q}").replace("a message", "{q}") for w in FUNC["message_box"][h]]
        for template in [w if "{q}" in w else w + " {q}" for w in text_templates]:
            add(template.format(q=payload), "type " + q, "text:" + template)
    for word in FUNC["send"][h]:
        add(word, "send", f"send:{word}")
    for key in ("play", "pause"):
        for word in FUNC[key][h]:
            add(word, key, f"playback:{word}")
    continuous = "keep scrolling down"  # W.ACTION_WORDS_TRAIN['scroll_down']
    add("keep nudging the page down" if held else continuous, "scroll_down continuous", "continuous:" + str(h))
    return out


# The oracle uses both wording partitions; generation independently enforces the
# split. Its decisions do not depend on which test/train pool supplied a phrase.
LEXICON: dict[str, str] = {}
for _phrase in vocabulary(False, list(APPS)) + vocabulary(True, list(APPS)):
    _key = _phrase.text.lower()
    if _key in LEXICON and LEXICON[_key] != _phrase.step:
        raise ValueError(f"ambiguous wording: {_key}")
    LEXICON[_key] = _phrase.step


def synonym_group(step: str) -> str | None:
    """'like', 'tap "heart"' and 'tap "the like button"' -> 'like'; None if not in a group."""
    head, _, arg = step.partition(" ")
    if head != "tap":
        return {"home": "home_tab"}.get(step, step if step in SYNONYM_ELEMENTS else None)
    noun = json.loads(arg).lower()
    for key in SYNONYM_ELEMENTS:
        if noun in (*ELEMENTS[key][3], *ELEMENTS[key][4]) or noun == f"the {key} button":
            return key
    return None


def reversible(step: str) -> bool:
    return step.split()[0] in {*SIMPLE, *MOVES, "open_app", "play", "pause", "play_pause"}


def chunks(heard: str) -> list[tuple[str, str]]:
    """Split outside quoted strings, retaining incomplete connectors/restarts.

    A trailing 'no' is already a cancellation signal. Literal 'no wait' within
    a quoted query/text is data. Commas are connectors, except in 'no wait,'.
    """
    pattern = r'"(?:\\.|[^"\\])*"?|\bno(?:\s+wait)?\b,?|\band(?:\s+then)?\b|\bthen\b|\bafter(?:\s+that)?\b|,'
    out, start = [], 0
    for match in re.finditer(pattern, heard, re.I):
        token = match.group()
        if token.startswith('"'):
            continue
        out.append((heard[start:match.start()].strip(), "restart" if token.lower().startswith("no") else "connector"))
        start = match.end()
    out.append((heard[start:].strip(), "end"))
    return out


def parse_step(text: str, closed: bool) -> str | None:
    """None means incomplete/unrecognized, not a guessed action."""
    text = FILLER.sub("", text).strip()
    lower = text.lower()
    if not text:
        return None
    # Preserve arbitrary text case; the finite lexicon is for wording, not values.
    for pattern, kind in ((r"(?:search(?: for)?|find) (.+)", "search"),
                          (r"look (.+) up", "search"),
                          (r"(?:type|write|start typing) (.+)", "type"),
                          (r"(?:tap|select|go for) (.+)", "tap")):
        m = re.fullmatch(pattern, text, re.I)
        if m:
            value = m[1].strip()
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    return None
            # 'search for' alone is not a search for "for".
            if not value or not closed or (kind == "search" and value.lower() == "for"):
                return None
            return kind + " " + quoted(value)
    step = LEXICON.get(lower)
    if step is None:
        return None
    if not closed:
        # An exact phrase can also be the start of a different intent, e.g.
        # 'go back' -> 'go back one' (not in this WHAT subset), or scroll counts.
        if step.split()[0] in MOVES and not step.endswith("continuous") and not re.search(r"\b(?:time|times)$", lower):
            return None
        if any(p.startswith(lower + " ") and s != step for p, s in LEXICON.items()):
            return None
    return step


def decide(heard: str, final: bool, done: list[str] | tuple[str, ...] = ()) -> str:
    """Visible-prefix oracle. Completed occurrences are consumed in order.

    Restarts erase pending work, not already committed occurrences. Repeating a
    command intentionally is distinct from having completed its first occurrence.
    Invalid/incomplete completed-history alignments fail closed.
    """
    remaining = list(done)
    pending: list[str | None] = []
    saw_command = False
    for text, boundary in chunks(heard):
        text = FILLER.sub("", text).strip()  # a lone mid-utterance 'uh' is not a step
        if text:
            step = parse_step(text, boundary != "end" or final)
            saw_command |= step is not None
            if remaining and step == remaining[0] and not pending:
                remaining.pop(0)
            else:
                pending.append(step)
        if boundary == "restart":
            pending.clear()
    if remaining:
        return "none" if final else "wait"
    if pending:
        step = pending[0]
        if step is None:
            return "none" if final else "wait"
        return step if final or reversible(step) else "wait"
    # A trailing connector/restart is an unfinished request even at ASR final.
    if final and saw_command and chunks(heard)[-1][0]:
        return "done"
    return "none" if final else "wait"


def trajectory(utterance: str) -> list[tuple[str, bool, list[str], str]]:
    """Every word boundary, then drain final steps and emit the terminal row."""
    done: list[str] = []
    rows = []
    for match in re.finditer(r"\S+(?=\s|$)", utterance):
        heard = utterance[:match.end()]
        answer = decide(heard, False, done)
        rows.append((heard, False, done.copy(), answer))
        if answer not in ("wait", "none", "done"):
            done.append(answer)
    while True:
        answer = decide(utterance, True, done)
        rows.append((utterance, True, done.copy(), answer))
        if answer in ("wait", "none", "done"):
            return rows
        done.append(answer)


def keep_rows(answers: list[str], rng: random.Random, wait_keep: float) -> list[bool]:
    """Every non-wait row and every wait next to a label change; interior waits by chance."""
    keep = []
    for i, answer in enumerate(answers):
        draw = rng.random() < wait_keep if answer == "wait" else True  # one draw per wait: a stable stream
        edge = any(0 <= j < len(answers) and answers[j] != "wait" for j in (i - 1, i + 1))
        keep.append(answer != "wait" or edge or draw)
    return keep


def make_episode(rng: random.Random, split: str, serial: int, wait_keep: float = 1.0) -> list[dict]:
    held = split == "test_unseen_phrasing"
    apps = sorted(V5.HELDOUT_APPS) if split == "test_unseen_apps" else V5.TRAIN_APPS
    pool = vocabulary(held, apps)
    # Sample families first to avoid the larger swipe/count bank dominating.
    families = sorted({p.step.split()[0] for p in pool})
    steps = []
    for _ in range(rng.randint(1, 4)):
        family = rng.choice(families)
        steps.append(rng.choice([p for p in pool if p.step.split()[0] == family]))
    utterance = steps[0].text
    for step in steps[1:]:
        utterance += rng.choice(CONNECTORS) + step.text
    augmentation = rng.choices(["plain", "filler", "restart", "trailing", "unrelated"], [60, 15, 15, 5, 5])[0]
    cancelled = None
    if augmentation == "filler":
        utterance = "uh " + utterance
    elif augmentation == "restart":
        cancelled = rng.choice(pool)
        utterance = cancelled.text + " no wait, " + utterance
    elif augmentation == "trailing":
        utterance += rng.choice(TRAILING)
    elif augmentation == "unrelated":
        utterance = rng.choice(UNRELATED)
        steps = []
    scene = V5.Scene(mode="live", app=rng.choice(apps))
    scene.screen = V5.Generator(rng, held, apps).screen(scene.app)
    initial_app = scene.app
    screens = {scene.app: scene.screen}
    # Candidate menu is constant across prefixes: includes full-plan alternatives
    # plus unrelated same-family choices, never just the single correct answer.
    plan = {p.step for p in steps} | ({cancelled.step} if cancelled else set())
    taken = {synonym_group(step) for step in plan} - {None}
    candidates = {"wait", "done", "none", *plan}

    def negative(step: str) -> None:
        if step in plan or synonym_group(step) not in taken:
            candidates.add(step)

    for p in steps:
        family = p.step.split()[0]
        alternatives = sorted({q.step for q in pool if q.step.split()[0] == family and q.step != p.step})
        if alternatives:
            negative(rng.choice(alternatives))
    candidates.update("open_app " + APPS[a].lower() for a in rng.sample(apps, 2))
    for p in rng.sample(pool, 4):
        negative(p.step)
    rows = []
    path = trajectory(utterance)
    keep = keep_rows([answer for *_, answer in path], rng, wait_keep)
    for index, (heard, final, done, answer) in enumerate(path):
        current_app = initial_app
        for completed in done:
            if completed.startswith("open_app "):
                current_app = next(a for a in apps if "open_app " + APPS[a].lower() == completed)
        if current_app not in screens:
            screens[current_app] = V5.Generator(rng, held, apps).screen(current_app)
        scene.app, scene.screen = current_app, screens[current_app]
        options = sorted(candidates | {answer})
        rng.shuffle(options)
        if not keep[index]:
            continue
        kind = "final_" if final else "partial_"
        kind += "wait" if answer == "wait" else "done" if answer == "done" else "none" if answer == "none" else "action"
        rows.append({
            "context": scene.text() + f"\nheard so far: {quoted(heard)}\nfinal: {'yes' if final else 'no'}\ndone steps: {json.dumps(done)}",
            "options": options, "option_keys": options.copy(), "label": options.index(answer), "kind": kind,
            "split": split, "id": f"{split}-{serial}-{index}",
            "meta": {"episode": serial, "utterance": utterance, "heard": heard, "final": final, "done": done,
                     "steps": [p.step for p in steps], "wordings": [p.source for p in steps] + ([cancelled.source] if cancelled else []),
                     "augmentation": augmentation, "app": scene.app},
        })
    return rows


def generate(out: Path, seed: int = 7, rows: int = 40000, wait_keep: float = 0.25) -> dict:
    if rows < 5:
        raise ValueError("rows must be at least 5 (one trajectory per split)")
    out.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), *(Path(__file__).with_name(n) for n in ("generate.py", "schema.py", "wordings.py", "targets.py", "bank.py"))]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    manifest = {"seed": seed, "requested_rows": rows, "wait_keep": wait_keep, "code_hash": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
                "source_hashes": hashes, "synthetic_only": True, "splits": {}}
    # Whole episodes remain together. Duplicate utterances across splits are
    # rejected, including their normalized filler/restart variants.
    seen: set[str] = set()
    for index, split in enumerate(SPLITS):
        rng = random.Random(seed + index)
        target = max(1, rows * (80 if split == "train" else 5) // 100)
        records, serial, attempts = [], 0, 0
        while len(records) < target:
            episode = make_episode(rng, split, serial, 1.0 if split.startswith("test_") else wait_keep)
            signature = re.sub(r"^uh\s+", "", episode[0]["meta"]["utterance"].lower())
            attempts += 1
            # The four unrelated phrases are a closed none class (as in v5), not a leak.
            if signature in seen and episode[0]["meta"]["augmentation"] != "unrelated":
                if attempts > target * 100 + 1000:
                    raise RuntimeError("exhausted unique utterances")
                continue
            seen.add(signature)
            records.extend(episode)
            serial += 1
        # Episodes are generated contiguously; load_rows(limit) and --val-limit take a prefix.
        rng.shuffle(records)
        path = out / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        manifest["splits"][split] = {
            "rows": len(records), "episodes": serial,
            "by_kind": dict(sorted(Counter(r["kind"] for r in records).items())),
            "by_label": dict(sorted(Counter(r["option_keys"][r["label"]] for r in records).items())),
            "by_action": dict(sorted(Counter(r["option_keys"][r["label"]].split()[0] for r in records).items())),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (out / "policy.txt").write_text(POLICY + "\n", encoding="utf-8")
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/what-v1"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--rows", type=int, default=40000, help="minimum total rows, rounded up to whole trajectories")
    parser.add_argument("--wait-keep", type=float, default=0.25, help="share of interior wait rows kept in train/validation")
    args = parser.parse_args()
    manifest = generate(args.out, args.seed, args.rows, args.wait_keep)
    print(json.dumps({s: v for s, v in manifest["splits"].items()}, indent=2))


if __name__ == "__main__":
    main()
