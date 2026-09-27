#version 460 core
// The Canti dot-field mood: 1-bit ordered dither (4x4 Bayer), after the FLCL-style isometric pixel art in
// ../README.md "Background". One colour, square dots on a grid of uCell device pixels:
//   * a dot field along the top: a 50% checker that thins out downward into scattered dots, its edge drifting
//     slowly (uTime);
//   * a clear band under each system bar (uInsetTop, uInsetBottom), the dots fading in from it over uFade cells
//     (the same ramp as the clearings around text, lib/src/theme/clearing.dart);
//   * a few isometric pillars rising from the bottom: solid tops, a 50% left face, a 25% right face, and bottoms
//     that dissolve; each bobs by whole cells.
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
uniform float uInsetBottom; // px over the bottom bar (navigation): clear, the pillars stand on its edge
uniform float uFade;        // cells over which the field fades in from those edges

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

// Density of one isometric pillar at cell c (0 when outside). top = the top face's centre, a = half width (cells),
// h = height (cells). Faces: top 1, left 1/2, right 1/4; the lowest third dissolves.
float pillar(vec2 c, vec2 top, float a, float h) {
  vec2 d = c - top;
  if (abs(d.x) / a + abs(d.y) / (0.5 * a) <= 1.0) return 1.0;
  if (abs(d.x) > a) return -1.0;
  float edge = 0.5 * a - 0.5 * abs(d.x);           // lower edge of the top diamond, relative to its centre
  float depth = d.y - edge;                         // cells below that edge
  if (depth < 0.0 || depth > h) return -1.0;
  float face = d.x < 0.0 ? 0.5 : 0.25;
  float fade = 1.0 - smoothstep(h * 0.55, h, depth);
  return face * fade;
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

  // pillars, front to back (larger top.y is nearer): anchored to the bottom corners
  float pil = -1.0;
  float bob0 = floor(sin(t * 0.50) * 1.2 + 0.5);
  float bob1 = floor(sin(t * 0.43 + 2.0) * 1.2 + 0.5);
  float bob2 = floor(sin(t * 0.37 + 4.0) * 1.2 + 0.5);
  float bob3 = floor(sin(t * 0.31 + 1.0) * 1.2 + 0.5);
  vec2 br = vec2(n.x, bottom0);
  float d;
  d = pillar(c, vec2(br.x - 7.0, br.y - 13.0 + bob0), 6.0, 16.0);
  if (d >= 0.0) pil = d;
  if (pil < 0.0) { d = pillar(c, vec2(br.x - 19.0, br.y - 20.0 + bob1), 5.0, 22.0); if (d >= 0.0) pil = d; }
  if (pil < 0.0) { d = pillar(c, vec2(8.0, br.y - 16.0 + bob2), 6.0, 18.0); if (d >= 0.0) pil = d; }
  if (pil < 0.0) { d = pillar(c, vec2(br.x - 11.0, br.y - 30.0 + bob3), 4.0, 26.0); if (d >= 0.0) pil = d; }

  float dens = pil >= 0.0 ? pil : top;
  // clear under the bars, then a ramp up to the field's 50% tone (a Bayer ramp, whole cells)
  float edge = min(c.y - top0, bottom0 - 1.0 - c.y);
  dens = edge < 0.0 ? 0.0 : min(dens, 0.5 * (edge + 1.0) / (uFade + 1.0));
  float on = step(bayer4(c) + 0.5 / 16.0, dens);
  // a small gap inside each cell for the dot-grid look
  vec2 in_cell = p - c * uCell;
  float gap = step(uCell - uGap, in_cell.x) + step(uCell - uGap, in_cell.y);
  on *= 1.0 - clamp(gap, 0.0, 1.0);
  fragColor = vec4(uDot.rgb * uDot.a, uDot.a) * on;
}
