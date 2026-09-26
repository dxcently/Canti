"""Feature messages (android/PROTOCOL.md v1) and the phone-side grouping / policy mirror."""

import json
import socket
import threading

import numpy as np

import synth
from vox_extract.extractor import extract_array
from vox_extract.lines import label_consistent, parse_line
from vox_extract.policy import action_for, group, not_deliberate
from vox_extract.protocol import DebugSocket, message
from vox_extract.vocab import LABELS

KEYS = {"v", "id", "mode", "armed", "sounds", "sequence", "timing", "phrase", "cursor"}


def check_message(m):
    assert set(m) == KEYS
    assert m["v"] == 1 and isinstance(m["id"], int) and m["mode"] in ("gesture", "cursor", "listening")
    assert isinstance(m["armed"], bool)
    assert 1 <= len(m["sounds"]) <= 3 and len(m["sounds"]) == len(m["sequence"]) == len(m["timing"])
    for text, label, t in zip(m["sounds"], m["sequence"], m["timing"]):
        assert label in LABELS
        assert label_consistent(label, parse_line(text))
        assert set(t) == {"t_start_ms", "t_end_ms"} and isinstance(t["t_start_ms"], int)
        assert 0 <= t["t_start_ms"] < t["t_end_ms"]
    json.dumps(m)


def test_messages_from_synthetic_events():
    clip = synth.demo(np.random.default_rng(5))
    evs = [e.to_dict() for e in extract_array(clip.audio, clip.sr)]
    assert len(evs) >= 8
    for i, e in enumerate(evs, 1):
        check_message(message([e], i))
    for i, g in enumerate(group(evs), 1):
        check_message(message(g, i))


def test_grouping_and_policy():
    pop = "a short lip pop; instant sound; loudness normal; sounds like mouth sound"
    click = "a tongue click; instant sound; loudness normal; sounds like mouth sound"
    e = lambda lab, text, t0, t1: {"label": lab, "text": text, "t_start_ms": t0, "t_end_ms": t1}  # noqa: E731
    evs = [e("click", click, 0, 20), e("pop", pop, 400, 420), e("pop", pop, 1100, 1120)]
    g = group(evs, 600)
    assert [len(x) for x in g] == [2, 1]
    assert action_for([(x["label"], x["text"]) for x in g[0]]) == "listen_for_phrase"
    assert action_for([(x["label"], x["text"]) for x in g[1]]) == "tap"
    talk = ("hum that falls from high to low; pitch change large (over 4 semitones); duration short (150-400 ms); "
            "tone clear tone; loudness normal; sounds like talking")
    assert not_deliberate("fall", talk) == "sounds-like-talking"
    short_flat = ("hum that stays level; pitch change small (under 2 semitones); duration short (150-400 ms); "
                  "tone clear tone; loudness normal; sounds like hum")
    assert action_for([("flat", short_flat)]) == "none"


def test_debug_socket_roundtrip():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = []

    def serve():
        c, _ = srv.accept()
        f = c.makefile("rw", encoding="utf-8", newline="\n")
        got.append(json.loads(f.readline()))
        f.write('{"ok": true}\n')
        f.flush()
        c.close()

    t = threading.Thread(target=serve)
    t.start()
    pop = {"label": "pop", "text": "a short lip pop; instant sound; loudness normal; sounds like mouth sound",
           "t_start_ms": 10, "t_end_ms": 30}
    s = DebugSocket("127.0.0.1", srv.getsockname()[1])
    assert json.loads(s.send(message([pop], 7))) == {"ok": True}
    s.close()
    t.join()
    srv.close()
    check_message(got[0])
    assert got[0]["id"] == 7
