// Builds ../canti-overview.pptx: the Canti project overview in the app's 1-bit pixel kit.
// The pixel art (dot field, frames, glyphs, brand art) is drawn per slide into one background PNG on the
// kit's grid; all text is live PowerPoint text on top, in Silkscreen (titles, labels) and IBM Plex Mono (body).
// Run: npm install && node build.js

const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');
const opentype = require('opentype.js');
const PptxGenJS = require('pptxgenjs');
const { execFileSync } = require('child_process');
const { readStl, renderIso } = require('./iso');

const REPO = path.join(__dirname, '..', '..');
const OUT = path.join(__dirname, '..', 'canti-overview.pptx');

// The slide is 320 x 180 art pixels (10 x 5.625 in, 1/32 in each), rendered at 6 device px per art px.
const W = 320, H = 180, K = 6;
const IN = (a) => a / 32;
const PT_PER_ART = 72 / 32;

const COLORS = {
  mintCream: 'DDEBD3',
  visorNavy: '1D2757',
  signalOrange: 'F2A33A',
  signalYellow: 'F6C945',
  signalRed: 'D6453D',
};
const LIGHT = { ink: COLORS.visorNavy, paper: COLORS.mintCream, dark: false };
const DARK = { ink: COLORS.mintCream, paper: COLORS.visorNavy, dark: true };

