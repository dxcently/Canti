"""A small SYNTHETIC regression (clean-ish clips). It guards against breaking the pipeline; it is not a
measure of accuracy on real voices. The full sweep is tests/synthetic_eval.py."""

import numpy as np
import pytest

import finetune_ref
import synth
from vox_extract import Config
from vox_extract.extractor import extract_array
from vox_extract.lines import label_consistent, parse_line
from vox_extract.policy import action_for, group
from vox_extract.vocab import DEFAULT_BINDINGS

EXPECT = {"rise": "swipe_up", "fall": "swipe_down", "arch": "swipe_right", "dip": "swipe_left",
          "flat": "long_press", "pop": "tap", "hiss": "back", "click": "none",
          "click_pop": DEFAULT_BINDINGS[("click", "pop")]}


def actions(clip):
    evs = [e.to_dict() for e in extract_array(clip.audio, clip.sr, Config())]
    for e in evs:
        assert label_consistent(e["label"], parse_line(e["text"])), e["text"]
    acts = [action_for([(x["label"], x["text"]) for x in g]) for g in group(evs)]
    return evs, [a for a in acts if a != "none"]


@pytest.mark.parametrize("cls", list(EXPECT))
def test_gestures_at_30db(cls):
    ok = 0
    for seed in range(4):
        clip = synth.make_clip(cls, np.random.default_rng(900 + seed), 16000, 30.0, synth.BACKGROUNDS[seed])
        _, acts = actions(clip)
        want = [] if EXPECT[cls] == "none" else [EXPECT[cls]]
        ok += acts == want
    assert ok >= 3   # one of the 4 backgrounds is cafe babble: an inserted blip within 600 ms voids a group


@pytest.mark.parametrize("cls", ["talk", "laugh", "cough", "music", "air", "silence"])
def test_negatives_at_30db_do_nothing(cls):
    fa = 0
    for seed in range(4):
        clip = synth.make_clip(cls, np.random.default_rng(950 + seed), 16000, 30.0, synth.BACKGROUNDS[seed])
        _, acts = actions(clip)
        fa += bool(acts)
    assert fa <= 1


def test_gesture_lines_are_in_the_training_distribution():
    seen = finetune_ref.seen_lines()
    if seen is None:
        pytest.skip("finetune not present")
    for cls in ("rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss"):
        for seed in range(3):
            clip = synth.make_clip(cls, np.random.default_rng(700 + seed), 16000, 30.0, "pink")
            evs, _ = actions(clip)
            for e in evs:
                assert e["text"] in seen, e["text"]
