# Gestures and phrases: seven defaults, re-recordable, bound per app

[Index](index.md) · [Hardware](hardware.md) · [Signal processing](signal-processing.md) · [Gestures and phrases](gesture-vocabulary.md) · [Decision models](decision-models.md) · [Phone control](phone-control.md) · [Prior art](prior-art.md) · [Latency and risks](latency-and-risks.md) · [Roadmap](roadmap.md) · [Sources](sources.md)

**Summary.** VOX ships seven default hum, pop and hiss gestures (a single pop always fires at once, because no default phrase starts with a pop), measured in semitones relative to each hum's start. Each can be re-recorded with 3–5 examples and matched by banded DTW with a reject threshold. Gestures combine into **sound phrases**, which are bound to actions in a **global profile plus per-app overrides**. A binding is either **fixed** (resolved locally) or a **plain-language rule** (resolved by Jev or the VOX student). Spoken phrases are an opt-in extra ([Phone control](phone-control.md#spoken-phrases-opt-in-module)).

## Default gestures

Contours are 12·log2(f/f_start). Absolute pitch lost to relative pitch in the prior art ([Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)).

| Gesture | Acoustic definition (starting values) | Default action | Phase 1 HID mapping |
|---|---|---|---|
| **Rise** | Tonal, end ≥ +4 st above start, 250–1000 ms | Swipe up | Button-drag up; on iOS a Switch Control key → recipe |
| **Fall** | ≤ −4 st | Swipe down | Button-drag down |
| **Arch** | Peak ≥ +4 st above both ends | Swipe right | Button-drag right |
| **Dip** | Trough ≤ −4 st below both ends | Swipe left | Button-drag left |
| **Pop** | Flux spike, low clarity, short. Fires immediately: nothing in the default profile starts with a pop | Tap | Button-1 click |
| **Hiss** | Unvoiced broadband noise, no pitch, 150–1000 ms. A steady hiss over ~1 s, or one flagged as background noise, is rejected (fans, air conditioning, traffic) | Back | Consumer key 0x224 ([Generic.kl](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/data/keyboards/Generic.kl)) |
| **Long flat hum** | Excursion < ~2 st, longer than ~800 ms, audible tick at threshold | Long-press / hold | Hold button 1 |
| **Device button** (not a sound) | Tactile button on a GPIO, plus a 3.5 mm mono jack so any assistive switch (head, foot, elbow) works the same | Press: cursor mode on/off. Hold: disarm / emergency stop (the Pico stops sending) | Same |

**Decided 2026-09-26:**
- Cursor mode and disarm live on the button or switch, not a sound. A sound can't reliably stop the thing that's misreading sounds.
- Back moved from pop-pop to **hiss**, so taps have no wait.
- **Pop-pop and click-click are unbound by default.** Users can bind them per app. The phone waits for a follow-up sound only when the active profile binds a sequence that starts with the sound just heard.
- Click-pop stays "listen for a spoken phrase".
- Sequences are grouped on the phone using the Pico's per-sound timestamps, not arrival time, so Bluetooth jitter can't split or merge a sequence.

The audible tick copies Sporka's fix for short/long confusion ("a short soft click") ([Sporka et al., ASSETS'06](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-sigaccess-nsi-paper.pdf)).

**About "move down on a low tone".** Mapping an absolute low note to a direction is the melodic scheme that lost: 2.6 s vs 1.4 s per target, and every user overshot ([Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)). Humming users also had to re-pick their threshold pitch every day ([Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)). The idea survives only in relative form, as "fall" and cursor mode's "below start = down".

## The speech gate

Every event must pass all of these checks before any matcher runs. The stack follows Parrot.py's patterns ([Parrot.py PATTERNS.md](https://raw.githubusercontent.com/chaosparrot/parrot.py/master/docs/PATTERNS.md)):

| Check | Starting value | Rationale |
|---|---|---|
| Loudness | Above tracked floor + 6–10 dB | Parrot `power` |
| Clarity (MPM) | ≥ ~0.8 for hums [EST] | Tonal, not noisy ([McLeod & Wyvill](https://www.cs.otago.ac.nz/graphics/Geoff/tartini/papers/A_Smarter_Way_to_Find_Pitch.pdf)) |
| Consecutive frames | 4 (≈ 65 ms detection) | Parrot `times` |
| Pitch excursion | ≥ ~4 semitones | Twice Sporka's 2-st threshold ([ASSETS'06](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-sigaccess-nsi-paper.pdf)), to reject speech intonation (unmeasured) |
| Duration | 250–1000 ms | Excludes syllables and long speech |
| Cooldown | ~300 ms | Parrot `throttle` |

