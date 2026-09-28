#!/usr/bin/env python3
"""Private range recording driver; stdlib-only until the explicit finalize command.

Default connection: emulator-5580, adb server 5038, debug socket 7789.
No device commands run on import. Every block is pulled and verified by measure.py.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import wave

os.environ.setdefault('VOX_SERIAL', 'emulator-5580')
os.environ.setdefault('ANDROID_ADB_SERVER_PORT', '5038')
os.environ.setdefault('VOX_SOCKET_PORT', '7789')

import measure
import voxlib

EXTRACTOR = Path(__file__).resolve().parents[2] / 'extractor'
sys.path.insert(0, str(EXTRACTOR))
import range_layout as L


def cut_wav(source, target, start_ms, end_ms, wav_t0_ms):
    """Sample-exact [start,end) slice. Reject lost pre/post-roll rather than silently clipping."""
    with wave.open(str(source), 'rb') as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        if wav.getsampwidth() != 2:
            raise ValueError('expected PCM16')
        start = round((start_ms - wav_t0_ms) * rate / 1000)
        end = round((end_ms - wav_t0_ms) * rate / 1000)
        if start < 0 or end > wav.getnframes() or end <= start:
            raise ValueError('cue window outside continuous WAV; missing pre/post-roll')
        wav.setpos(start)
        audio = wav.readframes(end - start)
        if len(audio) != (end - start) * channels * 2:
            raise ValueError('truncated continuous WAV')
    L.disk_guard(target, len(audio))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp.wav')
    with wave.open(str(tmp), 'wb') as out:
        out.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        out.writeframes(audio)
    tmp.replace(target)
    return end - start, channels, rate


def import_block(out, exported, manifest, spec):
    sid = str(manifest['sid'])
    events = measure.sessions((exported / 'events.jsonl').read_bytes().splitlines()).get(sid, [])
    start = measure.event(events, 'measure_start')
    stopped = measure.event(events, 'measure_stop')
    if start is None or stopped is None:
        raise ValueError('missing complete measurement events')
    meta = json.loads((out / 'session.json').read_text())
    if (start['rate'], start['channels']) != (meta['rate'], meta['channels']):
        raise ValueError('phone format changed; use another session')
    if not manifest['entries']:
        return
    cues = {e['n']: e for e in map(json.loads, events) if e.get('ev') == 'measure_prompt'}
    a = spec['analysis']
    with wave.open(str(exported / sid / 'audio.wav'), 'rb') as wav:
        audio_end = start['wav_t0_ms'] + wav.getnframes() * 1000 / wav.getframerate()
    # On retry, last-line-wins is also idempotent: already committed attempts are not appended twice.
    existing = {(r.get('import_id'), r.get('cue_n')) for name in ('labels.jsonl', 'backgrounds.jsonl')
                for r in L.read_rows(out / name)}
    for entry in manifest['entries']:
        t, cue = entry['take'], entry['cue']
        logged = cues.get(cue['n'])
        if logged is None or any(logged.get(k) != v for k, v in
                                 [('gesture', t['take_id']), ('t_ms', cue['t_ms']), ('text', t['cue'])]):
            raise ValueError('measure_cue reply does not match exported measure_prompt')
        if (manifest['id'], cue['n']) in existing:
            continue
        go = cue['t_ms']
        background = t['kind'] == 'backgrounds'
        begin = go if background else go - a['pre_roll_s'] * 1000
        end = go + (t['seconds'] if background else t['max_s'] + a['post_roll_s']) * 1000
        if begin < start['wav_t0_ms'] or end > audio_end:
            entry['incomplete'] = 'continuous WAV lacks the full cue window; repeat on resume'
            print(f"Incomplete {t['take_id']}: repeat on resume.")
            continue
        file = f"backgrounds/{t['name']}.wav" if background else f"takes/{t['block']}/{t['take_id']}.wav"
        frames, channels, rate = cut_wav(exported / sid / 'audio.wav', out / file, begin, end, start['wav_t0_ms'])
        if background:
            row = dict(name=t['name'], kind=t['bg_kind'], level=t['level'], seconds=t['seconds'], file=file)
            journal = 'backgrounds.jsonl'
        else:
            row = L.label_row(t, entry['redo'], begin, go, frames, rate)
            journal = 'labels.jsonl'
        row.update(import_id=manifest['id'], cue_n=cue['n'], sid=sid)
        L.append_row(out / journal, row)
    if any(e['take'].get('anchor') for e in manifest['entries']):
        meta['range_pending'] = True
        L.write_json(out / 'session.json', meta)


def recover(vox, out, spec):
    """Finish verified imports after a transfer failure without recording those takes again."""
    for path in sorted((out / 'imports').glob('*/pending.json')):
        manifest = json.loads(path.read_text())
        if manifest.get('imported'):
            continue
        if manifest.get('sid') is None:
            raise RuntimeError('lost measure_start reply; resolve the running session before resuming')
        exported = path.parent / 'verified'
        if not (path.parent / 'verified.json').exists():
            # A failed pull may leave files: preserve them and retry in a fresh directory.
            if exported.exists():
                exported.rename(path.parent / f'partial-{time.time_ns()}')
            measure.pull(vox, exported, [str(manifest['sid'])], validate_output=L.private_dir)
            L.write_json(path.parent / 'verified.json', dict(sid=manifest['sid']))
        import_block(out, exported, manifest, spec)
        manifest['imported'] = True
        L.write_json(path, manifest)


def cue_now(vox, take, wait, tries=10):
    """measure_cue; the app refuses one before the measurement's first sample (retry), then it must succeed."""
    for _ in range(tries - 1):
        r = vox.control('measure_cue', text=take['cue'], id=take['take_id'])
        if r.get('ok') or 'no sample yet' not in str(r.get('error')):
            break
        wait(.2)
    else:
        r = vox.control('measure_cue', text=take['cue'], id=take['take_id'])
    if not r.get('ok'):
        raise RuntimeError(f"measure_cue failed: {r.get('error')}")
    return r


