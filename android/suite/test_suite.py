"""VOX emulator test suite.

Replays device messages through the app's debug feature source (adb-forwarded socket) with the deterministic rule
decider, then asserts on the screen (the service's own tree dump, raw screenshots) and on the app's event log.

    python3 suite/test_suite.py                 # everything
    python3 suite/test_suite.py -k fixture      # tests whose name contains "fixture"
    python3 suite/test_suite.py --list

Results: printed, and written to suite/out/results-<time>.json.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import time
import traceback
import urllib.request
from pathlib import Path

from servers import FakeSystemOne, WebServer
from voxlib import (EventStream, Vox, adb, device_ms, dismiss_first_run, force_stop, launch, node_by_id, prime_organic_maps,
                    screen_diff, screenshot, sh, tap_node, start_activity, talking)

OUT = Path(__file__).resolve().parent / "out"
sys.dont_write_bytecode = True   # read-only import of the training schema (never write into finetune/)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "finetune"))
from vox import schema as SCHEMA  # noqa: E402
from vox import targets as TARGETS  # noqa: E402
POLICY_TARGETS = (Path(__file__).resolve().parents[2] / "finetune/data/targets-v1/policy.txt").read_text().rstrip("\n")
OPTION_RE = re.compile(r"(.*) \(([^,()]+), ([^,()]+)\)")
JEV_URL = "http://127.0.0.1:8765"   # finetune/servers/systemone.py (suite/run.sh jev start)
TESTS: list[tuple[str, callable]] = []


class Skip(Exception):
    """A test that cannot run in this environment (reported as SKIP, not as a pass)."""
FEED, MENU, LIST, CONTROLS, STATIC = (f"ai.vox.fixture/.{a}" for a in
                                      ("FeedActivity", "MenuActivity", "ListActivity", "ControlsActivity", "StaticActivity"))


def test(fn):
    TESTS.append((fn.__name__, fn))
    return fn


class Ctx:
    def __init__(self) -> None:
        self.ev = EventStream()
        self.vox = Vox()
        self.notes: list[str] = []

    def note(self, s: str) -> None:
        self.notes.append(s)
        print(f"    {s}")

    # -- helpers -----------------------------------------------------------------------------------------------------
    def wait_service(self, timeout: float = 20) -> None:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.vox.control("ping").get("ok"):
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise AssertionError("VOX service not reachable")

    def reset(self) -> None:
        self.vox.control("reset")
        self.vox.control("config", decider="rules", gap_ms=600, confirm_timeout_ms=1500, http_timeout_ms=2000, min_confidence=0.5,
                         target_model="", target_min_confidence=0.6, target_choose_ms=6000)
        self.vox.control("profile", profile=None)
        self.vox.mode("gesture")

    def outcome(self, mark: int, timeout: float = 4.0) -> dict:
        """Events of the next decision after `mark`: resolve, state, decision, exec, confirm (when applicable)."""
        out: dict = {}
        r = self.ev.wait(mark, lambda e: e["ev"] == "resolve", timeout)
        assert r, f"no resolve event; events: {[e['ev'] for e in self.ev.since(mark)]}"
        out["resolve"] = r
        n = r["n"]
        for name in ("state", "decision", "exec"):
            e = self.ev.wait(mark, lambda e, name=name: e["ev"] == name and e.get("n") == n, timeout)
            assert e, f"no {name} event for decision {n}"
            out[name] = e
        w = out["exec"].get("watch")
        if w is not None:
            c = self.ev.wait(mark, lambda e: e["ev"] == "confirm" and e.get("watch") == w, 5.0)
            assert c, "no confirm event"
            out["confirm"] = c
        return out

    def anchor(self, msg_id: int, timeout: float = 4.0) -> int:
        """Index of the app's `msg` event for the message we sent: robust against logcat lag or stale lines."""
        end = time.time() + timeout
        while time.time() < end:
            for i, e in enumerate(self.ev.since(0)):
                if e["ev"] == "msg" and e.get("id") == msg_id:
                    return i
            time.sleep(0.05)
        raise AssertionError(f"message {msg_id} never reached the app log")

    def act(self, *labels: str, timeout: float = 4.0, **kw) -> dict:
        reply = self.vox.sounds(*labels, **kw)
        assert reply.get("ok"), reply
        return self.outcome(self.anchor(self.vox.next_id), timeout=timeout)

    def texts_until(self, key: str, want: str, timeout: float = 3.0) -> dict:
        end = time.time() + timeout
        t = {}
        while time.time() < end:
            t = self.vox.texts()
            if t.get(key) == want:
                return t
            time.sleep(0.15)
        raise AssertionError(f"{key}: expected {want!r}, got {t.get(key)!r}")

    def open(self, component: str) -> None:
        start_activity(component)
        time.sleep(1.0)


def expect(o: dict, action: str, confirm: str | None = "confirmed (events)") -> None:
    got = o["decision"]["action"]
    assert got == action, f"decision {got} ({o['decision']['source']}), expected {action}"
    assert o["exec"]["ok"], f"exec failed: {o['exec']['how']}"
    if confirm is not None:
        assert o.get("confirm"), "no confirmation"
        assert o["confirm"]["result"] == confirm, f"confirm: {o['confirm']['result']} by {o['confirm']['by']} (expected {confirm})"


# --- default gestures on the fixture ----------------------------------------------------------------------------------

@test
def fixture_rise_swipes_up_to_next_video(c: Ctx):
    c.open(FEED)
    o = c.act("rise")
    assert "screen: video feed; media playing; scroll at the top; keyboard hidden" in o["state"]["text"], o["state"]["text"]
    expect(o, "swipe_up")
    c.texts_until("feed_index", "Video 2 of 20")


@test
def fixture_fall_swipes_down_to_previous_video(c: Ctx):
    c.open(FEED)
    c.act("rise")
    c.texts_until("feed_index", "Video 2 of 20")
    o = c.act("fall")
    expect(o, "swipe_down")
    c.texts_until("feed_index", "Video 1 of 20")


@test
def fixture_dip_swipes_left(c: Ctx):
    c.open(FEED)
    expect(c.act("dip"), "swipe_left")
    c.texts_until("feed_page", "page: 1")


@test
def fixture_arch_swipes_right(c: Ctx):
    c.open(FEED)
    expect(c.act("arch"), "swipe_right")
    c.texts_until("feed_page", "page: -1")


@test
def fixture_pop_taps_after_the_pop_pop_gap(c: Ctx):
    # 2026-09-27: pop pop = listen, so a lone pop waits one gap for a second pop, then taps
    c.open(FEED)
    m = c.ev.mark()
    o = c.act("pop")
    expect(o, "tap")
    assert o["resolve"]["waited"] and 550 <= o["resolve"]["held_ms"] <= 900, o["resolve"]
    w = next((e for e in c.ev.since(m) if e["ev"] == "wait"), None)
    assert w and "pop pop" in w["for"], w
    c.texts_until("feed_state", "paused")
    c.note(f"pop held {o['resolve']['held_ms']} ms before deciding (waiting for pop pop)")


