"""No model imports, network, installs, or device data are needed."""
import importlib.util
import random
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

from students.common import load_rows
from vox import generate as v5
from vox.schema import APPS
from vox import bank
from vox.whatgen import SPLITS, decide, load_bank, generate, keep_rows, synonym_group, trajectory, vocabulary

DATA = Path(__file__).resolve().parents[1] / "data"  # gitignored; keeps test output inside the checkout


def by_episode(rows):
    """Rows are shuffled in the file; ids end in the trajectory index."""
    episodes = {}
    for row in rows:
        episodes.setdefault(row["meta"]["episode"], []).append(row)
    return [sorted(e, key=lambda r: int(r["id"].rsplit("-", 1)[1])) for e in episodes.values()]

# Independent expected labels: these are not derived from the generator's plan.
CASES = [
    ("", False, [], "wait"),
    ("", True, [], "none"),
    ("uh", False, [], "wait"),
    ("uh what was that", True, [], "none"),
    ("open", False, [], "wait"),
    ("open you", False, [], "wait"),
    ("open YouTube", False, [], "open_app youtube"),
    ("open Google", False, [], "wait"),
    ("open Google Maps", False, [], "open_app google maps"),
    ("launch Spotify", True, [], "open_app spotify"),
    ("search", False, [], "wait"),
    ("search lofi", False, [], "wait"),
    ("search lofi", True, [], 'search "lofi"'),
    ("search for lofi beats", True, [], 'search "lofi beats"'),
    ('search "rock and roll"', True, [], 'search "rock and roll"'),
    ('search "no wait"', True, [], 'search "no wait"'),
    ('search "unfinished', True, [], "none"),
    ('type ""', True, [], "none"),
    ("type hello", False, [], "wait"),
    ("type Hello Alex", True, [], 'type "Hello Alex"'),
    ("type hello and go home", False, [], "wait"),
    ("type hello and go home", True, [], 'type "hello"'),
    ("type hello and go home", True, ['type "hello"'], "home"),
    ("tap first result", False, [], "wait"),
    ("tap first result", True, [], 'tap "first result"'),
    ("tap send button", False, [], "wait"),
    ("tap send button", True, [], 'tap "send button"'),
    ("send it", False, [], "wait"),
    ("send it", True, [], "send"),
    ("like it", False, [], "wait"),
    ("take a picture", False, [], "wait"),
    ("take a picture", True, [], "take_photo"),
    ("scroll down", False, [], "wait"),
    ("scroll down th", False, [], "wait"),
    ("scroll down three", False, [], "wait"),
    ("scroll down three times", False, [], "scroll_down 3"),
    ("scroll down then", False, [], "scroll_down 1"),
    ("scroll down", True, [], "scroll_down 1"),
    ("swipe left two times", False, [], "swipe_left 2"),
    ("swipe right one time", True, [], "swipe_right 1"),
    ("keep scrolling down", False, [], "scroll_down continuous"),
    ("go back", False, [], "back"),
    ("go home", False, [], "home"),
    ("play", False, [], "wait"),  # may continue 'play or pause'
    ("play", True, [], "play"),
    ("pause", True, [], "pause"),
    ("resume", False, [], "wait"),  # may continue 'resume or halt playback' (LLM bank)
    ("resume playing", False, [], "play"),
    ("volume up", False, [], "volume_up"),
    ("turn the volume down", False, [], "volume_down"),
    ("uh open YouTube", False, [], "open_app youtube"),
    ("open YouTube then search lofi", False, ["open_app youtube"], "wait"),
    ("open YouTube then search lofi", True, [], "open_app youtube"),
    ("open YouTube then search lofi", True, ["open_app youtube"], 'search "lofi"'),
    ("open YouTube then search lofi", True, ["open_app youtube", 'search "lofi"'], "done"),
    ("go home", False, ["home"], "wait"),
    ("go home", True, ["home"], "done"),
    ("go home then go home", True, ["home"], "home"),
    ("go home then go home", True, ["home", "home"], "done"),
    ("type hello no", False, [], "wait"),
    ("type hello no wait,", False, [], "wait"),
    ("type hello no wait,", True, [], "wait"),  # dangling restart: keep listening
    ("type hello no wait, go home", False, [], "home"),
    ("open YouTube no wait, open Spotify", True, [], "open_app spotify"),
    ("open YouTube no wait, open Spotify", False, ["open_app youtube"], "undo open_app youtube"),
    ("open YouTube no wait, open Spotify", False, ["open_app youtube", "undo open_app youtube"], "open_app spotify"),
    ("open YouTube no wait,", False, ["open_app youtube"], "undo open_app youtube"),
    ("open YouTube no", False, ["open_app youtube"], "wait"),  # bare trailing 'no' may be more speech
    ("open YouTube no", True, ["open_app youtube"], "undo open_app youtube"),
    ("open YouTube and no wait, open Spotify", False, ["open_app youtube"], "undo open_app youtube"),
    ("scroll down three times no wait, scroll up", False, ["scroll_down 3"], "undo scroll_down 3"),
    ("scroll down three times no wait, scroll up", True, ["scroll_down 3", "undo scroll_down 3"], "scroll_up 1"),
    ("open YouTube no wait, open Spotify no wait, open Chrome", False,
     ["open_app youtube", "undo open_app youtube", "open_app spotify"], "undo open_app spotify"),
    ("go home then open YouTube no wait, go back", False, ["home", "open_app youtube"], "undo open_app youtube"),
    ("go home then open YouTube no wait, go back", False, ["home", "open_app youtube", "undo open_app youtube"], "back"),
    ("go home no wait, go home", True, ["home", "undo home", "home"], "done"),
    ("go home then type hello no wait, go back", True, ["home"], "back"),
    ("go home no wait, go home", True, ["home"], "undo home"),
    ("go home no wait, go home", True, ["home", "undo home"], "home"),
    ("type a no wait, type b no wait, type c", True, [], 'type "c"'),
    ("go home and", True, ["home"], "wait"),
    ("go home", True, ["back"], "none"),
    ("go home, go back after that volume up", True, ["home"], "back"),
    ("jump to the launcher", False, [], "home"),
    ("start the Netflix app", False, [], "open_app netflix"),
    ('look "Book club" up', True, [], 'search "Book club"'),
    ('start typing "Book club"', False, [], "wait"),
    ("go for the dart icon", True, [], 'tap "the dart icon"'),
    # Unquoted payloads, as ASR delivers them.
    ("find Liked Songs", False, [], "wait"),
    ("find Liked Songs", True, [], 'search "Liked Songs"'),
    ("find Liked Songs then flick up two times", False, [], "wait"),
    ("find Liked Songs then flick up two times", True, ['search "Liked Songs"'], "swipe_up 2"),
    ("look Book club up", True, [], 'search "Book club"'),
    ("search for", True, [], "none"),
    ("search for", False, [], "wait"),
    ("go home, uh, go back", True, ["home"], "back"),
    ("go home then uh", False, ["home"], "wait"),
    ("go home and then", True, ["home"], "wait"),
    ("type Mom no wait,", True, [], "wait"),
    ("type Mom and", True, [], 'type "Mom"'),
    ("type Mom and", True, ['type "Mom"'], "wait"),
    ("pause it", True, [], "pause"),  # words, not media state (v5 said none when already paused)
    ("no I'm talking to someone", True, [], "none"),
    ("hmm", True, [], "none"),
]


