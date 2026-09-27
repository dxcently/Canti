"""vox_extract.sequencer_sim against the app: the Kotlin Sequencer's own test cases (CoreTest, NavigationTest) and
the bindings in android Vocab.kt, so the desktop would-act counts cannot drift from the app silently."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vox_extract import sequencer_sim as S
from vox_extract.lines import discrete_line, hiss_line
from vox_extract.policy import group
from vox_extract.vocab import DEFAULT_BINDINGS

VOCAB_KT = Path(__file__).resolve().parents[2] / "android/app/src/main/java/ai/vox/companion/Vocab.kt"

HISS = hiss_line("short (150-400 ms)", "normal", "mouth sound")
LINE = {"hiss": HISS, "click": discrete_line("click", "normal"), "pop": discrete_line("pop", "normal")}


def ev(label, t0, t1, **kw):
    return {"label": label, "text": LINE.get(label, ""), "t_start_ms": t0, "t_end_ms": t1, **kw}


def run(*events, **kw):
    return [(" ".join(g.labels), a) for g, a in S.app_actions(list(events), **kw)]


def test_bindings_match_vocab_kt():
    if not VOCAB_KT.exists():
        pytest.skip("android tree not present")
    src = VOCAB_KT.read_text()
    table = {}
    for name in ("DEFAULT_BINDINGS", "APP_ONLY_BINDINGS"):
        block = re.search(rf"val {name}: Map<List<String>, String> = linkedMapOf\((.*?)\n    \)", src, re.S).group(1)
        for seq, act in re.findall(r"listOf\(([^)]*)\) to \"(\w+)\"", block):
            table[tuple(re.findall(r'"(\w+)"', seq))] = act
    assert table == S.APP_BINDINGS
    # the training contract (vocab.py) is deliberately older: click pop, no click hiss
    assert DEFAULT_BINDINGS != S.APP_BINDINGS


def test_bound_and_absorbed_as_profile():
    bound, absorbed = S.bound_and_absorbed(S.APP_BINDINGS)
    assert absorbed == {("hiss", "click")}                       # NavigationTest.hissActsAtOnceAndClickWaits
    assert {("pop", "pop"), ("click", "click"), ("click", "hiss")} <= bound
    assert ("click", "pop") not in bound                          # CoreTest.clickPopIsUnbound


def test_lone_hiss_is_back_at_once():
    q = S.Sequencer()
    q.add("hiss", 0, 270, HISS)
    assert [g.labels for g in q.out] == [["hiss"]] and q.out[0].ended_by == "no-continuation" and q.pending is None


def test_click_click_home_and_click_hiss_forward():
    assert run(ev("click", 0, 30), ev("click", 250, 280)) == [("click click", "home")]
    assert run(ev("click", 0, 30), ev("hiss", 250, 500)) == [("click hiss", "forward")]


def test_hiss_click_is_one_back_and_the_click_is_absorbed():
    out = S.app_actions([ev("hiss", 0, 270), ev("click", 520, 530)])
    assert [(g.labels, a, g.absorbed) for g, a in out] == [(["hiss"], "back", ["click"])]


def test_hiss_click_click_is_back_then_a_lone_click_not_home():
    assert run(ev("hiss", 0, 270), ev("click", 520, 530), ev("click", 780, 790)) == [("hiss", "back"), ("click", "none")]


def test_hiss_hiss_click_is_two_backs():
    assert run(ev("hiss", 0, 200), ev("hiss", 400, 600), ev("click", 800, 810)) == [("hiss", "back"), ("hiss", "back")]


def test_pop_pop_within_the_gap_listens_apart_two_pops():
    assert run(ev("pop", 0, 30), ev("pop", 250, 280)) == [("pop pop", "listen_for_phrase")]
    # CoreTest.popPopFurtherApartThanTheGapIsTwoTaps: device gap 800 > 600. From the Pico (mic=False) two taps;
    # from the phone mic a lone pop does nothing (MicPopGate) unless the user bound it.
    far = (ev("pop", 0, 30), ev("pop", 830, 860))
    assert run(*far, mic=False) == [("pop", "tap"), ("pop", "tap")]
    assert run(*far) == [("pop", "none"), ("pop", "none")]
    assert run(*far, pop_allowed=True) == [("pop", "tap"), ("pop", "tap")]


def test_click_pop_is_unbound_and_merges_by_device_gap():
    # CoreTest.lateFollowUpStillMergesByDeviceGap: device gap 360 -> one "click pop", unbound
    out = S.app_actions([ev("click", 0, 40), ev("pop", 400, 430)])
    assert [(" ".join(g.labels), a, g.ended_by) for g, a in out] == [("click pop", "none", "no-continuation")]


def test_device_gap_and_clock_reset_split():
    # the lone pop times out (arrival 30 + 600 + 150 < 1040); the click waits until 1790 and the pop that arrives at
    # 1730 is 660 ms after it by the device: split (CoreTest.burstAfterStallIsSplitByDeviceGap)
    out = S.app_actions([ev("pop", 0, 30), ev("click", 1000, 1040), ev("pop", 1700, 1730)], mic=False)
    assert [(" ".join(g.labels), g.ended_by) for g, _ in out] == [("pop", "timeout"), ("click", "device-gap"), ("pop", "timeout")]
    q = S.Sequencer()                                             # CoreTest.deviceClockResetSplits
    q.add("click", 50_000, 50_040)
    q.add("pop", 10, 40)
    assert [(g.labels, g.ended_by) for g in q.flush()] == [(["click"], "device-clock-reset"), (["pop"], "timeout")]


def test_a_follow_up_that_arrives_after_the_timeout_does_not_join():
    # click waits until its arrival + 600 + 150 (t_end 40 -> 790); a hiss that starts in the gap (460 ms) but ends at
    # 1000 arrives after that: the click resolved alone (none) and the hiss is its own back.
    assert run(ev("click", 0, 40), ev("hiss", 500, 1000)) == [("click", "none"), ("hiss", "back")]
    assert run(ev("click", 0, 40), ev("hiss", 500, 700)) == [("click hiss", "forward")]


def test_gated_and_not_deliberate_sounds_do_nothing_but_still_break_the_group():
    # a gated hiss enters as unknown: "click unknown" does nothing, and the hiss is not a back
    assert run(ev("click", 0, 30), ev("hiss", 250, 500, gated="hiss centroid 6900 Hz over 6500 Hz")) == [("click unknown", "none")]
    bg = dict(ev("hiss", 0, 300), text=hiss_line("short (150-400 ms)", "normal", "background noise"))
    assert run(bg) == [("hiss", "none")]


def test_phone_gate_mirror():
    hi = ev("hiss", 0, 300, gate={"centroid_hz": 6900.0, "snr_db": 9.5})
    assert S.phone_gate(hi) == "hiss-centroid"
    assert S.phone_gate(hi, speaker_media=False) is None                     # earbuds / no media
    assert S.phone_gate(hi, hiss_max_centroid_hz=0) is None                  # setting off
    assert S.phone_gate(ev("hiss", 0, 300, raw={"centroid_hz": 6500.0})) is None  # boundary passes
    assert S.phone_gate(ev("pop", 0, 30, gate={"snr_db": 10.0})) == "pop"
    assert S.phone_gate(ev("pop", 0, 30, gate={"snr_db": 10.0}), media_gate=False) is None
    assert S.phone_gate(ev("rise", 0, 500, gate={"snr_db": 20.0, "clarity_med": 0.6})) == "hum-clarity"
    # the Z Flip media pattern: lone 7 kHz hisses every ~1.5 s -> backs, all gone with the rule
    media = [ev("hiss", t, t + 200, gate={"centroid_hz": 6900.0, "snr_db": 9.5}) for t in range(0, 60_000, 1500)]
    assert S.would_act(media, 1.0)["would_act"] == 40
    assert S.would_act(media, 1.0, gate={})["would_act"] == 0


def test_policy_group_undercounts_close_hisses():
    hisses = [ev("hiss", t, t + 150) for t in range(0, 6000, 400)]          # 15 hisses, 250 ms apart
    groups = group(hisses)
    assert len(groups) == 5                                                    # "hiss hiss hiss": unbound in policy
    assert S.would_act(hisses, 1.0)["actions"] == {"back": 15}                 # the app: one back per hiss