@test
def fixture_flat_hum_long_presses(c: Ctx):
    c.open(FEED)
    expect(c.act("flat"), "long_press")
    c.texts_until("feed_long", "long presses: 1")


@test
def fixture_hiss_goes_back(c: Ctx):
    c.open(MENU)
    sh(f"am start -W -n {FEED}")
    time.sleep(1.0)
    c.texts_until("feed_index", "Video 1 of 20")
    expect(c.act("hiss"), "back")
    c.texts_until("title", "VOX fixture menu")


@test
def fixture_pop_pop_listens_then_phrase_uses_screen_tiebreak(c: Ctx):
    c.open(FEED)
    m = c.ev.mark()
    assert c.vox.sounds("pop")["waiting"] is True, "pop should wait for a possible second pop"
    time.sleep(0.15)
    c.vox.sounds("pop")
    o = c.outcome(m)
    assert o["resolve"]["sequence"] == "pop pop" and o["resolve"]["waited"], o["resolve"]
    expect(o, "listen_for_phrase", confirm=None)
    assert o["decision"]["source"] == "app:listen", o["decision"]
    assert c.ev.wait(m, lambda e: e["ev"] == "listening" and e.get("state") == "open", 2), "listening window not opened"
    m2 = c.ev.mark()
    c.vox.phrase("next")
    o2 = c.outcome(m2)
    assert 'spoken phrase: "next"' in o2["state"]["text"] and "mode: listening" in o2["state"]["text"]
    # "next" in a video feed means swipe up (generate.py SCREEN_NEXT): the screen line broke the tie.
    expect(o2, "swipe_up")
    c.texts_until("feed_index", "Video 2 of 20")


@test
def fixture_phrase_outside_listening_window_is_ignored(c: Ctx):
    c.open(FEED)
    m = c.ev.mark()
    c.vox.phrase("next")
    assert c.ev.wait(m, lambda e: e["ev"] == "ignored" and "listening window" in e.get("reason", ""), 2)
    time.sleep(0.8)
    assert not any(e["ev"] == "resolve" for e in c.ev.since(m))
    assert c.vox.texts()["feed_index"] == "Video 1 of 20"


@test
def fixture_list_scrolls(c: Ctx):
    c.open(LIST)
    before = c.vox.all_text()
    assert "|Item 1|" in before
    o = c.act("rise")
    assert "screen: scrolling list; media none; scroll at the top; keyboard hidden" in o["state"]["text"], o["state"]["text"]
    expect(o, "swipe_up")
    time.sleep(0.5)
    assert "|Item 1|" not in c.vox.all_text(), "list did not scroll"


@test
def fixture_controls_tap_toggles_button(c: Ctx):
    c.open(CONTROLS)
    o = c.act("pop")
    expect(o, "tap")
    c.texts_until("toggle_state", "State: ON")
    c.note(f"confirmed by {o['confirm']['by']} in {o['confirm']['ms']} ms")


# --- timing rule: act at once unless a bound sequence starts with this sound ------------------------------------------

@test
def timing_lonely_click_waits_one_gap_then_resolves(c: Ctx):
    c.open(FEED)
    m = c.ev.mark()
    c.vox.sounds("click")
    w = c.ev.wait(m, lambda e: e["ev"] == "wait", 2)
    assert w and "click click" in w["for"] and "click pop" not in w["for"], w
    o = c.outcome(m, timeout=3)
    assert o["resolve"]["waited"] and 550 <= o["resolve"]["held_ms"] <= 900, o["resolve"]
    expect(o, "none", confirm=None)
    c.note(f"click alone held {o['resolve']['held_ms']} ms (gap 600)")


@test
def timing_an_app_rule_can_claim_pop_pop(c: Ctx):
    c.open(FEED)
    c.vox.control("profile", profile={"app:ai.vox.fixture": [{"phrase": ["pop", "pop"], "kind": "fixed", "action": "like"}]})
    # pop pop -> like (double-tap)
    m = c.ev.mark()
    assert c.vox.sounds("pop")["waiting"] is True
    time.sleep(0.15)
    c.vox.sounds("pop")
    o = c.outcome(m)
    assert o["resolve"]["sequence"] == "pop pop", o["resolve"]
    rules = o["state"]["text"].split("my rules:")[1]
    assert "VOX fixture" in rules and "like / favourite the current item" in rules, rules
    expect(o, "like")
    c.texts_until("feed_likes", "likes: 1")
    # other apps keep the default: pop pop opens the listen window there
    sh("input keyevent KEYCODE_HOME")
    time.sleep(1.0)
    m = c.ev.mark()
    c.vox.sounds("pop"); time.sleep(0.15); c.vox.sounds("pop")
    o3 = c.outcome(m)
    expect(o3, "listen_for_phrase", confirm=None)


@test
def timing_unbound_sound_after_wait_forms_unbound_sequence(c: Ctx):
    c.open(FEED)
    m = c.ev.mark()
    c.vox.sounds("click")
    time.sleep(0.1)
    c.vox.sounds("rise")
    o = c.outcome(m)
    assert o["resolve"]["sequence"] == "click rise", o["resolve"]
    expect(o, "none", confirm=None)


# --- device timestamps: grouping follows the device clock, not arrival ------------------------------------------

def resolves_after(c: Ctx, idx: int, n: int, timeout: float = 4.0) -> list[dict]:
    end = time.time() + timeout
    while time.time() < end:
        rs = [e for e in c.ev.since(idx) if e["ev"] == "resolve"]
        if len(rs) >= n:
            return rs
        time.sleep(0.05)
    raise AssertionError(f"expected {n} resolves, got {[e['sequence'] for e in c.ev.since(idx) if e['ev'] == 'resolve']}")


@test
def timing_device_stamps_merge_a_late_follow_up(c: Ctx):
    """click, then pop 650 ms later by arrival (> gap 600: arrival would split), but 300 ms later on the device."""
    c.open(FEED)
    t = device_ms()
    c.vox.sounds("click", timing=[(t - 40, t)])
    first = c.anchor(c.vox.next_id)
    time.sleep(0.65)
    c.vox.sounds("pop", timing=[(t + 300, t + 330)])         # happened 300 ms after the click; delivered late
    r = resolves_after(c, first, 1)[0]
    assert r["sequence"] == "click pop" and r["clock"] == "device" and r["gaps_ms"] == [300], r
    w = next(e for e in c.ev.since(first) if e["ev"] == "wait")
    c.note(f"device clock: waited {w['wait_ms']} ms for the follow-up; resolved as {r['sequence']!r} ({r['ended_by']})")
    # The same arrival pattern without stamps: arrival fallback splits it (click alone, then pop taps after its gap).
    c.vox.control("reset")
    c.open(FEED)
    c.vox.sounds("click")
    first = c.anchor(c.vox.next_id)
    time.sleep(0.65)
    c.vox.sounds("pop")
    rs = resolves_after(c, first, 2)
    assert [x["sequence"] for x in rs[:2]] == ["click", "pop"] and rs[0]["clock"] == "arrival", rs
    c.note("arrival clock, same timing: 'click' + 'pop' (split)")


