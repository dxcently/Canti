"""The emitted lines must be exactly the strings the decision model was trained on."""

import itertools

import pytest

import finetune_ref
from vox_extract import vocab
from vox_extract.lines import LineError, discrete_line, hiss_line, hum_line, label_consistent, parse_line
from vox_extract.vocab import CLARITY, CONTOURS, DURATION, EXCURSION, LOUDNESS, SOUNDS_LIKE

REF = finetune_ref.load()
needs_finetune = pytest.mark.skipif(REF is None, reason="/home/khoa/VOX/finetune not present")


@needs_finetune
def test_vocab_pinned_copy_matches_live_schema():
    S, _ = REF
    for name in ("CONTOURS", "DISCRETE", "EXCURSION", "DURATION", "CLARITY", "LOUDNESS", "SOUNDS_LIKE"):
        assert getattr(vocab, name) == getattr(S, name), f"{name} drifted from finetune/vox/schema.py"
    assert dict(vocab.DEFAULT_BINDINGS) == dict(S.DEFAULT_BINDINGS)
    ns = {k: getattr(S, k) for k in ("CONTOURS", "DISCRETE", "EXCURSION", "DURATION", "CLARITY", "LOUDNESS", "SOUNDS_LIKE")}
    assert vocab.digest(ns) == vocab.digest()


@needs_finetune
def test_every_generate_py_line_parses():
    seen = finetune_ref.seen_lines()
    assert len(seen) > 500
    kinds = set()
    for line in seen:
        kinds.add(parse_line(line)["kind"])
    assert kinds == {"hum", "hiss", "pop", "click"}


@needs_finetune
def test_builders_reproduce_generate_py_strings():
    """Rebuild each training line with our builders from its parsed fields: must be byte-identical."""
    for line in finetune_ref.seen_lines():
        p = parse_line(line)
        if p["kind"] == "hum":
            again = hum_line(p["contour"], p["pitch_change"], p["duration"], p["tone"], p["loudness"], p["sounds_like"])
        elif p["kind"] == "hiss":
            again = hiss_line(p["duration"], p["loudness"], p["sounds_like"])
        else:
            again = discrete_line(p["kind"], p["loudness"])
        assert again == line


def test_all_builder_combinations_roundtrip():
    n = 0
    for c, e, d, t, l, s in itertools.product(CONTOURS, EXCURSION, DURATION, CLARITY, LOUDNESS, SOUNDS_LIKE):
        line = hum_line(c, e, d, t, l, s)
        p = parse_line(line)
        assert (p["contour"], p["pitch_change"], p["duration"], p["tone"], p["loudness"], p["sounds_like"]) == (c, e, d, t, l, s)
        assert label_consistent(c, p)
        n += 1
    for d, l, s in itertools.product(DURATION, LOUDNESS, SOUNDS_LIKE):
        assert parse_line(hiss_line(d, l, s))["kind"] == "hiss"
    for k, l in itertools.product(("pop", "click"), LOUDNESS):
        assert parse_line(discrete_line(k, l)) == {"kind": k, "loudness": l, "sounds_like": "mouth sound"}
    assert n == 5 * 3 * 4 * 3 * 3 * 8


GOOD_HUM = ("hum that rises from low to high; pitch change large (over 4 semitones); duration short (150-400 ms); "
            "tone clear tone; loudness normal; sounds like hum")
BAD = [
    GOOD_HUM + ".",                                          # trailing period
    GOOD_HUM + " ",                                          # trailing space
    " " + GOOD_HUM,
    GOOD_HUM.replace("; ", ";"),                             # separator
    GOOD_HUM.replace("; ", ";  ", 1),
    GOOD_HUM.replace("rises from low to high", "rises"),     # contour text
    GOOD_HUM.replace("large (over 4 semitones)", "large"),   # bucket text
    GOOD_HUM.replace("150-400 ms", "150–400 ms"),            # en dash
    GOOD_HUM.replace("tone clear tone", "tone clear"),
    GOOD_HUM.replace("loudness normal", "loudness medium"),
    GOOD_HUM.replace("sounds like hum", "sounds like humming"),
    GOOD_HUM.replace("Hum", "hum").replace("hum that", "Hum that"),  # case
    "; ".join(GOOD_HUM.split("; ")[:5]),                     # missing field
    "; ".join([GOOD_HUM.split("; ")[0]] + GOOD_HUM.split("; ")[2:3] + GOOD_HUM.split("; ")[1:2] + GOOD_HUM.split("; ")[3:]),  # order
    "a short lip pop; instant sound; loudness normal; sounds like background noise",  # pop must be a mouth sound
    "a short lip pop; duration short (150-400 ms); loudness normal; sounds like mouth sound",
    "a hiss; instant sound; loudness normal; sounds like mouth sound",
    "a hiss; duration short (150-400 ms); loudness normal",
    "a tongue click; instant sound; loudness normal; sounds like mouth sound\n",
    "unknown sound",
    "",
]


@pytest.mark.parametrize("line", BAD)
def test_parser_rejects(line):
    with pytest.raises(LineError):
        parse_line(line)


def test_label_consistency():
    p = parse_line(GOOD_HUM)
    assert label_consistent("rise", p) and not label_consistent("fall", p)
    assert label_consistent("pop", parse_line("a short lip pop; instant sound; loudness quiet; sounds like mouth sound"))
    assert not label_consistent("click", parse_line("a short lip pop; instant sound; loudness quiet; sounds like mouth sound"))
