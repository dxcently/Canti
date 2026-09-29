"""Stdlib-only shared range spec, journal and layout contract.

validate_session(path, spec=None, complete=False) raises ValueError on invalid
metadata/audio and returns counts. Incomplete sittings are valid by default.
The last labels.jsonl row for a take_id wins (take_rows). t_go_ms is on the source clock;
clip_start_ms and go_offset_ms map it to the local take WAV, dur_ms is WAV length.

Missed takes (the phone's in-app recorder): a take its silence detector heard nothing in is saved with
`no_sound: true` and `attempt: <n>` (its redo) at takes/<block>/<take_id>.a<n>.wav, so a Try again never overwrites
it. The plain takes/<block>/<take_id>.wav is always the latest heard attempt. The take is its last heard row, else
(only missed attempts) its last missed one; no_sound_rows lists every missed attempt (range_suite counts them as
gate misses).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / 'prompts' / 'range_v2.json'
COND_KEYS = ('tone', 'pitch', 'speed', 'loud', 'dist', 'gap')
DEFAULT_PROFILE = 'full'
DEFAULT_SPEAKER = 'self'
SPEC_VERSIONS = ('range_v1', 'range_v2')


def load_spec(path=SPEC_PATH):
    spec = json.loads(Path(path).read_text())
    if spec['version'] not in SPEC_VERSIONS:
        raise ValueError('expected range_v1 or range_v2')
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


def is_no_sound(row):
    """A missed attempt: the recorder's silence detector heard nothing (the phone app tags it; kept, never overwritten)."""
    return row.get('no_sound') is True


def take_file(block, take_id, attempt=None):
    """A take's WAV: the plain path for a heard attempt, `.a<attempt>` for a missed (no_sound) one."""
    return f"takes/{block}/{take_id}.wav" if attempt is None else f"takes/{block}/{take_id}.a{attempt}.wav"


def _row_key(row):
    """A data/op row's target: its take_id (labels journal), else its name (backgrounds journal)."""
    return row['take_id'] if 'take_id' in row else row.get('name')


def effective_rows(rows):
    """(effective take/background rows, deletes in force, restorable del_ids) for one journal, in journal order.

    An operation row carries "op". A delete (op "delete") excludes the earlier rows its scope names (contract T):
    scope "take" excludes every earlier row of the take, "attempt" with an int excludes that missed (no_sound)
    attempt, "attempt" with null excludes the earlier heard attempts (they all name the plain path, the moved file).
    A restore (op "restore") undoes a delete (its del_id leaves the in-force set); a purge (op "purge") removes a
    delete's trash so it can never be restored but stays in force. Op rows are never effective rows themselves.
    """
    rows = list(rows)
    deletes, order, restored, purged = {}, [], set(), set()
    for r in rows:
        op = r.get('op')
        if op == 'delete':
            deletes[r['del_id']] = r
            order.append(r['del_id'])
        elif op == 'restore':
            restored.add(r['del_id'])
        elif op == 'purge':
            purged.update(r.get('del_ids') or [])
    in_force = [d for d in order if d not in restored]
    restorable = [d for d in in_force if d not in purged]
    excluded = set()
    for did in in_force:
        d = deletes[did]
        key, scope, attempt = _row_key(d), d['scope'], d.get('attempt')
        for i, r in enumerate(rows[:rows.index(d)]):
            if r.get('op') or _row_key(r) != key:
                continue
            if scope == 'take':
                excluded.add(i)
            elif attempt is not None:
                if is_no_sound(r) and r.get('attempt') == attempt:
                    excluded.add(i)
            elif not is_no_sound(r):
                excluded.add(i)
    effective = [r for i, r in enumerate(rows) if not r.get('op') and i not in excluded]
    return effective, in_force, restorable


def delete_files(rows, take_id, scope='take', attempt=None):
    """The distinct relative paths a delete of [take_id] with [scope]/[attempt] moves (contract T)."""
    if scope not in ('take', 'attempt'):
        raise ValueError('bad delete scope')
    files = []
    for r in rows:
        if r.get('op') or _row_key(r) != take_id:
            continue
        if scope == 'take':
            files.append(r['file'])
        elif attempt is not None:
            if is_no_sound(r) and r.get('attempt') == attempt:
                files.append(r['file'])
        elif not is_no_sound(r):
            files.append(r['file'])
    return list(dict.fromkeys(files))