@test
def timing_device_stamps_split_a_burst(c: Ctx):
    """A stall delivers click and pop 50 ms apart (arrival would merge into click pop), but they were 660 ms apart."""
    c.open(FEED)
    t = device_ms()
    c.vox.sounds("click", timing=[(t - 800, t - 760)])       # the click happened 760 ms ago (stalled link)
    first = c.anchor(c.vox.next_id)
    c.vox.sounds("pop", timing=[(t - 100, t - 60)])          # device gap 660 ms
    rs = resolves_after(c, first, 2)
    assert [x["sequence"] for x in rs[:2]] == ["click", "pop"], rs
    assert rs[0]["ended_by"] == "device-gap" and rs[1]["clock"] == "device", rs
    c.note(f"device clock: {rs[0]['sequence']!r} ended by {rs[0]['ended_by']}, then {rs[1]['sequence']!r}: {rs[1]['note']}")
    c.texts_until("feed_state", "paused")                    # the pop tapped the feed
    # Without stamps the same burst merges into "click pop" (unbound since 2026-09-27: nothing happens).
    c.vox.control("reset")
    c.open(FEED)
    c.vox.sounds("click")
    first = c.anchor(c.vox.next_id)
    c.vox.sounds("pop")
    r = resolves_after(c, first, 1)[0]
    assert r["sequence"] == "click pop" and r["clock"] == "arrival", r
    c.note("arrival clock, same burst: 'click pop' (merged)")


# --- confirmer ---------------------------------------------------------------------------------------------------------

@test
def confirmer_reports_no_visible_change_on_static_screen(c: Ctx):
    c.open(STATIC)
    o = c.act("pop")
    expect(o, "tap", confirm="no visible change")


@test
def screen_never_vetoes_an_explicit_gesture(c: Ctx):
    c.open(STATIC)
    o = c.act("rise")
    assert "scroll not scrollable" in o["state"]["text"]
    expect(o, "swipe_up", confirm="no visible change")   # still performed, then honestly reported


# --- gating, disarm, cursor, model client ---------------------------------------------------------------------------

@test
def talking_is_not_a_gesture(c: Ctx):
    c.open(FEED)
    o = c.act("rise", lines=[talking()])
    expect(o, "none", confirm=None)
    assert o["decision"]["source"].startswith("rules:not-deliberate"), o["decision"]
    assert c.vox.texts()["feed_index"] == "Video 1 of 20"


@test
def disarm_drops_pending_sound(c: Ctx):
    c.open(FEED)
    m = c.ev.mark()
    c.vox.sounds("click")
    c.vox.disarm()
    time.sleep(1.0)
    evs = c.ev.since(m)
    assert any(e["ev"] == "arm" and e.get("state") == "disarmed" for e in evs)
    assert not any(e["ev"] == "resolve" for e in evs), "pending click must be dropped on disarm"
    o = c.act("rise")   # the next message re-arms
    expect(o, "swipe_up")


@test
def cursor_mode_moves_stops_and_clicks(c: Ctx):
    c.open(CONTROLS)
    m = c.ev.mark()
    c.vox.mode("cursor")
    assert c.ev.wait(m, lambda e: e["ev"] == "mode" and e.get("mode") == "cursor", 2)
    o = c.act("pop", mode="cursor")          # cursor starts at the centre: click lands on the Toggle button
    assert "mode: cursor" in o["state"]["text"] and "cursor: stopped" in o["state"]["text"], o["state"]["text"]
    expect(o, "click")
    c.texts_until("toggle_state", "State: ON")
    o = c.act("rise", mode="cursor", loud="loud")
    expect(o, "move_up_fast", confirm=None)
    time.sleep(0.2)
    o = c.act("flat", mode="cursor")
    assert "cursor: moving up fast" in o["state"]["text"], o["state"]["text"]
    expect(o, "stop", confirm=None)
    o = c.act("click", "click", mode="cursor")   # unbound in cursor mode by default (the button owns the mode)
    expect(o, "none", confirm=None)
    # a user rule can bind it: click click -> drag_toggle, sent as two messages (click now waits for a second click)
    c.vox.control("profile", profile={"cursor": [{"phrase": ["click", "click"], "kind": "fixed", "action": "drag_toggle"}]})
    assert c.vox.sounds("click", mode="cursor")["waiting"] is True
    time.sleep(0.15)
    c.vox.sounds("click", mode="cursor")
    o = c.outcome(c.anchor(c.vox.next_id - 1))
    assert o["resolve"]["sequence"] == "click click", o["resolve"]
    expect(o, "drag_toggle", confirm=None)
    assert o["exec"]["how"].startswith("drag started"), o["exec"]
    m = c.ev.mark()
    c.vox.mode("gesture")
    assert c.ev.wait(m, lambda e: e["ev"] == "mode" and e.get("mode") == "gesture", 2)


@test
def http_decider_sends_scene_text_and_falls_back(c: Ctx):
    srv = FakeSystemOne()
    try:
        c.vox.control("config", decider="model", base_url=f"http://127.0.0.1:{srv.port}", model="vox-test", api_key="sk-suite-123",
                      http_timeout_ms=3000)
        c.open(FEED)
        o = c.act("rise")
        expect(o, "swipe_up")
        assert o["decision"]["source"] == "model", o["decision"]
        c.texts_until("feed_index", "Video 2 of 20")
        req = srv.requests[-1]
        assert req["model"] == "vox-test"
        assert req["state"] == o["state"]["text"], "request state must be exactly the logged Scene text"
        q = req["questions"]["action"]
        assert q["type"] == "choice" and len(q["criteria"]) == 25, q
        # full option list, in schema dict order (the JSON object keys as sent on the wire)
        assert list(q["criteria"]) == [SCHEMA.ACTIONS[k] for k in SCHEMA.ACTIONS], list(q["criteria"])
        assert "switch to cursor mode" not in q["criteria"]
        assert srv.headers[-1].get("authorization") == "Bearer sk-suite-123"
        # the key never reaches the event log
        assert not any("sk-suite-123" in json.dumps(e) for e in c.ev.since(0)), "API key leaked into the event log"
        srv.status = 500
        o = c.act("fall")
        expect(o, "swipe_down")
        assert o["decision"]["source"].startswith("model-fallback"), o["decision"]
        c.note(f"fallback source: {o['decision']['source'][:90]}")
    finally:
        c.vox.control("config", decider="rules", api_key="")
        srv.close()


# --- the local Jev stand-in: finetune/servers/systemone.py, model vox-jevlike, over the real HTTP path ---------------

