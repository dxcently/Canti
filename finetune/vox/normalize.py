"""Spoken-phrase normaliser for target picking: drops fillers and disfluencies before the phrase goes into the context.

Python mirror of the app's Kotlin normaliser (android/, applied before target picking). The two must agree
byte-for-byte on every phrase; `tests` below are shared cases. Used at eval/inference time only (the model is not
retrained for it), and by the filler augmentation, which must produce the same kind of text the app sends.

    from vox.normalize import normalize_phrase
    normalize_phrase("um so, uh, the the settings button, yeah that one")  -> "the settings button"

Also here: the filler / disfluency perturbations used to test robustness (eval) and to augment training rows.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from pathlib import Path

SPEC_VERSION = "TargetQuery.kt RULES 1-8 (android app, 2026-09-27); vectors: android/app/src/test/resources/target_query_cases.json"
CASES = Path(__file__).resolve().parents[2] / "android" / "app" / "src" / "test" / "resources" / "target_query_cases.json"

# PhraseGrammar.kt / TargetQuery.kt word lists (copied verbatim; the vectors catch drift)
CORRECTIONS = ["no wait", "wait no", "no no", "no sorry", "sorry no", "i mean", "scratch that", "or rather",
               "never mind", "forget it", "cancel that", "nevermind", "no", "wait", "sorry", "actually"]
TAKES_ARG = {"tap", "tab", "click", "press", "hit", "select", "touch", "push", "choose", "pick", "open", "the", "say", "on"}
SOFT_PHRASES = ["you know what", "you know", "kind of", "sort of", "real quick", "if you can", "if you could"]
LEAD_PHRASES = ["would you mind", "do you mind", "can you", "could you", "would you", "will you", "i want you to",
                "i need you to", "i want to", "i wanna", "i need to", "id like to", "i would like to", "lets", "let us", "go ahead and", "try to",
                "help me", "you can", "i said", "all right"]
HESITATION = re.compile(r"^(?:u+h+m*|u+m+|e+r+m*|a+h+|h+m+|m{2,}|e+h+)$")
UNITS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
         "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"}
TENS = {"twenty", "thirty", "forty", "fourty", "fifty", "sixty", "seventy", "eighty", "ninety"}
DETERMINERS = {"the", "a", "an", "this", "that", "these", "those", "my", "your", "his", "her", "their", "our"}
LIKE_OBJECTS = {"button", "icon", "heart", "count", "counter", "thumb", "thumbs", "symbol", "sign"}
LIKE_KEEP_AFTER = DETERMINERS | {"looks", "look", "looked", "looking", "something", "anything", "sounds", "seems", "feels"}
KIND_KEEP = {"what", "which", "any", "some", "every", "this", "that", "same"}
LEAD_WORDS = {"so", "well", "oh", "hey", "and", "just", "also", "alright", "actually", "canti"}
LEAD_GUARDED = {"ok", "okay", "yeah", "yes", "right", "now", "then", "sure"}
TRAIL_ANY = ["thanks", "thank you", "thx", "for me", "i guess", "i think", "or whatever", "or something", "canti"]
TRAIL_COMMA = ["yeah", "yep", "yes", "ok", "okay", "right", "now", "then", "instead", "that one", "this one", "yeah that one", "yes that one"]
ARG_WORDS = TAKES_ARG | {"a", "an", "says", "called", "labelled", "labeled", "or"}
SINGLE_MARKERS = {c for c in CORRECTIONS if " " not in c}
MULTI_MARKERS = sorted([c.split(" ") for c in CORRECTIONS if " " in c], key=len, reverse=True)   # stable, like sortedByDescending
SOFT = sorted([p.split(" ") for p in SOFT_PHRASES], key=len, reverse=True)
DROP_WORDS = {"please", "pls", "kinda", "sorta"}
LEADS = sorted([p.split(" ") for p in LEAD_PHRASES], key=len, reverse=True)
TRAILS = sorted([(p.split(" "), False) for p in TRAIL_ANY] + [(p.split(" "), True) for p in TRAIL_COMMA], key=lambda x: len(x[0]), reverse=True)
TRIM = ",;:-\u2013\u2014"
_JDOUBLE = re.compile(r"^[+-]?(NaN|Infinity|((\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)[fFdD]?)$")


def _lod(c: str) -> bool:
    """Kotlin Char.isLetterOrDigit: Unicode letter (L*) or decimal digit (Nd)."""
    return c.isalpha() or unicodedata.category(c) == "Nd"


def _is_number_word(w: str) -> bool:
    return bool(_JDOUBLE.match(w)) or w in UNITS or w in TENS


class _Tok:
    __slots__ = ("raw", "key")

    def __init__(self, raw: str):
        self.raw = raw
        k = raw.lower().replace("'", "").replace("\u2019", "")
        i, j = 0, len(k)
        while i < j and not _lod(k[i]):
            i += 1
        while j > i and not _lod(k[j - 1]):
            j -= 1
        self.key = k[i:j]

    @property
    def comma(self) -> bool:
        return self.raw.endswith(",") or self.raw.endswith(";")

    @property
    def dash(self) -> bool:
        return self.key == "" and ("\u2014" in self.raw or self.raw.strip(",;:.!?") == "-")


def _keys_at(toks, i, words) -> bool:
    return i + len(words) <= len(toks) and all(toks[i + n].key == words[n] for n in range(len(words)))


def _marker_at(toks, i) -> int:
    for m in MULTI_MARKERS:
        if _keys_at(toks, i, m):
            return len(m)
    tk = toks[i]
    if tk.dash:
        return 1 if 1 <= i < len(toks) - 1 else 0
    prev = toks[i - 1].key if i >= 1 else None
    nxt = toks[i + 1].key if i + 1 < len(toks) else None
    if tk.key in SINGLE_MARKERS and (i >= 1 or tk.comma) and prev not in ARG_WORDS and nxt not in ("thanks", "thank"):
        return 1
    return 0


def _parts(toks):
    out, cur, i = [], [], 0
    while i < len(toks):
        n = _marker_at(toks, i)
        if n > 0:
            out.append(cur)
            cur = []
            i += n
        else:
            cur.append(toks[i])
            i += 1
    out.append(cur)
    return out


def _clean(p):
    n = len(p)
    drop = [False] * n
    for i in range(n):
        k = p[i].key
        if k == "" or HESITATION.match(k) or k in DROP_WORDS or (i < n - 1 and p[i].raw.rstrip(",;").endswith("-")):
            drop[i] = True
    i = 0
    while i < n:
        ph = next((w for w in SOFT if _keys_at(p, i, w)), None)
        prev = p[i - 1].key if i >= 1 else None
        keep = ph is not None and ((ph[0] in ("kind", "sort") and prev in KIND_KEEP) or
                                   (ph[0] == "you" and prev in ("do", "did", "dont", "didnt", "if")))
        if ph is not None and not keep:
            for j in range(i, i + len(ph)):
                drop[j] = True
            i += len(ph)
        else:
            i += 1
    for j in range(n):
        if p[j].key != "like" or drop[j]:
            continue
        prev = p[j - 1] if j >= 1 else None
        nxt = p[j + 1] if j + 1 < n else None
        if nxt is None:
            d = False
        elif p[j].comma:
            d = True
        elif nxt.key in LIKE_OBJECTS:
            d = False
        elif prev is not None and prev.comma:
            d = True
        elif prev is not None and prev.key in LIKE_KEEP_AFTER:
            d = False
        elif prev is not None and (drop[j - 1] or prev.key in LEAD_WORDS or prev.key in LEAD_GUARDED):
            d = True
        elif prev is not None and (nxt.key in DETERMINERS or drop[j + 1]):
            d = True
        else:
            d = False
        drop[j] = d
    lst = [t for j, t in enumerate(p) if not drop[j]]
    while len(lst) > 1:   # lead
        ph = next((w for w in LEADS if _keys_at(lst, 0, w) and len(lst) > len(w)), None)
        if ph is not None:
            lst = lst[len(ph):]
            continue
        k = lst[0].key
        if k in LEAD_WORDS:
            lst = lst[1:]
            continue
        nk = lst[1].key
        if k in LEAD_GUARDED and (lst[0].comma or nk in LEAD_WORDS or nk in LEAD_GUARDED or nk in DETERMINERS):
            lst = lst[1:]
            continue
        break
    while len(lst) > 1:   # tail
        hit = None
        for w, needs_comma in TRAILS:
            if len(lst) <= len(w) or not _keys_at(lst, len(lst) - len(w), w):
                continue
            before = lst[len(lst) - len(w) - 1]
            if (before.comma if needs_comma else (before.key not in ARG_WORDS and before.key != "no")):
                hit = w
                break
        if hit is None:
            break
        lst = lst[:len(lst) - len(hit)]
    changed = True   # repeats
    while changed:
        changed = False
        for g in (3, 2, 1):
            for s in range(0, len(lst) - 2 * g + 1):
                a = [t.key for t in lst[s:s + g]]
                if a != [t.key for t in lst[s + g:s + 2 * g]] or all(_is_number_word(x) for x in a):
                    continue
                lst = lst[:s] + lst[s + g:]
                changed = True
                break
            if changed:
                break
    return lst


def _render(lst) -> str:
    s = " ".join(x for x in (t.raw.strip(TRIM) for t in lst) if x).rstrip(".,;: ")
    return s if any(_lod(c) for c in s) else ""


_WS = re.compile(r"\s+", re.ASCII)
_PUNCT_WS = re.compile(r"\s+([,;:!?.])", re.ASCII)


def normalize(raw: str) -> str:
    """TargetQuery.normalize: "" when nothing is left."""
    t = raw.replace("\u2014", " \u2014 ").replace("\u2013", " \u2014 ").replace("--", " \u2014 ").replace("\u2026", " ")
    t = _PUNCT_WS.sub(r"\1", t)
    toks = [_Tok(x) for x in _WS.split(t) if x]
    for part in reversed(_parts(toks)):
        out = _render(_clean(part))
        if out:
            return out
    return ""


def normalize_phrase(raw: str) -> str:
    """TargetQuery.forPicker: the normalised query, or the trimmed raw text when nothing is left (never empty)."""
    return normalize(raw) or raw.strip()


UTTER = re.compile(r'(spoken target: )"(.*)"\s*$', re.S)


def phrase_of(context: str) -> str:
    m = UTTER.search(context)
    return m.group(2) if m else ""


def with_phrase(context: str, phrase: str) -> str:
    """Replace the utterance in a row context (the state_template puts it last, in double quotes)."""
    m = UTTER.search(context)
    if not m:
        raise ValueError("context has no spoken target line")
    return context[:m.start()] + m.group(1) + '"' + phrase + '"'


# --- perturbations (robustness eval; training augmentation) -----------------------------------------------------------

PRE = ["uh ", "um ", "so um ", "okay uh ", "um, like, ", "uhh can you ", "hmm, ", "so like "]
POST = [" please", " thanks", " or whatever", " you know", " real quick", ""]


def filler(p: str, rng: random.Random) -> str:
    return rng.choice(PRE) + p + rng.choice(POST)


def heavy(p: str, rng: random.Random) -> str:
    w = p.split()
    if len(w) > 2:
        w.insert(rng.randrange(1, len(w)), rng.choice(["uh", "um", "like", "uh, the"]))
    return "um so, uh, " + " ".join(w) + ", yeah that one"


def restart(p: str, rng: random.Random) -> str:
    w = p.split()
    if len(w) < 2:
        return "the- " + p
    return w[0] + " " + w[0] + "- uh, " + p


PERTURB = {"orig": lambda p, rng: p, "filler": filler, "heavy": heavy, "restart": restart}


def transform(name: str):
    """'filler', 'heavy+norm', 'norm', 'orig' ... -> f(phrase, rng)."""
    base, _, post = name.partition("+")
    if base == "norm":
        return lambda p, rng: normalize_phrase(p)
    f = PERTURB[base]
    if post == "norm":
        return lambda p, rng: normalize_phrase(f(p, rng))
    return f


def check_vectors(path: Path = CASES) -> list:
    cases = json.loads(path.read_text())["cases"]
    bad = [(r, normalize(r), e) for r, e in cases if normalize(r) != e]
    bad += [(r, "not idempotent", normalize(normalize(r))) for r, e in cases if e and normalize(e) != e]
    return cases, bad


if __name__ == "__main__":
    cases, bad = check_vectors()
    print(json.dumps({"spec": SPEC_VERSION, "cases": len(cases), "failures": bad}, indent=1, ensure_ascii=False))
    raise SystemExit(1 if bad else 0)