const FONT_DIR = path.join(__dirname, 'fonts');
const loadFont = (f) => {
  const b = fs.readFileSync(path.join(FONT_DIR, f));
  return opentype.parse(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
};
const FONTS = {
  title: { face: 'Silkscreen', regular: loadFont('Silkscreen-Regular.ttf'), bold: loadFont('Silkscreen-Bold.ttf') },
  body: { face: 'IBM Plex Mono', regular: loadFont('IBMPlexMono-Regular.ttf'), bold: loadFont('IBMPlexMono-Bold.ttf') },
};
const textWidthArt = (s, font, size, bold) =>
  (FONTS[font][bold ? 'bold' : 'regular'].getAdvanceWidth(s, size) / PT_PER_ART);

// The app's glyphs, read from its source so the deck and the app never drift.
function loadGlyphs() {
  const src = fs.readFileSync(path.join(REPO, 'ui/lib/src/theme/glyphs.dart'), 'utf8');
  const out = {};
  for (const cls of src.split(/abstract final class /).slice(1)) {
    const name = cls.match(/^(\w+)/)[1];
    out[name] = {};
    for (const m of cls.matchAll(/static const (\w+) = Glyph\(\[([\s\S]*?)\]\)/g)) {
      out[name][m[1]] = [...m[2].matchAll(/'([^']*)'/g)].map((r) => r[1]);
    }
  }
  return out;
}
const G = loadGlyphs();

const readPng = (rel) => PNG.sync.read(fs.readFileSync(path.join(REPO, rel)));
const BRAND = {
  icon: readPng('ui/assets/brand/canti-icon-on@4.png'),
  wordmark: readPng('ui/assets/brand/canti-wordmark@6.png'),
  wordmarkLight: readPng('ui/assets/brand/canti-wordmark-light@6.png'),
  badge: readPng('ui/assets/badge/canti_badge.png'),
};
// The case (hardware/case/out), and its first version from git: the mic under the board (f03313d).
const stl = (rel) => readStl(fs.readFileSync(path.join(REPO, rel), 'utf8'));
const stlAt = (rev, rel) => readStl(execFileSync('git', ['-C', REPO, 'show', `${rev}:${rel}`], { encoding: 'utf8', maxBuffer: 64 << 20 }));
const CASE = {
  base: stl('hardware/case/out/base.stl'),
  lid: stl('hardware/case/out/lid.stl'),
  plunger: stl('hardware/case/out/plunger.stl'),
  clip: stl('hardware/case/out/mic_clip.stl'),
  micTest: stl('hardware/case/out/mic_test.stl'),
  baseV1: stlAt('f03313d', 'hardware/case/out/base.stl'),
};
// Mic pocket centres in each STL's coordinates (vox_case.scad: mic_x/mic_y; the lid is exported flipped, y -> -y).
const POCKET_V1 = [32, 60, 2];
const POCKET_V2 = [36.43, -60.4, 4];

const BADGE = JSON.parse(fs.readFileSync(path.join(REPO, 'ui/assets/badge/canti_badge.json'), 'utf8'));

const BAYER4 = [
  [0, 8, 2, 10],
  [12, 4, 14, 6],
  [3, 11, 1, 9],
  [15, 7, 13, 5],
];
const bayer = (x, y) => (BAYER4[y & 3][x & 3] + 0.5) / 16;

const rgb = (hex) => [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];

// A port of the kit's PixelCanvas (ui/lib/src/theme/pixel.dart) onto a device-pixel buffer, plus the slide's texts.
class Slide {
  constructor(theme) {
    this.t = theme;
    this.png = new PNG({ width: W * K, height: H * K });
    this.texts = [];
    this.clear = new Uint8Array(W * H); // art pixels where ink sits straight on the dot field
    this.pillars = [];
    this.covered = new Uint8Array(W * K * H * K); // device pixels the kit drew; the field stays under them
    this.devRect(0, 0, W * K, H * K, theme.paper, { under: true });
  }

  devRect(x, y, w, h, hex, { under = false } = {}) {
    const [r, g, b] = rgb(hex);
    const d = this.png.data;
    for (let j = Math.max(0, y); j < Math.min(H * K, y + h); j++) {
      for (let i = Math.max(0, x); i < Math.min(W * K, x + w); i++) {
        const n = j * W * K + i;
        if (under && this.covered[n]) continue;
        if (!under) this.covered[n] = 1;
        const o = n * 4;
        d[o] = r; d[o + 1] = g; d[o + 2] = b; d[o + 3] = 255;
      }
    }
  }

  ink(c) { return c === 'paper' ? this.t.paper : c === 'ink' || c === undefined ? this.t.ink : c; }
  rect(x, y, w, h, c) { this.devRect(x * K, y * K, w * K, h * K, this.ink(c)); }
  hline(x, y, w, c) { this.rect(x, y, w, 1, c); }
  vline(x, y, h, c) { this.rect(x, y, 1, h, c); }

  frame(x, y, w, h, c, { notch = false, dotted = false } = {}) {
    if (dotted) {
      for (let i = x; i < x + w; i += 2) { this.rect(i, y, 1, 1, c); this.rect(i, y + h - 1, 1, 1, c); }
      for (let j = y + 2; j < y + h - 1; j += 2) { this.rect(x, j, 1, 1, c); this.rect(x + w - 1, j, 1, 1, c); }
      return;
    }
    const n = notch ? 1 : 0;
    this.hline(x + n, y, w - 2 * n, c);
    this.hline(x + n, y + h - 1, w - 2 * n, c);
    this.vline(x, y + 1, h - 2, c);
    this.vline(x + w - 1, y + 1, h - 2, c);
  }

  block(x, y, w, h, c) {
    this.rect(x + 1, y, w - 2, h, c);
    this.rect(x, y + 1, 1, h - 2, c);
    this.rect(x + w - 1, y + 1, 1, h - 2, c);
  }

  glyph(rows, x, y, c, scale = 1) {
    rows.forEach((row, r) => {
      for (let i = 0; i < row.length; i++) if (row[i] === '#') this.rect(x + i * scale, y + r * scale, scale, scale, c);
    });
  }

  hatch(x, y, w, h, c, step = 4) {
    for (let j = y; j < y + h; j++) for (let i = x + ((step - (j % step)) % step); i < x + w; i += step) this.rect(i, j, 1, 1, c);
  }

  brackets(x, y, w, h, c, arm = 4, t = 1) {
    for (const [cx, cy, sx, sy] of [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]]) {
      this.rect(sx > 0 ? cx : cx - arm, sy > 0 ? cy : cy - t, arm, t, c);
      this.rect(sx > 0 ? cx : cx - t, sy > 0 ? cy : cy - arm, t, arm, c);
    }
  }

  // An image, [k] device px per source px, at art position (x, y). [clear] marks its opaque pixels as ink on the field.
  image(img, x, y, k, { sx = 0, sy = 0, sw = img.width, sh = img.height, clear = false } = {}) {
    const d = this.png.data;
    for (let j = 0; j < sh; j++) {
      for (let i = 0; i < sw; i++) {
        const so = ((sy + j) * img.width + (sx + i)) * 4;
        const a = img.data[so + 3] / 255;
        if (a === 0) continue;
        for (let v = 0; v < k; v++) {
          for (let u = 0; u < k; u++) {
            const px = x * K + i * k + u, py = y * K + j * k + v;
            if (px < 0 || py < 0 || px >= W * K || py >= H * K) continue;
            this.covered[py * W * K + px] = 1;
            const o = (py * W * K + px) * 4;
            for (let ch = 0; ch < 3; ch++) d[o + ch] = Math.round(img.data[so + ch] * a + d[o + ch] * (1 - a));
          }
        }
        if (clear) this.markClear(x + Math.floor((i * k) / K), y + Math.floor((j * k) / K), Math.ceil(k / K), Math.ceil(k / K));
      }
    }
  }

  markClear(x, y, w, h) {
    for (let j = Math.max(0, y); j < Math.min(H, y + h); j++) for (let i = Math.max(0, x); i < Math.min(W, x + w); i++) this.clear[j * W + i] = 1;
  }

  text(str, x, y, w, h, o = {}) {
    this.texts.push({ str, x, y, w, h, o });
    if (o.onField) this.markClear(x, y, w, h);
  }

  // --- the dot field (ui/shaders/dither_field.frag, still) -------------------------------------------------------

  // One dot per 2 art px cell: a 50% checker along the top that thins out downward, isometric pillars from the
  // bottom (solid top, 50% left face, 25% right face), and clearings around ink on the field.
  field({ top = 26 } = {}) {
    const dist = this.clearDistance();
    const cellsX = W / 2, cellsY = H / 2;
    for (let cy = 0; cy < cellsY; cy++) {
      for (let cx = 0; cx < cellsX; cx++) {
        let d = cy < 4 ? 0.5 : Math.max(0, 0.5 * (1 - (cy - 4) / (top - 4)));
        for (const p of this.pillars) d = Math.max(d, pillarDensity(p, cx, cy));
        if (d <= 0) continue;
        const dd = Math.min(dist[(cy * 2 + 1) * W + cx * 2 + 1], dist[cy * 2 * W + cx * 2]);
        if (dd < 3) continue;
        if (dd < 9) d = Math.min(d, (0.5 * (dd - 3)) / 6);
        if (bayer(cx, cy) >= d) continue;
        this.devRect(cx * 2 * K, cy * 2 * K, 2 * K - 2, 2 * K - 2, this.t.ink, { under: true });
      }
    }
  }

  // Chamfer distance (art px) from every art pixel to the nearest cleared-ink pixel.
  clearDistance() {
    const INF = 1e9, d = new Float32Array(W * H);
    for (let i = 0; i < W * H; i++) d[i] = this.clear[i] ? 0 : INF;
    const pass = (xs, ys, nbrs) => {
      for (const y of ys) for (const x of xs) {
        let v = d[y * W + x];
        for (const [dx, dy, c] of nbrs) {
          const nx = x + dx, ny = y + dy;
          if (nx >= 0 && ny >= 0 && nx < W && ny < H) v = Math.min(v, d[ny * W + nx] + c);
        }
        d[y * W + x] = v;
      }
    };
    const r = (n) => [...Array(n).keys()];
    pass(r(W), r(H), [[-1, 0, 1], [0, -1, 1], [-1, -1, 1.4], [1, -1, 1.4]]);
    pass(r(W).reverse(), r(H).reverse(), [[1, 0, 1], [0, 1, 1], [1, 1, 1.4], [-1, 1, 1.4]]);
    return d;
  }

  // --- the kit's pieces (ui/lib/src/theme/kit.dart) ----------------------------------------------------------------

  // A window: paper fill, a double frame with notched corners, and a title tab on the top edge.
  window(x, y, w, h, title) {
    const tabH = 11, fy = y + Math.floor(tabH / 2) - 1;
    const tab = Math.ceil(textWidthArt(title, 'title', 18, true)) + 9;
    this.block(x, fy, w, h - (fy - y), 'paper');
    this.frame(x, fy, w, h - (fy - y), 'ink', { notch: true });
    this.frame(x + 2, fy + 2, w - 4, h - (fy - y) - 4, 'ink');
    this.rect(x + 4, y + h - 5, 1, 1);
    this.rect(x + w - 5, y + h - 5, 1, 1);
    this.rect(x + w - 5, fy + 4, 1, 1);
    this.block(x + 5, y, tab, tabH, 'paper');
    this.frame(x + 5, y, tab, tabH, 'ink', { notch: true });
    this.text(title, x + 5, y, tab, tabH, { font: 'title', size: 18, bold: true, align: 'center' });
    return { x: x + 7, y: y + 14, w: w - 14, h: h - 19 };
  }

  panel(x, y, w, h) {
    this.block(x, y, w, h, 'ink');
    this.frame(x + 1, y + 1, w - 2, h - 2, 'paper', { notch: true });
  }

  box(x, y, w, h, { fill = 'paper', line = 'ink', dotted = false } = {}) {
    this.block(x, y, w, h, fill);
    this.frame(x, y, w, h, line, { notch: !dotted, dotted });
  }

  button(x, y, w, h, label, { main = false, pressed = false, disabled = false, focused = false } = {}) {
    const m = 2, bw = w - 2 * m, bh = h - 2 * m;
    this.block(x + m, y + m, bw, bh, pressed ? 'ink' : 'paper');
    if (disabled) this.frame(x + m, y + m, bw, bh, 'ink', { dotted: true });
    else {
      this.frame(x + m, y + m, bw, bh, 'ink', { notch: true });
      if (main) this.frame(x + m + 2, y + m + 2, bw - 4, bh - 4, pressed ? 'paper' : 'ink');
    }
    if (focused) this.brackets(x, y, w, h, 'ink', 4, 1);
    this.text(label, x, y, w, h, { font: 'title', size: 18, bold: true, align: 'center', color: pressed ? 'paper' : 'ink' });
  }

  lamp(x, y, lit) {
    this.block(x, y, 11, 11, 'ink');
    this.block(x + 1, y + 1, 9, 9, lit || 'paper');
    if (lit) { this.rect(x + 3, y + 3, 2, 1, 'paper'); this.rect(x + 3, y + 4, 1, 1, 'paper'); }
    else this.rect(x + 4, y + 4, 3, 3, 'ink');
  }

  pips(x, y, value, max, c = 'ink') {
    for (let i = 0; i < max; i++) this.glyph(G.Icons7[i < value ? 'pipOn' : 'pipOff'], x + i * 9, y + 2, c);
  }

  meter(x, y, w, frac, c = 'ink') {
    this.frame(x, y, w, 5, c, { notch: true });
    const fill = Math.round((w - 4) * frac);
    if (fill > 0) this.rect(x + 2, y + 2, fill, 1, c);
  }

  // A dotted leader from x0 to x1 on row y.
  leader(x0, x1, y, c = 'ink') {
    if (x1 - x0 < 4) warnings.push(`leader ${x0}..${x1} at y ${y} has no room`);
    for (let i = x0 + ((x0 & 1) ? 1 : 0); i < x1; i += 2) this.rect(i, y, 1, 1, c);
  }

  // A stat row: framed icon, LABEL, dotted leader, value (right-aligned). 11 art px tall; on a panel pass c: 'paper'.
  statRow(x, y, w, { icon, label, value, c = 'ink', valueSize = 12 }) {
    let lx = x;
    if (icon) {
      this.frame(x, y, 11, 11, c, { notch: true });
      this.glyph(icon, x + 2, y + 2, c);
      lx = x + 15;
    }
    const lw = Math.ceil(textWidthArt(label, 'title', 18, true));
    const vw = Math.ceil(textWidthArt(value, 'body', valueSize, false));
    this.text(label, lx, y, lw + 2, 11, { font: 'title', size: 18, bold: true, color: c });
    this.leader(lx + lw + 4, x + w - vw - 3, y + 8, c);
    this.text(value, x + w - vw - 1, y - 1, vw + 1, 12, { size: valueSize, color: c, align: 'right' });
  }

  // The screen header (kit ScreenHeader): a number box, then the title on a plate.
  header(n, title) {
    this.box(8, 6, 19, 19);
    this.text(String(n).padStart(2, '0'), 8, 6, 19, 19, { font: 'title', size: 18, bold: true, align: 'center' });
    const tw = Math.ceil(textWidthArt(title, 'title', 36, true));
    this.box(31, 6, tw + 14, 19);
    this.text(title, 31, 5, tw + 14, 20, { font: 'title', size: 36, bold: true, align: 'center' });
  }

  // An iso render (iso.js) at art position (x, y); its paper pixels cover the field too.
  iso(g, x, y) {
    for (let j = 0; j < g.h; j++) for (let i = 0; i < g.w; i++) {
      const v = g.px[j * g.w + i];
      if (v) this.rect(x + i, y + j, 1, 1, v === 1 ? 'ink' : 'paper');
    }
  }

  badgeFrame(state, x, y, k, { frame } = {}) {
    const s = BADGE.states[state];
    const f = frame ?? s.still ?? 0;
    const idx = s.frames[f];
    const fw = BADGE.frameWidth, fh = BADGE.frameHeight;
    this.image(BRAND.badge, x, y, k, { sx: (idx % BADGE.columns) * fw, sy: Math.floor(idx / BADGE.columns) * fh, sw: fw, sh: fh, clear: true });
  }
}

