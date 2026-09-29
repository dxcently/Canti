"""Schema/generator parity with the Android Vocab.kt (source of truth). No model imports.

Vocab.kt lives one level up from finetune/ (the android/ checkout is read-only here); we parse it
with regexes and assert vox.schema / vox.generate mirror the Kotlin tables key-for-key, value-for-value
and in the same order.
"""
import random
import re
import unittest
from pathlib import Path

from vox import generate
from vox import schema

VOCAB = (
    Path(__file__).resolve().parents[2]
    / "android/app/src/main/java/ai/vox/companion/Vocab.kt"
)


def _body(src: str, name: str) -> str:
    """Text between `val NAME ... linkedMapOf(` and its matching close paren."""
    start = src.index(f"val {name}")
    open_idx = src.index("linkedMapOf(", start) + len("linkedMapOf(")
    depth, i = 1, open_idx  # linkedMapOf( is already open
    while i < len(src):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[open_idx:i]
        i += 1
    raise AssertionError(f"unbalanced linkedMapOf for {name}")


def _str_map(src: str, name: str) -> dict:
    """`"key" to "value"` table -> dict (insertion order kept)."""
    return {m.group(1): m.group(2) for m in re.finditer(r'"([^"]+)"\s*to\s*"([^"]+)"', _body(src, name))}


def _seq_map(src: str, name: str) -> dict:
    """`listOf("a", "b") to "value"` table -> dict keyed by tuple."""
    out = {}
    for m in re.finditer(r'listOf\(([^)]*)\)\s*to\s*"([^"]+)"', _body(src, name)):
        out[tuple(re.findall(r'"([^"]+)"', m.group(1)))] = m.group(2)
    return out


def _freed(src: str) -> list:
    m = re.search(r"val FREED_SEQUENCES = listOf\((.*)\)", src)
    return [tuple(re.findall(r'"([^"]+)"', x)) for x in re.findall(r"listOf\(([^)]*)\)", m.group(1))]


def _defaults_text(src: str) -> str:
    return re.search(r'const val DEFAULTS_TEXT = "([^"]*)"', src).group(1)


def _assert_ordered_dict(self, py: dict, kt: dict, what: str) -> None:
    self.assertEqual(list(py.items()), list(kt.items()), f"{what}: keys, values and order differ")


class SchemaParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = VOCAB.read_text()

    def test_default_bindings(self):
        kt = _seq_map(self.src, "DEFAULT_BINDINGS")
        _assert_ordered_dict(self, schema.DEFAULT_BINDINGS, kt, "DEFAULT_BINDINGS")

    def test_freed_sequences(self):
        self.assertEqual(schema.FREED_SEQUENCES, _freed(self.src))

    def test_app_only_actions(self):
        kt = _str_map(self.src, "APP_ONLY_ACTIONS")
        _assert_ordered_dict(self, schema.APP_ONLY_ACTIONS, kt, "APP_ONLY_ACTIONS")

    def test_app_only_bindings(self):
        kt = _seq_map(self.src, "APP_ONLY_BINDINGS")
        _assert_ordered_dict(self, schema.APP_ONLY_BINDINGS, kt, "APP_ONLY_BINDINGS")

    def test_discrete(self):
        kt = _str_map(self.src, "DISCRETE")
        _assert_ordered_dict(self, schema.DISCRETE, kt, "DISCRETE")

    def test_actions(self):
        kt = _str_map(self.src, "ACTIONS")
        _assert_ordered_dict(self, schema.ACTIONS, kt, "ACTIONS")


class DefaultsTextParity(unittest.TestCase):
    """The DEFAULTS_TEXT line the app sends the model (Vocab.kt, from tools/gen_vocab.py) matches the generator."""

    def test_defaults_text_matches_kotlin(self):
        self.assertEqual(generate.DEFAULTS_TEXT, _defaults_text(VOCAB.read_text()))


class NoPopSound(unittest.TestCase):
    def test_generator_never_emits_pop(self):
        rng = random.Random(20260926)
        gen = generate.Generator(rng, heldout_phrasing=False, apps=list(schema.APPS), rich=True)
        kinds = list(generate.KIND_WEIGHTS)
        rows = []
        per_kind = -(-300 // len(kinds))
        for kind in kinds:
            for _ in range(per_kind):
                rows.append(gen.make(kind))
        self.assertGreaterEqual(len(rows), 300)
        for row in rows:
            ctx = row["context"]
            self.assertNotIn("lip pop", ctx, f"{row['kind']}: context contains 'lip pop'")
            self.assertNotRegex(ctx, r"sequence:.*pop", f"{row['kind']}: context has a pop sequence")


if __name__ == "__main__":
    unittest.main()
