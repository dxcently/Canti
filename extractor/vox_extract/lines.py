"""Format sound lines exactly as finetune/vox/generate.py does, and parse them strictly.

Three templates exist (generate.py):
  hum:        "hum that <CONTOURS[g]>; pitch change <EXCURSION>; duration <DURATION>; tone <CLARITY>;
               loudness <LOUDNESS>; sounds like <SOUNDS_LIKE>"
  hiss:       "a hiss; duration <DURATION>; loudness <LOUDNESS>; sounds like <SOUNDS_LIKE>"
  pop/click:  "<DISCRETE[pop|click]>; instant sound; loudness <LOUDNESS>; sounds like mouth sound"

The parser accepts nothing else: fixed field order, exact separators ("; "), exact vocabulary,
no extra whitespace. It returns a dict, or raises LineError.
"""

from __future__ import annotations

from .vocab import CLARITY, CONTOURS, DISCRETE, DURATION, EXCURSION, LOUDNESS, SOUNDS_LIKE


class LineError(ValueError):
    pass


def hum_line(contour: str, excursion: str, duration: str, tone: str, loudness: str, sounds_like: str) -> str:
    line = (f"hum that {CONTOURS[contour]}; pitch change {excursion}; duration {duration}; "
            f"tone {tone}; loudness {loudness}; sounds like {sounds_like}")
    parse_line(line)  # never emit a line the strict parser would reject
    return line


def hiss_line(duration: str, loudness: str, sounds_like: str) -> str:
    line = f"{DISCRETE['hiss']}; duration {duration}; loudness {loudness}; sounds like {sounds_like}"
    parse_line(line)
    return line


def discrete_line(kind: str, loudness: str) -> str:
    if kind not in ("pop", "click"):
        raise LineError(f"not an instant sound: {kind}")
    line = f"{DISCRETE[kind]}; instant sound; loudness {loudness}; sounds like mouth sound"
    parse_line(line)
    return line


def _field(part: str, key: str, vocab: list[str], line: str) -> str:
    prefix = key + " "
    if not part.startswith(prefix):
        raise LineError(f"expected '{key} ...', got '{part}' in: {line}")
    val = part[len(prefix):]
    if val not in vocab:
        raise LineError(f"'{val}' is not a valid {key} value in: {line}")
    return val


def parse_line(line: str) -> dict:
    """Strict parse. Returns {'kind': 'hum'|'hiss'|'pop'|'click', ...fields}."""
    if not isinstance(line, str) or line != line.strip() or "\n" in line:
        raise LineError(f"bad whitespace: {line!r}")
    parts = line.split("; ")
    if any(p == "" or p != p.strip() or ";" in p for p in parts):
        raise LineError(f"bad separators: {line!r}")
    head = parts[0]
    if head.startswith("hum that "):
        if len(parts) != 6:
            raise LineError(f"hum line needs 6 fields, got {len(parts)}: {line}")
        shape_text = head[len("hum that "):]
        contour = next((k for k, v in CONTOURS.items() if v == shape_text), None)
        if contour is None:
            raise LineError(f"unknown contour '{shape_text}': {line}")
        return {
            "kind": "hum", "contour": contour,
            "pitch_change": _field(parts[1], "pitch change", EXCURSION, line),
            "duration": _field(parts[2], "duration", DURATION, line),
            "tone": _field(parts[3], "tone", CLARITY, line),
            "loudness": _field(parts[4], "loudness", LOUDNESS, line),
            "sounds_like": _field(parts[5], "sounds like", SOUNDS_LIKE, line),
        }
    if head == DISCRETE["hiss"]:
        if len(parts) != 4:
            raise LineError(f"hiss line needs 4 fields, got {len(parts)}: {line}")
        return {
            "kind": "hiss",
            "duration": _field(parts[1], "duration", DURATION, line),
            "loudness": _field(parts[2], "loudness", LOUDNESS, line),
            "sounds_like": _field(parts[3], "sounds like", SOUNDS_LIKE, line),
        }
    for kind in ("pop", "click"):
        if head == DISCRETE[kind]:
            if len(parts) != 4 or parts[1] != "instant sound":
                raise LineError(f"{kind} line must be '<name>; instant sound; loudness ..; sounds like ..': {line}")
            like = _field(parts[3], "sounds like", SOUNDS_LIKE, line)
            if like != "mouth sound":  # generate.py only ever writes "mouth sound" here
                raise LineError(f"{kind} line must say 'sounds like mouth sound': {line}")
            return {"kind": kind, "loudness": _field(parts[2], "loudness", LOUDNESS, line), "sounds_like": like}
    raise LineError(f"unknown line head '{head}': {line}")


def label_consistent(label: str, parsed: dict) -> bool:
    """The protocol's sequence label must agree with the line."""
    if parsed["kind"] == "hum":
        return label == parsed["contour"]
    return label == parsed["kind"]