function pillarDensity({ cx, a, top }, x, y) {
  const dx = x - cx;
  if (Math.abs(dx) > a || y < top - a / 2) return 0;
  const edge = top + (a / 2) * (1 - Math.abs(dx) / a); // the top face's lower edge at this column
  const rim = top - (a / 2) * (1 - Math.abs(dx) / a); // its upper edge
  if (y < rim) return 0;
  if (y <= edge) return 1;
  return dx < 0 ? 0.5 : 0.25;
}

// --- text into pptx ------------------------------------------------------------------------------------------------

const warnings = [];

// Monospace line estimate for IBM Plex Mono (advance 0.6 em) to catch overflow before rendering.
function checkFit(slideNo, t) {
  const o = t.o;
  if ((o.font || 'body') !== 'body') {
    const lines = Array.isArray(t.str) ? 1 : String(t.str).split('\n').length;
    const w = textWidthArt(Array.isArray(t.str) ? t.str.map((r) => r.text).join('') : String(t.str).split('\n')[0], 'title', o.size || 18, o.bold);
    if (lines === 1 && w > t.w + 0.5) warnings.push(`slide ${slideNo}: "${t.str}" is ${w.toFixed(1)} wide in ${t.w}`);
    return;
  }
  const size = o.size || 13;
  const perLine = Math.floor((t.w * PT_PER_ART) / (0.6 * size));
  const paras = Array.isArray(t.str) ? splitRuns(t.str) : String(t.str).split('\n');
  let lines = 0;
  for (const p of paras) lines += Math.max(1, Math.ceil(p.length / perLine));
  const lineH = size * 1.3 * (o.lineSpacingMultiple || 1);
  const heightPt = lines * lineH + (paras.length - 1) * (o.paraSpaceAfter || 0);
  if (heightPt > t.h * PT_PER_ART + 1) warnings.push(`slide ${slideNo}: ${lines} lines (${heightPt.toFixed(0)}pt) in ${(t.h * PT_PER_ART).toFixed(0)}pt: "${paras[0].slice(0, 40)}"`);
}
function splitRuns(runs) {
  const paras = [''];
  for (const r of runs) {
    paras[paras.length - 1] += r.text;
    if (r.options && r.options.breakLine) paras.push('');
  }
  return paras.filter((p, i) => p || i < paras.length - 1);
}

function emit(pres, s, slideNo) {
  const buf = PNG.sync.write(s.png);
  const slide = pres.addSlide();
  slide.background = { data: 'image/png;base64,' + buf.toString('base64') };
  for (const t of s.texts) {
    checkFit(slideNo, t);
    const o = t.o;
    const font = FONTS[o.font || 'body'];
    const color = o.color === 'paper' ? s.t.paper : o.color && o.color !== 'ink' ? o.color : s.t.ink;
    slide.addText(t.str, {
      x: IN(t.x), y: IN(t.y), w: IN(t.w), h: IN(t.h),
      fontFace: font.face, fontSize: o.size || (o.font === 'title' ? 18 : 13), bold: !!o.bold,
      color, align: o.align || 'left', valign: o.valign || 'middle', margin: 0, isTextBox: true,
      paraSpaceAfter: o.paraSpaceAfter, lineSpacingMultiple: o.lineSpacingMultiple, fit: 'none', wrap: true,
    });
  }
}

// Bulleted Plex Mono paragraphs with a square bullet.
const bullets = (items, o = {}) => items.map((text, i) => ({
  text,
  options: { bullet: { code: '25A0', indent: o.indent || 14 }, breakLine: i < items.length - 1, bold: false },
}));

// --- the slides ----------------------------------------------------------------------------------------------------

const slides = [];

// Title
slides.push((n) => {
  const s = new Slide(DARK);
  s.pillars.push({ cx: 12, a: 9, top: 72 }, { cx: 26, a: 6, top: 80 }, { cx: 148, a: 8, top: 76 }, { cx: 136, a: 5, top: 83 });
  s.image(BRAND.icon, 28, 44, 3, { clear: true });
  s.image(BRAND.wordmarkLight, 130, 42, 2, { clear: true });
  s.text('Hands-free phone control by hum, pop and hiss.', 130, 130, 180, 10, { size: 14, onField: true });
  s.text('PROJECT OVERVIEW  ·  VOX / CANTI', 130, 144, 180, 8, { font: 'title', size: 18, onField: true });
  s.field({ top: 30 });
  return s;
});