def run_block(vox, out, spec, block, key=L.getkey, wait=time.sleep, auto=False):
    items = L.build_plan(spec, [block['id']], L.session_profile(json.loads((out / 'session.json').read_text())))
    rows = L.latest_rows(out / 'labels.jsonl')
    backgrounds = L.latest_rows(out / 'backgrounds.jsonl', 'name')
    done = set(rows) | {t['take_id'] for t in items if t.get('name') in backgrounds}
    if all(t['take_id'] in done for t in items):
        if block['id'] not in {r['block'] for r in L.read_rows(out / 'ratings.jsonl')}:
            L.rating(out, block['id'], 0, 0, spec, auto)
        return True
    if vox.control('measure_status').get('running'):
        raise RuntimeError('a measurement is already running')
    print('\n' + block['intro'])
    print('Distances:', spec['defaults']['distances_cm'], 'cm; gaps:', spec['defaults']['gap_s'], 's')
    print('Measured Hz:', json.loads((out / 'session.json').read_text())['range'])
    print('Enter to begin block; q to quit.')
    if key(auto) == 'q':
        return False
    run_id = f'{time.time_ns()}-{block["id"]}'
    folder = out / 'imports' / run_id
    folder.mkdir(parents=True)
    path = folder / 'pending.json'
    manifest = dict(id=run_id, sid=None, entries=[], imported=False)
    L.write_json(path, manifest)
    began = time.monotonic()
    completed, redos = False, 0
    try:
        start = measure.checked(vox, 'measure_start', phase='range-' + block['id'], prompt=False,
                                record=True, max_s=spec['phone']['max_s'])
        manifest['sid'] = measure.safe_sid(start['sid'])
        L.write_json(path, manifest)
        meta = json.loads((out / 'session.json').read_text())
        actual = (start.get('rate', meta['rate']), start.get('channels', meta['channels']))
        if actual != (meta['rate'], meta['channels']):
            if rows or backgrounds:
                raise ValueError('phone capture format changed; use another session')
            meta['rate'], meta['channels'] = actual
            L.write_json(out / 'session.json', meta)

        def capture(take):
            L.disk_guard(out)
            # Wait before every cue so even a first prompt has a full second of pre-roll.
            wait(spec['analysis']['pre_roll_s'])
            if time.monotonic() - began + take.get('seconds', take.get('max_s', 0)) + spec['analysis']['post_roll_s'] >= spec['phone']['max_s']:
                raise RuntimeError('block time limit reached; resume remaining takes in another sitting')
            cue = cue_now(vox, take, wait)
            print('● GO · ' + take['cue'], flush=True)
            previous = rows.get(take['take_id'])
            redo = previous['redo'] + 1 if previous else 0
            manifest['entries'].append(dict(take=take, cue=cue, redo=redo))
            L.write_json(path, manifest)
            rows[take['take_id']] = dict(redo=redo)
            wait(take['seconds'] if take['kind'] == 'backgrounds' else take['max_s'] + spec['analysis']['post_roll_s'])

        completed, redos = L.operate(items, done, capture, auto, key)
    finally:
        measure.stop(vox)
        if manifest['sid'] is not None:
            recover(vox, out, spec)
    if completed:
        L.rating(out, block['id'], time.monotonic() - began, redos, spec, auto)
    return completed


