#!/usr/bin/env python3
"""Private desktop range recorder. All prompts/timing/thresholds come from range_v1.json."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
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
    rows = L.take_rows(out / 'labels.jsonl')   # the last heard attempt: a missed (no_sound) retry never replaces it
    for take in L.build_plan(spec, ['range']):
        row = rows.get(take['take_id'])
        if row and not L.is_no_sound(row):
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
        gap = {'quick': .15, 'normal': .35, 'slow': .8, 'na': 0}[take['cond']['gap']]
        if len(take['expect']) == 1:
            # a single click (a short decaying burst) or a hiss lasting the cell's target_s (0.3/0.5/0.7/1.0 s)
            x = rng.normal(0, .1, n)
            if sound == 'click':
                x = x * np.exp(-ts * 70)
        else:
            # combos: n clicks spaced by the gap; 'hiss click' is a hiss, then the gap, then a click
            x = np.zeros(n)
            step = round(.3 * rate) + round(gap * rate)
            at = 0
            for s in take['expect']:
                m = round(.3 * rate)
                seg = rng.normal(0, .1, m)
                if s == 'click':
                    seg = seg * np.exp(-np.arange(m) / rate * 70)
                end = min(at + m, n)
                x[at:end] += seg[:end - at]
                at += step
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

    def rkey(auto):
        return L.getkey(auto, extra='du')

    def count_files(take):
        rows_ = L.read_rows(out / 'labels.jsonl' if take['kind'] != 'backgrounds' else out / 'backgrounds.jsonl')
        return len(L.delete_files(rows_, take['take_id'] if take['kind'] != 'backgrounds' else take['name'], 'take'))

    def delete(take):
        if take['kind'] == 'backgrounds':
            del_id = L.delete_background(out, take['name'])
            bgs.pop(take['name'], None)
        else:
            del_id = L.delete_take(out, take['take_id'], 'take')
            rows.pop(take['take_id'], None)
        return del_id

    def undo(del_id):
        key = L.restore(out, del_id)
        rows.clear()
        rows.update(L.take_rows(out / 'labels.jsonl'))
        bgs.clear()
        bgs.update(L.latest_rows(out / 'backgrounds.jsonl', 'name'))
        return key

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
                redo = L.next_redo(L.read_rows(out / 'labels.jsonl'), take['take_id'])
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

            completed, redos = L.operate(items, done, capture, args.auto, rkey, delete=delete, undo=undo,
                                        count=count_files)
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


def _open_existing(args):
    """The private folder of an existing session, for a non-recording command (no audio source is opened)."""
    session = getattr(args, 'session', None)
    path = L.private_dir(args.out if args.out is not None else L.HERE / 'recordings' / L.safe_name(session))
    if not (path / 'session.json').is_file():
        raise ValueError(f'{path.name}: not an existing range session')
    return path


def list_takes(args):
    out = _open_existing(args)
    spec = L.load_spec(out / 'spec.json')
    profile = L.session_profile(json.loads((out / 'session.json').read_text()))
    plan = [t for t in L.build_plan(spec, args.block, profile) if t['kind'] == 'takes']
    journal = L.read_rows(out / 'labels.jsonl')
    rows = L.take_rows(journal)
    in_force = set(L.effective_rows(journal)[1])
    attempts, deletes = {}, {}
    for r in journal:
        if r.get('op'):
            if r.get('op') == 'delete' and r.get('del_id') in in_force:
                deletes[r['take_id']] = deletes.get(r['take_id'], 0) + 1
        else:
            attempts[r['take_id']] = attempts.get(r['take_id'], 0) + 1
    for t in plan:
        tid = t['take_id']
        status = 'missing' if tid not in rows else ('no_sound' if L.is_no_sound(rows[tid]) else 'done')
        print(f"{tid}  {status}  attempts={attempts.get(tid, 0)}  deletes={deletes.get(tid, 0)}")
    return 0


def delete_command(args):
    out = _open_existing(args)
    scope, attempt = 'take', None
    if args.attempt is not None:
        scope, attempt = 'attempt', args.attempt
    elif args.heard:
        scope, attempt = 'attempt', None
    if not args.yes and input(f'Delete {args.take_id}? [y/N] ').strip().lower() not in ('y', 'yes'):
        print('Not deleted.')
        return 0
    del_id = L.delete_take(out, args.take_id, scope, attempt)
    print(f'Deleted {args.take_id} ({del_id}). u = restore {del_id}')
    return 0


def restore_command(args):
    out = _open_existing(args)
    key = L.restore(out, args.del_id)
    print(f'Restored {key}.')
    return 0


def clear_trash_command(args):
    out = _open_existing(args)
    if not args.yes and input('Clear the trash? Type "yes" to confirm: ').strip() != 'yes':
        print('Trash kept.')
        return 0
    del_ids = L.purge_trash(out)
    print(f'Purged {len(del_ids)} delete(s).')
    return 0


_COMMANDS = ('list-takes', 'delete', 'restore', 'clear-trash')


def run_command(name, argv):
    p = argparse.ArgumentParser(prog=f'range_session.py {name}')
    p.add_argument('--session', help='the session folder under extractor/recordings')
    p.add_argument('--out', type=Path, help='or the absolute private session folder')
    if name == 'list-takes':
        p.add_argument('--block', action='append')
    elif name == 'delete':
        p.add_argument('take_id')
        g = p.add_mutually_exclusive_group()
        g.add_argument('--attempt', type=int, help='delete that missed (no_sound) attempt')
        g.add_argument('--heard', action='store_true', help='delete the current heard attempt')
        g.add_argument('--all', action='store_true', help='delete every attempt of the take (the default)')
        p.add_argument('--yes', action='store_true')
    elif name == 'restore':
        p.add_argument('del_id')
    elif name == 'clear-trash':
        p.add_argument('--yes', action='store_true')
    args = p.parse_args(argv)
    try:
        return {'list-takes': list_takes, 'delete': delete_command, 'restore': restore_command,
                'clear-trash': clear_trash_command}[name](args)
    except (ValueError, RuntimeError) as e:
        print(f'range_session: {e}', file=sys.stderr)
        return 2


def main():
    if len(sys.argv) > 1 and sys.argv[1] in _COMMANDS:
        return run_command(sys.argv[1], sys.argv[2:])
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
    try:
        run_session(args)
    except (ValueError, RuntimeError) as e:
        print(f'range_session: {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    main()
