#!/usr/bin/env python3
"""Private desktop range recorder. All prompts/timing/thresholds come from range_v1.json."""
from __future__ import annotations

import argparse
import contextlib
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf

import guided_session as G
import record as R
import range_layout as L
import voice_cursor_test as V
from vox_extract.config import Config


@contextlib.contextmanager
def pitch_settings(spec):
    old = V.SPEC
    V.use_spec(dict(old, analysis=dict(old['analysis'], **spec['analysis']), live=dict(old['live'], **spec['live'])))
    try:
        yield
    finally:
        V.use_spec(old)


def median_pitch(audio, rate, spec):
    from vox_extract.resample import to_16k
    a = spec['analysis']
    x = to_16k(np.asarray(audio, dtype=np.float32), rate)
    pitches = []
    with pitch_settings(spec):
        for i in range(0, len(x) - a['win'] + 1, a['hop']):
            f0, clarity, level = V.live_pitch(x[i:i + a['win']], a['fs'])
            if clarity >= a['clarity_min'] and level >= a['min_level_db'] and f0 > 0:
                pitches.append(f0)
    return float(np.median(pitches)) if pitches else None


def finalize_range(out, spec):
    meta = json.loads((out / 'session.json').read_text())
    rows = L.latest_rows(out / 'labels.jsonl')
    for take in L.build_plan(spec, ['range']):
        row = rows.get(take['take_id'])
        if row:
            x, rate = sf.read(out / row['file'], always_2d=True, dtype='float32')
            start = round(row['go_offset_ms'] * rate / 1000)
            meta['range'][take['anchor']] = median_pitch(x[start:, 0], rate, spec)
    bottom = meta['range']['bottom_hz']
    meta['range']['below_f0_min'] = bottom is not None and bottom < Config().f0_min_hz
    meta['range_pending'] = any(meta['range'][t['anchor']] is None for t in L.build_plan(spec, ['range']))
    L.write_json(out / 'session.json', meta)
    print('Measured range (Hz):', meta['range'])
    if meta['range']['below_f0_min']:
        print(f'!!! BOTTOM {bottom:.1f} Hz IS BELOW EXTRACTOR f0_min_hz={Config().f0_min_hz:g} Hz !!!')
    return meta['range']


def synthetic_audio(take, rate, spec):
    """Signal fixtures only, never evidence of real performance."""
    if take['kind'] == 'backgrounds':
        rng = np.random.default_rng(7)
        return rng.normal(0, .005, round(take['seconds'] * rate)).astype(np.float32)
    a = spec['analysis']
    if L.is_quiet(take):
        # the room step: silence over the whole fixed window (the fake's floor is digital silence) with one early
        # room transient (a tap): a silence detector would end the take ~1 s after it
        n = round(take['max_s'] * rate)
        x = np.zeros(n)
        k = np.arange(round(.02 * rate))
        x[round(.3 * rate) + k] += .1 * np.exp(-k / (.003 * rate)) * np.random.default_rng(12).normal(0, 1, k.size)
        return np.concatenate((np.zeros(round(a['pre_roll_s'] * rate)), x,
                               np.zeros(round(a['post_roll_s'] * rate)))).astype(np.float32)
    duration = take['target_s']
    n = round(duration * rate)
    ts = np.arange(n) / rate
    hz = {'bottom': 55, 'home': 120, 'top': 240, 'na': 120}[take['cond']['pitch']]
    if take['cond']['tone'] == 'whistle':
        hz = 1000
    sound = take['expect'][0]
    pos = np.linspace(0, 1, n)
    shapes = {'rise': pos, 'fall': 1 - pos, 'arch': np.sin(np.pi * pos),
              'dip': -np.sin(np.pi * pos), 'flat': np.zeros(n)}
    if sound in shapes:
        f0 = hz * 2 ** (shapes[sound] / 3)
        x = .15 * np.sin(2 * np.pi * np.cumsum(f0) / rate)
    else:
        rng = np.random.default_rng(19)
        x = rng.normal(0, .1, n)
        if sound in ('pop', 'click'):
            x *= np.exp(-ts * 70)
        if len(take['expect']) == 2:
            second = rng.normal(0, .1, n) * np.exp(-np.maximum(0, ts - duration / 2) * 70)
            second[ts < duration / 2] = 0
            x += second
    # The calibration anchors have flat envelopes except short attack/release ramps.
    x *= np.minimum(1, np.minimum(np.arange(n), np.arange(n)[::-1]) / (rate * .02))
    return np.concatenate((np.zeros(round(a['pre_roll_s'] * rate)), x,
                           np.zeros(round(a['post_roll_s'] * rate)))).astype(np.float32)


