import { COLORS, PixelCanvas, applyScale, artPx, blinkOn, chrome, ditherField, paintChrome, pixelButton, repaintAll,
  setTheme, theme } from './kit.js';
import { SCRIPTS, WIKI_URL, stepText } from './scripts.js';

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const S = {
  target: localStorage.getItem('canti.target') || 'emulator',
  sounds: {}, fpNames: [], fpRange: [],
  running: false, step: 0, busy: false,
  msgNo: 0, lastMsgT: null, waiter: null,
};

// ---------------------------------------------------------------- api

async function cmd(body) {
  try {
    const r = await fetch('/api/cmd', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: S.target, ...body }) });
    return await r.json();
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// ---------------------------------------------------------------- the mic: 10 ms frames, replayed in real time

let MIC_W = 300;
const PITCH_H = 46, ENERGY_H = 20, MIC_H = PITCH_H + ENERGY_H + 3;
const F_LO = 70, F_HI = 700;
const mic = { cols: [], queue: [], clock: 0, seed: 7, cv: null };

function rnd() { mic.seed = (mic.seed * 1103515245 + 12345) & 0x7fffffff; return mic.seed / 0x7fffffff; }

function idleFrame() {
  return { e: -57 + rnd() * 3, f0: 80 + rnd() * 900, clar: rnd() * 0.4, cent: 1200 + rnd() * 900 };
}

/** Queue a sound's frames; resolves when the sound has ended (plus the 100 ms hangover), as the device sends then. */
function playSound(name, { pre = true, holdMs = 0 } = {}) {
  const s = S.sounds[name];
  let rows = s.frames.filter((r) => pre || r[0] >= -20);
  if (holdMs) {
    const body = rows.filter((r) => r[0] >= 0 && r[0] < s.dur_ms);
    const mid = body.slice(10, body.length - 10);
    const head = rows.filter((r) => r[0] < 0), tail = rows.filter((r) => r[0] >= s.dur_ms);
    const need = Math.max(0, Math.round(holdMs / 10) - body.length);
    const loop = [];
    for (let i = 0; i < need; i++) loop.push(mid[i % mid.length]);
    rows = [...head, ...body.slice(0, 10), ...loop, ...body.slice(10), ...tail];
  }
  const endAt = (holdMs || s.dur_ms) + 100;
  return new Promise((resolve) => {
    let t = rows.length ? rows[0][0] : 0, fired = false;
    rows.forEach((r, i) => {
      const f = { e: r[1], f0: r[2], clar: r[3], cent: r[4], live: true };
      const tt = holdMs ? (i - (rows.findIndex((x) => x[0] >= 0))) * 10 : r[0];
      if (!fired && tt >= endAt) { fired = true; f.onPush = resolve; }
      mic.queue.push(f);
      t = tt;
    });
    if (!fired) mic.queue.push({ ...idleFrame(), onPush: resolve });
  });
}

function idle(ms) {
  for (let i = 0; i < ms / 10; i++) mic.queue.push(idleFrame());
  return new Promise((r) => { mic.queue.push({ ...idleFrame(), onPush: r }); });
}

function micTick(now) {
  if (!mic.clock) mic.clock = now;
  let n = Math.min(30, Math.floor((now - mic.clock) / 10));
  mic.clock += n * 10;
  let last = null;
  while (n-- > 0) {
    const f = mic.queue.length ? mic.queue.shift() : idleFrame();
    mic.cols.push(f);
    if (f.onPush) f.onPush();
    last = f;
  }
  if (mic.cols.length > MIC_W) mic.cols.splice(0, mic.cols.length - MIC_W);
  if (last) { drawMic(); micStats(last); }
  requestAnimationFrame(micTick);
}

function yPitch(f0) {
  const v = Math.log2(f0 / F_LO) / Math.log2(F_HI / F_LO);
  return Math.round((PITCH_H - 2) * (1 - Math.min(1, Math.max(0, v)))) + 1;
}

