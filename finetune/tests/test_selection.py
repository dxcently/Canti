"""Unit tests for the checkpoint-selection tie rule (no torch / GPU / model imports)."""

import unittest

from students.jevlike.selection import selection_improves


class TestSelectionImproves(unittest.TestCase):
    def test_acc_higher_is_better(self):
        self.assertTrue(selection_improves({"acc": 0.9}, {"acc": 0.8}, "acc"))
        self.assertFalse(selection_improves({"acc": 0.8}, {"acc": 0.9}, "acc"))

    def test_acc_tie_keeps_earliest_by_default(self):
        # exact tie, default (earliest): the later epoch must NOT replace the current best
        self.assertFalse(selection_improves({"acc": 1.0}, {"acc": 1.0}, "acc"))

    def test_acc_tie_later_replaces(self):
        self.assertTrue(selection_improves({"acc": 1.0}, {"acc": 1.0}, "acc", tie_later=True))

    def test_nll_lower_is_better(self):
        self.assertTrue(selection_improves({"nll": 0.01}, {"nll": 0.02}, "nll"))
        self.assertFalse(selection_improves({"nll": 0.02}, {"nll": 0.01}, "nll"))

    def test_nll_tie(self):
        self.assertFalse(selection_improves({"nll": 0.01}, {"nll": 0.01}, "nll"))
        self.assertTrue(selection_improves({"nll": 0.01}, {"nll": 0.01}, "nll", tie_later=True))

    def test_nll_t_uses_its_own_key_and_tie(self):
        self.assertTrue(selection_improves({"nll_t": 0.1}, {"nll_t": 0.2}, "nll_t"))
        self.assertFalse(selection_improves({"nll_t": 0.1}, {"nll_t": 0.1}, "nll_t"))
        self.assertTrue(selection_improves({"nll_t": 0.1}, {"nll_t": 0.1}, "nll_t", tie_later=True))

    def test_lower_better_ignores_acc_key(self):
        # for nll selection, only the nll key is compared (acc must not influence the tie)
        self.assertTrue(selection_improves({"nll": 0.01, "acc": 0.5}, {"nll": 0.02, "acc": 0.9}, "nll"))


if __name__ == "__main__":
    unittest.main()