## Re-recording by banded DTW

- Each gesture stores **3–5 examples** as 64-point semitone contours.
- Matching uses **DTW with a Sakoe-Chiba band of about ±8**.
- Borrow from the $1 recognizer, but **without rotation invariance**, since rise and fall differ only by rotation [design].
- The cost is about 0.1–0.3 ms per event, and templates take about 8 KB in int8 [EST].
- For the **reject threshold**, start at the largest distance between a class's enrolment examples × 1.3–1.5 [design].
- A rejected event goes to the model in Design A, or to `none` ([Decision models](decision-models.md)).

This prototype-plus-open-set-rejection pattern matches the few-shot keyword-spotting literature ([arXiv 2306.02161](https://arxiv.org/pdf/2306.02161)).

## Sound phrases

A **phrase** is a sequence of recognised gestures with gaps of up to about **600 ms** [starting value], such as rise-rise or pop-hum-fall. It can also be a whole pattern the user records as a template. Phrases bind to actions from a fixed **action catalogue**:

- Swipes in four directions, tap, long-press.
- Back, Home, Recents, Notifications (`performGlobalAction`).
- Scroll page; pinch in and out (two strokes in one `GestureDescription`, which allows up to 20 ([GestureDescription.java](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/core/java/android/accessibilityservice/GestureDescription.java))).
- Media keys.
- Grid mode, recentre. (Cursor mode on/off is the button or switch only, never a sound, so a misheard sound can't change modes.)

**The prefix cost.** A gesture that is also the prefix of a longer phrase cannot fire until the gap window expires. It is why Back moved off pop-pop: a single pop would otherwise wait out the pop-pop window (about 300–400 ms) before it became a tap. The profile editor should:

1. Compile each profile's bindings into a **prefix tree** (trie).
2. **Warn at binding time** when a new phrase delays an existing binding, and show the added delay.
3. Cap phrases at about **three elements** [design].

## Profiles: global plus per-app, fixed or rule

The foreground app is the package name the AccessibilityService reads from `TYPE_WINDOW_STATE_CHANGED` events ([AccessibilityEvent](https://developer.android.com/reference/android/view/accessibility/AccessibilityEvent)).

| Binding kind | Example | Resolved by | Latency |
|---|---|---|---|
| **Fixed** | rise → swipe up; pop-pop → back | Local lookup | microseconds |
| **Rule** | "In Maps, rise means zoom in" | Jev or the VOX student, reading the rule from state ([Decision models](decision-models.md)) | ~250–440 ms (Jev) the first time, then cached per (app, phrase, rule version) |

**Resolution order:** per-app fixed → per-app rule → global fixed → global rule → none.

```json
{
  "global": [
    {"phrase": ["rise"], "kind": "fixed", "action": "swipe_up"},
    {"phrase": ["pop", "pop"], "kind": "fixed", "action": "back"},
    {"phrase": ["rise", "rise"], "kind": "fixed", "action": "notifications"}
  ],
  "app:tiktok": [
    {"phrase": ["pop"], "kind": "fixed", "action": "tap_center"}
  ],
  "app:maps": [
    {"phrase": ["rise"], "kind": "rule", "rule": "In Maps, rise means zoom in and fall means zoom out"}
  ],
  "app:reader": [
    {"phrase": ["arch"], "kind": "rule", "rule": "Arch turns to the next page; dip goes back a page"},
    {"phrase": ["pop", "long_hum", "fall"], "kind": "fixed", "action": "cursor_mode_toggle"}
  ]
}
```

In Phase 1 (HID only), fixed phrases can be compiled on the Pico into keys or mouse actions, but per-app profiles need the Android app because the Pico can't see the foreground app.

## Open questions / to verify on hardware

- **Resolved:** arm/disarm and cursor mode are on the button or switch jack; long flat hum = long-press; the tap delay is gone because Back is on hiss.
- **Hiss false triggers.** Measure how often fans, AC, breath and sibilant speech ("s", "sh") pass the hiss detector. Back is fairly safe to misfire, but it still costs a screen.
- Is the **4-semitone** excursion floor too high for some users, or too low to reject expressive speech? Measure on negatives.
- Does the **600 ms phrase gap** suit users with slower breath control? It should be adjustable per user.
- The default vocabulary **cannot target** a specific point on screen. That is the job of [cursor mode](decision-models.md#jev-cursor-mode-is-design-b-applied-to-pointing).
- Test the DTW reject threshold multiplier (1.3–1.5) against false accepts on speech negatives.
