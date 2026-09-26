# AMBIGUITY — wordings a human should eyeball

Scope: entries in `bank.json` that I could not defend as mapping to exactly one action (or one contour).
Everything else I judged unambiguous. Nothing here breaks `validate.py`; the file is for review, not a failure list.

Reading the "could also be" column: that is the *other* option a student could reasonably pick if the rule
sentence is the only context it has.

## Actions

| wording | filed under | could also be read as | why it is thin |
|---|---|---|---|
| swipe the content upward | swipe_up | next_item | in a vertical feed an upward swipe *is* how you get the next video |
| slide the page up with your finger | swipe_up | next_item, scroll_up | "page" moves either way; size of move unstated |
| sweep a finger up the page | swipe_up | scroll_up | no distance given |
| swipe downwards from the top edge | swipe_down | notifications | the top edge is where the shade lives |
| pull the screen downward with your fingertip | swipe_down | notifications | pull-down is the shade gesture |
| creep up a little | scroll_up | swipe_up | smallness is the only thing separating the two |
| drift up a bit | scroll_up | swipe_up | same |
| nudge up slightly | scroll_up | swipe_up | same |
| creep down a little | scroll_down | swipe_down | same |
| drift down a bit | scroll_down | swipe_down | same |
| nudge down slightly | scroll_down | swipe_down | same |
| step back | back | previous_item | reads as one item back, not one screen back |
| go back a step | back | previous_item | same |
| take a step back through the app | back | previous_item | "through the app" argues for back, but "step" does not |
| flip back a screen | back | previous_item | "flip" is also page-turn language |
| the last video I saw | previous_item | next_item | "last" can mean final in the list, not most recent |
| the thing I just watched | previous_item | next_item | could be the item still on screen |
| the item I just passed | previous_item | swipe_up, next_item | "passed" is directional only in a feed |
| the gesture you'd do to see the next video | next_item | swipe_up | the brief's own example of a descriptive wording; it names the intent, and in a feed the gesture for that intent is a swipe up |
| the next page of the document | next_item | back | "page" is both a document page and a navigation screen |
| the following page | next_item | back | same |
| open the top drawer | notifications | swipe_down | "drawer" + "top" is the shade, but the motion is a swipe down |
| pull the shade down | notifications | swipe_down | same |
| slide the notifications down | notifications | swipe_down | same |
| the shade at the top of the screen | notifications | swipe_down | names the target, not the motion |
| open the notification bar | notifications | swipe_down | "bar" could be read as the status bar |
| tap the surface | tap | long_press | surface is vague; only "tap" carries the shortness |
| one quick touch | tap | double_tap | "quick" without a count |
| love the post | like | none | some apps treat love as a reaction distinct from like |
| show the creator some love | like | none | same |
| show some love to the post | like | none | same |
| snap it | take_photo | none | "snap" is also a generic "grab" |
| snap the shot | take_photo | none | "shot" could be a screenshot, which is not an option |
| get the shot | take_photo | none | same |
| kill the volume | volume_down | none | implies mute; no mute action exists, so down is the only sensible landing |
| hush the audio | volume_down | none | same |
| turn on pointing | enter_cursor_mode | none | "pointing" is thin; the cursor reading is the only one that maps to an option |
| make the map bigger | zoom_in | none | app-specific (Maps) sitting in a global-meaning list |
| make the map smaller | zoom_out | none | same |
| have the mic ready to listen | listen_for_phrase | none | could be read as the phone passively listening, i.e. no command |
| wait for speech | listen_for_phrase | none | same |
| the mic should be listening | listen_for_phrase | none | same |
| wait for me to say something | listen_for_phrase | none | same |

## Gestures (contour vs contour, or gesture vs speech)

| wording | filed under | could also be read as | why it is thin |
|---|---|---|---|
| a hum that swells in pitch and returns | arch | arch with loudness swell | "swell" is often amplitude, not pitch |
| a hum that takes off and comes back | arch | arch | "takes off" does not say which way |
| a hum with a hump in the middle | arch | arch | "hump" is informal; the direction is implicit |
| a hum that dives and comes back | dip | dip | same shape, unstated depth |
| a dipped hum | dip | dip | terse to the point of vagueness |
| a hum shaped like a valley | dip | dip | relies on the valley/hill metaphor |
| a humming drone on one note | flat | flat | "drone" can imply a long held sound of any contour |
| a hum that keeps flat | flat | flat | "flat" also has a musical (off-pitch) reading |
| a lip smack | pop | pop, click | a smack is a louder, pursed sound than a clean pop |
| a smack of the lips | pop | pop, click | same |
| a tsk sound | click | click, none | tsk can be a whole-mouth disapproval sound, not a tongue click |
| a tut sound | click | click, none | same |
| a clucking sound | click | click | cluck is chicken-like in some readings |
| a tutting sound | click | click, none | same |
| a cluck of the tongue | click | click | same |
| a shhh sound | hiss | listen_for_phrase | a shhh is often deliberate speech (shushing), not a breath hiss |
| a sibilant hiss | hiss | hiss | jargon; the lay reader may not know the word |
| a hiss of air | hiss | none | could be ambient air, not a made gesture |

## Deliberate omissions (asked for by the brief, not included)

| phrase | why it is out |
|---|---|
| "nuke the volume" | the brief's slangy example, but its direction is a coin flip between volume_up and volume_down |
| "go back" / "go back one item" for previous_item | the brief bars it; previous_item here never uses "back" |
| "mute it" | no mute action exists; it would sit between volume_down and none |
| "go to the next item" family for swipe_up | would make swipe_up and next_item lexical twins |

## Residual risks I could not close inside the scope

- Three wordings coincide exactly with `schema.PHRASES` values: `turn it down` (volume_down), `snap a photo`
  (take_photo), `heart it` (like). `PHRASES` is the spoken-phrase module's vocabulary, not `wordings.py`, so
  `validate.py` passes and I left them in — they are too natural to drop. `validate.py --info` lists them.
- Held-out wordings live in `generate.py`, which the brief forbids opening. Overlap between this bank and the
  held-out set is therefore **unverified by construction**, not verified clean.
- `wordings.py` contains the phrase-level strings "volume down", "volume up" and "take a picture"; this bank
  avoids all three, and avoids `check_disjoint`'s exact-match rule by construction.
