"""Stdlib-only shared range spec, journal and layout contract.

validate_session(path, spec=None, complete=False) raises ValueError on invalid
metadata/audio and returns counts. Incomplete sittings are valid by default.
The last labels.jsonl row for a take_id wins. t_go_ms is on the source clock;
clip_start_ms and go_offset_ms map it to the local take WAV, dur_ms is WAV length.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / 'prompts' / 'range_v1.json'
COND_KEYS = ('tone', 'pitch', 'speed', 'loud', 'dist', 'gap')
DEFAULT_PROFILE = 'full'
DEFAULT_SPEAKER = 'self'


def load_spec(path=SPEC_PATH):
    spec = json.loads(Path(path).read_text())
    if spec['version'] != 'range_v1':
        raise ValueError('expected range_v1')
    ids, block_ids = set(), set()
    for block in spec['blocks']:
        safe_name(block['id'])
        if block['id'] in block_ids or block['kind'] not in ('takes', 'backgrounds'):
            raise ValueError('duplicate block or unknown block kind')
        block_ids.add(block['id'])
        for cell in block['cells']:
            key = (block['id'], cell['cell_id'])
            safe_name(cell['cell_id'])
            if key in ids or type(cell['reps']) is not int or cell['reps'] < 1:
                raise ValueError('duplicate cell or invalid reps')
            ids.add(key)
            if not isinstance(cell['cue'], str) or not cell['cue']:
                raise ValueError('missing cue')
            if block['kind'] == 'backgrounds':
                safe_name(cell['name'])
                if cell['kind'] not in ('media', 'tv', 'fan', 'talk', 'other') or not (
                        cell['level'] is None or type(cell['level']) is int) or cell['seconds'] <= 0:
                    raise ValueError('invalid background')
            if block['kind'] != 'backgrounds':
                if cell['cond_id'] != cond_id(cell['cond']):
                    raise ValueError('unstable cond_id')
                for k, v in cell['cond'].items():
                    if v not in spec['cond_values'][k]:
                        raise ValueError('invalid condition')
                # a quiet cell (the room step) expects nothing and is recorded over a fixed window
                if bool(cell['expect']) == is_quiet(cell) or not 0 < cell['target_s'] <= cell['max_s']:
                    raise ValueError('invalid take')
    cells = {b['id']: {c['cell_id'] for c in b['cells']} for b in spec['blocks']}
    if 'profiles' in spec:
        if 'full' not in spec['profiles']:
            raise ValueError('profiles need "full"')
        for name, profile in spec['profiles'].items():
            safe_name(name)
            seen = [b['id'] for b in profile['blocks']]
            if len(set(seen)) != len(seen) or seen != [b for b in cells if b in seen]:
                raise ValueError(f'profile {name}: blocks must be unique and in spec order')
            for b in profile['blocks']:
                if b['id'] not in cells or not b['cells'] or not set(b['cells']) <= cells[b['id']]:
                    raise ValueError(f'profile {name}: unknown block or cell')
                if b['reps'] is not None and (type(b['reps']) is not int or b['reps'] < 1):
                    raise ValueError(f'profile {name}: invalid reps')
    return spec


def is_quiet(take):
    """A quiet take (the room step): nothing expected, a fixed max_s window instead of the silence detector."""
    return take.get('quiet') is True


def profile_blocks(spec, profile=DEFAULT_PROFILE):
    """{block id: {cells, reps}} of [profile], in spec order. A spec without profiles has only "full" (everything)."""
    profiles = spec.get('profiles') or {DEFAULT_PROFILE: dict(blocks=[
        dict(id=b['id'], cells=[c['cell_id'] for c in b['cells']], reps=None) for b in spec['blocks']])}
    if profile not in profiles:
        raise ValueError(f'unknown profile {profile!r}; the spec has {sorted(profiles)}')
    return {b['id']: b for b in profiles[profile]['blocks']}


def safe_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError(f'unsafe name: {name!r}')
    return name


def cond_id(cond):
    if set(cond) != set(COND_KEYS):
        raise ValueError('condition must have all six contract keys')
    return '-'.join(cond[k] for k in COND_KEYS)


def build_plan(spec, blocks=None, profile=DEFAULT_PROFILE):
    """The takes of [profile] (only [blocks] when given), in spec order. A profile selects cells and may lower their
    reps; take IDs are the full grid's, so profiles and speakers compare take for take."""
    known = {b['id'] for b in spec['blocks']}
    if blocks and not set(blocks) <= known:
        raise ValueError('unknown block')
    chosen = profile_blocks(spec, profile)
    if blocks and not set(blocks) <= set(chosen):
        raise ValueError(f'block not in profile {profile!r}')
    plan = []
    for b in spec['blocks']:
        if b['id'] not in chosen or (blocks and b['id'] not in blocks):
            continue
        sel = chosen[b['id']]
        cells = set(sel['cells'])
        for c in b['cells']:
            if c['cell_id'] in cells:
                plan += [dict(c, block=b['id'], kind=b['kind'], bg_kind=c.get('kind'), rep=r,
                              take_id=f"{b['id']}-{c['cell_id']}-r{r}")
                         for r in range(1, (sel['reps'] or c['reps']) + 1)]
    return plan


