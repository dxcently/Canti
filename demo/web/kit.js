// The Canti 1-bit pixel kit for the web: a port of ui/lib/src/theme (pixel.dart, kit.dart, dither_field.frag).
// Everything is drawn on whole art pixels; one art pixel is a whole number of device pixels (about 2 CSS px).

export const COLORS = {
  mint: '#DDEBD3', navy: '#1D2757', orange: '#F2A33A', yellow: '#F6C945', red: '#D6453D',
};

export const theme = { dark: true, ink: COLORS.mint, paper: COLORS.navy };

export function setTheme(dark) {
  theme.dark = dark;
  theme.ink = dark ? COLORS.mint : COLORS.navy;
  theme.paper = dark ? COLORS.navy : COLORS.mint;
  const r = document.documentElement.style;
  r.setProperty('--ink', theme.ink);
  r.setProperty('--paper', theme.paper);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

/** Device px per art px (whole), and the CSS size of one art px. */
export function artPx() {
  const dpr = window.devicePixelRatio || 1;
  const dev = Math.max(1, Math.round(2 * dpr));
  return { dev, css: dev / dpr };
}

export function applyScale() {
  document.documentElement.style.setProperty('--p', `${artPx().css}px`);
}

/** Drawing in art pixels on a canvas whose backing store is in device pixels. */
export class PixelCanvas {
  constructor(canvas, w, h) {
    const { dev, css } = artPx();
    this.u = dev;
    this.w = w;
    this.h = h;
    canvas.width = w * dev;
    canvas.height = h * dev;
    canvas.style.width = `${w * css}px`;
    canvas.style.height = `${h * css}px`;
    this.ctx = canvas.getContext('2d');
    this.ctx.imageSmoothingEnabled = false;
  }

  clear() { this.ctx.clearRect(0, 0, this.w * this.u, this.h * this.u); }

  rect(x, y, w, h, c) {
    if (w <= 0 || h <= 0) return;
    this.ctx.fillStyle = c;
    this.ctx.fillRect(x * this.u, y * this.u, w * this.u, h * this.u);
  }

  hline(x, y, w, c) { this.rect(x, y, w, 1, c); }
  vline(x, y, h, c) { this.rect(x, y, 1, h, c); }

  /** A 1-pixel outline; notch leaves the four corner pixels out (the kit's clipped corners). */
  frame(x, y, w, h, c, { notch = false, dotted = false } = {}) {
    if (w <= 0 || h <= 0) return;
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

  /** A filled rect with notched corners. */
  block(x, y, w, h, c) {
    this.rect(x + 1, y, w - 2, h, c);
    this.rect(x, y + 1, 1, h - 2, c);
    this.rect(x + w - 1, y + 1, 1, h - 2, c);
  }

  /** Corner brackets: the kit's hover/focus cursor. */
  brackets(x, y, w, h, c, arm = 4, t = 2) {
    for (const [cx, cy, sx, sy] of [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]]) {
      this.rect(sx > 0 ? cx : cx - arm, sy > 0 ? cy : cy - t, arm, t, c);
      this.rect(sx > 0 ? cx : cx - t, sy > 0 ? cy : cy - arm, t, arm, c);
    }
  }

  /** The diagonal hatch for empty areas. */
  hatch(x, y, w, h, c, step = 4) {
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) if ((i + j) % step === 0) this.rect(x + i, y + j, 1, 1, c);
  }
}

// ---------------------------------------------------------------- chrome painted behind DOM elements

const painters = new Map();
const ro = new ResizeObserver((entries) => entries.forEach((e) => paintChrome(e.target)));

/** Give an element a painted background canvas (kind: window | panel | box | button). */
export function chrome(el) {
  let cv = el.querySelector(':scope > canvas.chrome');
  if (!cv) {
    cv = document.createElement('canvas');
    cv.className = 'chrome';
    el.prepend(cv);
  }
  painters.set(el, cv);
  ro.observe(el);
  paintChrome(el);
}

