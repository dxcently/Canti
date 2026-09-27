"""eval_real/calib_gestures.py: the calibration -> Config derivation and the scoring rules (no recordings needed)."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval_real"))
import calib_gestures as CG  # noqa: E402

from vox_extract import Config  # noqa: E402

VOICE = {"range": {"home_st": 17.8, "clarity_on": 0.82, "lo_st": 9.93, "hi_st": 18.8},
         "vowels": {"centroids_bark": {"ee": [4.3, 12.7]}},
         "pops": {"pop": {"peak_db": 15.6, "rise_db": 9.93, "core_ticks": 5}, "pop_labels": ["pop"]}}


def test_derive_uses_only_the_setup_numbers_and_real_config_fields():
    c = CG.derive(VOICE)
    assert set(c) == {"voicing", "f0_floor", "excursion", "pop_core", "pop_rise"}
    assert c["voicing"]["overrides"] == {"voiced_clarity": 0.82}
    assert c["f0_floor"]["overrides"]["f0_min_hz"] == pytest.approx(55 * 2 ** ((9.93 - 3) / 12), abs=0.05)
    assert c["pop_core"]["overrides"] == {"discrete_core_ms": 100}          # 5 ticks x 20 ms
    assert c["pop_rise"]["overrides"]["pop_onset_flux_db"] == pytest.approx(6 * 9.93 / 5, abs=0.01)
    s = (18.8 - 9.93) / 12
    ex = c["excursion"]["overrides"]
    assert ex["exc_medium_st"] == pytest.approx(2.0 * s, abs=0.01) and ex["exc_large_st"] == pytest.approx(4.0 * s, abs=0.01)
    names = set(Config().__dataclass_fields__)
    for cand in c.values():                    # every override is a vx_config field and has a formula
        assert set(cand["overrides"]) <= names and set(cand["overrides"]) == set(cand["formula"])
        Config.from_dict(cand["overrides"])    # loads as a partial config
    for o in CG.WHATIFS.values():
        assert set(o) <= names


def test_derive_leaves_out_skipped_or_missing_steps():
    v = {"range": {**VOICE["range"], "skipped": ["home"]}, "vowels": None, "pops": {"skipped": ["pops"]}}
    c = CG.derive(v)
    assert "voicing" not in c and "pop_core" not in c and "pop_rise" not in c
    assert "f0_floor" in c and "excursion" in c
    assert CG.derive({"range": None, "vowels": None, "pops": None}) == {}
    wide = CG.derive({"range": {"lo_st": 0.0, "hi_st": 40.0}, "pops": None})
    assert wide["excursion"]["overrides"]["exc_medium_st"] == pytest.approx(3.0)   # scale clipped at 1.5


def test_expected_labels_and_label_rules():
    assert CG.expected("whistle_arch", "wh_quiet_arch_1") == ["arch"]
    assert CG.expected("pop_click", "ck_pop_click_1") == ["pop", "click"]
    assert CG.expected("click_run", "ck_run4_2") == ["click"] * 4
    assert CG.label_ok(["click"] * 3, ["click"] * 4, "click_run")           # a run: 3+ clicks
    assert not CG.label_ok(["click", "pop", "click"], ["click"] * 3, "click_run")
    assert not CG.label_ok(["rise", "rise"], ["rise"], "whistle_rise")
    assert CG.seg_error([], ["pop"]) == "missed"
    assert CG.seg_error(["pop"], ["pop", "click"]) == "merged"
    assert CG.seg_error(["rise", "rise"], ["rise"]) == "split"
    assert CG.seg_error(["click", "pop"], ["click", "pop"]) == "count ok"


def test_deliberate_drops_what_the_phone_would_not_act_on():
    from vox_extract import lines, vocab
    ev = [{"label": "pop", "text": lines.discrete_line("pop", vocab.LOUDNESS[1]), "emit": True},
          {"label": "flat", "text": lines.hum_line("flat", vocab.EXCURSION[0], vocab.DURATION[2], vocab.CLARITY[2],
                                                   vocab.LOUDNESS[1], "talking"), "emit": True},
          {"label": "unknown", "text": "", "emit": True}]
    assert CG.deliberate(ev) == ["pop"]


def test_paired_bootstrap_and_rates():
    a, b = np.zeros(50), np.zeros(50)
    b[:5] = 1
    d = CG.boot_ci(a, b, n=500)
    assert d["mean"] == pytest.approx(0.1) and d["lo"] >= 0 and d["p_pos"] > 0.95
    units0 = [{"min": 1.0, "fa": 1, "act": 0} for _ in range(10)]
    units1 = [{"min": 1.0, "fa": 2, "act": 0} for _ in range(10)]
    r = CG.rate_ci(units0, "fa", units1, n=200)
    assert r["per_min"] == pytest.approx(1.0) and r["events"] == 10


def test_verdict_needs_a_real_gain_and_no_new_false_triggers():
    base = {"gained": 3, "lost": 0, "d_acc": {"p_pos": 0.97}, "d_fa": {"events": 0}, "fa_by_set": {"x": 0},
            "voiced_gained": 0, "voiced_lost": 0}
    assert CG.verdict(base)[0] == "GO"
    assert CG.verdict({**base, "gained": 1})[0] == "NO-GO"                 # one take is not a decision
    assert CG.verdict({**base, "d_fa": {"events": 1}})[0] == "NO-GO"
    assert CG.verdict({**base, "fa_by_set": {"x": -5, "y": 2}})[0] == "NO-GO"
    assert CG.verdict({**base, "voiced_lost": 2})[0] == "NO-GO"
