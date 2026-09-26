"""Pinned copy of the sound vocabulary from finetune/vox/schema.py.

The extractor must emit exactly the strings the decision model was trained on
(finetune/vox/generate.py: deliberate_sound, junk_sound, air_hiss). This module keeps
a frozen copy so the extractor never imports from a directory other work is editing.
tests/test_lines.py loads the live schema read-only and fails if the copy drifts
(the same idea as the Android app's Vocab.kt digest).
"""

from __future__ import annotations

import hashlib
import json

CONTOURS = {
    "rise": "rises from low to high",
    "fall": "falls from high to low",
    "arch": "rises then falls",
    "dip": "falls then rises",
    "flat": "stays level",
}
DISCRETE = {
    "pop": "a short lip pop",
    "click": "a tongue click",
    "hiss": "a hiss",
}
EXCURSION = ["small (under 2 semitones)", "medium (2-4 semitones)", "large (over 4 semitones)"]
DURATION = ["very short (under 150 ms)", "short (150-400 ms)", "medium (400-1000 ms)", "long (over 1 s)"]
CLARITY = ["noisy", "breathy", "clear tone"]
LOUDNESS = ["quiet", "normal", "loud"]
SOUNDS_LIKE = ["hum", "whistle", "talking", "laughing", "coughing", "background music", "background noise", "mouth sound"]

# Sequence labels accepted by the phone (android Message.kt LABELS).
LABELS = list(CONTOURS) + list(DISCRETE) + ["unknown"]

# Default bindings (schema.DEFAULT_BINDINGS), used only by policy.py to score synthetic tests.
DEFAULT_BINDINGS = {
    ("rise",): "swipe_up",
    ("fall",): "swipe_down",
    ("arch",): "swipe_right",
    ("dip",): "swipe_left",
    ("pop",): "tap",
    ("hiss",): "back",
    ("flat",): "long_press",
    ("click", "pop"): "listen_for_phrase",
}


def digest(ns: dict | None = None) -> str:
    """sha256 over the vocabulary lists, so a C port can embed and check the same number."""
    src = ns if ns is not None else globals()
    blob = {k: src[k] for k in ("CONTOURS", "DISCRETE", "EXCURSION", "DURATION", "CLARITY", "LOUDNESS", "SOUNDS_LIKE")}
    return hashlib.sha256(json.dumps(blob, sort_keys=True).encode()).hexdigest()[:16]