// The idea
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.pillars.push({ cx: 6, a: 7, top: 80 }, { cx: 154, a: 6, top: 78 });
  s.header(n, 'The idea');
  const a = s.window(8, 31, 162, 140, 'WHAT CANTI IS');
  s.text([
    { text: 'You make a small sound. The phone swipes, taps or goes back.', options: { breakLine: true, bold: true } },
    { text: 'No words needed: hums that rise, fall, arch or dip, lip pops, tongue clicks, hisses and whistles, plus sounds you invent.', options: { breakLine: true } },
    { text: 'Spoken phrases are an opt-in extra, opened by "pop pop".', options: { breakLine: true } },
    { text: 'Pitch is read relative to where each hum starts, never as an absolute note. Absolute notes lost in the prior art: 2.6 s against 1.4 s per target (Sporka 2006).', options: {} },
  ], a.x + 2, a.y + 1, a.w - 4, a.h - 3, { size: 13, valign: 'top', paraSpaceAfter: 7 });

  const b = s.window(176, 31, 136, 104, 'EIGHT SOUNDS');
  s.panel(b.x, b.y, b.w, b.h);
  const names = ['rise', 'fall', 'arch', 'dip', 'flat', 'pop', 'click', 'hiss'];
  const cw = 30, ch = 40, gx = b.x + Math.floor((b.w - 4 * cw) / 2), gy = b.y + 4;
  names.forEach((n, i) => {
    const cx = gx + (i % 4) * cw, cy = gy + Math.floor(i / 4) * ch;
    s.glyph(G.GestureGlyphs[n], cx + 3, cy + 3, 'paper', 2);
    s.text(n.toUpperCase(), cx, cy + 29, cw, 8, { font: 'title', size: 18, color: 'paper', align: 'center' });
  });
  s.field();
  return s;
});

// How it works
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.pillars.push({ cx: 8, a: 8, top: 82 }, { cx: 152, a: 7, top: 80 });
  s.header(n, 'How it works');
  const steps = [
    ['HEAR', 'sound', 'A Pico 2 W pendant with an I2S mic hears each sound.'],
    ['DESCRIBE', 'link', 'It writes the sound as one line of text and sends it over Bluetooth LE.'],
    ['DECIDE', 'decider', 'The phone groups sounds, reads the screen, and picks the action.'],
    ['ACT', 'hand', 'Android swipes, taps or goes back, then checks that it worked.'],
  ];
  const ww = 70, gap = 8;
  steps.forEach(([title, icon, body], i) => {
    const x = 8 + i * (ww + gap);
    const a = s.window(x, 31, ww, 92, `${i + 1} ${title}`);
    s.glyph(G.Icons7[icon], a.x + 2, a.y + 2, 'ink', 3);
    s.text(body, a.x + 2, a.y + 27, a.w - 3, a.h - 28, { size: 12, valign: 'top' });
    if (i < 3) { s.glyph(G.Marks.right, x + ww + 2, 72, 'ink'); s.markClear(x + ww + 2, 72, 4, 7); }
  });
  s.panel(8, 130, 304, 36);
  s.text('WHAT THE PENDANT SENDS', 16, 134, 200, 9, { font: 'title', size: 18, bold: true, color: 'paper' });
  s.text('hum that rises from low to high; pitch change large; duration short; …', 16, 146, 290, 14, { size: 13, color: 'paper' });
  s.field();
  return s;
});

// The sounds
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'The sounds');
  const a = s.window(8, 31, 304, 132, 'DEFAULT BINDINGS');
  const colW = 126;
  const singles = [['rise', 'swipe up'], ['fall', 'swipe down'], ['arch', 'swipe right'], ['dip', 'swipe left'], ['flat', 'long press'], ['hiss', 'back'], ['pop', 'tap']];
  const seqs = [[['hiss', 'click'], 'back'], [['click', 'click'], 'home'], [['click', 'hiss'], 'forward'], [['pop', 'pop'], 'listen'], [['rise', 'flat'], 'keep scrolling']];
  const rowH = 14;
  s.panel(a.x, a.y, colW, 7 * rowH + 8);
  s.text('ONE SOUND', a.x + 5, a.y + 2, 70, 8, { font: 'title', size: 18, bold: true, color: 'paper' });
  singles.forEach(([g, act], i) => {
    const y = a.y + 11 + i * 13;
    s.glyph(G.GestureGlyphs[g], a.x + 5, y - 1, 'paper');
    const lw = Math.ceil(textWidthArt(g.toUpperCase(), 'title', 18, false));
    s.text(g.toUpperCase(), a.x + 21, y, lw + 2, 10, { font: 'title', size: 18, color: 'paper' });
    const vw = Math.ceil(textWidthArt(act, 'body', 12));
    s.leader(a.x + 21 + lw + 4, a.x + colW - vw - 8, y + 7, 'paper');
    s.text(act, a.x + colW - vw - 6, y - 1, vw + 1, 11, { size: 12, color: 'paper', align: 'right' });
  });
  const x2 = a.x + colW + 6, w2 = a.w - colW - 6;
  s.panel(x2, a.y, w2, 5 * rowH + 11);
  s.text('SEQUENCES', x2 + 5, a.y + 2, 70, 8, { font: 'title', size: 18, bold: true, color: 'paper' });
  seqs.forEach(([gs, act], i) => {
    const y = a.y + 11 + i * 14;
    s.glyph(G.GestureGlyphs[gs[0]], x2 + 5, y - 1, 'paper');
    s.glyph(G.GestureGlyphs[gs[1]], x2 + 20, y - 1, 'paper');
    const label = gs.join(' ').toUpperCase();
    const shown = i === 4 ? 'RISE + HOLD' : label;
    const lw = Math.ceil(textWidthArt(shown, 'title', 18, false));
    s.text(shown, x2 + 36, y, lw + 2, 10, { font: 'title', size: 18, color: 'paper' });
    const vw = Math.ceil(textWidthArt(act, 'body', 12));
    s.leader(x2 + 36 + lw + 4, x2 + w2 - vw - 8, y + 7, 'paper');
    s.text(act, x2 + w2 - vw - 6, y - 1, vw + 1, 11, { size: 12, color: 'paper', align: 'right' });
  });
  s.text('A lone pop taps only from the pendant; phone-mic pops do nothing. Every binding can be changed per app.',
    x2, a.y + 5 * rowH + 15, w2, 28, { size: 11, valign: 'top' });
  s.field();
  return s;
});

