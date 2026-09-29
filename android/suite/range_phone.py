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
import shutil
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


def pull_dest(out):
    """The recorder's local destination: <repo>/zflip/range by default, or --out under a private root."""
    if out is None:
        return EXTRACTOR.parent / 'zflip' / 'range'
    return L.private_dir(out)


QUICKREC_ROOTS = (EXTRACTOR.parent / 'zflip' / 'quickrec', EXTRACTOR.parent / 'android' / '.state')


def quickrec_dir(path):
    """Quick-record clips land only under the gitignored zflip/quickrec or android/.state (never a tracked path)."""
    path = Path(path).expanduser().resolve()
    if not any(path == root or path.is_relative_to(root) for root in QUICKREC_ROOTS):
        raise ValueError('quick records go under zflip/quickrec or android/.state')
    return path


def _remote_entries(prefix):
    """The run-as find listing under [prefix] (relative to the app's data dir), byte-safe. Stdlib only."""
    return [e for e in
            measure.adb("exec-out", "run-as", voxlib.APP, "sh", "-c",
                        f"find {prefix} -type f 2>/dev/null; true", binary=True).decode(errors="replace").split()
            if e]


def _remote_names(folder):
    return [n for n in measure.adb("exec-out", "run-as", voxlib.APP, "sh", "-c", f"ls {folder} 2>/dev/null; true",
                                   binary=True).decode(errors="replace").split() if n]


def _copy_remote_dir(prefix, target):
    """Byte-exact copy of every finished remote file under [prefix] into [target]; every WAV is checked with
    measure.wav_info. The app writes <name>.tmp(.wav) then renames, so a .tmp file is a write in progress: skipped."""
    files = [f for f in _remote_entries(prefix) if '.tmp' not in f.rsplit('/', 1)[-1]]
    target.mkdir(parents=True, exist_ok=True)
    for rf in files:
        rel = rf[len(prefix) + 1:]
        if not rel:
            continue
        size = int(measure.adb("exec-out", "run-as", voxlib.APP, "stat", "-c", "%s", rf).strip())
        L.disk_guard(target, size)
        data = measure.adb("exec-out", "run-as", voxlib.APP, "cat", rf, binary=True)
        if len(data) != size:
            raise ValueError(f"{rel}: byte size mismatch ({len(data)} != {size})")
        if rel.endswith('.wav'):
            measure.wav_info(data)
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if p.stat().st_size != size:
            raise ValueError(f"{rel}: local verification failed")
    return target


def _replace(target, src, check=None):
    """Swaps [src] in for [target]: the old folder is renamed aside first and deleted only after the new one is in
    place, so a failure never leaves neither. [check] refuses an existing folder (a desktop session is never replaced)."""
    if target.exists():
        if check:
            check(target)
        aside = target.with_name(f'.old-{time.time_ns()}-{target.name}')
        target.rename(aside)
        try:
            src.rename(target)
        except BaseException:
            aside.rename(target)
            raise
        shutil.rmtree(aside)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        src.rename(target)


def _app_only(target):
    meta = target / 'session.json'
    if not meta.exists() or json.loads(meta.read_text()).get('recorder') != 'app':
        raise ValueError(f"{target.name}: existing local folder is not a recorder 'app' session")


def _journal_extends(local, remote):
    """True when [remote] (the phone's journal) starts with [local] (the PC copy): the phone must extend the local
    one, so a local row the phone lacks (e.g. a delete made on the PC) refuses the replace."""
    for name in ('labels.jsonl', 'backgrounds.jsonl'):
        lr = L.read_rows(local / name)
        rr = L.read_rows(remote / name)
        if rr[:len(lr)] != lr:
            return False
    return True


