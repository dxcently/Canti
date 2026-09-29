"""The recorder pull (range_phone.pull, contract §8) against a fake adb/vox that serves a session written the way the
app writes it. Synthetic audio only; no device or git calls."""
import json
import shutil
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

import range_layout as L

sys.path.insert(0, str(L.HERE.parent / 'android' / 'suite'))
import measure
import range_phone as P


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    monkeypatch.setattr(measure, 'adb', lambda *a, **k: pytest.fail('unmocked adb'))
    monkeypatch.setattr(P.voxlib, 'Vox', lambda: pytest.fail('unmocked Vox'))


@pytest.fixture
def tmp_path():
    """Pulls only write under the gitignored roots, so every test works in a private android/.state folder."""
    root = L.HERE.parent / 'android' / '.state'
    root.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix='range-pull-', dir=root))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def spec():
    return L.load_spec()


def write_wav(path, samples, rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        w.writeframes(np.asarray(samples).astype('<i2').tobytes())


def build_session(root, name, recorder='app'):
    """Writes one recorder session the way the app does (the exact range_layout layout)."""
    sp = spec()
    sess = root / 'files' / 'range' / name
    sess.mkdir(parents=True)
    L.write_json(sess / 'spec.json', sp)
    meta = dict(device='phone', mic='phone built-in mic', rate=16000, channels=1, spec='range_v1',
                synthetic=False, profile='short', speaker='self',
                range=dict(bottom_hz=None, home_hz=None, top_hz=None, whistle_home_hz=None, below_f0_min=False),
                sittings=[dict(started=1.0, ended=None)],
                private='Never commit, upload, or send recordings to a model.',
                recorder=recorder, range_pending=True,
                app_range=dict(bottom_hz=None, home_hz=None, top_hz=None, whistle_home_hz=None),
                skipped_by_sitting=[[]])
    L.write_json(sess / 'session.json', meta)
    for j in ('labels.jsonl', 'backgrounds.jsonl', 'ratings.jsonl'):
        (sess / j).write_text('')
    take = next(t for t in L.build_plan(sp, profile='short') if t['kind'] == 'takes')
    clip = np.arange(16000 * 2, dtype='<i2')   # 2 s
    write_wav(sess / 'takes' / take['block'] / f"{take['take_id']}.wav", clip)
    L.append_row(sess / 'labels.jsonl', L.label_row(take, 0, 0, 1000, len(clip), 16000))
    return sess


class RecPhone:
    """Fake vox + adb: serves the files/ layout from [files], records control calls, can corrupt a transfer."""
    def __init__(self, files):
        self.files = {str(p.relative_to(files)): p.read_bytes() for p in files.rglob('*') if p.is_file()}
        self.calls = []
        self.open = None
        self.corrupt = None

    def control(self, op, **kw):
        self.calls.append((op, kw))
        if op == 'rec_status':
            return dict(ok=True, active=self.open is not None, name=self.open)
        if op == 'rec_clear':
            return dict(ok=True, deleted=dict(sessions=kw['sessions'], quickrec=kw['quickrec']))
        raise AssertionError(op)

    def adb(self, *args, **kw):
        cmd = ' '.join(str(a) for a in args)
        if 'ls files/range' in cmd:
            names = sorted({p.split('/')[2] for p in self.files if p.startswith('files/range/')})
            return ('\n'.join(names) + '\n').encode()
        if 'ls files/quickrec' in cmd:
            names = sorted({p.split('/')[2] for p in self.files if p.startswith('files/quickrec/')})
            return ('\n'.join(names) + '\n').encode()
        if 'find files/range' in cmd or 'find files/quickrec' in cmd:
            prefix = cmd.split('find ')[1].split(' -type')[0]
            return ('\n'.join(sorted(p for p in self.files if p.startswith(prefix + '/')))).encode()
        if 'stat' in args:
            return str(len(self.files[args[-1]])).encode()
        if 'cat' in args:
            data = self.files[args[-1]]
            if self.corrupt == args[-1]:
                data = data[:-2]
            return data
        raise AssertionError(args)


def pull_phone(tmp_path, monkeypatch, files, **kw):
    phone = RecPhone(files)
    monkeypatch.setattr(measure, 'adb', phone.adb)
    monkeypatch.setattr(measure.subprocess, 'run', lambda *a, **k: pytest.fail('git/subprocess forbidden'))
    return phone, P.pull(phone, tmp_path / 'dest', quickrec_dest=tmp_path / 'quickrec', **kw)


def test_pull_validates_and_replaces(tmp_path, monkeypatch):
    files = tmp_path / 'remote'
    build_session(files, 'range-self-0101')
    phone, pulled = pull_phone(tmp_path, monkeypatch, files)
    assert pulled == (['range-self-0101'], [])
    out = tmp_path / 'dest' / 'range-self-0101'
    assert L.validate_session(out)['takes'] == 1
    assert json.loads((out / 'session.json').read_text())['recorder'] == 'app'


def test_pull_refuses_open_session(tmp_path, monkeypatch):
    files = tmp_path / 'remote'
    build_session(files, 'range-self-0101')
    phone = RecPhone(files)
    phone.open = 'range-self-0101'
    monkeypatch.setattr(measure, 'adb', phone.adb)
    with pytest.raises(RuntimeError, match='open'):
        P.pull(phone, tmp_path / 'dest')


def test_pull_refuses_mismatched_size(tmp_path, monkeypatch):
    files = tmp_path / 'remote'
    build_session(files, 'range-self-0101')
    phone = RecPhone(files)
    phone.corrupt = 'files/range/range-self-0101/takes/range/range-bottom_hz-r1.wav'
    monkeypatch.setattr(measure, 'adb', phone.adb)
    with pytest.raises(ValueError, match='byte size mismatch'):
        P.pull(phone, tmp_path / 'dest')
    assert not (tmp_path / 'dest' / 'range-self-0101').exists()   # nothing replaced
    assert not any(op == 'rec_clear' for op, _ in phone.calls)


def test_pull_refuses_non_app_existing_folder(tmp_path, monkeypatch):
    files = tmp_path / 'remote'
    build_session(files, 'range-self-0101')
    phone = RecPhone(files)
    monkeypatch.setattr(measure, 'adb', phone.adb)
    dest = tmp_path / 'dest'
    (dest / 'range-self-0101').mkdir(parents=True)
    json.dump(dict(recorder='desktop'), (dest / 'range-self-0101' / 'session.json').open('w'))
    with pytest.raises(ValueError, match='not a recorder'):
        P.pull(phone, dest)


def test_pull_clears_only_verified_names(tmp_path, monkeypatch):
    files = tmp_path / 'remote'
    build_session(files, 'range-self-0101')
    build_session(files, 'range-self-0102')
    phone = RecPhone(files)
    phone.corrupt = 'files/range/range-self-0102/takes/range/range-bottom_hz-r1.wav'   # the second fails
    monkeypatch.setattr(measure, 'adb', phone.adb)
    with pytest.raises(ValueError, match='byte size mismatch'):
        P.pull(phone, tmp_path / 'dest', clear=True, confirm=lambda _: True)
    assert not any(op == 'rec_clear' for op, _ in phone.calls)   # nothing cleared when verification failed
    # now it succeeds and clears exactly the two verified names
    phone.corrupt = None
    P.pull(phone, tmp_path / 'dest', clear=True, confirm=lambda _: True)
    clear_call = next(kw for op, kw in phone.calls if op == 'rec_clear')
    assert set(clear_call['sessions']) == {'range-self-0101', 'range-self-0102'}


def quick(files, qid, finished=True):
    d = files / 'files' / 'quickrec' / qid
    write_wav(d / ('clip.wav' if finished else 'clip.tmp.wav'), np.zeros(1600))
    if finished:
        L.write_json(d / 'meta.json', dict(id=qid, label='hiss', source='phone'))


def test_clear_needs_a_yes(tmp_path, monkeypatch):
    files = tmp_path / 'remote'
    build_session(files, 'range-self-0101')
    phone, _ = pull_phone(tmp_path, monkeypatch, files, clear=True, confirm=lambda _: False)
    assert not any(op == 'rec_clear' for op, _ in phone.calls)
    phone, _ = pull_phone(tmp_path, monkeypatch, files, clear=True)   # no confirm callback: never clears
    assert not any(op == 'rec_clear' for op, _ in phone.calls)
    assert L.validate_session(tmp_path / 'dest' / 'range-self-0101')['takes'] == 1   # a re-pull replaces cleanly


def test_quickrec_skips_unfinished_saves_and_clears_only_finished(tmp_path, monkeypatch):
    files = tmp_path / 'remote'
    quick(files, '1700000000001')
    quick(files, '1700000000002', finished=False)   # a save in progress: only clip.tmp.wav
    phone, (names, qids) = pull_phone(tmp_path, monkeypatch, files, quickrec=True, clear=True,
                                      confirm=lambda _: True)
    assert (names, qids) == ([], ['1700000000001'])
    assert (tmp_path / 'quickrec' / '1700000000001' / 'clip.wav').exists()
    assert not (tmp_path / 'quickrec' / '1700000000002').exists()
    assert next(kw for op, kw in phone.calls if op == 'rec_clear') == dict(sessions=[], quickrec=['1700000000001'])


def test_destinations_must_be_gitignored(tmp_path, monkeypatch):
    files = tmp_path / 'remote'
    build_session(files, 'range-self-0101')
    phone = RecPhone(files)
    monkeypatch.setattr(measure, 'adb', phone.adb)
    with pytest.raises(ValueError, match='private'):
        P.pull(phone, L.HERE / 'tracked-dest', quickrec_dest=tmp_path / 'q')
    with pytest.raises(ValueError, match='quick records'):
        P.pull(phone, tmp_path / 'dest', quickrec=True, quickrec_dest=L.HERE / 'tracked-quickrec')
    assert not (L.HERE / 'tracked-dest').exists() and not (L.HERE / 'tracked-quickrec').exists()


def test_cli_pull_parses_and_calls_pull(tmp_path, monkeypatch):
    """The pull subcommand once shadowed the pull() function (TypeError on every run)."""
    seen = {}
    class V:
        def close(self): seen['closed'] = True
    monkeypatch.setattr(P.voxlib, 'Vox', V)
    monkeypatch.setattr(P, 'pull', lambda vox, dest, *a, **k: seen.update(dest=dest, args=a) or (['s'], []))
    monkeypatch.setattr(sys, 'argv', ['range_phone.py', 'pull', '--out', str(tmp_path / 'dest'), '--clear'])
    P.main()
    assert seen['dest'] == (tmp_path / 'dest').resolve() and seen['args'] == (None, False, True) and seen['closed']


def test_plan_fixture_is_current():
    import make_range_plan_fixture as M
    stored = json.loads((Path(__file__).parent / 'fixtures' / 'range_v1_plan.json').read_text())
    assert M.build() == stored
    assert len(stored['short']) == 42
    assert len(stored['full']) == 269 + 7
    assert sum(1 for t in stored['full'] if t['kind'] == 'backgrounds') == 7