@test
def jev_local_systemone_vox_jevlike(c: Ctx):
    """~10 scenes through HttpDecider -> adb reverse -> the local server (CPU). Asserts the answer parses (choice,
    probabilities, confidence, latency), is a real model answer (no fallback), is the right action, and was executed.
    Speed is logged, not asserted."""
    try:
        health = json.loads(urllib.request.urlopen(JEV_URL + "/health", timeout=3).read())
    except OSError as e:
        raise Skip(f"no local systemone server on {JEV_URL} ({type(e).__name__}); start it with suite/run.sh jev start")
    c.note(f"server: {health}")
    adb("reverse", "tcp:8765", "tcp:8765")
    lat: list[tuple[str, int, float]] = []
    wrong: list[str] = []
    try:
        c.vox.control("config", decider="model", base_url=JEV_URL, model="vox-jevlike", api_key="", http_timeout_ms=180000)

        def check(name: str, o: dict, expected: str) -> None:
            d = o["decision"]
            assert d["source"] == "model", f"{name}: not a model answer: {d['source']}"
            assert 0.0 <= d["confidence"] <= 1.0, d
            assert d.get("top") and d["top"][0]["option"] in SCHEMA.ACTIONS.values(), d
            assert d.get("server_ms") is not None, d
            lat.append((name, d["ms"], d["server_ms"]))
            c.note(f"{name}: {d['action']} conf {d['confidence']:.3f} top {[(t['option'], round(t['p'], 3)) for t in d['top']]} "
                   f"app {d['ms']} ms, server {d['server_ms']:.0f} ms")
            if d["action"] != expected:
                wrong.append(f"{name}: got {d['action']}, expected {expected}")
            else:
                assert d["top"][0]["option"] == SCHEMA.ACTIONS[expected], d
                assert o["exec"]["ok"], o["exec"]

        scenes = [   # (name, labels, extra kwargs, expected action, fixture text that must follow)
            ("rise", ("rise",), {}, "swipe_up", ("feed_index", "Video 2 of 20")),
            ("fall", ("fall",), {}, "swipe_down", None),
            ("dip", ("dip",), {}, "swipe_left", ("feed_page", "page: 1")),
            ("arch", ("arch",), {}, "swipe_right", ("feed_page", "page: -1")),
            ("pop", ("pop",), {}, "tap", ("feed_state", "paused")),
            ("flat", ("flat",), {}, "long_press", ("feed_long", "long presses: 1")),
            ("talking", ("rise",), {"lines": [talking()]}, "none", None),
            ("click rise", ("click", "rise"), {}, "none", None),
            ("hiss", ("hiss",), {}, "back", None),
        ]
        for name, labels, kw, expected, after in scenes:
            c.open(FEED)
            o = c.act(*labels, timeout=200, **kw)
            check(name, o, expected)
            if after and o["decision"]["action"] == expected:
                c.texts_until(*after)
            if name == "hiss" and o["decision"]["action"] == "back":
                time.sleep(1.0)
                assert c.vox.control("ping")["app"] != "ai.vox.fixture", "back did not leave the feed"
        # pop pop -> listen (the app, source app:listen), then the phrase "next" (screen tie-break: video feed -> swipe up)
        c.open(FEED)
        o = c.act("pop", "pop", timeout=200)
        check("pop pop", o, "listen_for_phrase")
        if o["decision"]["action"] == "listen_for_phrase":
            assert c.ev.wait(0, lambda e: e["ev"] == "listening" and e.get("state") == "open", 3)
            m = c.ev.mark()
            c.vox.phrase("next")
            o2 = c.outcome(m, timeout=200)
            check("phrase 'next'", o2, "swipe_up")
            if o2["decision"]["action"] == "swipe_up":
                c.texts_until("feed_index", "Video 2 of 20")
        apps = [x[1] for x in lat]
        servers = [x[2] for x in lat]
        c.note(f"{len(lat)} requests: app-side median {statistics.median(apps):.0f} ms (max {max(apps)}), "
               f"server median {statistics.median(servers):.0f} ms (max {max(servers):.0f})")
        assert len(lat) >= 10, lat
        assert not wrong, f"{len(wrong)}/{len(lat)} wrong: {wrong}"
    finally:
        c.vox.control("config", decider="rules", http_timeout_ms=2000)
        adb("reverse", "--remove", "tcp:8765", check=False)


# --- intent cursor mode: pop pop, a spoken target, then tap / highlight / not on screen ----------------------------

def name_target(c: Ctx, phrase: str, timeout: float = 10) -> dict:
    """In cursor mode: "pop pop" (the app opens the listening window), then the phrase. Returns the target events."""
    m = c.ev.mark()
    assert c.vox.sounds("pop", mode="cursor")["waiting"] is True, "in cursor mode pop must wait for a second pop"
    time.sleep(0.15)
    c.vox.sounds("pop", mode="cursor")
    d = c.ev.wait(m, lambda e: e["ev"] == "decision" and e.get("source") == "app:cursor-listen", 3)
    assert d and d["action"] == "listen_for_phrase", [e["ev"] for e in c.ev.since(m)]
    assert c.ev.wait(m, lambda e: e["ev"] == "listening" and e.get("state") == "open", 2), "listening window not opened"
    m2 = c.ev.mark()
    c.vox.phrase(phrase)
    st = c.ev.wait(m2, lambda e: e["ev"] == "target_state", 5)
    assert st, [e["ev"] for e in c.ev.since(m2)]
    td = c.ev.wait(m2, lambda e: e["ev"] == "target_decision" and e.get("n") == st["n"], timeout)
    tg = c.ev.wait(m2, lambda e: e["ev"] == "target" and e.get("n") == st["n"], 5)
    return {"state": st, "decision": td, "target": tg, "mark": m2}


def use_fake_targets(c: Ctx, srv: FakeSystemOne) -> None:
    c.vox.control("config", decider="hybrid", base_url=f"http://127.0.0.1:{srv.port}", model="vox-test",
                  target_model="vox-targets-fake", http_timeout_ms=5000)


def enter_cursor(c: Ctx) -> None:
    m = c.ev.mark()
    c.vox.mode("cursor")
    assert c.ev.wait(m, lambda e: e["ev"] == "mode" and e.get("mode") == "cursor", 2)


def open_newpipe(c: Ctx) -> None:
    force_stop("org.schabi.newpipe")
    launch("org.schabi.newpipe")
    time.sleep(4)
    dismiss_first_run(vox=c.vox, log=c.note)
    time.sleep(1)
    assert c.vox.control("ping")["app"] == "org.schabi.newpipe"


def selected_tab_becomes(c: Ctx, want: str, timeout: float = 4) -> None:
    end = time.time() + timeout
    got = None
    while time.time() < end:
        got = selected_tab(c)
        if got == want:
            return
        time.sleep(0.3)
    raise AssertionError(f"selected tab {got!r}, expected {want!r}")


def split(cands: list[str], ps: list[float]):
    """A fake answer: the first candidate on top but below target_min_confidence, the rest close behind."""
    probs = dict(zip(cands, ps))
    return lambda opts: {"choice": cands[0], "probabilities": {o: probs.get(o, 0.0) for o in opts}, "confidence": ps[0]}


