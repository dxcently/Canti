// Isometric 1-bit renders of STL meshes, on the art-pixel grid: ink outlines where the silhouette, a depth step or a
// crease is, and the faces shaded as ordered-dither ink density (the kit's "a shade is a density of dots").

const BAYER4 = [
  [0, 8, 2, 10],
  [12, 4, 14, 6],
  [3, 11, 1, 9],
  [15, 7, 13, 5],
];

// ASCII STL (what OpenSCAD writes) to triangles [[x, y, z] x 3].
function readStl(text) {
  const v = [...text.matchAll(/vertex\s+(\S+)\s+(\S+)\s+(\S+)/g)].map((m) => [+m[1], +m[2], +m[3]]);
  const tris = [];
  for (let i = 0; i + 2 < v.length; i += 3) tris.push([v[i], v[i + 1], v[i + 2]]);
  return tris;
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(...a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

// Render [tris] seen from [yaw] degrees round z and [el] degrees above the horizon, [scale] art px per mm.
// Returns { w, h, px, marks } with px[i] = 0 empty, 1 ink, 2 paper, and [marks] (3D points) in art px on the render.
function renderIso(tris, { yaw = 30, el = 45, scale = 1.2, ss = 3, crease = 0.6, step = 1.2, tones = [0.7, 0.4, 0.1], marks = [] } = {}) {
  const cy = Math.cos((yaw * Math.PI) / 180), sy = Math.sin((yaw * Math.PI) / 180);
  const ce = Math.cos((el * Math.PI) / 180), se = Math.sin((el * Math.PI) / 180);
  const right = [cy, sy, 0];
  const back = [-sy, cy, 0];
  const up = [back[0] * se, back[1] * se, ce]; // screen up
  const toward = [-back[0] * ce, -back[1] * ce, se]; // towards the viewer
  const light = norm([right[0] * 0.45 + up[0] * 0.55 + toward[0] * 0.7, right[1] * 0.45 + up[1] * 0.55 + toward[1] * 0.7, up[2] * 0.55 + toward[2] * 0.7]);

  const proj = (p) => [dot(p, right), -dot(p, up), dot(p, toward)];
  const P = tris.map((t) => t.map(proj));
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const t of P) for (const [x, y] of t) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  const w = Math.ceil((x1 - x0) * scale) + 3, h = Math.ceil((y1 - y0) * scale) + 3;
  const W = w * ss, H = h * ss, k = scale * ss;

  const depth = new Float32Array(W * H).fill(-Infinity);
  const nrm = new Array(W * H);
  P.forEach((t, ti) => {
    let n = norm(cross(sub(tris[ti][1], tris[ti][0]), sub(tris[ti][2], tris[ti][0])));
    if (dot(n, toward) < 0) n = [-n[0], -n[1], -n[2]];
    const q = t.map(([x, y, d]) => [(x - x0) * k + ss, (y - y0) * k + ss, d]);
    const minx = Math.max(0, Math.floor(Math.min(q[0][0], q[1][0], q[2][0])));
    const maxx = Math.min(W - 1, Math.ceil(Math.max(q[0][0], q[1][0], q[2][0])));
    const miny = Math.max(0, Math.floor(Math.min(q[0][1], q[1][1], q[2][1])));
    const maxy = Math.min(H - 1, Math.ceil(Math.max(q[0][1], q[1][1], q[2][1])));
    const area = (q[1][0] - q[0][0]) * (q[2][1] - q[0][1]) - (q[2][0] - q[0][0]) * (q[1][1] - q[0][1]);
    if (Math.abs(area) < 1e-9) return;
    for (let py = miny; py <= maxy; py++) {
      for (let px = minx; px <= maxx; px++) {
        const sx = px + 0.5, syy = py + 0.5;
        const w0 = ((q[1][0] - sx) * (q[2][1] - syy) - (q[2][0] - sx) * (q[1][1] - syy)) / area;
        const w1 = ((q[2][0] - sx) * (q[0][1] - syy) - (q[0][0] - sx) * (q[2][1] - syy)) / area;
        const w2 = 1 - w0 - w1;
        if (w0 < -1e-6 || w1 < -1e-6 || w2 < -1e-6) continue;
        const d = w0 * q[0][2] + w1 * q[1][2] + w2 * q[2][2];
        const i = py * W + px;
        if (d > depth[i]) { depth[i] = d; nrm[i] = n; }
      }
    }
  });

  // Down to art pixels: covered if most samples are; the front-most sample gives depth and normal.
  const D = new Float32Array(w * h).fill(-Infinity), N = new Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let hits = 0, best = -Infinity, bn = null;
    for (let v = 0; v < ss; v++) for (let u = 0; u < ss; u++) {
      const i = (y * ss + v) * W + x * ss + u;
      if (depth[i] === -Infinity) continue;
      hits++;
      if (depth[i] > best) { best = depth[i]; bn = nrm[i]; }
    }
    if (hits * 2 > ss * ss) { D[y * w + x] = best; N[y * w + x] = bn; }
  }

  const px = new Uint8Array(w * h);
  const on = (x, y) => x >= 0 && y >= 0 && x < w && y < h && D[y * w + x] !== -Infinity;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    if (!on(x, y)) continue;
    let edge = !on(x - 1, y) || !on(x + 1, y) || !on(x, y - 1) || !on(x, y + 1);
    for (const [nx, ny] of [[x + 1, y], [x, y + 1], [x - 1, y], [x, y - 1]]) {
      if (edge || !on(nx, ny)) continue;
      const j = ny * w + nx;
      if (D[i] - D[j] > step) edge = true; // this pixel is the nearer side of a step
      else if (Math.abs(D[i] - D[j]) <= step && (nx > x || ny > y) && dot(N[i], N[j]) < crease) edge = true;
    }
    if (edge) { px[i] = 1; continue; }
    const s = Math.max(0, dot(N[i], light));
    const dens = s > tones[0] ? 0 : s > tones[1] ? 0.25 : s > tones[2] ? 0.5 : 0.75;
    px[i] = (BAYER4[y & 3][x & 3] + 0.5) / 16 < dens ? 1 : 2;
  }
  const at = marks.map((m) => { const [x, y] = proj(m); return [Math.round((x - x0) * scale + 1), Math.round((y - y0) * scale + 1)]; });
  return { w, h, px, marks: at };
}

// Rigid transforms for placing a part before the render.
const rotX = (deg) => (p) => { const c = Math.cos((deg * Math.PI) / 180), s = Math.sin((deg * Math.PI) / 180); return [p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c]; };
const move = (dx, dy, dz) => (p) => [p[0] + dx, p[1] + dy, p[2] + dz];
const apply = (tris, ...fs) => tris.map((t) => t.map((p) => fs.reduce((q, f) => f(q), p)));

module.exports = { readStl, renderIso, rotX, move, apply };