// The pendant
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.pillars.push({ cx: 150, a: 8, top: 78 });
  s.header(n, 'The pendant');
  const a = s.window(8, 31, 170, 110, 'HARDWARE');
  s.panel(a.x, a.y, a.w, a.h);
  const rows = [
    ['device', 'BOARD', 'Pico 2 W · $7'],
    ['sound', 'MIC', 'INMP441 I2S MEMS'],
    ['app', 'WIRED BUILD', '~$15–20'],
    ['power', 'WITH BATTERY', '~$25–32'],
    ['gear', 'FIRMWARE', 'vox_node 0.2.2'],
    ['decider', 'FLASH / RAM', '519 KB / 270 KB'],
  ];
  rows.forEach(([icon, label, value], i) => s.statRow(a.x + 5, a.y + 5 + i * 14, a.w - 10, { icon: G.Icons7[icon], label, value, c: 'paper' }));
  s.text('Worn as a necklace in a 3D-printed case. It runs from a USB power bank.', 8, 148, 170, 20, { size: 12, onField: true, valign: 'top' });

  const b = s.window(184, 31, 128, 100, 'ONE BUTTON');
  const presses = [['5 PRESSES', 'arm / off'], ['1 CLICK', 'gesture ⇄ cursor'], ['HOLD 1 S', 'disarm, sleep'], ['HOLD 5 S', 'pair for 60 s']];
  presses.forEach(([label, value], i) => s.statRow(b.x + 2, b.y + 4 + i * 16, b.w - 4, { label, value }));
  s.text('A sound cannot reliably stop the thing that is misreading sounds, so stop lives on the button.', 184, 137, 128, 30, { size: 11, onField: true, valign: 'top' });
  s.field();
  return s;
});

// The case: the printed parts
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'The case');
  const a = s.window(8, 31, 200, 142, 'PRINTED PARTS');
  const T = { yaw: 30, el: 50, scale: 0.95 };
  const base = renderIso(CASE.base, T), lid = renderIso(CASE.lid, T);
  s.iso(base, a.x + 2, a.y + 1);
  s.iso(lid, a.x + a.w - lid.w - 2, a.y + 3);
  const ly = a.y + Math.max(base.h, lid.h + 2) + 1;
  s.text('BASE', a.x + 2, ly, base.w, 9, { font: 'title', size: 18, bold: true, align: 'center' });
  s.text('LID, INSIDE UP', a.x + a.w - lid.w - 2, ly, lid.w, 9, { font: 'title', size: 18, bold: true, align: 'center' });
  const plunger = renderIso(CASE.plunger, { yaw: 30, el: 35, scale: 2 });
  const clip = renderIso(CASE.clip, { yaw: 30, el: 55, scale: 2 });
  const py = ly + 12;
  s.iso(plunger, a.x + 12, py);
  s.text('PLUNGER', a.x + 12 + plunger.w + 4, py + 4, 50, 9, { font: 'title', size: 18, bold: true });
  s.text('presses the button through the lid', a.x + 12 + plunger.w + 4, py + 13, 60, 12, { size: 9, valign: 'top' });
  s.iso(clip, a.x + a.w - clip.w - 50, py - 2);
  s.text('MIC CLIP', a.x + a.w - 48, py + 4, 48, 9, { font: 'title', size: 18, bold: true });
  s.text('holds the mic in the lid', a.x + a.w - 48, py + 13, 48, 12, { size: 9, valign: 'top' });

  const b = s.window(214, 31, 98, 142, 'PRINT');
  const parts = [
    ['BASE', 'back face down · 1'],
    ['LID', 'outer face down · 1'],
    ['PLUNGER', 'flange down · 1'],
    ['MIC CLIP', 'flat · print 2–3, tiny'],
    ['FIT TEST', 'optional: board fit'],
    ['MIC TEST', 'optional: pocket, 10 min'],
  ];
  parts.forEach(([name, how], i) => {
    const y = b.y + i * 15;
    s.text(name, b.x + 1, y, b.w - 2, 8, { font: 'title', size: 18, bold: true });
    s.text(how, b.x + 1, y + 8, b.w - 2, 6, { size: 10 });
  });
  s.hline(b.x + 1, b.y + 91, b.w - 2);
  s.text('PLA, 0.2 mm layers, no supports. About 55 × 75 × 20 mm plus the necklace loop.', b.x + 1, b.y + 94, b.w - 2, 28, { size: 10, valign: 'top' });
  s.field();
  return s;
});

// Moving the mic: v1 under the board, v2 in the lid
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'Moving the mic');
  const T = { yaw: 30, el: 50, scale: 0.9 };
  const views = [
    [8, 'V1 · UNDER THE BOARD', CASE.baseV1, POCKET_V1, [
      'A pocket on the back wall, under the board, with the port through the back.',
      'Six short wires soldered to the board.',
      'Way too hard to work with: to reach the mic, the whole board comes out.',
    ]],
    [170, 'V2 · IN THE LID', CASE.lid, POCKET_V2, [
      'Clipped into a pocket in the lid, over a 2 mm hole.',
      'Five Dupont wires plug onto a header on the board.',
      'Unplug the lid and the mic comes with it: easy to swap or take out.',
    ]],
  ];
  views.forEach(([x, title, mesh, pocket, lines]) => {
    const a = s.window(x, 31, 142, 142, title);
    const g = renderIso(mesh, { ...T, marks: [pocket] });
    const gx = a.x + Math.floor((a.w - g.w) / 2), gy = a.y;
    s.iso(g, gx, gy);
    const [mx, my] = g.marks[0];
    s.brackets(gx + mx - 13, gy + my - 10, 26, 20, 'ink', 5, 1);
    s.text(bullets(lines), a.x + 1, gy + g.h + 1, a.w - 2, a.y + a.h - gy - g.h - 2, { size: 10, valign: 'top', paraSpaceAfter: 2 });
  });
  s.glyph(G.Marks.right, 158, 92, 'ink', 2);
  s.markClear(158, 92, 8, 14);
  s.field();
  return s;
});