@test
def intent_cursor_confident_target_is_tapped(c: Ctx):
    srv = FakeSystemOne()
    try:
        use_fake_targets(c, srv)
        open_newpipe(c)
        start = selected_tab(c)
        want = "What's New (tab, top)"
        srv.target_answer = lambda opts: {"choice": want, "confidence": 0.93,
                                          "probabilities": {o: 0.93 if o == want else 0.07 / (len(opts) - 1) for o in opts}}
        enter_cursor(c)
        r = name_target(c, "the what's new tab")
        st, opts = r["state"]["text"], r["state"]["options"]
        c.note(f"{len(opts)} options: {opts}")
        assert st.startswith("mode: cursor\napp: NewPipe (org.schabi.newpipe)\nscreen: "), st
        assert st.endswith('\nspoken target: "the what\'s new tab"') and st.count("\n") == 3, st
        assert opts[-1] == TARGETS.NONE_OPTION and want in opts and len(opts) == len(set(opts)) <= 40, opts
        for o in opts[:-1]:
            mt = OPTION_RE.fullmatch(o)
            assert mt and mt[2] in TARGETS.ROLE_WORDS and mt[3] in TARGETS.POSITIONS, o
        req = srv.requests[-1]
        assert req["model"] == "vox-targets-fake" and req["state"] == st, req
        q = req["questions"]["target"]
        assert list(req["questions"]) == ["target"] and q["type"] == "choice" and q["instructions"] == POLICY_TARGETS, q
        assert list(q["criteria"]) == opts, "criteria must go out in the logged reading order, none last"
        t = r["target"]
        assert t and t["result"] == "tap" and t["option"] == want and t["ok"], t
        cf = c.ev.wait(r["mark"], lambda e: e["ev"] == "confirm" and e.get("watch") == t["watch"], 5)
        assert cf and cf["result"] == "confirmed (events)", cf
        selected_tab_becomes(c, "What's New")
        c.note(f"tab {start!r} -> 'What's New'; confirm {cf['result']} by {cf['by']} in {cf['ms']} ms")
    finally:
        srv.close()


@test
def intent_cursor_low_confidence_highlights_top3_and_rise_rise_pop_taps_third(c: Ctx):
    srv = FakeSystemOne()
    try:
        use_fake_targets(c, srv)
        open_newpipe(c)
        cands = ["What's New (tab, top)", "Subscriptions (tab, top)", "Bookmarked Playlists (tab, top right)"]
        srv.target_answer = split(cands + [TARGETS.NONE_OPTION], [0.36, 0.33, 0.29, 0.02])
        enter_cursor(c)
        start = selected_tab(c)
        before = screenshot()
        r = name_target(c, "the tab")
        t = r["target"]
        assert t and t["result"] == "choose" and t["candidates"] == cands, t
        assert r["decision"]["confidence"] < 0.6
        time.sleep(0.6)
        shown = screenshot()
        d = screen_diff(before, shown)
        assert d > 0.0005, f"no highlight drawn (diff {d:.3%})"
        assert selected_tab(c) == start, "nothing may be tapped while choosing"
        m = c.ev.mark()
        for want in (2, 3):
            c.vox.sounds("rise", mode="cursor")
            e = c.ev.wait(m, lambda e, w=want: e["ev"] == "choice" and e.get("event") == "select" and e.get("selected") == w, 3)
            assert e, [x for x in c.ev.since(m) if x["ev"] == "choice"]
        assert e["option"] == cands[2]
        c.vox.sounds("pop", mode="cursor")
        tap = c.ev.wait(m, lambda e: e["ev"] == "target" and e.get("result") == "tap", 3)
        assert tap and tap["option"] == cands[2] and tap["why"] == "picked 3 of 3" and tap["ok"], tap
        cf = c.ev.wait(m, lambda e: e["ev"] == "confirm" and e.get("watch") == tap["watch"], 5)
        assert cf and cf["result"] == "confirmed (events)", cf
        selected_tab_becomes(c, "Bookmarked Playlists")
        c.note(f"highlight diff {d:.2%}; rise, rise, pop -> {tap['option']}; confirm {cf['result']} by {cf['by']}")
    finally:
        srv.close()


@test
def intent_cursor_not_on_screen_cancel_and_timeout(c: Ctx):
    srv = FakeSystemOne()
    try:
        use_fake_targets(c, srv)
        c.vox.control("config", target_choose_ms=1500)
        c.open(CONTROLS)
        enter_cursor(c)
        m0 = c.ev.mark()
        # none of these -> a toast, nothing tapped
        srv.target_answer = lambda opts: {"choice": opts[-1], "probabilities": {o: 0.9 if o == opts[-1] else 0.1 for o in opts},
                                          "confidence": 0.9}
        r = name_target(c, "the like button")
        assert r["target"]["result"] == "not on screen", r["target"]
        assert c.ev.wait(r["mark"], lambda e: e["ev"] == "toast" and e.get("text") == "not on screen", 2)
        assert r["state"]["options"] == ["Type here (text field, top)", "TOGGLE (button, center)", TARGETS.NONE_OPTION], r["state"]["options"]
        # low confidence -> highlight; hiss cancels
        cands = ["TOGGLE (button, center)", "Type here (text field, top)"]
        srv.target_answer = split(cands + [TARGETS.NONE_OPTION], [0.45, 0.40, 0.15])
        r = name_target(c, "the switch")
        assert r["target"]["result"] == "choose" and r["target"]["candidates"] == cands, r["target"]
        m = c.ev.mark()
        c.vox.sounds("hiss", mode="cursor")
        assert c.ev.wait(m, lambda e: e["ev"] == "choice" and e.get("event") == "cancelled" and e.get("why") == "hiss", 2)
        # ...and the timeout cancels (target_choose_ms = 1500 here; 6000 by default)
        r = name_target(c, "the switch")
        assert r["target"]["result"] == "choose", r["target"]
        t0 = time.time()
        e = c.ev.wait(r["mark"], lambda e: e["ev"] == "choice" and e.get("event") == "cancelled", 4)
        assert e and e["why"] == "timeout", e
        c.note(f"timeout cancel after {time.time() - t0:.1f}s")
        time.sleep(0.3)
        assert c.vox.texts()["toggle_state"] == "State: OFF", "nothing may have been tapped"
        assert not any(x["ev"] == "target" and x.get("result") == "tap" for x in c.ev.since(m0))
        # with the rule decider there is no model to ask
        c.vox.control("config", decider="rules")
        r = name_target(c, "the switch", timeout=1)
        assert r["target"]["result"] == "no model (decider=rules)", r["target"]
    finally:
        srv.close()


# --- F-Droid stand-ins: one gesture each ------------------------------------------------------------------------------

# --- personalization (enrolled custom / ignore sounds) ------------------------------------------------------------------

FP_DIM = 24


def fp_centre(seed: int) -> list[float]:
    """A synthetic fp1-like vector: every feature differs between classes (see the near-constant-feature caveat)."""
    rng = random.Random(seed)
    return [rng.uniform(-3, 3) for _ in range(FP_DIM)]


def fp_near(centre: list[float], rng: random.Random, noise: float = 0.05, version: str = "fp1") -> dict:
    return {"fp": [x + rng.uniform(-noise, noise) for x in centre], "fp_version": version, "pitch16": []}


def personal_act(c: Ctx, feats: dict | None, label: str = "rise") -> tuple[dict, dict | None]:
    """Send one sound (the extractor said `label`, normal hum line) with a fingerprint; return (outcome, match event)."""
    mark = c.ev.mark()
    o = c.act(label, features=[feats])
    m = c.ev.wait(mark, lambda e: e["ev"] == "match" and e.get("id") == c.vox.next_id, 2) if feats else None
    return o, m