export function repaintAll() { painters.forEach((_, el) => paintChrome(el)); }

export function paintChrome(el) {
  const cv = painters.get(el);
  if (!cv) return;
  const { css } = artPx();
  const w = Math.max(4, Math.floor(el.clientWidth / css));
  const h = Math.max(4, Math.floor(el.clientHeight / css));
  const c = new PixelCanvas(cv, w, h);
  const { ink, paper } = theme;
  const kind = el.dataset.kind;
  if (kind === 'window') {
    const label = (el.dataset.title || '').toUpperCase();
    const tabH = 12, y = tabH / 2 - 1, tab = label.length * 8 + 6;
    c.block(0, y, w, h - y, paper);
    c.frame(0, y, w, h - y, ink, { notch: true });
    c.frame(2, y + 2, w - 4, h - y - 4, ink);
    c.rect(4, h - 5, 1, 1, ink);
    c.rect(w - 5, h - 5, 1, 1, ink);
    c.rect(w - 5, y + 4, 1, 1, ink);
    c.block(5, 0, tab, tabH, paper);
    c.frame(5, 0, tab, tabH, ink, { notch: true });
  } else if (kind === 'panel') {
    c.block(0, 0, w, h, ink);
    c.frame(1, 1, w - 2, h - 2, paper, { notch: true });
  } else if (kind === 'box') {
    const inv = el.classList.contains('inv');
    c.block(0, 0, w, h, inv ? ink : paper);
    c.frame(0, 0, w, h, ink, { notch: true });
  } else if (kind === 'button') {
    const m = 2, bw = w - 2 * m, bh = h - 2 * m;
    const disabled = el.disabled;
    const inv = !disabled && (el.classList.contains('on') || el.classList.contains('down'));
    c.block(m, m, bw, bh, inv ? ink : paper);
    if (disabled) c.frame(m, m, bw, bh, ink, { dotted: true });
    else {
      c.frame(m, m, bw, bh, ink, { notch: true });
      if (el.classList.contains('main')) c.frame(m + 2, m + 2, bw - 4, bh - 4, inv ? paper : ink);
    }
    if (!disabled && (el.matches(':hover') || el.matches(':focus-visible'))) c.brackets(0, 0, w, h, ink, 4, 1);
  } else if (kind === 'hatch') {
    c.hatch(0, 0, w, h, ink);
  }
}

/** Buttons: repaint on hover/press, like the kit's states. */
export function pixelButton(el) {
  el.dataset.kind = 'button';
  chrome(el);
  for (const ev of ['mouseenter', 'mouseleave', 'focus', 'blur']) el.addEventListener(ev, () => paintChrome(el));
  el.addEventListener('pointerdown', () => { el.classList.add('down'); paintChrome(el); });
  for (const ev of ['pointerup', 'pointerleave']) el.addEventListener(ev, () => { el.classList.remove('down'); paintChrome(el); });
}

// ---------------------------------------------------------------- the dot field (dither_field.frag, per cell on the CPU)

const fract = (x) => x - Math.floor(x);
const bayer2 = (x, y) => { x = Math.floor(x); y = Math.floor(y); return fract(x * 0.5 + y * y * 0.75); };
const bayer4 = (x, y) => bayer2(0.5 * x, 0.5 * y) * 0.25 + bayer2(x, y);
const hash = (x, y) => fract(Math.sin(x * 12.9898 + y * 78.233) * 43758.5453);
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

function pillar(cx, cy, tx, ty, a, h) {
  const dx = cx - tx, dy = cy - ty;
  if (Math.abs(dx) / a + Math.abs(dy) / (0.5 * a) <= 1) return 1;
  if (Math.abs(dx) > a) return -1;
  const depth = dy - (0.5 * a - 0.5 * Math.abs(dx));
  if (depth < 0 || depth > h) return -1;
  return (dx < 0 ? 0.5 : 0.25) * (1 - smooth(h * 0.55, h, depth));
}