def pull(vox, dest, sessions=None, quickrec=False, clear=False, quickrec_dest=None, confirm=None, force=False):
    """The recorder pull (contract §8): verify every session into .pull-<ns>, replace (recorder "app" folders only),
    then, only with [clear] and a yes from [confirm], rec_clear exactly the verified names/ids. Everything lands under
    gitignored roots (zflip/range or --out via private_dir; zflip/quickrec). Never runs against a real device in tests.

    A local copy is replaced only if the phone's journal extends the local one (a PC-side delete would be lost
    otherwise); [force] replaces it anyway."""
    dest = Path(dest).expanduser().resolve()
    qdest = quickrec_dir(quickrec_dest or QUICKREC_ROOTS[0])
    st = vox.control("rec_status")
    if st.get("active"):
        raise RuntimeError(f"session {st.get('name')} is open in the app; rec_close first")
    names = _remote_names("files/range")
    if sessions is not None:
        missing = [s for s in sessions if s not in names]
        if missing:
            raise ValueError(f"no such session: {', '.join(missing)}")
        names = [n for n in names if n in sessions]
    for name in names:
        L.safe_name(name)
        L.private_dir(dest / name)
    qids = [q for q in _remote_names("files/quickrec") if L.safe_name(q)] if quickrec else []
    if not names and not qids:
        raise ValueError("nothing to pull: no recorder sessions" + (" or quick records" if quickrec else "")
                         + " on the device")
    staging = dest / f".pull-{time.time_ns()}"
    qdone = []
    try:
        for name in names:
            _copy_remote_dir(f"files/range/{name}", staging / name)
            L.validate_session(staging / name)   # complete=False
        for qid in qids:
            q = _copy_remote_dir(f"files/quickrec/{qid}", staging / 'quickrec' / qid)
            if (q / 'clip.wav').exists() and (q / 'meta.json').exists():
                qdone.append(qid)                  # an unfinished save stays on the phone (never cleared)
        # all verified: replace, then clear only the verified names/ids
        for name in names:
            target = dest / name
            if target.exists() and not force and not _journal_extends(target, staging / name):
                raise ValueError(f"{name}: changed on the PC since the last pull (a delete?); "
                                 "delete on the phone too, or pass --force")
            _replace(target, staging / name, _app_only)
        for qid in qdone:
            _replace(qdest / qid, staging / 'quickrec' / qid)
        if clear and (names or qdone):
            what = f"{len(names)} session(s) and {len(qdone)} quick record(s)"
            if confirm is None or not confirm(f"Pulled and verified {what}. Delete them from the phone? [y/N] "):
                print("Left on the phone.")
            else:
                r = vox.control("rec_clear", sessions=names, quickrec=qdone)
                if not r.get("ok"):
                    raise RuntimeError(f"rec_clear: {r.get('error')}")
                gone = r.get("deleted") or {}
                if sorted(gone.get("sessions", [])) != sorted(names) or sorted(gone.get("quickrec", [])) != sorted(qdone):
                    print(f"Warning: the phone deleted {gone}, asked for {names} + {qdone}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return names, qdone


def ask(prompt):
    return input(prompt).strip().lower() in ('y', 'yes')


# --- push (contract L): explicit PC -> phone copies under files/range_pc/ ------------------------------------------

PUSH_FILES = ('session.json', 'spec.json', 'labels.jsonl', 'backgrounds.jsonl', 'ratings.jsonl', 'report.json')


def _push_files(session):
    """The relative paths a push copies: the fixed json/jsonl/report files plus every takes/**/*.wav and
    backgrounds/*.wav. run-*/, trash/ and report.md are never copied."""
    out = []
    for name in PUSH_FILES:
        if (session / name).is_file():
            out.append(name)
    for sub in ('takes', 'backgrounds'):
        for f in sorted((session / sub).rglob('*.wav')):
            if f.is_file():
                out.append(f.relative_to(session).as_posix())
    return out


def _write_remote(path, data):
    """Byte-exact write through `adb exec-in run-as <app> sh -c 'cat > <path>'` (contract L)."""
    measure.adb("exec-in", "run-as", voxlib.APP, "sh", "-c", f"cat > {path}", binary=True, input=data)


def _remote_size(path):
    return int(measure.adb("exec-out", "run-as", voxlib.APP, "stat", "-c", "%s", path).strip())


def _remote_sh(cmd):
    return measure.adb("exec-out", "run-as", voxlib.APP, "sh", "-c", f"{cmd} 2>/dev/null; true", binary=True)


def _pushed_names():
    return [n for n in _remote_names("files/range_pc") if not n.startswith('.')]


def push(sessions, replace=False):
    """The recorder push (contract L): validate each local session (a private root, the phone owner's own "self"
    speaker only), copy its fixed files + WAVs into files/range_pc/.staging-<name>/ (size-checked, never run-*/,
    trash/ or report.md), then swap it in as files/range_pc/<name>/ (the old copy is removed only after the new one is
    complete). Only your own sessions go to the phone (exit 2, no override)."""
    existing = set(_pushed_names())
    pushed = []
    for s in sessions:
        s = Path(s).expanduser().resolve()
        L.private_dir(s)
        meta = json.loads((s / 'session.json').read_text())
        if meta.get('speaker', L.DEFAULT_SPEAKER) != L.DEFAULT_SPEAKER:
            print("only your own sessions go to the phone", file=sys.stderr)
            sys.exit(2)
        L.validate_session(s)
        name = s.name
        L.safe_name(name)
        if name in existing and not replace:
            raise ValueError(f"{name}: already on the phone; pass --replace")
        staging = f"files/range_pc/.staging-{name}"
        try:
            for rel in _push_files(s):
                data = (s / rel).read_bytes()
                remote = f"{staging}/{rel}"
                _write_remote(remote, data)
                if _remote_size(remote) != len(data):
                    raise ValueError(f"{rel}: byte size mismatch on device")
            # all verified: remove the old copy, then move the staging in
            _remote_sh(f"rm -rf files/range_pc/{name}; mv {staging} files/range_pc/{name}")
        except BaseException:
            _remote_sh(f"rm -rf {staging}")
            raise
        pushed.append(name)
    return pushed


def remove_pushed(name, yes=False):
    """--remove: delete one pushed copy (a typed yes unless [yes])."""
    L.safe_name(name)
    if name not in _pushed_names():
        raise ValueError(f"no such pushed session: {name}")
    if not yes and not ask(f"Remove {name} from the phone? [y/N] "):
        return False
    _remote_sh(f"rm -rf files/range_pc/{name}")
    return True


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
    pull_cmd = subs.add_parser('pull', help='copy test recorder sessions (and quick records) off the phone')
    pull_cmd.add_argument('--out', type=Path, help='default zflip/range; must be a private root')
    pull_cmd.add_argument('--session', action='append', help='only this session (repeatable); default all')
    pull_cmd.add_argument('--quickrec', action='store_true', help='also pull quick records to zflip/quickrec')
    pull_cmd.add_argument('--clear', action='store_true', help='after verifying, offer to delete them on the phone')
    pull_cmd.add_argument('--yes', action='store_true', help='with --clear: delete without asking')
    pull_cmd.add_argument('--force', action='store_true', help='replace a local copy even if it has rows the phone lacks')
    push_cmd = subs.add_parser('push', help='copy your own PC range sessions into the app (files/range_pc/)')
    push_cmd.add_argument('session', type=Path, nargs='*')
    push_cmd.add_argument('--replace', action='store_true', help='replace an existing pushed copy')
    push_cmd.add_argument('--list', action='store_true', help='show the pushed names')
    push_cmd.add_argument('--remove', metavar='NAME', help='delete one pushed copy')
    push_cmd.add_argument('--yes', action='store_true', help='with --remove: delete without asking')
    args = p.parse_args()
    if args.command == 'finalize':
        from range_session import finalize_range
        out = L.private_dir(args.session)
        finalize_range(out, L.load_spec(out / 'spec.json'))
        L.validate_session(out)
    elif args.command == 'pull':
        dest = pull_dest(args.out)
        vox = voxlib.Vox()
        try:
            names, qids = pull(vox, dest, args.session, args.quickrec, args.clear,
                               confirm=(lambda _: True) if args.yes else ask, force=args.force)
            print("Pulled: " + " ".join(names + [f"quickrec/{q}" for q in qids]))
            if names:
                print("Next: finalize each session under extractor/run (range_session.py), then range_suite.py.")
        finally:
            vox.close()
    elif args.command == 'push':
        if args.list:
            print(" ".join(_pushed_names()))
        elif args.remove:
            print(f"Removed {args.remove}" if remove_pushed(args.remove, yes=args.yes) else "Left on the phone.")
        else:
            if not args.session:
                p.error('push needs at least one session dir (or --list / --remove)')
            print("Pushed: " + " ".join(push(args.session, replace=args.replace)))
    else:
        run_session(args)


if __name__ == '__main__':
    main()