@test
def personal_custom_meow_bound_ignore_sneeze_and_far_sound(c: Ctx):
    rng = random.Random(11)
    meow, sneeze, far = fp_centre(1), fp_centre(2), fp_centre(3)
    try:
        c.vox.control("enroll_delete", all=True)
        r = c.vox.control("enroll_add", kind="custom", name="meow", examples=[fp_near(meow, rng) for _ in range(5)])
        assert r["ok"], r
        r = c.vox.control("enroll_add", kind="ignore", name="sneeze", examples=[fp_near(sneeze, rng) for _ in range(3)])
        assert r["ok"], r
        # rejected: another fp version / another length; the store is unchanged
        bad = c.vox.control("enroll_add", kind="custom", name="meow", examples=[fp_near(meow, rng, version="fp2")])
        assert not bad["ok"] and "fp_version" in bad["error"], bad
        bad = c.vox.control("enroll_add", kind="custom", name="meow", examples=[{"fp": meow[:10], "fp_version": "fp1"}])
        assert not bad["ok"] and "fp has 10 values" in bad["error"], bad
        en = c.vox.control("enroll_list")["enrollment"]
        cls = {x["name"]: x for x in en["classes"]}
        assert en["fp_version"] == "fp1" and en["dim"] == FP_DIM, en
        assert cls["meow"]["examples"] == 5 and cls["sneeze"]["examples"] == 3 and all(x["active"] for x in cls.values()), en
        c.note(f"thresholds: meow {cls['meow']['threshold']} (5 ex), sneeze {cls['sneeze']['threshold']} (3 ex): "
               "leave-one-out x1.4")
        # the shipped per-feature std floors for fp1 are in use, marked provisional (and logged as such)
        assert en["floors"] == "provisional", en
        fl = c.vox.control("fp_floors")
        assert fl["status"] == "provisional" and not fl["override"] and len(fl["table"]["fp1"]["floor"]) == FP_DIM, fl
        assert fl["table"]["fp1"]["provisional"] is True, fl
        # an on-device override replaces the fp1 entry without a rebuild; reset goes back to the asset
        fl = c.vox.control("fp_floors", table={"fp1": {"floor": [0.01] * FP_DIM, "provisional": False, "source": "suite"}})
        assert fl["status"] == "final" and fl["override"] and fl["table"]["fp1"]["source"] == "suite", fl
        bad = c.vox.control("fp_floors", table={"fp1": {"floor": [-1] * FP_DIM}})
        assert not bad["ok"] and "floor[0]" in bad["error"], bad
        fl = c.vox.control("fp_floors", reset=True)
        assert fl["status"] == "provisional" and not fl["override"], fl
        # one store per mic source (files/enroll/<profile>@<source>.json); enroll_list names it
        store = c.vox.control("enroll_list")["enrollment"]["file"]
        stored = json.loads(sh(f"run-as ai.vox.companion cat files/enroll/{store}"))
        assert [x["name"] for x in stored["classes"]] == ["meow", "sneeze"], stored

        c.vox.control("profile", profile={"global": [{"sound": "my:meow", "kind": "fixed", "action": "open_camera"}]})
        camera = "No activity found" not in sh("cmd package resolve-activity -a android.media.action.STILL_IMAGE_CAMERA", check=False)
        c.open(FEED)

        # near-meow: the line becomes my sound "meow", the fixed rule opens the camera; the model is never asked
        mark = c.ev.mark()
        o, m = personal_act(c, fp_near(meow, rng))
        assert m and m["result"] == "custom" and m["class"] == "meow" and m["distance"] <= m["threshold"], m
        assert m["floors"] == "provisional", m
        assert 'sound 1: my sound "meow"; duration short (150-400 ms); loudness normal' in o["state"]["text"], o["state"]["text"]
        assert "sequence: my:meow" in o["state"]["text"], o["state"]["text"]
        expect(o, "open_camera", confirm=None)
        assert o["decision"]["source"].startswith("personal:custom-sound"), o["decision"]
        c.note(f"near-meow: d={m['distance']} <= {m['threshold']} -> open_camera ({o['exec']['how']}), camera app: {camera}")
        if camera:
            # The AVD has no camera hardware (emu.sh), so Camera2 starts and then crashes; the service seeing its
            # window is the evidence that the intent launched it.
            assert o["exec"]["ok"], o["exec"]
            seen = c.ev.wait(mark, lambda e: e["ev"] == "app" and "camera" in e.get("package", ""), 5)
            assert seen, "the camera app never came to the front"
            c.note(f"camera window seen: {seen['package']} (it then crashes: the AVD has no camera)")
        sh("input keyevent KEYCODE_HOME", check=False)
        for pkg in ("com.android.camera2", "com.android.camera"):
            force_stop(pkg)
        c.open(FEED)
        assert c.vox.texts()["feed_index"] == "Video 1 of 20"

        # far vector: no class within its threshold, the extractor's line is kept -> the normal rise
        o, m = personal_act(c, fp_near(far, rng))
        assert m and m["result"] == "none" and m["distance"] > m["threshold"], m
        assert "sound 1: hum that rises" in o["state"]["text"] and "my sound" not in o["state"]["text"]
        expect(o, "swipe_up")
        c.texts_until("feed_index", "Video 2 of 20")
        c.note(f"far: nearest {m['nearest']} d={m['distance']} > {m['threshold']} -> swipe_up")

        # near-sneeze: sounds like one of my ignore sounds -> none (the extractor called it a rise)
        o, m = personal_act(c, fp_near(sneeze, rng))
        assert m and m["result"] == "ignore" and m["class"] == "sneeze", m
        assert "sounds like one of my ignore sounds" in o["state"]["text"], o["state"]["text"]
        expect(o, "none", confirm=None)
        assert "my-ignore-sound" in o["decision"]["source"], o["decision"]
        assert c.vox.texts()["feed_index"] == "Video 2 of 20"

        # a mismatched fp version is not matched (logged), the sound goes through unchanged
        o, m = personal_act(c, fp_near(meow, rng, version="fp2"))
        assert m and m["result"] == "skipped" and "fp_version 'fp2'" in m["reason"], m
        expect(o, "swipe_up")

        # model decider: an unbound custom sound and an ignore sound are decided locally, without a request
        srv = FakeSystemOne()
        try:
            c.vox.control("profile", profile=None)       # meow now unbound
            c.vox.control("config", decider="model", base_url=f"http://127.0.0.1:{srv.port}", model="fake")
            o, m = personal_act(c, fp_near(meow, rng))
            assert m["result"] == "custom", m
            expect(o, "none", confirm=None)
            assert o["decision"]["source"].startswith("personal:custom-sound") and "unbound" in o["decision"]["source"], o["decision"]
            o, m = personal_act(c, fp_near(sneeze, rng))
            expect(o, "none", confirm=None)
            assert not srv.requests, f"the model was called for a custom/ignore sound: {len(srv.requests)}"
            srv.answer = "swipe down"
            o, m = personal_act(c, fp_near(far, rng))    # an ordinary sound still goes to the model
            assert len(srv.requests) == 1 and srv.requests[0]["state"] == o["state"]["text"], len(srv.requests)
            assert o["decision"]["source"] == "model", o["decision"]
            c.note("model decider: 0 requests for custom/ignore sounds, 1 for the far sound")
        finally:
            srv.close()
            c.vox.control("config", decider="rules")

        # enrollment is per profile
        c.vox.control("profile", profile={"name": "alice", "global": []})
        assert c.vox.control("enroll_list")["enrollment"]["classes"] == []
        c.vox.control("profile", profile=None)
        assert len(c.vox.control("enroll_list")["enrollment"]["classes"]) == 2
        r = c.vox.control("enroll_delete", name="meow", index=0)
        assert r["deleted"] and {x["name"]: x["examples"] for x in r["enrollment"]["classes"]}["meow"] == 4, r
    finally:
        c.vox.control("profile", profile=None)
        c.vox.control("enroll_delete", all=True)