function drawMic() {
  const c = mic.cv;
  if (!c) return;
  const ink = theme.paper, bg = theme.ink;   // inverted panel: paper on ink
  c.rect(0, 0, MIC_W, MIC_H, bg);
  for (const hz of [100, 200, 400]) {
    const y = yPitch(hz);
    for (let x = 0; x < MIC_W; x += 4) c.rect(x, y, 1, 1, ink);
  }
  let prev = null;
  mic.cols.forEach((f, x) => {
    const voiced = f.clar >= 0.6 && f.f0 > 0;
    if (voiced) {
      const y = yPitch(f.f0);
      if (prev !== null && Math.abs(prev - y) > 1) c.rect(x, Math.min(prev, y), 1, Math.abs(prev - y), ink);
      c.rect(x, y - 1, 1, 2, ink);
      prev = y;
    } else prev = null;
    const h = Math.round(ENERGY_H * Math.min(1, Math.max(0, (f.e + 66) / 44)));
    const y0 = MIC_H - h;
    if (h > 0) c.rect(x, y0, 1, 1, ink);
    for (let y = y0 + 1; y < MIC_H; y++) if ((x + y) % 2 === 0) c.rect(x, y, 1, 1, ink);
  });
  c.rect(0, PITCH_H + 1, MIC_W, 1, ink);
}

function micStats(f) {
  const voiced = f.clar >= 0.6 && f.f0 > 0;
  $('s-f0').textContent = voiced ? `${Math.round(f.f0)} Hz` : '–';
  $('s-level').textContent = `${Math.round(f.e)} dBFS`;
  $('s-clar').textContent = f.clar.toFixed(2);
  $('s-cent').textContent = `${Math.round(f.cent)} Hz`;
}

// ---------------------------------------------------------------- the extractor readout

let P16_W = 132;
const P16_H = 44, FP_W = 24 * 6 + 1, FP_H = 34;
let p16cv, fpcv;

function drawP16(pts, upto = 16) {
  const c = p16cv, bg = theme.ink, fg = theme.paper;
  c.rect(0, 0, P16_W, P16_H, bg);
  const mid = Math.round(P16_H / 2);
  for (let x = 0; x < P16_W; x += 4) c.rect(x, mid, 1, 1, fg);
  if (!pts || !pts.length) { c.hatch(0, 0, P16_W, P16_H, fg, 6); return; }
  const lim = Math.max(8, ...pts.map(Math.abs));
  const y = (v) => Math.round(mid - (v / lim) * (P16_H / 2 - 3));
  const x = (i) => Math.round(4 + i * (P16_W - 9) / 15);
  for (let i = 0; i < Math.min(upto, 16); i++) {
    c.rect(x(i) - 1, y(pts[i]) - 1, 3, 3, fg);
    if (i) {
      const [x0, y0, x1, y1] = [x(i - 1), y(pts[i - 1]), x(i), y(pts[i])];
      const n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0));
      for (let k = 0; k <= n; k++) c.rect(Math.round(x0 + (x1 - x0) * k / n), Math.round(y0 + (y1 - y0) * k / n), 1, 1, fg);
    }
  }
}

function drawFp(fp, upto = 24, hi = -1) {
  const c = fpcv, bg = theme.ink, fg = theme.paper;
  c.rect(0, 0, FP_W, FP_H, bg);
  const mid = Math.round(FP_H / 2);
  c.rect(0, mid, FP_W, 1, fg);
  if (!fp) return;
  for (let i = 0; i < Math.min(upto, 24); i++) {
    const v = fp[i] / (S.fpRange[i] || 1);
    const h = Math.round(Math.min(1, Math.abs(v)) * (mid - 2));
    const x = 1 + i * 6;
    if (v >= 0) c.rect(x, mid - h, 5, h, fg); else c.rect(x, mid + 1, 5, h, fg);
    if (i === hi) c.frame(x - 1, 0, 7, FP_H, fg);
  }
}

function fmt(v) { return Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2); }

async function showExtract(name) {
  const s = S.sounds[name];
  const lab = $('e-label');
  lab.textContent = s.label;
  blinkOn(lab);
  const loud = /loudness (\w+)/.exec(s.line)?.[1] || '';
  $('e-meta').textContent = `${s.dur_ms} ms` + (s.raw.f0_med_hz ? ` · ${Math.round(s.raw.f0_med_hz)} Hz` : '') + (loud ? ` · ${loud}` : '');
  const line = $('e-line');
  const fp = s.features.fp, p16 = s.features.pitch16;
  const jobs = [];
  jobs.push((async () => { for (let i = 1; i <= 16; i++) { drawP16(p16, i); await sleep(12); } })());
  jobs.push((async () => { for (let i = 1; i <= 24; i++) { drawFp(fp, i); await sleep(9); } })());
  jobs.push((async () => {
    for (let i = 0; i <= s.line.length; i += 3) {
      line.innerHTML = '';
      line.append(s.line.slice(0, i));
      const cur = document.createElement('span'); cur.className = 'cursor'; line.append(cur);
      await sleep(8);
    }
    line.textContent = s.line;
  })());
  await Promise.all(jobs);
  const top = fp.map((v, i) => [Math.abs(v / (S.fpRange[i] || 1)), i]).sort((a, b) => b[0] - a[0]).slice(0, 3);
  $('fp-name').textContent = top.map(([, i]) => `${S.fpNames[i]} ${fmt(fp[i])}`).join(' · ');
}

