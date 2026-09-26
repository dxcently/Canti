# Canti brand

The app is named after Canti, the robot from *FLCL* ("canti" is also Italian for songs). The colours come from the character; the lettering is **original**, drawn to echo the FLCL logo's style without copying it. Don't use FLCL's logo or character art in the app.

| File | Use |
|---|---|
| [`canti-wordmark.svg`](canti-wordmark.svg) | Colour wordmark: teal letters, ink outline, hard navy shadow, cel shading, orange bar in the A |
| [`canti-wordmark-mono.svg`](canti-wordmark-mono.svg) | One-colour wordmark, for small sizes and print. Use mint cream on dark backgrounds |
| [`canti-icon.svg`](canti-icon.svg) | App icon: an original robot head inspired by Canti (not a likeness), peeking in from the lower-left corner of a charcoal square. Teal head, navy screen with a glare and no face, orange antenna light |
| [`canti-icon-waves.svg`](canti-icon-waves.svg) | Previous app icon, kept as an alternative: teal body, navy visor, the C sending out sound waves |

The app icon is full-bleed with square corners, because Android masks launcher icons itself. It deliberately drops the ink outlines listed under Shape language, to keep the flat, minimal peeking style. The waves icon keeps them.

The subtitle `[ HUM · CLICK · SWIPE ]` is live text, using Futura or a fallback. Convert it to outlines before any print use.

## Colours

| Token | Hex | From Canti | Use |
|---|---|---|---|
| `teal` | `#6DB8A8` | body | primary surfaces, buttons |
| `teal-shade` | `#4A9488` | body shadow | cel shading, pressed state, the lower band of cards |
| `mint-cream` | `#DDEBD3` | chest panels | light background, text on dark, glints |
| `visor-navy` | `#1D2757` | face screen | dark surfaces, hard shadows, the "screen" areas |
| `screen-glow` | `#7FE0C9` | what the visor shows | live values on navy, focus rings |
| `slate` | `#3C4C7E` | hands | secondary dark, disabled |
| `signal-orange` | `#F2A33A` | shoulder and hip lights | **active / listening** |
| `signal-yellow` | `#F6C945` | lights | pending, waiting for a follow-up sound |
| `signal-red` | `#D6453D` | waist trim | **stop**, errors |
| `ink` | `#16192B` | line art | outlines, body text |

The signal colours carry meaning; don't use them for decoration. Orange means listening, yellow means waiting, red means stop.

## Shape language: cartoonishly edged

- **Uneven corners.** Big radius on the leading corner (top-left) and on its diagonal opposite; a small radius or a square cut on the others. It's the wordmark's rule (rounded where a stroke turns, square where it ends) and the icon's visor.
- **Thick ink outlines.** 2–3 dp on cards, buttons and chips, in `ink`. Outlines, not elevation, separate things.
- **Hard shadows, no blur.** Offset 3–4 dp down and right, in `visor-navy`. A pressed button drops onto its shadow: move it by the offset and hide the shadow.
- **Cel shading.** A flat `teal-shade` band on the bottom third of large teal surfaces, and short `mint-cream` glint strokes near a top-left corner. Never gradients.
- **Screens.** Live data (the current sound, the decision, the confidence) sits on a `visor-navy` panel in `screen-glow` text, like Canti's face.
- **Detached pieces.** The A's floating bar is the motif: status lights and small indicators sit on their own with a gap, not attached to their parent.