def standin(c: Ctx, pkg: str, labels: tuple[str, ...], action: str, prepare=None, check=None, confirm: str | None = "confirmed (events)",
            source: str | None = None, min_diff: float = 0.01) -> None:
    """Open a stand-in app, send one gesture, and assert: the decision, the gesture was performed, the screenshot
    changed, an app-specific check (before -> after), and (unless confirm=None) the confirmer's verdict."""
    force_stop(pkg)
    if prepare:
        prepare()
    else:
        launch(pkg)
    time.sleep(4)
    dismiss_first_run(vox=c.vox, log=c.note)
    time.sleep(1)
    fg = c.vox.control("ping")["app"]
    assert fg == pkg, f"foreground is {fg}, expected {pkg}"
    c.note(f"{pkg}: {c.vox.control('screen')['line']}")
    probe = check() if check else None
    before = screenshot()
    o = c.act(*labels)
    time.sleep(1.5)
    after = screenshot()
    d = screen_diff(before, after)
    cf = o.get("confirm", {})
    c.note(f"decision {o['decision']['action']} ({o['decision']['source']}); exec {o['exec']['how']}; "
           f"confirmer: {cf.get('result')} by {cf.get('by')} in {cf.get('ms')} ms; screenshot diff {d:.1%}")
    expect(o, action, confirm=None)
    if source:
        assert o["decision"]["source"] == source, o["decision"]
    assert d >= min_diff, f"screen did not visibly change (diff {d:.2%})"
    if check:
        now = check()
        c.note(f"check: {probe!r} -> {now!r}")
        assert now != probe, f"app state unchanged: {now!r}"
    if confirm:
        assert cf.get("result") == confirm, f"confirmer said {cf.get('result')!r}"


def selected_tab(c: Ctx):
    """Label of the tab strip entry that is not clickable (the selected one), as NewPipe/VLC tab strips expose it."""
    tabs = [n for n in c.vox.control("dump")["nodes"] if n["cls"] == "LinearLayout" and n["desc"]
            and 150 < int(n["bounds"].split(",")[1]) < 450]   # the tab strip; VLC's collapsing app bar moves it
    sel = [n["desc"] for n in tabs if not n["click"]]
    return sel[0] if sel else None


def visible_texts(c: Ctx, prefix: str):
    return sorted({n["text"] or n["desc"] for n in c.vox.control("dump")["nodes"] if (n["text"] or n["desc"]).startswith(prefix)})



@test
def ble_ops_without_a_device(c: Ctx):
    """The BLE source runs on the emulator (no VOX device): its debug ops answer and validate, nothing crashes.
    The real Pico -> phone test is manual (README "BLE end-to-end test")."""
    st = c.vox.control("ble_status")
    assert st["ok"] and st["ble"]["state"] in ("idle", "off", "waiting", "connecting", "scanning"), st
    assert set(st["ble"]["permissions"]) == {"scan", "connect"}, st
    bad = c.vox.control("ble_connect", address="not-an-address")
    assert not bad["ok"], bad
    bad = c.vox.control("config", ble_device="12:34")
    assert not bad["ok"] and "ble_device" in bad["error"], bad
    r = c.vox.control("config", ble_device=None)
    assert r["ok"] and r["settings"]["ble_device"] is None, r
    bad = c.vox.control("ble_config", config={"v": 1, "test_sounds": True})
    assert not bad["ok"] and ("not connected" in bad["error"] or "not ready" in bad["error"]), bad
    # app commands to the device need a ready link; the op validates first
    bad = c.vox.control("device", armed=False)
    assert not bad["ok"] and "no device connected" in bad["error"], bad
    bad = c.vox.control("device", mode="listening")
    assert not bad["ok"] and "mode must be one of" in bad["error"], bad
    bad = c.vox.control("device", sleep=True, armed=True)
    assert not bad["ok"] and "sleep cannot be combined" in bad["error"], bad
    dev = c.vox.control("ble_status")["ble"]["device"]
    assert dev["ready"] is False and dev["asleep"] is False and dev["error"] is None, dev
    f = c.vox.control("ble_forget")
    assert f["ok"], f
    # a message the BLE path would synthesise on a dropped link disarms like a device armed:false
    mark = c.ev.mark()
    c.vox.send({"v": 1, "armed": False, "sounds": [], "sequence": []})
    assert c.ev.wait(mark, lambda e: e["ev"] == "arm" and e.get("state") == "disarmed", 2)
    c.vox.control("reset")
    c.note(f"adapter {st['ble']['adapter']}, state {st['ble']['state']}, permissions {st['ble']['permissions']}")

@test
def standin_newpipe_dip_swipes_tabs(c: Ctx):
    standin(c, "org.schabi.newpipe", ("dip",), "swipe_left", check=lambda: selected_tab(c))


@test
def standin_vlc_dip_swipes_tabs(c: Ctx):
    def prepare():   # VLC restores its last screen and tab: go to Video, first tab, so a left swipe has somewhere to go
        launch("org.videolan.vlc")
        time.sleep(4)
        dismiss_first_run(vox=c.vox, log=c.note)
        n = node_by_id(c.vox, "nav_video")
        if n:
            tap_node(n)
            time.sleep(1)
        for _ in range(3):
            sh("input swipe 200 1300 900 1300 200")
            time.sleep(0.6)
    standin(c, "org.videolan.vlc", ("dip",), "swipe_left", prepare=prepare, check=lambda: selected_tab(c))


@test
def standin_organic_maps_rise_zooms_in_by_app_rule(c: Ctx):
    prime_organic_maps(c.vox, log=c.note)
    # The map is an OpenGL surface: the pinch's own click echo is ignored and no other event arrives, so the
    # confirmer has to fall back to comparing screenshots.
    def prepare():   # the app restores its last zoom; repeated runs reach the maximum, where a pinch-out changes nothing
        launch("app.organicmaps")
        time.sleep(4)
        for _ in range(4):
            n = node_by_id(c.vox, "nav_zoom_out")
            if n:
                tap_node(n)
                time.sleep(0.5)
    standin(c, "app.organicmaps", ("rise",), "zoom_in", prepare=prepare, source="rules:app-binding", confirm="confirmed (pixels)",
            min_diff=0.05)


