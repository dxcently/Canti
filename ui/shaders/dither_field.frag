#version 460 core
// The Canti dot-field mood: 1-bit ordered dither (4x4 Bayer), after the FLCL-style isometric pixel art in
// ../README.md "Background". One colour, square dots on a grid of uCell device pixels:
//   * a dot field along the top: a 50% checker that thins out downward into scattered dots, its edge drifting
//     slowly (uTime);
//   * a clear band under each system bar (uInsetTop, uInsetBottom), the dots fading in from it over uFade cells
//     (the same ramp as the clearings around text, lib/src/theme/clearing.dart);
//   * a row of EQ bars standing on the bottom bar, 3 cells wide with a 1-cell gap, each a solid cap over a body that
//     fades upward. uMode 0 (idle): short ticks. 1 (hearing): bars as high as uLevel (0..1; < 0 for none, then a
//     made-up level), moving with uTime, a peak dot over every other bar, all within BAND cells. 2 (off, paused): no
//     bars at all, and the top field thinned to a quarter: the screen goes quiet.
// Everything is computed per pixel from the cell index: no textures, no loops over the screen.
#include <flutter/runtime_effect.glsl>

precision highp float;

uniform vec2 uSize;      // px
uniform float uCell;     // dot pitch in logical px (a whole number of device px)
uniform float uTime;     // s, advanced a few times per second at most
uniform vec4 uDot;       // dot colour, straight alpha
uniform float uTop;      // how far down the top field reaches, as a fraction of the height
uniform float uGap;      // empty margin at each cell's right and bottom, px (0 = touching square pixels)
uniform float uInsetTop;    // px under the system's top bar (status bar): clear, the field fades in below it
uniform float uInsetBottom; // px over the bottom bar (navigation): clear, the bars stand on its edge
uniform float uFade;        // cells over which the field fades in from those edges
uniform float uMode;        // 0 idle (ticks), 1 hearing (bars), 2 off (flat, dimmed)
uniform float uLevel;       // hearing: the mic level 0..1, or < 0 when there is none

out vec4 fragColor;

// 4x4 Bayer threshold in [0, 1): bayer2 on two scales (float-only, no arrays or bit ops, for SkSL).
float bayer2(vec2 a) {
  a = floor(a);
  return fract(dot(a, vec2(0.5, a.y * 0.75)));
}
float bayer4(vec2 a) {
  return bayer2(0.5 * a) * 0.25 + bayer2(a);
}

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

// The EQ band's height in cells: the bars and their peak dots stay under it (lib/src/theme/dither_background.dart
// `eqBandCells`). No screen reserves room for them; they show where content leaves space.
const float BAND = 14.0;

// Density of the EQ bars at cell column cx, y cells above the bottom bar (0 = the row standing on it); -1 for none.
float bars(float cx, float y, float nx, float t) {
  if (y < 0.0 || mod(cx, 4.0) > 2.5) return -1.0;    // 3 cells wide, then a 1-cell gap
  if (uMode > 1.5) return -1.0;                       // off: no bars
  float col = floor(cx / 4.0);
  float h = mod(col, 3.0) == 1.0 ? 2.0 : 1.0;         // idle ticks
  if (uMode > 0.5) {
    float u = cx / nx - 0.5;
    float bell = exp(-u * u / 0.0784);                // louder in the middle (0.28^2)
    float nz = 0.5 + 0.25 * sin(col * 1.7 + 0.4 + t * 2.3) + 0.25 * sin(col * 0.53 + 2.1 - t * 1.4);
    float lv = uLevel >= 0.0 ? uLevel : 0.75 + 0.2 * sin(t * 0.9);
    h = floor(1.5 + lv * (2.0 + 9.0 * nz) * (0.35 + 0.65 * bell)); // up to 12 cells
    if (h >= 3.0 && h + 2.0 < BAND && y == h + 2.0 && mod(col, 2.0) < 0.5) return 1.0; // peak dot
  }
  if (y == h - 1.0) return 1.0;                       // solid cap
  if (y < h - 1.0) return 0.5 * (1.0 - 0.75 * y / h); // the body fades up
  return -1.0;
}

void main() {
  vec2 p = FlutterFragCoord().xy;
  vec2 c = floor(p / uCell);                        // cell index
  vec2 n = uSize / uCell;                           // cells across, down
  float top0 = ceil(uInsetTop / uCell);             // the first cell row below the top bar
  float bottom0 = floor((uSize.y - uInsetBottom) / uCell); // the first cell row on the bottom bar
  float t = uTime;

  // top field
  float wave = floor(2.0 * sin(c.x * 0.13 + t * 0.35) + 1.5 * sin(c.x * 0.047 - t * 0.21));
  float reach = n.y * uTop;
  float f = 1.0 - clamp((c.y - top0 + wave) / reach, 0.0, 1.0);
  float jitter = (hash(floor(c / 3.0)) - 0.5) * 0.35;   // 3x3-cell blocks: an organised, blocky dissolve
  float top = clamp(f * f * 0.75 + jitter * f, 0.0, 0.5);
  if (uMode > 1.5) top *= 0.25;                         // off: the field thins out

  // clear under the bars, then a ramp up to the field's 50% tone (a Bayer ramp, whole cells)
  float edge = min(c.y - top0, bottom0 - 1.0 - c.y);
  float dens = edge < 0.0 ? 0.0 : min(top, 0.5 * (edge + 1.0) / (uFade + 1.0));
  // the EQ bars stand on the bottom bar's edge, over the field (not faded by that ramp)
  float bar = bars(c.x, bottom0 - 1.0 - c.y, n.x, t);
  if (bar >= 0.0) dens = bar;
  float on = step(bayer4(c) + 0.5 / 16.0, dens);
  // a small gap inside each cell for the dot-grid look
  vec2 in_cell = p - c * uCell;
  float gap = step(uCell - uGap, in_cell.x) + step(uCell - uGap, in_cell.y);
  on *= 1.0 - clamp(gap, 0.0, 1.0);
  fragColor = vec4(uDot.rgb * uDot.a, uDot.a) * on;
}
