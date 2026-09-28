# Canti brand

The app is named after Canti, the robot from *FLCL* ("canti" is also Italian for songs). The colours come from the character; the lettering is **original**, drawn to echo the FLCL logo's style without copying it. Don't use FLCL's logo or character art in the app.

| File | Use |
|---|---|
| [`canti-wordmark.svg`](canti-wordmark.svg) | **Primary wordmark.** One colour, `ink` on transparent. Heavy strokes, big rounded corners where a stroke turns, square cuts where it stops. The letters interlock with an even gap: the C's top arm runs over the A's rounded shoulder, and the small-cap n sits under the T's bar. The A's bar floats |
| [`canti-wordmark-light.svg`](canti-wordmark-light.svg) | The same wordmark in `mint-cream`, for dark backgrounds |
| [`canti-wordmark-color.svg`](canti-wordmark-color.svg) | Stylised colour wordmark to match the app icon, for light backgrounds. Same letters, top-lit `teal` fading to deeper teal, a darker teal underside under each letter like the helmet brim, `ink` outline, a `signal-yellow` trim line on the C, the A's bar lit as the orange lamp. Subtitle in `ink` |
| [`canti-wordmark-color-dark.svg`](canti-wordmark-color-dark.svg) | The same colour wordmark for dark backgrounds (`#1E1F24`), with the subtitle in `mint-cream` |
| [`canti-icon.svg`](canti-icon.svg) | **App icon, on state (default).** An original robot head inspired by Canti (not a likeness): a teal helmet with a brim and gold trim over a squared navy screen, two lit scanline eyes, a soft lens shine under the brim, and the orange lamp lit. Shown while the device is paired and connected, and as the default |
| [`canti-icon-off.svg`](canti-icon-off.svg) | **App icon, off state.** The same head with the eyes dark and the lamp unlit. The app switches to it (activity-alias) only when the pairing/connection state changes |
| [`canti-icon-stipple.svg`](canti-icon-stipple.svg) | **Stipple app icon, on state.** The same design as `canti-icon.svg` as pixel art (see Stipple below): every edge, line and highlight on a 4-unit grid, the shading as ordered-dither dots, the eyes as pixel crescents with scanline rows, the lamp a pixel disc with a dotted halo. Only squares. The app's launcher icons and in-app icon are made from it |
| [`canti-icon-stipple-off.svg`](canti-icon-stipple-off.svg) | The stipple icon, off state: eyes dark, lamp unlit, no halo |
| [`canti-wordmark-stipple.svg`](canti-wordmark-stipple.svg) | **Stipple wordmark.** `canti-wordmark.svg`'s letters, `ink` on transparent: solid tops that fall off into a regular dot grid toward the baseline, a little ink crumbling off the undersides of the top strokes (a few sparse rows), dithered pillars dissolving below the baseline. The A's bar and the subtitle stay solid. Reads from 160 px wide |
| [`canti-wordmark-stipple-light.svg`](canti-wordmark-stipple-light.svg) | The stipple wordmark in `mint-cream`, for dark backgrounds |
| [`tools/stipple.py`](tools/stipple.py) | Generates the four stipple files, the Android launcher layers (`../android/app/src/main/res`) and the app's pixel PNGs (`../ui/assets/brand`, one per whole-pixel scale) |
| [`old/`](old/) | Retired designs: the first colour wordmark and its one-colour twin, the peeking-robot icon, and the sound-waves icon |

The app shows the stipple wordmark and the stipple icon (below, "Stipple"), drawn as pixel-exact PNGs. The solid
one-colour wordmark is the master letterform and the one for print; use `canti-wordmark-light.svg` on dark
backgrounds. The colour wordmark is for places that show the soft-shaded icon's look, such as a store banner. It uses
gradients and blur, so use the one-colour files for print and small sizes.

`canti-icon.svg` is the soft-shaded master icon: full-bleed with square corners, because Android masks launcher icons
itself, with the lamp and eyes inside the area every launcher mask keeps. Shines are soft lens highlights that follow
the surface's curve, never star sparkles. The launcher icons and the in-app icon are its stipple version, as raster
layers made by `tools/stipple.py` (the original's blur, masks and clips aren't expressible as Android vector
drawables).

