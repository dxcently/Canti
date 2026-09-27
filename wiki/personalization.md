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
| **Re-recorded gesture** (your own way of doing rise, arch, pop, …) | that gesture | the normal gesture line, now trusted (relabelled when the extractor heard another gesture) | its normal binding |

Built-in negatives with no enrollment: `sounds like yelling`. It is set by a generic brightness cue (open-mouth voiced energy above 1 kHz) that is being validated across speakers. Pitch ranges are *not* used as a gate, because voices differ too much.

## Gesture training (on the phone)

Decided with the user on 2026-09-27: "There should be calibration for all gestures with variations." Built as a **Train gestures** screen, separate from the voice cursor's 25 s setup (status screen, window "Train gestures"; protocol: `android/PROTOCOL.md` "Gesture training").

- **One card per gesture**, each with its progress (e.g. 5/8). A card records only its missing takes, one prompt at a time, and can be stopped at any point: every accepted take is stored at once. **Delete / redo** clears a card.
- **Variations.** Rise, fall, arch and dip: hummed or whistled × starting low or high × slow (about 1.5 s) or quick (about 0.5 s), 8 takes. Flat: hum or whistle × low or high note × short or long, 8 takes. Pop, click and hiss: soft and loud, 2 takes each, 4 takes. 52 takes per mic.
- **Checks per take.** One sound; the extractor's label must be the prompted gesture; for contours the tone (whistle = median pitch 600 Hz or higher, the extractor's own whistle line) and the speed must match. Start pitch and loudness are recorded but not checked, since neither has a fixed reference. A failed take **stops, shows why** ("Heard a dip (down then up): an arch goes up then down.") **and waits for Retry or Skip**, the rule for every setup step. When only the shape was wrong, **Keep anyway** stores it as the prompted gesture; that choice is logged, because it is how the store learns a user's own version.
- **What you see.** The prompt names the cell ("Whistle a QUICK rise, starting LOW"); a live pitch trace while recording on the phone or USB mic (the Pico sends no live ticks, so its take's shape is shown afterwards); after each take, what Canti heard: shape, tone and pitch, start note, length.
- **Per mic.** Each mic source (phone, USB, Canti device) has its own enrollment store, since fingerprints differ between mics, and matching uses the current source's. A store from before this change becomes the store of the source that was current when it was first loaded. The phone and USB mic run the same C++ extractor as the Pico (`vx_json_features`), so their sounds already carried the fingerprint and pitch track.
- **What it changes.** From 3 takes on, a trained gesture takes part in matching on its mic. When a sound matches it (within the class's reject threshold, plus the pitch-track DTW test for a contour) and the extractor labelled it as something else, the line becomes that gesture's normal line, keeping what the extractor measured (duration, tone, loudness). Example: the extractor heard a dip, your trained arch matches, so Canti acts on an arch. When both agree the line is kept and logged as trusted. Custom and ignore sounds keep their precedence (the nearest class decides). The setting `enroll_gesture_relabel` (default on) turns relabelling off. A sound the phone mic's media gate or media-hiss rule turned into `unknown` on purpose (the message's `gated` flag) is never relabelled, so a trained pop or click cannot undo those guards while a video plays.

## Fingerprint (message field `fp`, version `fp1`)

- About 24 numbers per sound, computed on the Pico after the sound ends: f0 statistics, brightness (E1k, E3.5), harmonicity, duration and a few log-mel band means. The exact contents come from the real-audio evaluation of which cues separate sounds across speakers.
- The message also carries a **16-point pitch track** (semitones relative to the start; empty for unpitched sounds), for DTW matching of re-recorded contours.
- **Matching:** standardise by the user's enrollment statistics, then nearest-neighbour on `fp` (plus banded DTW on the pitch track for contour classes). A **reject threshold** applies: a sound matches a class only if it is closer than the largest distance within that class's examples × 1.3–1.5. Otherwise the extractor's own line is kept.

## Model side (training data v6)

- A new line kind is added for `my sound "<name>"`, with names drawn from a bank (held-out names in the tests). It is bound to actions by rules like "when I make my {name} sound, …". Unbound means none.
- New sounds_like values: `yelling` and `one of my ignore sounds`. Both mean none.
- The extractor's real out-of-distribution lines (long non-gesture hums, short voiced blips, …) are added, along with the deferred play/pause words and a harder unseen-phrasing test.

## Open questions

- Can the joystick's one-time setup (range, voicing, pops) tune the gesture extractor per person? Desktop answer, 2026-09-27: not on current data. All candidate `vx_config` overrides are NO-GO, and the misses it saw (inverted arches and dips, long-tailed pops, low-centroid clicks) look like enrollment problems. See [Calibration vs gesture labels](calibration-gestures.md).
- How many enrollment examples are needed before false accepts on the negative datasets become acceptable?
- Fingerprint stability across mics, since the Pico's MEMS mic differs from a USB headset. Enrolling on the device you use is the safe default, and the stores are now kept per mic source.