def capture_live(rec, take, spec, meter=None, target=None, fake=None):
    """guided_session's silence detector, with every timing/threshold supplied by this spec."""
    a = spec['analysis']
    signal = None
    if fake:
        signal = synthetic_audio(take, rec.rate, spec)
        if take['kind'] != 'backgrounds':
            signal = signal[round(a['pre_roll_s'] * rec.rate):len(signal) - round(a['post_roll_s'] * rec.rate)]
    if not rec.wait_s(a['pre_roll_s'] + a['key_guard_s']):
        raise RuntimeError('capture ended before GO')
    go = rec.n
    print('● GO', flush=True)
    if fake:
        with fake.lock:
            fake.pending.append(signal)
    if take['kind'] == 'backgrounds':
        if not rec.wait_until(go + round(take['seconds'] * rec.rate)):
            raise RuntimeError('background capture ended early')
        return rec.audio(go, go + round(take['seconds'] * rec.rate)), go, go
    hop = round(a['tick_s'] * rec.rate)
    pre = rec.audio(go - round(a['floor_window_s'] * rec.rate), go)
    frames = pre[:len(pre) // hop * hop].reshape(-1, hop)
    base = np.median(20 * np.log10(np.sqrt(np.mean(frames.astype(float) ** 2, axis=1)) + 1e-9))
    heard, last, reason = False, go, 'max length'
    need = round(a['win'] * rec.rate / a['fs'])
    with pitch_settings(spec):
        while True:
            if not rec.wait_s(a['tick_s']):
                raise RuntimeError('capture ended during take')
            now = rec.n
            x = rec.audio(now - hop, now)
            level = 20 * np.log10(np.sqrt(np.mean(x.astype(float) ** 2)) + 1e-9)
            if level > base + a['open_db'] or (heard and level >= base + a['close_db']):
                heard, last = True, now
            if meter:
                f0, cl, lv = V.live_pitch(rec.audio(now - need, now), rec.rate)
                cur = float(V.st(f0)) if f0 > 0 and cl >= a['clarity_min'] and lv >= a['min_level_db'] else None
                if G.TTY:
                    meter.draw(cur, target, note=f'{f0:.1f} Hz' if cur else '')
            elapsed = (now - go) / rec.rate
            # Fixed windows for acoustic mixed checks (background can keep the energy gate open) and for the quiet
            # room step (a transient must not end it early, nor silence end it as 'no sound').
            fixed = take['bg'] is not None or L.is_quiet(take)
            if not fixed and heard and (now - last) / rec.rate >= a['silence_s']:
                reason = 'silence'
                break
            if elapsed >= take['max_s']:
                break
            if not fixed and not heard and elapsed >= a['no_sound_s']:
                reason = 'no sound'
                break
    end = (last if heard and reason == 'silence' else rec.n) + round(a['post_roll_s'] * rec.rate)
    if not rec.wait_until(end):
        raise RuntimeError('capture ended before post-roll')
    start = go - round(a['pre_roll_s'] * rec.rate)
    return rec.audio(start, end), start, go


def run_session(args):
    spec = L.load_spec(args.spec)
    profile = getattr(args, 'profile', None) or L.DEFAULT_PROFILE
    speaker = getattr(args, 'speaker', None) or L.DEFAULT_SPEAKER
    L.build_plan(spec, args.block, profile)
    if args.auto and args.source != 'fake':
        raise ValueError('--auto requires --source fake')
    session = getattr(args, 'session', None) or L.default_session_name(speaker)
    out = L.private_dir(args.out or L.HERE / 'recordings' / L.safe_name(session))
    fake = args.source == 'fake'
    rate = args.rate or spec['defaults']['rate']
    args.rate = rate
    src = R.FakeSource(rate, rate // 20, getattr(args, 'fake_speed', 100), 7) if fake else R.make_source(args)
    meta = L.open_session(out, spec, 'desktop', 'fake (SYNTHETIC)' if fake else src.name, rate, 1, fake,
                          profile=profile, speaker=speaker)
    chosen = L.profile_blocks(spec, profile)
    sitting = len(meta['sittings'])
    rows = L.latest_rows(out / 'labels.jsonl')
    bgs = L.latest_rows(out / 'backgrounds.jsonl', 'name')
    rec = None
    try:
        rec = R.Recorder(src, Config(), out / f'run-{sitting:03d}', print_events=False)
        rec.start()
        for block in spec['blocks']:
            if block['id'] not in chosen or (args.block and block['id'] not in args.block):
                continue
            items = L.build_plan(spec, [block['id']], profile)
            done = set(rows) | {t['take_id'] for t in items if t.get('name') in bgs}
            if all(t['take_id'] in done for t in items):
                if block['id'] not in {r['block'] for r in L.read_rows(out / 'ratings.jsonl')}:
                    L.rating(out, block['id'], 0, 0, spec, args.auto)
                continue
            print('\n' + block['intro'])
            print('Distances:', spec['defaults']['distances_cm'], 'cm; gaps:', spec['defaults']['gap_s'], 's')
            print('Your measured Hz:', meta['range'])
            began = time.monotonic()

            def capture(take):
                L.disk_guard(out, round((take.get('seconds', take.get('max_s', 0)) +
                                        spec['analysis']['pre_roll_s'] + spec['analysis']['post_roll_s']) * rate * 2))
                previous = rows.get(take['take_id'])
                redo = previous['redo'] + 1 if previous else 0
                meter, target = None, None
                if take.get('cond', {}).get('tone') in ('hum', 'whistle'):
                    rg = meta['range']
                    scale = [rg.get(k) for k in ('bottom_hz', 'home_hz', 'top_hz')]
                    if not all(scale) or not scale[0] < scale[2]:
                        scale = spec['live']['initial_scale_hz']
                    with pitch_settings(spec):
                        meter = V.Meter(tuple(float(V.st(f)) for f in scale), [])
                    hz = rg.get('whistle_home_hz' if take['cond']['tone'] == 'whistle' else take['cond']['pitch'] + '_hz')
                    target = float(V.st(hz)) if hz else None
                clip, start, go = capture_live(rec, take, spec, meter, target, src if fake else None)
                if take['kind'] == 'backgrounds':
                    row = {k: take[k] for k in ('name', 'kind', 'level', 'seconds')}
                    # plan.kind describes the block; preserve the background's acoustic kind.
                    row['kind'] = take['bg_kind']
                    row['file'] = f"backgrounds/{take['name']}.wav"
                    journal = 'backgrounds.jsonl'
                else:
                    row = L.label_row(take, redo, start * 1000 / rate, go * 1000 / rate, len(clip), rate)
                    journal = 'labels.jsonl'
                path = out / row['file']
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix('.tmp.wav')
                sf.write(temp, clip, rate, subtype='PCM_16')
                temp.replace(path)
                L.append_row(out / journal, row)
                if take['kind'] == 'backgrounds':
                    bgs[take['name']] = row
                else:
                    rows[take['take_id']] = row
                    if take.get('anchor'):
                        meta['range'] = finalize_range(out, spec)

            completed, redos = L.operate(items, done, capture, args.auto, G.getkey)
            if not completed:
                break
            L.rating(out, block['id'], time.monotonic() - began, redos, spec, args.auto)
    finally:
        if rec:
            rec.stop()
        saved = json.loads((out / 'session.json').read_text())
        saved['sittings'][-1]['ended'] = time.time()
        L.write_json(out / 'session.json', saved)
    print(out)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, default=L.SPEC_PATH)
    p.add_argument('--session', help='default: range-<time>, or range-<speaker>-<time> for another speaker')
    p.add_argument('--profile', default=L.DEFAULT_PROFILE,
                   help='the spec profile: "full" (the whole grid) or "short" (about 8 minutes, e.g. a second speaker)')
    p.add_argument('--speaker', default=L.DEFAULT_SPEAKER,
                   help='a short pseudonymous speaker id (letters, digits, - and _; never a real name)')
    p.add_argument('--out', type=Path)
    p.add_argument('--block', action='append')
    p.add_argument('--source', choices=['auto', 'pw', 'sd', 'fake'], default='auto')
    p.add_argument('--device')
    p.add_argument('--rate', type=int, default=None)
    p.add_argument('--auto', action='store_true')
    p.add_argument('--fake-speed', type=float, default=100)
    args = p.parse_args()
    if args.rate is None:
        args.rate = L.load_spec(args.spec)['defaults']['rate']
    run_session(args)


if __name__ == '__main__':
    main()