def run_session(args, vox=None):
    spec = L.load_spec(args.spec)
    profile = getattr(args, 'profile', None) or L.DEFAULT_PROFILE
    speaker = getattr(args, 'speaker', None) or L.DEFAULT_SPEAKER
    L.build_plan(spec, args.block, profile)
    session = getattr(args, 'session', None) or L.default_session_name(speaker)
    out = L.private_dir(args.out or EXTRACTOR.parent / 'zflip' / 'range' / L.safe_name(session))
    existing = json.loads((out / 'session.json').read_text()) if (out / 'session.json').exists() else {}
    L.open_session(out, spec, 'phone', args.mic, args.rate or existing.get('rate', spec['defaults']['rate']),
                   args.channels or existing.get('channels', spec['defaults']['channels']),
                   profile=profile, speaker=speaker)
    chosen = L.profile_blocks(spec, profile)
    own_vox = vox is None
    try:
        if own_vox:
            # Respect explicit coordinator settings, including when voxlib was imported earlier.
            voxlib.SERIAL = os.environ['VOX_SERIAL']
            voxlib.SOCKET_PORT = int(os.environ['VOX_SOCKET_PORT'])
            vox = voxlib.Vox()
        recover(vox, out, spec)
        for block in spec['blocks']:
            if block['id'] not in chosen or (args.block and block['id'] not in args.block):
                continue
            if not run_block(vox, out, spec, block):
                break
            if block['id'] == 'range':
                try:
                    from range_session import finalize_range
                except ModuleNotFoundError:
                    print('Hz pending: finalize this session under extractor/run after the range block.')
                else:
                    finalize_range(out, spec)
    finally:
        saved = json.loads((out / 'session.json').read_text())
        saved['sittings'][-1]['ended'] = time.time()
        L.write_json(out / 'session.json', saved)
        if own_vox and vox is not None:
            vox.close()
    print('Run finalize under extractor/run before analysis; Hz may still be pending.')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest='command', required=True)
    run = subs.add_parser('run')
    run.add_argument('--out', type=Path)
    run.add_argument('--session', help='default: range-<time>, or range-<speaker>-<time> for another speaker')
    run.add_argument('--profile', default=L.DEFAULT_PROFILE, help='"full" (the whole grid) or "short" (about 8 minutes)')
    run.add_argument('--speaker', default=L.DEFAULT_SPEAKER,
                     help='a short pseudonymous speaker id (letters, digits, - and _; never a real name)')
    run.add_argument('--spec', type=Path, default=L.SPEC_PATH)
    run.add_argument('--block', action='append')
    run.add_argument('--mic', default='phone built-in mic')
    run.add_argument('--rate', type=int)
    run.add_argument('--channels', type=int, choices=[1, 2])
    finalize = subs.add_parser('finalize')
    finalize.add_argument('session', type=Path)
    args = p.parse_args()
    if args.command == 'finalize':
        from range_session import finalize_range
        out = L.private_dir(args.session)
        finalize_range(out, L.load_spec(out / 'spec.json'))
        L.validate_session(out)
    else:
        run_session(args)


if __name__ == '__main__':
    main()
