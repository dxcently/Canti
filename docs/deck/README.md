# Overview deck

`../canti-overview.pptx` is the project overview (16:9): a 9-slide talk for a 3–4 minute slot, then an appendix for questions, drawn in the app's 1-bit pixel kit
(`../../brand/README.md` "Shape language", `../../ui/lib/src/theme`).

- **Art.** Each slide's pixel art is one background PNG on the kit's grid: 320 x 180 art pixels, 6 device px each
  (1920 x 1080). It holds the dot field with its clearings and pillars, the windows, panels, buttons, lamps, meters and
  hatch, the glyphs (read from `ui/lib/src/theme/glyphs.dart`), and the brand PNGs (`ui/assets/brand`, `ui/assets/badge`).
- **Case renders.** The case slides draw the STLs in `hardware/case/out` as isometric 1-bit art with `iso.js`: ink
  outlines on silhouettes, steps and creases, and the faces shaded as dither density. The first case, with the mic
  under the board, is read from git (`f03313d`), so the build needs the repo's history.
- **Text.** All text is live PowerPoint text on top of the art, so it can be edited. Titles and labels are in Silkscreen,
  body text in IBM Plex Mono, in place of the app's Press Start 2P and Tiny5, which are hard to read on slides.
- **Photos.** `inspiration/` holds the two reference photos (FLCL's Canti, Yondu from Guardians of the Galaxy Vol. 2), shown in colour. They are third-party images: keep them out of anything published from the deck.
- **Fonts.** A .pptx doesn't carry its fonts. Install the four files in `fonts/` (OFL) before you open or present the deck,
  or PowerPoint substitutes its own and the labels no longer line up with their frames.

Rebuild after changing `build.js`, the glyphs or the brand art:

```
cd docs/deck
npm install
node build.js
```

The script prints a `fit:` line for any text it estimates won't fit its box.