class LabelCases(unittest.TestCase):
    pass


def case_test(case):
    def test(self):
        heard, final, done, expected = case
        self.assertEqual(decide(heard, final, done), expected)
    return test


for index, case in enumerate(CASES):
    setattr(LabelCases, f"test_case_{index:02d}", case_test(case))


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DATA.mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=DATA, prefix="test-whatgen-")
        cls.root = Path(cls.tmp.name)
        cls.manifest = generate(cls.root / "a", seed=17, rows=2000)
        cls.rows = {s: load_rows(str(cls.root / "a" / f"{s}.jsonl")) for s in SPLITS}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_determinism_and_seed(self):
        generate(self.root / "b", seed=17, rows=2000)
        for path in (self.root / "a").iterdir():
            self.assertEqual(path.read_bytes(), (self.root / "b" / path.name).read_bytes())
        generate(self.root / "c", seed=18, rows=2000)
        self.assertNotEqual((self.root / "a/train.jsonl").read_bytes(), (self.root / "c/train.jsonl").read_bytes())

    def test_hash_seed_determinism(self):
        for hash_seed in ("1", "987"):
            subprocess.run([sys.executable, "-m", "vox.whatgen", "--out", str(self.root / hash_seed), "--seed", "9", "--rows", "150"],
                           check=True, stdout=subprocess.DEVNULL, env={**os.environ, "PYTHONHASHSEED": hash_seed})
        for path in (self.root / "1").iterdir():
            self.assertEqual(path.read_bytes(), (self.root / "987" / path.name).read_bytes())

    def test_split_wordings_and_apps(self):
        train_sources = {p.source for p in vocabulary(False, v5.TRAIN_APPS)}
        held_sources = {p.source for p in vocabulary(True, v5.TRAIN_APPS)}
        self.assertFalse(train_sources & held_sources)
        seen_utterances = set()
        for split, rows in self.rows.items():
            utterances = {r["meta"]["utterance"].lower().removeprefix("uh ") for r in rows if r["meta"]["augmentation"] != "unrelated"}
            self.assertFalse(seen_utterances & utterances)
            seen_utterances |= utterances
            allowed = v5.HELDOUT_APPS if split == "test_unseen_apps" else set(v5.TRAIN_APPS)
            forbidden = set(APPS) - set(allowed)
            sources = held_sources if split == "test_unseen_phrasing" else train_sources
            for row in rows:
                self.assertIn(row["meta"]["app"], allowed)
                self.assertLessEqual(set(row["meta"]["wordings"]), sources)
                # Scan all fields, including options, completed/cancelled steps.
                text = json.dumps(row).lower()
                for app in forbidden:
                    if split != "test_unseen_apps":
                        self.assertNotIn(APPS[app].lower(), text)
                    # 'camera' may describe a symbolic target without referring
                    # to the Camera app; check typed app arguments separately.
                    self.assertNotIn("open_app " + APPS[app].lower(), row["options"])
                    self.assertNotIn(app.lower(), text)

    def test_rows_options_and_hard_negatives(self):
        for rows in self.rows.values():
            for row in rows:
                opts = row["options"]
                answer = opts[row["label"]]
                self.assertEqual(len(set(opts)), len(opts))
                self.assertEqual(opts, row["option_keys"])
                self.assertEqual(opts.count(answer), 1)
                self.assertLessEqual({"wait", "done", "none"}, set(opts))
                self.assertLessEqual(set(row["meta"]["steps"]), set(opts))
                # All later and already-done steps remain order distractors.
                opens = [o for o in opts if o.startswith("open_app ")]
                self.assertGreaterEqual(len(opens), 2)
                for field in ("mode: live", "app: ", "screen: ", "defaults: ", "my rules: none", "heard so far: ", "final: ", "done steps: "):
                    self.assertIn(field, row["context"])
                self.assertEqual(answer, decide(row["meta"]["heard"], row["meta"]["final"], row["meta"]["done"]))
                completed_apps = [s for s in row["meta"]["done"] if s.startswith("open_app ")]
                if completed_apps:
                    self.assertEqual("open_app " + APPS[row["meta"]["app"]].lower(), completed_apps[-1])
                if row["kind"] == "partial_action":
                    self.assertNotIn(answer.split()[0], {"type", "search", "tap", "like", "send", "take_photo"})

    def test_every_boundary_and_final_completion(self):
        for split, rows in self.rows.items():
            for episode in by_episode(rows):
                utterance = episode[0]["meta"]["utterance"]
                prefixes = [utterance[:m.end()] for m in re.finditer(r"\S+(?=\s|$)", utterance)]
                heard = [r["meta"]["heard"] for r in episode if not r["meta"]["final"]]
                if split.startswith("test_"):
                    self.assertEqual(heard, prefixes)  # test splits are the full runtime stream
                else:
                    self.assertEqual(heard, [p for p in prefixes if p in heard])
                    full = trajectory(utterance)
                    self.assertEqual(len([a for *_, a in full if a != "wait"]), len([r for r in episode if r["options"][r["label"]] != "wait"]))
                last = episode[-1]
                expected = {"unrelated": "none", "trailing": "wait"}.get(last["meta"]["augmentation"], "done")
                self.assertEqual(last["options"][last["label"]], expected)
                if last["meta"]["augmentation"] in {"plain", "filler"} or (
                        last["meta"]["augmentation"] == "trailing" and not utterance.endswith("no wait,")):
                    # Source-plan comparison is a test only, never oracle input.
                    actions = [r["options"][r["label"]] for r in episode if r["kind"].endswith("_action")]
                    self.assertEqual(actions, last["meta"]["steps"])

    def test_vocabulary_round_trip(self):
        for held in (False, True):
            for phrase in vocabulary(held, list(APPS)):
                self.assertEqual(decide(phrase.text, True), phrase.step, phrase.text)

    def test_heldout_wordings_absent_from_training_text(self):
        training = "\n".join(r["meta"]["utterance"].lower() for r in self.rows["train"])
        for phrase in vocabulary(True, v5.TRAIN_APPS):
            self.assertNotIn(phrase.text.lower(), training)

    def test_label_independent_of_future_words(self):
        # Shared prefix, different futures: never consult a plan's end offset.
        for text in ("scroll down then go home", "scroll down three times", "scroll down a little"):
            first = [row for row in trajectory(text) if row[0] == "scroll down"]
            self.assertEqual(first, [("scroll down", False, [], "wait")])

    def test_manifest_counts(self):
        for split, rows in self.rows.items():
            entry = self.manifest["splits"][split]
            self.assertEqual(entry["rows"], len(rows))
            self.assertEqual(entry["by_kind"], dict(Counter(r["kind"] for r in rows)))
            self.assertEqual(entry["by_label"], dict(Counter(r["options"][r["label"]] for r in rows)))
        self.assertGreaterEqual(sum(len(rows) for rows in self.rows.values()), 2000)
        self.assertEqual(len(self.manifest["code_hash"]), 64)

    def test_required_families_and_augmentations(self):
        rows = self.rows["train"]
        answers = {r["options"][r["label"]].split()[0] for r in rows}
        self.assertLessEqual({"open_app", "search", "type", "tap", "send", "scroll_down", "swipe_left", "back", "home", "volume_up", "wait", "done", "none"}, answers)
        self.assertEqual({r["meta"]["augmentation"] for r in rows}, {"plain", "filler", "restart", "trailing", "unrelated"})
        self.assertIn("undo", answers)
        self.assertEqual({len(r["meta"]["steps"]) for r in rows} - {0}, {1, 2, 3, 4})

    def test_jevlike_validator_if_available(self):
        # Do not discover/import editable installations pointing outside this
        # worktree: the task expressly forbids reading ~/jevlike.
        spec = importlib.util.find_spec("jevlike")
        if spec is None:
            self.skipTest("jevlike unavailable in the isolated test venv; students.common validated all rows")
        workspace = Path(__file__).resolve().parents[2]
        if not spec.origin or not Path(spec.origin).resolve().is_relative_to(workspace):
            self.skipTest("jevlike is external to the permitted worktree")
        from jevlike.data import validate
        for rows in self.rows.values():
            for row in rows:
                validate(row)

    def test_invalid_size(self):
        with self.assertRaises(ValueError):
            generate(self.root / "invalid", rows=0)

    def test_undo_rows(self):
        undos = [r for rows in self.rows.values() for r in rows if r["options"][r["label"]].startswith("undo ")]
        self.assertTrue(undos)
        for row in undos:
            self.assertTrue(row["meta"]["augmentation"] == "restart" or row["meta"]["utterance"].endswith("no wait,"))
            self.assertIn(row["options"][row["label"]].removeprefix("undo "), row["meta"]["done"])
        distractors = [r for r in self.rows["train"] if r["meta"]["augmentation"] != "restart" and any(o.startswith("undo ") for o in r["options"])]
        self.assertTrue(distractors)

    def test_pause_follows_words_not_media(self):
        rows = [r for rows in self.rows.values() for r in rows]
        self.assertTrue([r for r in rows if r["options"][r["label"]] == "pause" and "media paused" in r["context"]])
        self.assertTrue([r for r in rows if r["options"][r["label"]] == "play" and "media playing" in r["context"]])

    def test_bank_is_training_only(self):
        kept, dropped = load_bank()
        words = {w for ws in kept.values() for w in ws}
        self.assertGreater(len(words), 200)
        self.assertIn("heldout", dropped)
        held = [p.text for p in vocabulary(True, list(APPS))] + [w for k, v in v5.ACTION_WORDS.items() for w in v[1]]
        for word in words:
            self.assertFalse(any(bank.near(word, h) for h in held), word)
        train_sources = {w for r in self.rows["train"] for w in r["meta"]["wordings"]}
        self.assertTrue({f"action:{w}" for w in words} & train_sources)
        for row in self.rows["test_unseen_phrasing"]:
            text = row["meta"]["utterance"].lower()
            for word in words:
                self.assertNotRegex(text, rf"\b{re.escape(word.lower())}\b")

    def test_asr_like_heard_text(self):
        for rows in self.rows.values():
            for row in rows:
                self.assertNotIn('"', row["meta"]["heard"])

    def test_no_synonym_negatives(self):
        self.assertEqual(synonym_group('tap "the paper plane"'), "send")
        self.assertEqual(synonym_group('tap "the like button"'), "like")
        self.assertEqual(synonym_group("home"), synonym_group('tap "the home icon"'))
        self.assertIsNone(synonym_group('tap "comments"'))
        for rows in self.rows.values():
            for row in rows:
                answer = row["options"][row["label"]]
                group = synonym_group(answer)
                if group:
                    self.assertEqual([o for o in row["options"] if synonym_group(o) == group and o not in row["meta"]["steps"]
                                      and o != answer], [], row["id"])

    def test_class_balance(self):
        # Test splits keep every boundary; train is subsampled but never loses a non-wait row.
        share = {s: Counter(r["options"][r["label"]] == "wait" for r in rows)[True] / len(rows) for s, rows in self.rows.items()}
        self.assertLess(share["train"], 0.6)
        self.assertGreater(share["test_iid"], share["train"])
        kinds = Counter(r["kind"] for r in self.rows["train"])
        self.assertGreater(kinds["final_none"], 0.01 * len(self.rows["train"]))

    def test_keep_rows_keeps_edges(self):
        answers = ["wait", "wait", "wait", "home", "wait", "wait", "wait", "done"]
        keep = keep_rows(answers, random.Random(0), 0.0)
        self.assertEqual(keep, [False, False, True, True, True, False, True, True])
        self.assertEqual(keep_rows(["wait"] * 4, random.Random(0), 0.0), [False, False, False, True])
        self.assertTrue(all(keep_rows(answers, random.Random(0), 1.0)))

    def test_rows_shuffled(self):
        episodes = [r["meta"]["episode"] for r in self.rows["train"][:200]]
        self.assertNotEqual(episodes, sorted(episodes))

    def test_restart_does_not_execute_cancelled_text(self):
        rows = trajectory('type "old" no wait, type "new" then go home')
        actions = [answer for _, _, _, answer in rows if answer not in {"wait", "done", "none"}]
        self.assertEqual(actions, ['type "new"', "home"])


if __name__ == "__main__":
    unittest.main()
