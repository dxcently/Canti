# Personalization: your voice changes what the line says

**Summary.** The decision model (Jev or the VOX student) only reads the text line the extractor writes. If a meow and a hum produce the same line, no amount of model training can tell them apart. So personalization happens *before* the model, on the phone. The Pico sends a small **sound fingerprint** with every sound. The app matches it against **your own recorded examples** and rewrites the line. The model then sees `my sound "meow"` or `sounds like yelling` and acts on your rules. Agreed with the user on 2026-09-26.

## Why not on the Pico, and why not by retraining Jev

- **Phone (chosen).** Examples, matching and thresholds live in the app. Re-enrolling is just recording again, with no re-flash. The phone has memory and compute to spare, and a user can carry several profiles.
- **Pico.** It would work without the app, but its flash and RAM are tight, and enrolling would still need a link to copy examples over.
- **Retraining the model on your voice.** This only helps once the lines already differ, so it comes after, not instead.

## What gets enrolled

| You record | 3–5 examples of | Matching sounds become | Default action |
|---|---|---|---|
| **Custom sound** (any sound you invent: meow, kiss, trill, two-note whistle, …) and give it a name | that sound | `my sound "<name>"` | none, until a rule binds it ("when I meow, open the camera") |
| **Ignore sound** (your sneeze, laugh, a cat, the kettle, …) | that sound | `sounds like one of my ignore sounds` | always none |
| **Re-recorded gesture** (your own way of doing rise, arch, pop, …) | that gesture | the normal gesture line, now trusted | its normal binding |

Built-in negatives with no enrollment: `sounds like yelling`. It is set by a generic brightness cue (open-mouth voiced energy above 1 kHz) that is being validated across speakers. Pitch ranges are *not* used as a gate, because voices differ too much.

## Fingerprint (message field `fp`, version `fp1`)

- About 24 numbers per sound, computed on the Pico after the sound ends: f0 statistics, brightness (E1k, E3.5), harmonicity, duration and a few log-mel band means. The exact contents come from the real-audio evaluation of which cues separate sounds across speakers.
- The message also carries a **16-point pitch track** (semitones relative to the start; empty for unpitched sounds), for DTW matching of re-recorded contours.
- **Matching:** standardise by the user's enrollment statistics, then nearest-neighbour on `fp` (plus banded DTW on the pitch track for contour classes). A **reject threshold** applies: a sound matches a class only if it is closer than the largest distance within that class's examples × 1.3–1.5. Otherwise the extractor's own line is kept.

## Model side (training data v6)

- A new line kind is added for `my sound "<name>"`, with names drawn from a bank (held-out names in the tests). It is bound to actions by rules like "when I make my {name} sound, …". Unbound means none.
- New sounds_like values: `yelling` and `one of my ignore sounds`. Both mean none.
- The extractor's real out-of-distribution lines (long non-gesture hums, short voiced blips, …) are added, along with the deferred play/pause words and a harder unseen-phrasing test.

## Open questions

- How many enrollment examples are needed before false accepts on the negative datasets become acceptable?
- Fingerprint stability across mics, since the Pico's MEMS mic differs from a USB headset. Enrolling on the device you use is the safe default.
