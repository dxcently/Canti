"""What would the phone do with these events under the DEFAULT profile? Used only to score tests.

Mirrors android Decider.notDeliberate (the rules decider) and schema.DEFAULT_BINDINGS / POLICY:
a sound is not deliberate if it sounds like talking / laughing / coughing / background music /
background noise, if a hum is noisy or very short, if a non-flat hum changes pitch by only a small
amount, if a flat hum is shorter than 400 ms, or if a hiss is long. A sequence acts only when every
sound passes and the whole sequence is bound.
"""

from __future__ import annotations

from .lines import parse_line
from .vocab import DEFAULT_BINDINGS, DURATION, EXCURSION

NOT_GESTURE_SOURCES = {"talking", "laughing", "coughing", "background music", "background noise"}


def not_deliberate(label: str, text: str) -> str | None:
    if label == "unknown":
        return "unmatched-sound"
    p = parse_line(text)
    if p["sounds_like"] in NOT_GESTURE_SOURCES:
        return "sounds-like-" + p["sounds_like"]
    if p["kind"] == "hum":
        if p["tone"] == "noisy":
            return "noisy"
        if p["duration"] == DURATION[0]:
            return "too-short"
        if label != "flat" and p["pitch_change"] == EXCURSION[0]:
            return "small-change"
        if label == "flat" and p["duration"] in (DURATION[0], DURATION[1]):
            return "short-flat"
    if p["kind"] == "hiss" and p["duration"] == DURATION[3]:
        return "long-hiss"
    return None


def action_for(sequence: list[tuple[str, str]]) -> str:
    """sequence = [(label, text), ...] of one group. Returns the default-profile action or 'none'."""
    for label, text in sequence:
        if not_deliberate(label, text):
            return "none"
    return DEFAULT_BINDINGS.get(tuple(l for l, _ in sequence), "none")


def group(events: list[dict], gap_ms: int = 600) -> list[list[dict]]:
    """Phone-side grouping by device timestamps (PROTOCOL.md): next.start - prev.end <= gap_ms."""
    groups: list[list[dict]] = []
    for e in events:
        if groups and e["t_start_ms"] - groups[-1][-1]["t_end_ms"] <= gap_ms and len(groups[-1]) < 3:
            groups[-1].append(e)
        else:
            groups.append([e])
    return groups