// ---------------------------------------------------------------- BLE panel

function showPacket(name, modeNow) {
  const s = S.sounds[name];
  S.msgNo += 1;
  const now = Math.round(performance.now());
  const msg = { v: 1, id: S.msgNo, mode: modeNow, armed: true, sounds: [s.line], sequence: [s.label],
    timing: [{ t_start_ms: now - s.dur_ms, t_end_ms: now }], features: [s.features] };
  const text = JSON.stringify(msg);
  $('b-id').textContent = `#${S.msgNo} · ${s.label}`;
  $('b-size').textContent = `${new TextEncoder().encode(text).length} B`;
  $('b-packet').textContent = text.replace(/,"/g, ', "');
  blinkOn($('b-packet'), 1, 60);
}

// ---------------------------------------------------------------- the app pipeline (real events)

const ACTIONS = {
  swipe_up: 'swipe up', swipe_down: 'swipe down', swipe_left: 'swipe left', swipe_right: 'swipe right',
  tap: 'tap', back: 'back', home: 'home', forward: 'forward', long_press: 'long press',
  listen_for_phrase: 'listening', click: 'click', stop: 'cursor stop', none: 'nothing',
};
const niceAction = (a) => ACTIONS[a] || (a || '').replace(/_/g, ' ').replace(/ (slow|fast)$/, ' · $1');

function row(ev, value) {
  const el = document.querySelector(`#pipe .stat[data-ev="${ev}"]`);
  if (!el) return;
  el.querySelector('.v').textContent = value;
  el.classList.add('live');
  setTimeout(() => el.classList.remove('live'), 450);
}

function clearPipe() {
  document.querySelectorAll('#pipe .stat .v').forEach((v) => { v.textContent = '–'; });
}

function onApp(ev) {
  const e = ev.ev;
  switch (e) {
    case 'msg':
      if (ev.sequence) { clearPipe(); row('msg', `${ev.sequence} · ${ev.source || ''}`); S.lastMsgT = ev.t; }
      if (ev.mode) $('a-mode').textContent = ev.mode;
      break;
    case 'wait': lamp('waiting'); row('resolve', `${ev.sequence} … waiting for ${ev.for || 'more'}`); break;
    case 'resolve':
      lamp('listening');
      row('resolve', `${ev.sequence}${ev.waited ? ` · waited ${ev.waited} ms` : ''}`);
      break;
    case 'decision':
      row('decision', `${niceAction(ev.action)} · ${ev.source}${ev.confidence != null ? ` · ${Number(ev.confidence).toFixed(2)}` : ''}`);
      caption(ev.action);
      if (S.waiter) S.waiter.decided();
      break;
    case 'exec':
      if (S.lastMsgT != null && ev.t != null) $('a-lat').textContent = `${ev.t - S.lastMsgT} ms heard → acting`;
      row('exec', `${niceAction(ev.action)} · ${ev.ok ? 'ok' : 'failed'}${ev.how ? ` · ${String(ev.how).split('(')[0].split(';')[0]}` : ''}`);
      if (S.waiter) S.waiter.executed();
      break;
    case 'confirm':
      row('confirm', `${ev.result}${ev.ms != null ? ` · ${ev.ms} ms` : ''}`);
      if (S.waiter) S.waiter.done();
      break;
    case 'mic_sound':
      if (!ev.dropped && ev.label) {
        $('e-label').textContent = ev.label;
        blinkOn($('e-label'));
        $('e-meta').textContent = `${(ev.t_end_ms - ev.t_start_ms) || 0} ms · ${ev.latency_ms != null ? `${Math.round(ev.latency_ms)} ms` : ''}`;
        $('e-line').textContent = ev.text || '';
        $('cap-sound').textContent = ev.label;
      }
      break;
    case 'sound_source': S.source = ev.source; showSource(); break;
    case 'cursor': $('a-cursor').textContent = ev.state || '–'; break;
    case 'mode': if (ev.mode) $('a-mode').textContent = ev.mode; break;
    case 'auto_scroll': row('exec', `auto-scroll · ${ev.state || ev.what || ''}`); break;
    default: break;
  }
  if (!['state'].includes(e)) logLine(`${e}${summary(ev)}`);
}

function summary(ev) {
  const skip = new Set(['ev', 't', 'text', 'screen', 'top', 'unscored']);
  const parts = Object.entries(ev).filter(([k, v]) => !skip.has(k) && v !== null && v !== '' && typeof v !== 'object')
    .slice(0, 6).map(([k, v]) => `${k}=${v}`);
  return parts.length ? `  ${parts.join('  ')}` : '';
}

function logLine(text) {
  const log = $('log');
  const d = document.createElement('div');
  d.textContent = text;
  log.append(d);
  while (log.children.length > 40) log.firstChild.remove();
}

function caption(action) {
  $('cap-action').textContent = niceAction(action);
  blinkOn($('cap-action'));
}

function showSource() {
  const b = $('src');
  if (b) { b.textContent = S.source === 'phone' ? 'Src: phone mic' : 'Src: VOX'; paintChrome(b); }
}

async function toggleSource() {
  const next = S.source === 'phone' ? 'pico' : 'phone';
  const r = await cmd({ op: 'control', name: 'config', args: { sound_source: next } });
  if (r.ok) { S.source = next; showSource(); refreshStatus(); }
}

function lamp(state) { $('lamp').className = `lamp ${state}`; }

/** Resolve when the app has shown the result: confirm, or a decision with nothing to execute, or a timeout. */
function waitPipeline(maxMs = 4500) {
  return new Promise((resolve) => {
    let t = setTimeout(done, maxMs);
    function done() { clearTimeout(t); S.waiter = null; resolve(); }
    S.waiter = {
      decided() { clearTimeout(t); t = setTimeout(done, 1600); },
      executed() { clearTimeout(t); t = setTimeout(done, 2500); },
      done,
    };
  });
}

// ---------------------------------------------------------------- one sound, as the device hears and sends it

let deviceMode = 'gesture';

async function perform(name, { pre = true } = {}) {
  $('cap-sound').textContent = S.sounds[name].label;
  $('cap-action').textContent = '…';
  lamp('listening');
  await playSound(name, { pre });
  showExtract(name);
  showPacket(name, deviceMode);
  return cmd({ op: 'sound', name });
}

async function runStep(s) {
  if (s.reset) {
    deviceMode = 'gesture';
    $('a-mode').textContent = 'gesture';
    await cmd({ op: 'reset' });
  } else if (s.shell) {
    await cmd({ op: 'shell', preset: s.shell, url: WIKI_URL });
  } else if (s.mode) {
    deviceMode = s.mode;
    $('a-mode').textContent = s.mode;
    await cmd({ op: 'mode', mode: s.mode });
  } else if (s.wait) {
    await idle(s.wait);
  } else if (s.seq) {
    const w = waitPipeline();
    for (let i = 0; i < s.seq.length; i++) {
      if (i) await idle(s.gap ?? 250);
      await perform(s.seq[i], { pre: i === 0 });
    }
    $('cap-sound').textContent = s.seq.join(' · ');
    await w;
  } else if (s.sound && s.hold) {
    const w = waitPipeline();
    await perform(s.sound);
    await w;
    // the held hum: hold start ~300 ms in, hold end when it stops, then its own feature message
    $('cap-sound').textContent = 'hum · held';
    const held = S.sounds.hum_long ? 'hum_long' : 'flat';
    const hum = playSound(held, { pre: false, holdMs: s.hold });
    await sleep(300);
    const r = cmd({ op: 'hold', name: held, ms: s.hold - 300 });
    await hum;
    showExtract(held);
    showPacket(held, deviceMode);
    await r;
  } else if (s.sound) {
    const w = waitPipeline();
    await perform(s.sound);
    await w;
  }
  await idle(s.after ?? 700);
}

// ---------------------------------------------------------------- script runner + operator

function script() { return SCRIPTS[S.target]; }

function renderSteps() {
  const ol = $('steps');
  ol.innerHTML = '';
  script().steps.forEach((s, i) => {
    const li = document.createElement('li');
    li.textContent = stepText(s);
    if (i === S.step) li.className = 'cur';
    else if (i < S.step) li.className = 'done';
    ol.append(li);
  });
  $('stepinfo').textContent = `${script().title} · ${Math.min(S.step + 1, script().steps.length)}/${script().steps.length}`;
  ol.children[S.step]?.scrollIntoView({ block: 'nearest' });
}

async function stepOnce() {
  if (S.busy) return;
  const steps = script().steps;
  if (S.step >= steps.length) S.step = 0;
  S.busy = true;
  renderSteps();
  try { await runStep(steps[S.step]); } finally { S.busy = false; }
  S.step += 1;
  renderSteps();
}

async function runAll() {
  if (S.running) return;
  S.running = true;
  $('run').classList.add('on'); paintChrome($('run'));
  if (S.step >= script().steps.length) S.step = 0;
  while (S.running && S.step < script().steps.length) await stepOnce();
  S.running = false;
  $('run').classList.remove('on'); paintChrome($('run'));
}

function stopAll() { S.running = false; }

function setTarget(t) {
  S.target = t;
  localStorage.setItem('canti.target', t);
  S.step = 0;
  document.querySelectorAll('.tgt').forEach((b) => { b.classList.toggle('on', b.dataset.target === t); paintChrome(b); });
  $('targetline').textContent = t === 'phone' ? '→ Galaxy Z Flip' : '→ Android 15 · Pixel 6';
  renderSteps();
  refreshStatus();
}

async function manual(name) {
  if (S.busy) return;
  S.busy = true;
  try {
    const w = waitPipeline();
    await perform(name);
    await w;
  } finally { S.busy = false; }
}

async function manualSeq(names, gap = 250) {
  if (S.busy) return;
  S.busy = true;
  try { await runStep({ seq: names, gap, after: 0 }); } finally { S.busy = false; }
}

function buildPad() {
  const pad = $('pad');
  const keys = ['rise', 'fall', 'arch', 'dip', 'flat', 'pop', 'click', 'hiss'];
  keys.forEach((k, i) => {
    const b = document.createElement('button');
    b.textContent = `${i + 1} ${k}`;
    b.onclick = () => manual(k);
    pad.append(b);
    pixelButton(b);
  });
  const extra = [
    ['Q clk·clk', () => manualSeq(['click', 'click'])],
    ['W pop·pop', () => manualSeq(['pop', 'pop'])],
    ['E hold', () => !S.busy && (S.busy = true, runStep({ sound: 'rise', hold: 2000, after: 0 }).finally(() => { S.busy = false; }))],
    ['C mode', () => toggleMode()],
  ];
  for (const [label, fn] of extra) {
    const b = document.createElement('button');
    b.textContent = label;
    b.onclick = fn;
    pad.append(b);
    pixelButton(b);
  }
}

async function toggleMode() {
  deviceMode = deviceMode === 'gesture' ? 'cursor' : 'gesture';
  $('a-mode').textContent = deviceMode;
  await cmd({ op: 'mode', mode: deviceMode });
}

// ---------------------------------------------------------------- status + events

async function refreshStatus() {
  let st;
  try { st = await (await fetch('/api/status')).json(); } catch { lamp('stop'); $('linkstate').textContent = 'BLE · OFFLINE'; return; }
  const t = st.targets[S.target];
  const up = t && t.adb === 'device';
  if (!up) { lamp('stop'); $('linkstate').textContent = 'BLE · NO LINK'; $('b-link').textContent = 'not connected'; return; }
  if (S.target === 'phone') {
    const p = await cmd({ op: 'ping' });
    if (p.settings?.sound_source) { S.source = p.settings.sound_source; showSource(); }
    if (S.source === 'phone') {
      $('linkstate').textContent = 'MIC · PHONE';
      $('b-link').textContent = 'on-phone extractor';
      if ($('lamp').classList.contains('stop')) lamp('listening');
      return;
    }
    const r = await cmd({ op: 'control', name: 'ble_status' });
    const st2 = r.state || r.ble?.state;
    const mtu = r.mtu || r.ble?.mtu;
    const ready = st2 === 'ready';
    $('linkstate').textContent = ready ? 'BLE · CONNECTED' : `BLE · ${(st2 || 'unknown').toUpperCase()}`;
    $('b-link').textContent = ready ? `connected${mtu ? ` · MTU ${mtu}` : ''}` : (st2 || 'unknown');
    if (!ready) lamp('stop'); else if ($('lamp').classList.contains('stop')) lamp('listening');
  } else {
    $('linkstate').textContent = 'BLE · CONNECTED';
    $('b-link').textContent = 'connected · MTU 517';
    if ($('lamp').classList.contains('stop')) lamp('listening');
  }
}

function events() {
  const es = new EventSource('/api/events');
  es.onmessage = (m) => {
    let d;
    try { d = JSON.parse(m.data); } catch { return; }
    if (d.src === 'app' && d.target === S.target) onApp(d.ev);
  };
}

// ---------------------------------------------------------------- boot

function brandImages() {
  const { dev } = artPx();
  const dpr = window.devicePixelRatio || 1;
  const k = Math.min(8, Math.max(1, dev));
  const wm = $('wordmark');
  wm.src = `/ui/brand/canti-wordmark${theme.dark ? '-light' : ''}@${k}.png`;
  wm.onload = () => { wm.style.width = `${wm.naturalWidth / dpr}px`; };
  const n = Math.min(4, Math.max(1, Math.round(dpr)));
  const ic = $('devicon');
  ic.src = `/ui/brand/canti-icon-on@${n}.png`;
  ic.onload = () => { ic.style.width = `${ic.naturalWidth / dpr}px`; };
}

function canvases() {
  const panel = $('mic').parentElement;
  MIC_W = Math.max(120, Math.floor(panel.clientWidth / artPx().css) - 8);
  mic.cv = new PixelCanvas($('mic'), MIC_W, MIC_H);
  P16_W = Math.max(64, Math.min(160, Math.floor($('p16').parentElement.clientWidth / artPx().css) - 8));
  p16cv = new PixelCanvas($('p16'), P16_W, P16_H);
  fpcv = new PixelCanvas($('fp'), FP_W, FP_H);
  drawP16(null);
  drawFp(null);
}

async function boot() {
  applyScale();
  setTheme(localStorage.getItem('canti.theme') !== 'light');
  // real recorded takes (tools/record_demo_sounds.py) when present, else the extractor's reference clips
  let d;
  try { const r = await fetch('data/sounds.recorded.json'); if (!r.ok) throw 0; d = await r.json(); }
  catch { d = await (await fetch('data/sounds.json')).json(); }
  S.sounds = d.sounds;
  S.fpNames = d.fp1_names;
  S.fpRange = S.fpNames.map((_, i) => Math.max(1e-3, ...Object.values(S.sounds).map((s) => Math.abs(s.features.fp[i]))));
  brandImages();
  document.querySelectorAll('[data-kind]').forEach((el) => { if (el.dataset.kind !== 'button') chrome(el); });
  document.querySelectorAll('button').forEach(pixelButton);
  ditherField($('field'), { clear: () => [$('wordmark').getBoundingClientRect()] });
  canvases();
  buildPad();
  $('fp').addEventListener('mousemove', (e) => {
    const s = Object.values(S.sounds).find((x) => x.label === $('e-label').textContent);
    if (!s) return;
    const i = Math.min(23, Math.max(0, Math.floor(e.offsetX / artPx().css / 6)));
    drawFp(s.features.fp, 24, i);
    $('fp-name').textContent = `${S.fpNames[i]} = ${fmt(s.features.fp[i])}`;
  });

  document.querySelectorAll('.tgt').forEach((b) => { b.onclick = () => setTarget(b.dataset.target); });
  $('run').onclick = runAll;
  $('step').onclick = stepOnce;
  $('stop').onclick = stopAll;
  $('reset').onclick = () => { S.step = 0; renderSteps(); runStep({ reset: true, after: 0 }); };
  $('mirror').onclick = () => cmd({ op: 'scrcpy' });
  $('src').onclick = toggleSource;
  $('openwiki').onclick = () => cmd({ op: 'shell', preset: 'wiki', url: WIKI_URL });

  addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    const k = e.key.toLowerCase();
    if (k === ' ') { e.preventDefault(); stepOnce(); }
    else if (k === 'enter') runAll();
    else if (k === 'escape') stopAll();
    else if (k === 'h') $('op').classList.toggle('hidden');
    else if (k === 't') {
      setTheme(!theme.dark);
      localStorage.setItem('canti.theme', theme.dark ? 'dark' : 'light');
      brandImages(); repaintAll(); canvases();
    }
    else if (k >= '1' && k <= '8') manual(['rise', 'fall', 'arch', 'dip', 'flat', 'pop', 'click', 'hiss'][+k - 1]);
    else if (k === 'q') manualSeq(['click', 'click']);
    else if (k === 'w') manualSeq(['pop', 'pop']);
    else if (k === 'c') toggleMode();
    else if (k === 's') toggleSource();
  });
  addEventListener('resize', () => { applyScale(); repaintAll(); canvases(); });

  setTarget(S.target);
  lamp('listening');
  events();
  setInterval(refreshStatus, 4000);
  requestAnimationFrame(micTick);
}

boot();