The subtitle `[ HUM · SING · SWIPE ]` is drawn as paths like the rest of the wordmark: geometric capitals with wide tracking between square brackets. There's no text and no font dependency, so the files work as they are for print.

## Colours

| Token | Hex | From Canti | Use |
|---|---|---|---|
| `teal` | `#6DB8A8` | body | the icon's helmet and body |
| `teal-shade` | `#4A9488` | body shadow | the icon's shading (dithered against `teal`) |
| `mint-cream` | `#DDEBD3` | chest panels | the app's paper in light, its ink in dark; the light wordmark |
| `visor-navy` | `#1D2757` | face screen | the app's ink in light, its paper in dark; the icon's screen |
| `screen-glow` | `#7FE0C9` | what the visor shows | the icon's lit eyes and the shine under the brim |
| `slate` | `#3C4C7E` | hands | the lighter tone dithered into the icon's screen |
| `signal-orange` | `#F2A33A` | shoulder and hip lights | **active / listening** |
| `signal-yellow` | `#F6C945` | lights | pending, waiting for a follow-up sound |
| `signal-red` | `#D6453D` | waist trim | **stop**, errors |
| `ink` | `#16192B` | line art | the wordmark on light backgrounds, the icon's darkest screen tone |

The signal colours carry meaning; don't use them for decoration. Orange means listening, yellow means waiting, red means stop.

## Shape language: a 1-bit pixel kit

The app is drawn like a 1-bit RPG screen, in the brand's two darkest and lightest tones and on the same kind of pixel
grid as the stipple art. The code is `../ui/lib/src/theme` (`../ui/README.md` "Look").

- **Two tones.** Each surface is ink on paper: `visor-navy` on `mint-cream`, swapped in dark. No greys, tints,
  gradients, blur or shadows; a shade is a density of ink dots (ordered dither, as in the stipple art). Colour is
  kept for the brand art and the status lamp, where it means something (above, "Colours").
- **One pixel grid.** Everything sits on whole *art pixels*, each a whole number of device pixels (about 2 dp). Lines
  are one art pixel, gaps and paddings are whole pixels, and nothing is scaled by a fraction or smoothed. Brand
  PNGs are drawn at a whole number of device pixels per dot, the wordmark at one dot per art pixel.
- **Frames, not elevation.** Windows have a double-line frame with notched (clipped) corners and a title tab in
  capitals on the top edge. Live data sits on inverted panels (ink fill, paper text), like the "screen" of Canti's
  face. Buttons are square framed boxes, a double frame for the main action.
- **State by inversion and pattern.** Pressed and selected invert (paper on ink); disabled is a dotted frame; focus
  and hover are corner brackets around the target; empty areas are a diagonal hatch.
- **Dither for mood.** Behind the windows is a one-colour dot field after FLCL's isometric pixel art: a 50% checker
  along the top that thins out downward, and a row of EQ bars along the bottom: calm ticks when idle, dithered
  level bars while Canti hears, and nothing (the top field thinned out) when it is off or paused. Where text or the logo
  sits on it, the field opens a *clearing*, never a plate: within a few pixels of the ink (its own shape, dilated)
  the dots stop, and over the next few they come back in the same ordered dither, whole dots on the field's grid.
  The field also clears under the phone's status and navigation bars and fades in below them.
- **Pixel type.** Press Start 2P (capitals: titles, labels, buttons) and Tiny5 (lowercase body text), only at whole
  multiples of their 8-pixel em.
- **Square cuts, rounded turns.** The letterforms keep the wordmark's rule: rounded where a stroke turns, square where
  it stops, and the A's bar floating free.
- **Motion without fades.** Two tones allow no fades: things switch on like a pixel screen (off, on, off, on, in whole
  steps).

## Stipple (pixel art) versions

The `*-stipple*` files, the launcher icons and the app's brand PNGs are pixel art made by
[`tools/stipple.py`](tools/stipple.py) from the originals. The rules:

- **One grid, whole cells.** Everything is square cells on one grid anchored at the artwork's origin. Nothing is a
  curve or anti-aliased edge: a shape is the cells it covers more than half of (tested by supersampling), a line is a
  one-cell contour of a shape (so it is the same thickness everywhere), and a highlight too small for that keeps its
  best-covered cell. The exception is the wordmark: its solid tops are the letters themselves, and dots at a letter's
  edge are clipped to it, so its outlines stay the letterform's curves.
- **Two pitches.** The icon's stipple dots are 8 units (512 = the icon's width); edges, the eyes, the trim, the lamp
  and the shine's core are on the 4-unit sub-grid (half a dot, so a dot is exactly 2 x 2 cells). The wordmark's cell is
  4 units (its viewBox starts at -10, and cells start at -10 + 4k).
- **Ordered dither, never random.** A 4x4 Bayer matrix, threshold `(B + 0.5) / 16`, for surfaces, glows and the
  wordmark's pillars; an 8x8 Bayer (the 4x4 one, recursively) plus a fixed seeded whole-cell offset per column for the
  wordmark's staggered holes and crumble, so they don't line up like a ruler.
- **Tones.** Each icon surface keeps its flat base colour and dithers toward at most one darker and one lighter tone
  (2-3 tones): body and brim `teal-shade` / `teal` / `#8FCBBE`, lip `#3F877B` / `teal-shade` / `teal`, glass `ink` /
  `visor-navy` / `slate`, brim underside and crown `#3F877B` / `teal-shade`. Where the dots go comes from the
  original icon's shading (each cell's mean brightness against the surface's median, with a dead zone that stays
  flat: cartoon shading, flat areas with dithered transitions). Glows are posterised rings of dots in their own colour
  (the lamp's halo `#C9C470`), never a scatter.
- **Kept from the originals.** The eyes are rounded crescents (a domed top over an underside that arches up in the
  middle, round tips) with lit/dim scanline rows, at the original size, spacing and 5 degree inward tilt; on, a
  one-cell dim halo hugs them. The shine stays a soft lens (stepped cores over dithered falloff), never a star. The
  gold trim is one cell of gold over one cell of teal along the brim's edge.
- **Rasters are pixel-exact.** A PNG is rendered straight from the cell grid at a size where a dot is a whole number of
  device pixels, with no resampling. Launcher layers (108 dp, the icon's 512 units being the 72 dp in the middle, so the
  canvas is -128..640): dots of 1 / 2 / 2 / 3 / 4 px at mdpi / hdpi / xhdpi / xxhdpi / xxxhdpi, and a fine grid of
  half a dot where that is a whole pixel (1 px, except 2 px at xxxhdpi). The app's PNGs are one per whole-pixel
  scale, `name@n.png`: the icon 48 dots across with dots of n = 1-4 px, the wordmark 89 x 41 cells with cells of
  k = 1-8 px (its viewBox made 164 units tall, 41 whole cells, and rendered at exactly 89k x 41k px, so every cell
  lands on whole pixels). The app uses n = round(devicePixelRatio) for the icon and, for the wordmark, k = its art
  pixel, round(2 x devicePixelRatio), and draws the PNG 1:1 with nearest-neighbour filtering (`FilterQuality.none`)
  on the device grid. A PNG or SVG drawn at a fractional scale makes some dots a pixel wider than others.
- **Launcher icon.** Adaptive layers: `ic_launcher_bg` (the body), `ic_launcher_on_fg` / `ic_launcher_off_fg`
  (everything else, transparent around it) and a one-colour themed layer (`drawable/ic_launcher_mono_on|off.xml`: the
  screen with the crescent eyes cut out, and the lamp, a disc when on and a ring when off). The body is full bleed;
  the hood, crown dither, trim and body continue across the full 108 dp layer (v5b, 2026-09-27), so no box edge shows in any mask or when a launcher moves the layers (parallax).

Regenerate from `~/VOX` (needs numpy, pillow and rsvg-convert; the nix command is at the top of the script):
`stipple.py all` (the four SVGs here), `stipple.py launcher` (Android), `stipple.py app` (Flutter PNGs),
`stipple.py preview <dir>` (48 and 192 px checks).