// The mic in the lid: the pocket, the stack, the plug
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'The mic in the lid');
  const a = s.window(8, 31, 150, 142, 'MIC POCKET');
  const pocket = renderIso(CASE.micTest, { yaw: 30, el: 55, scale: 2.8 });
  const clip = renderIso(CASE.clip, { yaw: 30, el: 55, scale: 2.4 });
  s.iso(pocket, a.x, a.y);
  s.iso(clip, a.x + a.w - clip.w, a.y + 44);
  s.text('C-CLIP', a.x + a.w - clip.w, a.y + 34, clip.w, 8, { font: 'title', size: 18, bold: true, align: 'center' });
  s.text('The lid\'s pocket, printed on its own as mic_test.stl (about 10 minutes) to check the module, foam and clip fit before the whole lid.',
    a.x + 1, a.y + pocket.h + 2, a.w - 2, a.h - pocket.h - 3, { size: 10, valign: 'top' });

  const b = s.window(164, 31, 148, 78, 'THE STACK');
  const L = b.x + 2, R = b.x + 50, mid = Math.round((L + R) / 2);
  const layers = [];
  let y = b.y + 3;
  const layer = (label, draw, h) => { draw(y, h); layers.push([label, y + Math.floor(h / 2)]); y += h + 5; };
  layer('fabric disc', (yy, h) => s.hatch(L + 12, yy, R - L - 24, h, 'ink', 2), 3);
  layer('lid, 2 mm hole', (yy, h) => { s.rect(L, yy, mid - 1 - L, h); s.rect(mid + 2, yy, R - mid - 2, h); }, 4);
  layer('foam ring', (yy, h) => { s.hatch(L + 14, yy, mid - 2 - L - 14, h, 'ink', 2); s.hatch(mid + 3, yy, R - 14 - mid - 3, h, 'ink', 2); s.frame(L + 14, yy, R - L - 28, h, 'ink'); s.rect(mid - 1, yy, 3, h, 'paper'); }, 4);
  layer('mic, label side up', (yy, h) => { s.rect(L + 4, yy, mid - L - 4, h); s.rect(mid + 1, yy, R - 4 - mid - 1, h); s.rect(mid - 5, yy + h, 11, 2); }, 3);
  layer('C-clip', (yy, h) => { s.rect(L + 3, yy, 8, h); s.rect(R - 11, yy, 8, h); }, 2);
  layer('5 wires to the board', (yy, h) => { for (let i = 0; i < 5; i++) s.vline(L + 14 + i * 6, yy - 2, h + 2); }, 6);
  layers.forEach(([label, ly]) => {
    s.leader(R + 3, R + 9, ly);
    s.text(label, R + 11, ly - 4, b.x + b.w - R - 11, 8, { size: 10 });
  });

  const c = s.window(164, 113, 148, 60, 'THE PLUG');
  ['GND', '3V3', 'SD', 'WS', 'SCK'].forEach((pin, i) => {
    const x = c.x + i * 27;
    s.box(x, c.y, 25, 11, { fill: i === 0 ? 'ink' : 'paper' });
    s.text(pin, x, c.y, 25, 11, { font: 'title', size: 18, bold: true, align: 'center', color: i === 0 ? 'paper' : 'ink' });
  });
  s.text(bullets(['A right-angle header, column 9, rows 3–7: the plug lies flat under the lid.', '8–9 cm of cable: the lid sets down beside the case, still plugged in.', 'L/R is bridged to GND on the module, so 5 wires, not 6.']), c.x, c.y + 13, c.w, c.h - 13, { size: 9, valign: 'top', paraSpaceAfter: 1 });
  s.field();
  return s;
});

// Mapping the board, and the build book
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'Mapped, then built');
  const a = s.window(8, 31, 150, 142, 'BOARD MAP');
  // The protoboard at 4 art px per 2.54 mm hole (hardware/case/out/layout.svg), component side up, USB at the bottom.
  const bx = a.x + 1, by = a.y + 1, bw = 79, bh = 110;
  const X = (c) => bx + 5 + 4 * c, Y = (r) => by + bh - 10 - 4 * r;
  s.box(bx, by, bw, bh);
  for (let c = 0; c < 18; c++) for (let r = 0; r < 24; r++) s.rect(X(c), Y(r), 1, 1);
  s.box(X(0) - 3, Y(19) - 3, X(7) - X(0) + 7, Y(0) - Y(19) + 7);
  for (let r = 0; r < 20; r++) { s.rect(X(0), Y(r), 1, 1); s.rect(X(7), Y(r), 1, 1); }
  s.text('PICO', X(0), Y(12), X(7) - X(0) + 1, 9, { font: 'title', size: 18, bold: true, align: 'center' });
  s.box(X(3) - 3, Y(0) + 2, 8, 6, { fill: 'ink' });
  s.box(X(13) - 5, Y(10.5) - 5, 11, 11);
  s.block(X(13) - 2, Y(10.5) - 2, 5, 5, 'ink');
  s.box(X(13) - 3, Y(16) - 3, 7, 7, { fill: 'ink' });
  for (let r = 3; r <= 7; r++) s.rect(X(9), Y(r), 2, 2);
  s.frame(X(9) + 3, Y(7) - 2, 25, Y(3) - Y(7) + 5, 'ink', { dotted: true });
  const zr = 13.9, zx = X(13), zy = Y(21.5);
  for (let t = 0; t < 360; t += 7) s.rect(Math.round(zx + zr * Math.cos((t * Math.PI) / 180)), Math.round(zy + zr * Math.sin((t * Math.PI) / 180)), 1, 1);
  const lx = bx + bw + 3, lw = a.x + a.w - lx;
  const labels = [
    [zy, zx + zr + 1, 'MIC ZONE', 'parts under 4 mm'],
    [Y(16), X(13) + 4, 'LED', 'GP13'],
    [Y(10.5), X(13) + 6, 'BUTTON', 'GP14'],
    [Y(5), X(9) + 29, 'MIC PLUG', 'col 9, rows 3–7'],
    [Y(0) + 5, X(3) + 6, 'USB', ''],
  ];
  labels.forEach(([y, from, name, sub]) => {
    s.leader(from + 1, lx - 1, Math.round(y));
    s.text(name, lx, Math.round(y) - 8, lw, 8, { font: 'title', size: 18 });
    s.text(sub, lx, Math.round(y) + 1, lw, 7, { size: 9 });
  });
  s.text('A 1:1 template (layout.svg): print it, check the 40 mm bar, build the board on it.', a.x + 1, by + bh + 1, a.w - 2, 13, { size: 9, valign: 'top' });

  const b = s.window(164, 31, 148, 142, 'BUILD BOOK · 28 STEPS');
  const stages = [
    ['BREADBOARD · 1–10', ['1–4 Pico headers, button, LED, flash and test.', '5–10 rails, mic wires, L/R bridge, mic level.'], 2],
    ['NECKLACE · 11–28', ['11–15 template, place and solder the Pico.', '16–21 LED, button, mic header, beep test.', '22–28 measure, print, foam ring, plug, mic into the lid, close.'], 4],
    ['MEASURE FIRST', ['Measured values drive every hole in the OpenSCAD model. Asserts stop a change that breaks a fit, and the clash check must come out empty.'], 4],
  ];
  let y = b.y;
  stages.forEach(([title, lines, rows]) => {
    s.panel(b.x, y, b.w, 11);
    s.text(title, b.x + 4, y + 1, b.w - 8, 9, { font: 'title', size: 18, bold: true, color: 'paper' });
    s.text(lines.join('\n'), b.x + 1, y + 13, b.w - 2, rows * 6.5, { size: 10, valign: 'top' });
    y += 13 + rows * 6.5 + 5;
  });
  s.field();
  return s;
});

// On the pendant: the extractor and the link
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.pillars.push({ cx: 6, a: 6, top: 84 });
  s.header(n, 'Listening');
  const a = s.window(8, 31, 186, 140, 'EVERY 10 MS');
  const chain = ['16 KHZ MIC', 'PITCH', 'LABEL'];
  let x = a.x + 1;
  chain.forEach((c, i) => {
    const w = Math.ceil(textWidthArt(c, 'title', 18, true)) + 8;
    s.box(x, a.y + 1, w, 13);
    s.text(c, x, a.y + 1, w, 13, { font: 'title', size: 18, bold: true, align: 'center' });
    x += w;
    if (i < chain.length - 1) { s.glyph(G.Marks.right, x + 2, a.y + 4, 'ink'); x += 8; }
  });
  s.text('Every 10 ms the pendant looks at the last 32 ms of sound, tracks pitch (MPM) and the noise floor, and labels each finished sound: rise, fall, arch, dip, flat, pop, click, hiss or unknown. The code is a C++ port of the Python reference extractor, on the Pico\'s second core.',
    a.x + 1, a.y + 19, a.w - 2, 44, { size: 12, valign: 'top' });
  s.statRow(a.x + 1, a.y + 66, a.w - 2, { label: 'HOP COST', value: '16% of budget' });
  s.meter(a.x + 1, a.y + 79, a.w - 2, 0.16);
  s.statRow(a.x + 1, a.y + 88, a.w - 2, { label: 'CORE 1 LOAD', value: '15.6%' });
  s.meter(a.x + 1, a.y + 101, a.w - 2, 0.156);
  s.statRow(a.x + 1, a.y + 110, a.w - 2, { label: 'TEST VECTORS', value: '19 / 19 pass' });

  const b = s.window(200, 31, 112, 140, 'BLE LINK');
  s.panel(b.x, b.y, b.w, 44);
  [['EVENT', 'notify'], ['CONFIG', 'write'], ['INFO', 'read']].forEach(([label, value], i) =>
    s.statRow(b.x + 4, b.y + 4 + i * 13, b.w - 8, { label, value, c: 'paper' }));
  s.text(bullets([
    'Encrypted bonding; new bonds only in a 60 s window.',
    'Every command gets one reply, or times out at 1.5 s.',
    'A dropped link disarms.',
  ]), b.x + 1, b.y + 49, b.w - 2, b.h - 50, { size: 11, valign: 'top', paraSpaceAfter: 4 });
  s.field();
  return s;
});