def _new_del_id(rows):
    """d<wall_ms>-<n>: n counts the delete rows already in the journal, so a del_id is never reused."""
    return f"d{int(time.time() * 1000)}-{sum(1 for r in rows if r.get('op') == 'delete')}"


def _move_to_trash(out, del_id, files):
    """Moves each existing [files] to trash/<del_id>/<file>, returning the ones actually moved."""
    moved = []
    for f in files:
        src = out / f
        if src.exists():
            dst = out / 'trash' / del_id / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            moved.append(f)
    return moved


def delete_take(out, take_id, scope='take', attempt=None):
    """Soft-delete a take: move its WAV(s) to trash/<del_id>/<file>, THEN append the delete row (contract T)."""
    out = Path(out)
    rows = read_rows(out / 'labels.jsonl')
    files = delete_files(rows, take_id, scope, attempt)
    del_id = _new_del_id(rows)
    moved = _move_to_trash(out, del_id, files)
    append_row(out / 'labels.jsonl', dict(op='delete', del_id=del_id, take_id=take_id, scope=scope, attempt=attempt,
                                          files=moved, trash=f'trash/{del_id}', t=time.time()))
    return del_id


def delete_background(out, name):
    """Soft-delete a background (scope "take"): move its WAV to trash, THEN append the row to backgrounds.jsonl."""
    out = Path(out)
    rows = read_rows(out / 'backgrounds.jsonl')
    files = delete_files(rows, name, 'take')
    del_id = _new_del_id(rows)
    moved = _move_to_trash(out, del_id, files)
    append_row(out / 'backgrounds.jsonl', dict(op='delete', del_id=del_id, name=name, scope='take', attempt=None,
                                               files=moved, trash=f'trash/{del_id}', t=time.time()))
    return del_id


def restore(out, del_id):
    """Undo a delete: move its files back, THEN append the restore row. Refused (no row) if a destination exists
    again, if the delete was purged, or if it was already restored."""
    out = Path(out)
    for journal in ('labels.jsonl', 'backgrounds.jsonl'):
        rows = read_rows(out / journal)
        d = next((r for r in rows if r.get('op') == 'delete' and r.get('del_id') == del_id), None)
        if d is None:
            continue
        purged = {did for r in rows if r.get('op') == 'purge' for did in (r.get('del_ids') or [])}
        if del_id in purged:
            raise ValueError(f'{del_id}: already purged, cannot restore')
        if any(r.get('op') == 'restore' and r.get('del_id') == del_id for r in rows):
            raise ValueError(f'{del_id}: already restored')
        for f in d['files']:
            if (out / f).exists():
                raise ValueError(f'{del_id}: {f} exists now (the take was re-recorded)')
        for f in d['files']:
            os.replace(out / 'trash' / del_id / f, out / f)
        shutil.rmtree(out / 'trash' / del_id, ignore_errors=True)
        key = 'take_id' if 'take_id' in d else 'name'
        append_row(out / journal, dict(op='restore', del_id=del_id, **{key: d[key]}, t=time.time()))
        return d[key]
    raise ValueError(f'unknown delete {del_id!r}')


def purge_trash(out, del_ids=None):
    """Remove trash/<del_id>/ for each id and append a purge row. None purges every restorable delete (clear trash)."""
    out = Path(out)
    if del_ids is None:
        del_ids = effective_rows(read_rows(out / 'labels.jsonl'))[2] + \
            effective_rows(read_rows(out / 'backgrounds.jsonl'))[2]
    del_ids = list(del_ids)
    for did in del_ids:
        shutil.rmtree(out / 'trash' / did, ignore_errors=True)
    # Each purge row goes to the journal that holds the delete, so that journal's restore sees it (backgrounds too).
    bg = {r['del_id'] for r in read_rows(out / 'backgrounds.jsonl') if r.get('op') == 'delete'}
    takes = [d for d in del_ids if d not in bg]
    bgs = [d for d in del_ids if d in bg]
    if takes or not bgs:
        append_row(out / 'labels.jsonl', dict(op='purge', del_ids=takes, take_id=None, t=time.time()))
    if bgs:
        append_row(out / 'backgrounds.jsonl', dict(op='purge', del_ids=bgs, name=None, t=time.time()))
    return del_ids