@test
def standin_fossify_gallery_dip_next_photo(c: Ctx):
    def prepare():
        out = sh("content query --uri content://media/external/images/media --projection _id:_display_name", check=False)
        ids = [line.split("_id=")[1].split(",")[0] for line in out.splitlines() if "vox_test_0" in line]
        assert ids, f"seeded photo not in MediaStore: {out[:300]}"
        sh(f"am start -W -a android.intent.action.VIEW -d content://media/external/images/media/{ids[0]} -t image/png "
           f"-p org.fossify.gallery")
    standin(c, "org.fossify.gallery", ("dip",), "swipe_left", prepare=prepare, check=lambda: visible_texts(c, "vox_test_"))


@test
def standin_fennec_rise_scrolls_page(c: Ctx):
    web = WebServer(8766)
    try:
        def prepare():
            sh(f"am start -W -a android.intent.action.VIEW -d {web.url} -p org.mozilla.fennec_fdroid")
            time.sleep(4)
            dismiss_first_run(vox=c.vox, log=c.note)
            # a fresh query string so Fennec does not restore an old scroll position
            sh(f"am start -W -a android.intent.action.VIEW -d {web.url}?t={int(time.time())} -p org.mozilla.fennec_fdroid")
        standin(c, "org.mozilla.fennec_fdroid", ("rise",), "swipe_up", prepare=prepare,
                check=lambda: visible_texts(c, "Section "))
    finally:
        web.close()


# --- VOX's own Flutter UI ---------------------------------------------------------------------------------------------

def own_targets(c: Ctx, want: str, timeout: float = 20) -> dict:
    """The `targets` op on VOX's own screen, polled until an option starts with `want` (a debug build's first frame is slow)."""
    end = time.time() + timeout
    t: dict = {}
    while time.time() < end:
        t = c.vox.control("targets")
        if t.get("package") == "ai.vox.companion" and any(o.startswith(want) for o in t.get("options", [])):
            return t
        time.sleep(0.5)
    raise AssertionError(f"no option {want!r} on VOX's screen: {t.get('package')} {t.get('options')}")


def own_text(c: Ctx) -> str:
    d = c.vox.control("dump")
    return " | ".join(n["text"] or n["desc"] for n in d["nodes"] if n["text"] or n["desc"])


def tap_option(t: dict, prefix: str) -> None:
    hit = [x for x in t["targets"] if x["option"].startswith(prefix)]
    assert hit, f"{prefix!r} not in {[x['option'] for x in t['targets']]}"
    tap_node(hit[0])


@test
def ui_flutter_status_screen_is_readable_and_pausable(c: Ctx):
    """The Flutter status screen (ui/) as the accessibility service sees it: Targets.kt lists its controls by their
    semantics labels, and tapping them (adb input at the listed bounds) pauses, resumes and opens the legacy settings."""
    mark = c.ev.mark()
    sh("am start -W -n ai.vox.companion/.MainActivity")   # not start_activity: its -S force-stop would kill the service
    t = own_targets(c, "Pause Canti")
    opts = t["options"]
    for want in ("Pause Canti", "Refresh status", "Legacy settings"):
        assert any(o.startswith(want + " (") for o in opts), f"{want!r} missing from {opts}"
    assert "Listening for sounds" in own_text(c), own_text(c)
    ff = c.ev.wait(mark, lambda e: e["ev"] == "ui" and e.get("what") == "first_frame", 5)
    c.note(f"options: {opts}")
    if ff:
        c.note(f"first frame {ff.get('since_create_ms')} ms after onCreate")
    # pause from the screen: the service ignores sounds and says why
    mark = c.ev.mark()
    tap_option(t, "Pause Canti")
    e = c.ev.wait(mark, lambda e: e["ev"] == "pause" and e.get("state") == "paused", 4)
    assert e and e["by"] == "app", e
    assert c.vox.control("ping")["paused"] is True
    c.vox.sounds("rise")
    ign = c.ev.wait(mark, lambda e: e["ev"] == "ignored" and e.get("id") == c.vox.next_id, 3)
    assert ign and ign["reason"] == "paused (app)", ign
    assert not c.ev.wait(mark, lambda e: e["ev"] == "exec", 1.0), "a paused VOX acted"
    t = own_targets(c, "Resume Canti", 5)
    assert "Paused" in own_text(c), own_text(c)
    # resume
    mark = c.ev.mark()
    tap_option(t, "Resume Canti")
    e = c.ev.wait(mark, lambda e: e["ev"] == "pause" and e.get("state") == "resumed", 4)
    assert e and e["by"] == "app", e
    assert c.vox.control("ping")["paused"] is False
    # the legacy settings screen opens over it, and back returns to the Flutter screen
    t = own_targets(c, "Legacy settings", 5)
    tap_option(t, "Legacy settings")
    end = time.time() + 5
    while time.time() < end and "LegacySettingsActivity" not in sh("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -1", check=False):
        time.sleep(0.3)
    top = sh("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -1", check=False)
    assert "LegacySettingsActivity" in top, top
    sh("input keyevent KEYCODE_BACK")
    own_targets(c, "Pause Canti", 5)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("-k", default="")
    p.add_argument("--list", action="store_true")
    a = p.parse_args()
    chosen = [(n, f) for n, f in TESTS if a.k in n]
    if a.list:
        print("\n".join(n for n, _ in chosen))
        return
    c = Ctx()
    c.wait_service()
    sh("settings put system screen_off_timeout 1800000", check=False)
    results = []
    t0 = time.time()
    for name, fn in chosen:
        c.notes = []
        c.reset()
        print(f"RUN  {name}")
        ts = time.time()
        try:
            fn(c)
            status, err = "PASS", ""
        except Skip as e:
            status, err = "SKIP", str(e)
        except Exception as e:  # noqa: BLE001
            status, err = "FAIL", f"{type(e).__name__}: {e}"
            traceback.print_exc(limit=2)
        dt = time.time() - ts
        print(f"{status} {name} ({dt:.1f}s){'  ' + err if err else ''}")
        results.append({"test": name, "status": status, "seconds": round(dt, 1), "error": err, "notes": c.notes})
    sh("input keyevent KEYCODE_HOME", check=False)
    passed = sum(r["status"] == "PASS" for r in results)
    skipped = sum(r["status"] == "SKIP" for r in results)
    print(f"\n{passed}/{len(results)} passed, {skipped} skipped, in {time.time() - t0:.0f}s")
    for r in results:
        if r["status"] != "PASS":
            print(f"  {r['status']} {r['test']}: {r['error']}")
    OUT.mkdir(exist_ok=True)
    f = OUT / f"results-{time.strftime('%Y%m%d-%H%M%S')}.json"
    f.write_text(json.dumps({"passed": passed, "skipped": skipped, "total": len(results), "results": results}, indent=1) + "\n")
    print(f"results: {f}")
    c.ev.close()
    sys.exit(0 if passed + skipped == len(results) else 1)


if __name__ == "__main__":
    main()