// On the phone
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'On the phone');
  const a = s.window(8, 31, 304, 64, 'ANDROID APP');
  const stages = [
    ['SOURCE', 'pendant, phone mic or USB mic'],
    ['GROUP', 'groups sounds on the device clock'],
    ['MATCH', 'matches your enrolled sounds'],
    ['DECIDE', 'rules first, a model for hard cases'],
    ['ACT', 'gestures via accessibility'],
  ];
  const bw = 50, gap = (a.w - 5 * bw) / 4;
  stages.forEach(([t, d], i) => {
    const x = Math.round(a.x + i * (bw + gap));
    s.box(x, a.y + 2, bw, 15, { fill: 'ink' });
    s.text(t, x, a.y + 2, bw, 15, { font: 'title', size: 18, bold: true, align: 'center', color: 'paper' });
    s.text(d, x, a.y + 21, bw, 40, { size: 11, valign: 'top' });
    if (i < 4) s.glyph(G.Marks.right, Math.round(x + bw + gap / 2 - 2), a.y + 6, 'ink');
  });
  const g = s.window(8, 101, 150, 72, 'GUARDS');
  s.text(bullets([
    'Likes, follows and shares need a confirm pop.',
    'A stale screen tree is refused.',
    'Model calls time out; late answers are dropped.',
  ]), g.x + 1, g.y, g.w - 2, g.h, { size: 12, valign: 'top', paraSpaceAfter: 4 });
  const p = s.window(164, 101, 148, 72, 'PHRASES');
  s.text(bullets([
    '"pop pop" opens a 6 s window.',
    'On-device speech recognition, offline.',
    'Timers, volume, open app, tap a target, type.',
  ]), p.x + 1, p.y, p.w - 2, p.h, { size: 12, valign: 'top', paraSpaceAfter: 4 });
  s.field();
  return s;
});

// Deciding
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'Deciding');
  const a = s.window(8, 31, 176, 140, 'RULES FIRST');
  s.text('Seconds from the end of a sound to the action (estimates):', a.x + 1, a.y, a.w - 2, 16, { size: 11, valign: 'top' });
  const sx = a.x + 4, sw = a.w - 10, scale = (v) => sx + Math.round(v * sw);
  const bars = [['FAST PATH', 0.2, 0.45], ['PHONE MODEL', 0.2, 0.5], ['CLOUD MODEL', 0.45, 0.9]];
  bars.forEach(([label, lo, hi], i) => {
    const y = a.y + 19 + i * 20;
    s.text(label, sx, y, 80, 8, { font: 'title', size: 18, bold: true });
    s.block(scale(lo), y + 9, scale(hi) - scale(lo), 6, 'ink');
  });
  const ay = a.y + 80;
  s.hline(sx, ay, sw + 1);
  [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
    s.vline(scale(v), ay, 3);
    s.text(v === 0 ? '0' : v.toFixed(2).replace(/0$/, '') + ' s', scale(v) - 12, ay + 4, 24, 7, { size: 10, align: 'center' });
  });
  s.text('A 225 ms lag tripled pointing errors (MacKenzie & Ware 1993). So fixed bindings act locally, and models only get what rules cannot settle.',
    a.x + 1, ay + 13, a.w - 2, a.h - (ay + 13 - a.y), { size: 11, valign: 'top' });

  const b = s.window(190, 31, 122, 140, 'MODELS');
  const models = [
    ['RULES', 'On the phone today.', null],
    ['VERDICT 118M', 'Target picker. Chosen for the phone; not on it yet.', COLORS.signalYellow],
    ['JEVLIKE', 'Gesture decider, served on the PC.', null],
    ['CLOUD', 'DeepSeek via Ollama, hard cases only.', null],
  ];
  let y = b.y;
  models.forEach(([name, d, lamp]) => {
    s.lamp(b.x + 1, y, lamp);
    s.text(name, b.x + 16, y + 1, b.w - 16, 9, { font: 'title', size: 18, bold: true });
    const lines = Math.ceil(d.length / Math.floor(((b.w - 16) * PT_PER_ART) / 6.6));
    s.text(d, b.x + 16, y + 11, b.w - 17, lines * 6.5 + 1, { size: 11, valign: 'top' });
    y += 12 + lines * 6.5 + 4;
  });
  s.field();
  return s;
});

// Your voice
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'Your voice');
  const a = s.window(8, 31, 180, 140, 'TRAIN GESTURES');
  const cards = [['rise', 7, 8], ['fall', 0, 8], ['arch', 5, 8], ['dip', 0, 8], ['flat', 0, 8], ['pop', 4, 4], ['click', 2, 4], ['hiss', 0, 4]];
  const cw = Math.floor((a.w - 4) / 2), ch = 22;
  cards.forEach(([g, n, m], i) => {
    const x = a.x + (i % 2) * (cw + 4), y = a.y + Math.floor(i / 2) * (ch + 3);
    const inv = n === m;
    s.box(x, y, cw, ch, { fill: inv ? 'ink' : 'paper' });
    const c = inv ? 'paper' : 'ink';
    s.glyph(G.GestureGlyphs[g], x + 3, y + 5, c);
    s.text(g.toUpperCase(), x + 19, y + 2, 50, 9, { font: 'title', size: 18, bold: true, color: c });
    s.meter(x + 19, y + 13, cw - 42, n / m, c);
    s.text(`${n}/${m}`, x + cw - 21, y + 11, 18, 9, { size: 10, color: c, align: 'right' });
  });
  s.text('Each take is one variation: hummed or whistled, low or high, slow or quick. Takes save as you go.',
    a.x, a.y + 4 * (ch + 3) + 1, a.w, 22, { size: 11, valign: 'top' });

  const b = s.window(194, 31, 118, 140, 'ENROL YOUR OWN');
  const kinds = [
    ['CUSTOM SOUND', 'Invent one (a meow, a trill). It becomes my sound "meow"; bind it with a rule.'],
    ['IGNORE SOUND', 'Your sneeze, the kettle. Always does nothing.'],
    ['YOUR GESTURE', 'Your own rise or pop, trusted over the default.'],
  ];
  let y = b.y;
  kinds.forEach(([k, d]) => {
    s.panel(b.x, y, b.w, 11);
    s.text(k, b.x + 4, y + 1, b.w - 8, 9, { font: 'title', size: 18, bold: true, color: 'paper' });
    s.text(d, b.x + 1, y + 13, b.w - 2, 22, { size: 11, valign: 'top' });
    y += 34;
  });
  s.text('3–5 examples each, matched on the phone before any model.', b.x + 1, y + 1, b.w - 2, 14, { size: 10, valign: 'top' });
  s.field();
  return s;
});