def read_rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()] if Path(path).exists() else []


def latest_rows(path, key='take_id'):
    return {r[key]: r for r in read_rows(path)}


def append_row(path, row):
    with Path(path).open('a') as stream:
        stream.write(json.dumps(row, allow_nan=False) + '\n')
        stream.flush()


def write_json(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def private_dir(path):
    """Only known ignored local roots; no git discovery, network or device calls."""
    path = Path(path).expanduser().resolve()
    roots = (HERE / 'recordings', HERE.parent / 'android' / '.state', HERE.parent / 'zflip' / 'range')
    if not any(path.is_relative_to(root) and path != root for root in roots):
        raise ValueError('use a private session under extractor/recordings, android/.state, or zflip/range')
    return path


def disk_guard(path, needed=0):
    parent = Path(path)
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free - needed < 30 * 1024**3:
        raise RuntimeError('recording would leave less than 30 GiB free')


def open_session(out, spec, device, mic, rate, channels, synthetic=False, profile=DEFAULT_PROFILE,
                 speaker=DEFAULT_SPEAKER):
    profile_blocks(spec, profile)
    safe_name(speaker)
    disk_guard(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'session.json'
    if path.exists():
        meta = json.loads(path.read_text())
        if (meta['device'], meta['mic'], meta['rate'], meta['channels'], meta['synthetic']) != (
                device, mic, rate, channels, synthetic):
            raise ValueError('session device/mic/format/source differs; use another session')
        if (meta.get('profile', DEFAULT_PROFILE), meta.get('speaker', DEFAULT_SPEAKER)) != (profile, speaker):
            raise ValueError('session profile/speaker differs; use another session')
        if json.loads((out / 'spec.json').read_text()) != spec:
            raise ValueError('session spec differs; use the saved spec or another session')
    else:
        meta = dict(device=device, mic=mic, rate=rate, channels=channels, spec=spec['version'], synthetic=synthetic,
                    profile=profile, speaker=speaker,
                    range=dict(bottom_hz=None, home_hz=None, top_hz=None, whistle_home_hz=None, below_f0_min=False),
                    sittings=[], private='Never commit, upload, or send recordings to a model.')
        write_json(out / 'spec.json', spec)
    for name in ('labels.jsonl', 'backgrounds.jsonl', 'ratings.jsonl'):
        (out / name).touch(exist_ok=True)
    meta['sittings'].append(dict(started=time.time(), ended=None))
    write_json(path, meta)
    return meta


def label_row(take, redo, start_ms, go_ms, frames, rate):
    return {k: take[k] for k in ('take_id', 'block', 'expect', 'cond', 'cond_id', 'rep', 'bg')} | dict(
        file=f"takes/{take['block']}/{take['take_id']}.wav", redo=redo, t_go_ms=go_ms,
        dur_ms=frames * 1000 / rate, clip_start_ms=start_ms, go_offset_ms=go_ms - start_ms)


def rating(out, block, seconds, redos, spec, auto=False, ask=input):
    if auto:
        value, note = spec['ratings']['max'], 'SYNTHETIC self-test'
    else:
        while True:
            try:
                value = int(ask('Ease (1-5): '))
                if spec['ratings']['min'] <= value <= spec['ratings']['max']:
                    break
            except ValueError:
                pass
        note = ask('Note (optional): ')
    append_row(out / 'ratings.jsonl', dict(block=block, rating=value, note=note, seconds=seconds, redos=redos))


def getkey(auto=False, default='\n'):
    """The guided recorder's single-key control, kept stdlib-only for Android's dev env."""
    import sys
    if auto:
        return default
    if sys.stdin.isatty():
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            termios.tcflush(fd, termios.TCIFLUSH)
            while True:
                ch = sys.stdin.read(1)
                if ch in ('\n', '\r'):
                    return '\n'
                if ch.lower() in ('r', 's', 'q'):
                    return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    line = sys.stdin.readline()
    if not line:
        return 'q'
    line = line.strip().lower()
    return line[:1] if line[:1] in ('r', 's', 'q') else '\n'


def operate(items, done, capture, auto=False, key=getkey):
    """Enter records; r repeats the last take; s skips for this sitting; q resumes later.

    Also offer a review prompt after the final take, so its redo is reachable.
    capture must persist each accepted attempt before returning.
    """
    pending = [t for t in items if t['take_id'] not in done]
    previous = None
    redos = 0
    i = 0
    while i <= len(pending):
        if i == len(pending) and previous is None:
            break
        take = pending[i] if i < len(pending) else None
        print(take['cue'] if take else 'Block complete. Enter to finish; r to redo last.')
        print('Enter = record/continue · r = redo last · s = skip · q = quit')
        action = key(auto)
        if action == 'q':
            return False, redos
        if action == 'r':
            if previous is None:
                continue
            print('Redo: ' + previous['cue'])
            capture(previous)
            redos += 1
            continue
        if take is None:
            break
        if action != 's':
            capture(take)
            previous = take
        i += 1
    return True, redos


def validate_session(path, spec=None, complete=False):
    path = Path(path)
    spec = spec or load_spec(path / 'spec.json' if (path / 'spec.json').exists() else SPEC_PATH)
    for name in ('session.json', 'labels.jsonl', 'backgrounds.jsonl', 'ratings.jsonl'):
        if not (path / name).is_file():
            raise ValueError(f'missing layout file: {name}')
    meta = json.loads((path / 'session.json').read_text())
    if type(meta['rate']) is not int or meta['rate'] <= 0 or meta['channels'] not in (1, 2):
        raise ValueError('invalid session rate/channels')
    if meta['device'] not in ('desktop', 'phone') or meta['spec'] != spec['version']:
        raise ValueError('bad session device/spec')
    if not isinstance(meta['mic'], str) or not isinstance(meta['sittings'], list):
        raise ValueError('bad mic/sittings')
    for k in ('bottom_hz', 'home_hz', 'top_hz', 'whistle_home_hz'):
        v = meta['range'][k]
        if v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0):
            raise ValueError('invalid range Hz')
        if complete and v is None:
            raise ValueError('range needs finalize or rerecording')
    if not isinstance(meta['range']['below_f0_min'], bool):
        raise ValueError('bad range flag')
    profile = session_profile(meta)
    blocks = set(profile_blocks(spec, profile))
    safe_name(session_speaker(meta))
    full = build_plan(spec, profile=profile)
    plan = {t['take_id']: t for t in full if t['kind'] == 'takes'}
    rows = latest_rows(path / 'labels.jsonl')

    def wav_info(file):
        target = (path / file).resolve()
        if not target.is_relative_to(path.resolve()):
            raise ValueError('WAV escapes session')
        with wave.open(str(target), 'rb') as w:
            n, ch, rate = w.getnframes(), w.getnchannels(), w.getframerate()
            if (w.getsampwidth(), ch, rate) != (2, meta['channels'], meta['rate']):
                raise ValueError('WAV format mismatch')
            if len(w.readframes(n)) != n * ch * 2 or n <= 0:
                raise ValueError('empty/truncated WAV')
        return n * 1000 / rate

    for tid, r in rows.items():
        if tid not in plan:
            raise ValueError('unknown take_id')
        t = plan[tid]
        for k in ('block', 'expect', 'cond', 'cond_id', 'rep', 'bg'):
            if r[k] != t[k]:
                raise ValueError(f'{tid}: {k} differs from spec')
        if r['file'] != f"takes/{t['block']}/{tid}.wav" or type(r['redo']) is not int or r['redo'] < 0:
            raise ValueError('bad file/redo')
        if any(not math.isfinite(r[k]) or r[k] < 0 for k in ('t_go_ms', 'dur_ms')) or abs(
                wav_info(r['file']) - r['dur_ms']) > 1000 / meta['rate']:
            raise ValueError('bad take timing')
        if 'go_offset_ms' in r and (not math.isfinite(r['go_offset_ms']) or
                abs(r['go_offset_ms'] - spec['analysis']['pre_roll_s'] * 1000) > 1000 / meta['rate'] or
                r['go_offset_ms'] >= r['dur_ms'] or
                abs(r['clip_start_ms'] + r['go_offset_ms'] - r['t_go_ms']) > 1000 / meta['rate']):
            raise ValueError('bad GO/pre-roll mapping')
    bgs = latest_rows(path / 'backgrounds.jsonl', 'name')
    expected_bg = {t['name']: t for t in full if t['kind'] == 'backgrounds'}
    for name, r in bgs.items():
        if name not in expected_bg:
            raise ValueError('unknown background')
        t = expected_bg[name]
        if r['kind'] != t['bg_kind'] or any(r[k] != t[k] for k in ('level', 'seconds')) or r['file'] != f'backgrounds/{name}.wav':
            raise ValueError('background differs from spec')
        if abs(wav_info(r['file']) / 1000 - r['seconds']) > 1 / meta['rate']:
            raise ValueError('background duration mismatch')
    ratings = read_rows(path / 'ratings.jsonl')
    for r in ratings:
        if r['block'] not in blocks or type(r['rating']) is not int or not (
                spec['ratings']['min'] <= r['rating'] <= spec['ratings']['max']):
            raise ValueError('invalid rating')
        if not isinstance(r['note'], str) or r['seconds'] < 0 or type(r['redos']) is not int or r['redos'] < 0:
            raise ValueError('invalid rating metadata')
    if complete and (set(rows) != set(plan) or set(bgs) != set(expected_bg) or
                     {r['block'] for r in ratings} != blocks):
        raise ValueError('incomplete session')
    return dict(takes=len(rows), backgrounds=len(bgs), ratings=len(ratings), sittings=len(meta['sittings']))


def session_profile(meta):
    """The session's profile ("full" for sessions recorded before profiles existed)."""
    return meta.get('profile', DEFAULT_PROFILE)


def session_speaker(meta):
    """The session's speaker id ("self" for sessions recorded before speakers existed)."""
    return meta.get('speaker', DEFAULT_SPEAKER)


def default_session_name(speaker=DEFAULT_SPEAKER):
    return time.strftime('range-%Y%m%d-%H%M%S' if speaker == DEFAULT_SPEAKER else f'range-{safe_name(speaker)}-%Y%m%d-%H%M%S')


validate_layout = validate_session