/**
 * The dot field. `clear()` returns the viewport rects (CSS px) of things drawn straight on the field (the wordmark):
 * around each one the field opens a clearing, never a plate: no dots within `margin` cells, then they come back over
 * `ramp` cells in the same ordered dither (clearing.dart).
 */
export function ditherField(canvas, { cell = 4, reach = 0.34, fps = 6, clear = () => [], margin = 2, ramp = 3 } = {}) {
  let t0 = performance.now();
  function draw() {
    const { dev, css } = artPx();
    const W = Math.ceil(innerWidth / css), H = Math.ceil(innerHeight / css);
    const nx = Math.ceil(W / cell), ny = Math.ceil(H / cell);
    const c = new PixelCanvas(canvas, nx * cell, ny * cell);
    c.clear();
    const px = css * cell;   // CSS px per cell
    const holes = clear().filter((r) => r && r.width && r.bottom > 0 && r.top < innerHeight)
      .map((r) => [Math.floor(r.left / px), Math.floor(r.top / px), Math.ceil(r.right / px) - 1, Math.ceil(r.bottom / px) - 1]);
    const cleared = (x, y) => {
      let d = Infinity;
      for (const [x0, y0, x1, y1] of holes) d = Math.min(d, Math.max(x0 - x, 0, x - x1, y0 - y, y - y1));
      if (d <= margin) return true;
      return d < margin + ramp && bayer4(x + 2, y + 5) >= (d - margin) / ramp;
    };
    const t = (performance.now() - t0) / 1000;
    const bobs = [0.5, 0.43, 0.37].map((f, i) => Math.floor(Math.sin(t * f + [0, 2, 4][i]) * 1.2 + 0.5));
    const pillars = [[nx - 7, ny - 13 + bobs[0], 6, 16], [nx - 19, ny - 20 + bobs[1], 5, 22], [8, ny - 16 + bobs[2], 6, 18]];
    const fade = 3;
    for (let y = 0; y < ny; y++) {
      for (let x = 0; x < nx; x++) {
        const wave = Math.floor(2 * Math.sin(x * 0.13 + t * 0.35) + 1.5 * Math.sin(x * 0.047 - t * 0.21));
        const f = 1 - Math.min(1, Math.max(0, (y + wave) / (ny * reach)));
        const jitter = (hash(Math.floor(x / 3), Math.floor(y / 3)) - 0.5) * 0.35;
        let d = Math.min(0.5, Math.max(0, f * f * 0.75 + jitter * f));
        let pil = -1;
        for (const [px, py, a, h] of pillars) { const v = pillar(x, y, px, py, a, h); if (v >= 0) { pil = v; break; } }
        if (pil >= 0) d = pil;
        const edge = Math.min(x, y, nx - 1 - x) / fade;
        if (edge < 1 && bayer4(x + 7, y + 3) > edge) d = 0;
        if (d > bayer4(x, y) && !(holes.length && cleared(x, y))) c.rect(x * cell, y * cell, cell - 1, cell - 1, theme.ink);
      }
    }
  }
  draw();
  let last = 0;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  function loop(now) {
    if (now - last > 1000 / fps) { last = now; draw(); }
    if (!reduce) requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  addEventListener('resize', draw);
  addEventListener('scroll', draw, { passive: true });
  return { redraw: draw };
}

/** Things switch on like a pixel screen: off, on, off, on, in whole steps. */
export function blinkOn(el, times = 2, ms = 70) {
  let n = 0;
  el.style.visibility = 'hidden';
  const iv = setInterval(() => {
    el.style.visibility = n % 2 ? 'hidden' : 'visible';
    if (++n >= times * 2 - 1) { clearInterval(iv); el.style.visibility = 'visible'; }
  }, ms);
}