// The look
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'The look');
  const a = s.window(8, 31, 192, 140, 'THE PIXEL KIT');
  s.block(a.x, a.y, 30, 20, 'ink');
  s.text('INK', a.x, a.y + 2, 30, 8, { font: 'title', size: 18, bold: true, color: 'paper', align: 'center' });
  s.text('1D2757', a.x, a.y + 10, 30, 8, { size: 9, color: 'paper', align: 'center' });
  s.box(a.x + 34, a.y, 36, 20);
  s.text('PAPER', a.x + 34, a.y + 2, 36, 8, { font: 'title', size: 18, bold: true, align: 'center' });
  s.text('DDEBD3', a.x + 34, a.y + 10, 36, 8, { size: 9, align: 'center' });
  s.text('Two tones, no greys. A shade is a density of dots.', a.x + 76, a.y - 1, a.w - 76, 22, { size: 11, valign: 'middle' });
  const bw = Math.floor(a.w / 4);
  const btn = [['MAIN', { main: true }], ['PRESS', { pressed: true }], ['OFF', { disabled: true }], ['FOCUS', { focused: true }]];
  btn.forEach(([l, o], i) => s.button(a.x + i * bw, a.y + 25, bw - 2, 19, l, o));
  s.text('Buttons: double frame for the main action, inverted when pressed, dotted when disabled, corner brackets for focus.',
    a.x, a.y + 46, a.w, 20, { size: 11, valign: 'top' });
  s.hatch(a.x, a.y + 70, 60, 34, 'ink');
  s.box(a.x + 12, a.y + 81, 36, 12);
  s.text('EMPTY', a.x + 12, a.y + 81, 36, 12, { font: 'title', size: 18, bold: true, align: 'center' });
  s.pips(a.x + 66, a.y + 70, 3, 4);
  s.meter(a.x + 66, a.y + 86, 60, 0.6);
  s.text('Hatch for empty areas; pips and bars for meters; motion flickers on in whole steps, never fades.',
    a.x + 132, a.y + 67, a.w - 132, 40, { size: 10, valign: 'top' });
  s.text('Type here: Silkscreen for titles and labels, IBM Plex Mono for reading. The app uses Press Start 2P and Tiny5.',
    a.x, a.y + 107, a.w, 20, { size: 10, valign: 'top' });

  const b = s.window(206, 31, 106, 66, 'SIGNALS');
  [[COLORS.signalOrange, 'LISTENING'], [COLORS.signalYellow, 'WAITING'], [COLORS.signalRed, 'STOP']].forEach(([c, l], i) => {
    s.lamp(b.x + 1, b.y + 1 + i * 15, c);
    s.text(l, b.x + 16, b.y + 2 + i * 15, 70, 9, { font: 'title', size: 18, bold: true });
  });
  s.badgeFrame('idle', 214, 110, 6);
  s.badgeFrame('scroll_up', 254, 110, 6);
  s.text('Canti, the badge', 208, 160, 100, 8, { size: 10, onField: true, align: 'center' });
  s.pillars.push({ cx: 150, a: 7, top: 60 });
  s.field();
  return s;
});

// Where it stands (the round 6 handoff)
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.header(n, 'Where it stands');
  const a = s.window(8, 31, 304, 142, 'ROUND 6 · 2026-09-27');
  const rows = [
    [null, 'JVM TESTS', '498 / 498 pass'],
    [null, 'PYTEST', '145 pass + 8 xfail'],
    [null, 'FLUTTER', '94 ui + 10 desktop pass'],
    [null, 'FIRMWARE PARITY', 'pass'],
    [null, 'VERDICT WRONG TAPS', '0.036 (bound 0.050)'],
    [COLORS.signalRed, 'VERDICT NONE RECALL', '0.62 (gate 0.8)'],
    [COLORS.signalRed, 'EMULATOR SUITE', '12 pass · 11 fail'],
    [COLORS.signalRed, 'PENDANT MIC', 'reads all zeros'],
    [COLORS.signalYellow, 'B4A CROSS-FIT', 'interrupted, rerun'],
  ];
  rows.forEach(([lamp, label, value], i) => {
    const y = a.y + i * 13.5;
    s.lamp(a.x + 1, Math.round(y), lamp);
    s.statRow(a.x + 16, Math.round(y), a.w - 18, { label, value });
  });
  s.field();
  return s;
});

// Next
slides.push((n) => {
  const s = new Slide(LIGHT);
  s.pillars.push({ cx: 150, a: 8, top: 74 }, { cx: 138, a: 5, top: 80 });
  s.header(n, 'Next');
  const a = s.window(8, 31, 196, 142, 'DO FIRST');
  const todo = [
    'Find why 11 emulator tests fail: gesture confirmation and cursor taps.',
    'Check the pendant mic wiring on the lid header.',
    'Rerun the Verdict b4a cross-fit and refit the phone thresholds.',
    'Calibrate the phone mic: clicks, whistle, hiss, room.',
    'Recapture three screen sets with the badge hidden.',
    'Fold this session into the decision log.',
  ];
  todo.forEach((t, i) => {
    const y = a.y + i * 20;
    s.box(a.x, y, 13, 13);
    s.text(String(i + 1), a.x, y, 13, 13, { font: 'title', size: 18, bold: true, align: 'center' });
    s.text(t, a.x + 17, y - 1, a.w - 18, 16, { size: 11, valign: 'middle' });
  });
  const b = s.window(210, 31, 102, 52, 'HOUSE RULE');
  s.text('Before any phone install: run the emulator suite and a launch check. Unit tests never build the real screen, and that let a launch crash through.',
    b.x + 1, b.y, b.w - 2, b.h, { size: 10, valign: 'top' });
  s.field();
  return s;
});

// End
slides.push((n) => {
  const s = new Slide(DARK);
  s.pillars.push({ cx: 12, a: 9, top: 70 }, { cx: 148, a: 9, top: 72 }, { cx: 134, a: 5, top: 80 });
  s.badgeFrame('idle', 58, 38, 12);
  s.text('Thanks.', 150, 62, 150, 22, { font: 'title', size: 54, bold: true, onField: true });
  s.text('Questions?', 150, 88, 150, 12, { size: 18, onField: true });
  s.text('Design docs: wiki/index.md  ·  Brand: brand/README.md', 150, 106, 160, 16, { size: 11, onField: true, valign: 'top' });
  s.field({ top: 30 });
  return s;
});

const pres = new PptxGenJS();
pres.layout = 'LAYOUT_16x9';
pres.title = 'Canti: project overview';
pres.company = 'VOX';
slides.forEach((make, i) => emit(pres, make(i), i + 1));
for (const w of warnings) console.warn('fit:', w);
pres.writeFile({ fileName: OUT }).then((f) => console.log('wrote', f));