def next_redo(rows, take_id):
    """The next redo of a take is 1 + its max redo over ALL take rows, excluded ones included (an .a<N> name is
    never reused)."""
    redos = [r['redo'] for r in rows if r.get('take_id') == take_id and not r.get('op') and 'redo' in r]
    return max(redos) + 1 if redos else 0


def latest_rows(path, key='take_id'):
    return {r[key]: r for r in effective_rows(read_rows(path))[0]}


def take_rows(path_or_rows):
    """{take_id: the take's row}: its last heard (not no_sound) row, else its last row (only missed attempts)."""
    rows = read_rows(path_or_rows) if isinstance(path_or_rows, (str, Path)) else path_or_rows
    out = {}
    for r in effective_rows(rows)[0]:
        if not is_no_sound(r) or r['take_id'] not in out or is_no_sound(out[r['take_id']]):
            out[r['take_id']] = r
    return out


def no_sound_rows(path_or_rows):
    """Every missed (no_sound) attempt, in journal order."""
    rows = read_rows(path_or_rows) if isinstance(path_or_rows, (str, Path)) else path_or_rows
    return [r for r in effective_rows(rows)[0] if is_no_sound(r)]


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
                 speaker=DEFAULT_SPEAKER, recorder=None, twin=None):
    profile_blocks(spec, profile)
    safe_name(speaker)
    disk_guard(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'session.json'
    if path.exists():
        meta = json.loads(path.read_text())
        if meta.get('spec') != spec['version']:
            raise ValueError(f"session {out.name} was recorded with {meta.get('spec')}; this recorder runs "
                             f"{spec['version']}. Start a new session, or pass --spec prompts/{meta.get('spec')}.json "
                             "to finish it")
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
        if recorder is not None:
            meta['recorder'] = recorder
        if twin is not None:
            meta['twin'] = twin
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


def getkey(auto=False, default='\n', extra=''):
    """The guided recorder's single-key control, kept stdlib-only for Android's dev env. [extra] adds accepted keys
    (e.g. 'du' for the range recorder's delete/undo) without changing guided_session's default set."""
    import sys
    keys = tuple('rsq' + extra)
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
                if ch.lower() in keys:
                    return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    line = sys.stdin.readline()
    if not line:
        return 'q'
    line = line.strip().lower()
    return line[:1] if line[:1] in keys else '\n'


def cue_text(cue, tty):
    """The cue, with its ALL-CAPS key words in reverse video (ANSI) on a TTY, plain otherwise."""
    if not tty:
        return cue
    return re.sub(r'(?<![A-Za-z0-9])[A-Z]{2,}(?![A-Za-z0-9])',
                  lambda m: f'\x1b[7m{m.group(0)}\x1b[0m', cue)


def operate(items, done, capture, auto=False, key=getkey, delete=None, undo=None, count=None):
    """Enter records; r repeats the last take; s skips for this sitting; q resumes later.

    d deletes the last saved take this sitting (after a y/N confirm; it is prompted again next) and u restores the
    most recent delete of this sitting. [delete] (take -> del_id), [undo] (del_id -> take_id) and [count] (take ->
    number of files moved) are the range recorder's hooks; without them d/u are not offered and nothing changes.
    Also offer a review prompt after the final take, so its redo is reachable.
    capture must persist each accepted attempt before returning.
    """
    import sys
    tty = sys.stdout.isatty()
    pending = [t for t in items if t['take_id'] not in done]
    previous = None
    deleted = []
    redos = 0
    i = 0
    while i <= len(pending):
        if i == len(pending) and previous is None:
            break
        take = pending[i] if i < len(pending) else None
        print(cue_text(take['cue'], tty) if take else 'Block complete. Enter to finish; r to redo last.')
        keys = 'Enter = record/continue · r = redo last · s = skip · q = quit'
        if delete is not None:
            keys += ' · d = delete last · u = undo'
        print(keys)
        action = key(auto)
        if action == 'q':
            return False, redos
        if action == 'r':
            if previous is None:
                continue
            print('Redo: ' + cue_text(previous['cue'], tty))
            capture(previous)
            redos += 1
            continue
        if action == 'd' and delete is not None:
            if previous is None:
                continue
            n = (count or (lambda t: 1))(previous)
            print(f'Delete {previous["take_id"]} ({n} attempt files)? y/N')
            if key(auto) != 'y':
                continue
            del_id = delete(previous)
            if del_id is not None:
                deleted.append((previous, del_id))
                print('Deleted. u = undo')
                i -= 1
            continue
        if action == 'u' and undo is not None:
            if not deleted:
                continue
            take0, del_id = deleted[-1]
            restored = undo(del_id)
            if restored is not None:
                deleted.pop()
                i += 1
                print(f'Restored {restored}.')
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
    if 'twin' in meta and meta['twin'] is not None and not isinstance(meta['twin'], str):
        raise ValueError('bad twin (a session folder name or null)')
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
    journal = read_rows(path / 'labels.jsonl')
    rows = take_rows(journal)
    missed = no_sound_rows(journal)

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

    # the take rows, plus every missed attempt (each keeps its own .a<n> WAV)
    checked = list(rows.values()) + [r for r in missed if r is not rows.get(r['take_id'])]
    for r in checked:
        tid = r['take_id']
        if tid not in plan:
            raise ValueError('unknown take_id')
        t = plan[tid]
        for k in ('block', 'expect', 'cond', 'cond_id', 'rep', 'bg'):
            if r[k] != t[k]:
                raise ValueError(f'{tid}: {k} differs from spec')
        if 'no_sound' in r and not isinstance(r['no_sound'], bool):
            raise ValueError('bad no_sound flag')
        if is_no_sound(r):
            if type(r.get('attempt')) is not int or r['attempt'] < 0:
                raise ValueError(f'{tid}: a no_sound row needs an int attempt')
            want = take_file(t['block'], tid, r['attempt'])
        else:
            want = take_file(t['block'], tid)
        if r['file'] != want or type(r['redo']) is not int or r['redo'] < 0:
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
    bg_journal = read_rows(path / 'backgrounds.jsonl')

    # operation rows (contract T): validate their shape, and count the deletes still in force.
    del_ids = set()
    for op_rows, known in ((journal, plan), (bg_journal, expected_bg)):
        for r in op_rows:
            op = r.get('op')
            if op is None:
                continue
            if op not in ('delete', 'restore', 'purge'):
                raise ValueError('unknown op')
            if op == 'purge':
                if r.get('take_id') is not None or not isinstance(r.get('del_ids'), list):
                    raise ValueError('bad purge row')
                continue
            did = r.get('del_id')
            if not isinstance(did, str) or not did:
                raise ValueError('bad del_id')
            if op == 'delete':
                if did in del_ids:
                    raise ValueError('duplicate del_id')
                del_ids.add(did)
                if r.get('scope') not in ('take', 'attempt'):
                    raise ValueError('bad delete scope')
                if r.get('attempt') is not None and type(r.get('attempt')) is not int:
                    raise ValueError('bad delete attempt')
            if _row_key(r) not in known:
                raise ValueError('unknown delete/restore target')
    deleted = len(effective_rows(journal)[1]) + len(effective_rows(bg_journal)[1])

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
    if len({(r['take_id'], r['attempt']) for r in missed}) != len(missed):
        raise ValueError('duplicate no_sound attempt')
    return dict(takes=len(rows), backgrounds=len(bgs), ratings=len(ratings), sittings=len(meta['sittings']),
                no_sound=len(missed), deleted=deleted)


def session_profile(meta):
    """The session's profile ("full" for sessions recorded before profiles existed)."""
    return meta.get('profile', DEFAULT_PROFILE)


def session_speaker(meta):
    """The session's speaker id ("self" for sessions recorded before speakers existed)."""
    return meta.get('speaker', DEFAULT_SPEAKER)


def default_session_name(speaker=DEFAULT_SPEAKER):
    return time.strftime('range-%Y%m%d-%H%M%S' if speaker == DEFAULT_SPEAKER else f'range-{safe_name(speaker)}-%Y%m%d-%H%M%S')


validate_layout = validate_session
