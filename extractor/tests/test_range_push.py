"""The recorder push (range_phone.push, contract L) against a fake adb that models the device's files/range_pc/ tree.
Synthetic audio only; no device or git calls."""
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


@pytest.fixture
def tmp_path():
    """Pushes validate under the private roots only, so every test works in a private android/.state folder."""
    root = L.HERE.parent / 'android' / '.state'
    root.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix='range-push-', dir=root))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def spec():
    return L.load_spec()


def write_wav(path, samples, rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        w.writeframes(np.asarray(samples).astype('<i2').tobytes())


def build_session(root, name, speaker='self'):
    """One PC recorder session the way range_session writes it, plus a run-*/ trash/ and report.md that a push must skip."""
    sp = spec()
    sess = root / name
    sess.mkdir(parents=True)
    L.write_json(sess / 'spec.json', sp)
    meta = dict(device='desktop', mic='pc mic', rate=16000, channels=1, spec=sp['version'],
                synthetic=False, profile='short', speaker=speaker,
                range=dict(bottom_hz=100.0, home_hz=150.0, top_hz=220.0, whistle_home_hz=1200.0, below_f0_min=False),
                sittings=[dict(started=1.0, ended=None)],
                private='Never commit, upload, or send recordings to a model.',
                recorder='desktop')
    L.write_json(sess / 'session.json', meta)
    for j in ('labels.jsonl', 'backgrounds.jsonl', 'ratings.jsonl'):
        (sess / j).write_text('')
    take = next(t for t in L.build_plan(sp, profile='short') if t['kind'] == 'takes')
    clip = np.arange(16000 * 2, dtype='<i2')
    write_wav(sess / 'takes' / take['block'] / f"{take['take_id']}.wav", clip)
    L.append_row(sess / 'labels.jsonl', L.label_row(take, 0, 0, 1000, len(clip), 16000))
    # files a push must never copy
    L.write_json(sess / 'report.json', dict(done=True))
    (sess / 'run-1').mkdir(); (sess / 'run-1' / 'extra.wav').write_bytes(b'x')
    (sess / 'trash').mkdir(); (sess / 'trash' / 'd1').mkdir()
    (sess / 'trash' / 'd1' / 'gone.wav').write_bytes(b'x')
    (sess / 'report.md').write_text('markdown')
    return sess


class PushPhone:
    """Fake adb: models files/range_pc/ (path -> bytes) and the ls/stat/rm/mv/cat commands the push sends."""
    def __init__(self):
        self.files = {}

    def adb(self, *args, **kw):
        a = [str(x) for x in args]
        if a[0] == 'exec-in':
            cmd = a[-1]
            assert cmd.startswith('cat > '), cmd
            self.files[cmd[len('cat > '):]] = kw['input']
            return b''
        assert a[0] == 'exec-out', args
        if 'stat' in a:
            return str(len(self.files.get(a[-1], b''))).encode()
        cmd = a[-1].split(' 2>/dev/null')[0]
        if cmd.startswith('ls '):
            folder = cmd[3:].strip()
            prefix = folder.rstrip('/') + '/'
            names = sorted({p[len(prefix):].split('/')[0] for p in self.files if p.startswith(prefix)})
            return ('\n'.join(names) + '\n').encode()
        for stmt in cmd.split(';'):
            stmt = stmt.strip()
            if not stmt:
                continue
            if stmt.startswith('rm -rf '):
                prefix = stmt[len('rm -rf '):].strip().rstrip('/') + '/'
                self.files = {p: v for p, v in self.files.items() if not p.startswith(prefix)}
            elif stmt.startswith('mv '):
                src, dst = stmt[len('mv '):].strip().split()
                sp, dp = src.rstrip('/') + '/', dst.rstrip('/') + '/'
                for p in [p for p in self.files if p.startswith(sp)]:
                    self.files[dp + p[len(sp):]] = self.files.pop(p)
        return b''


def push_phone(tmp_path, monkeypatch, files, *sessions, **kw):
    phone = PushPhone()
    monkeypatch.setattr(measure, 'adb', phone.adb)
    monkeypatch.setattr(measure.subprocess, 'run', lambda *a, **k: pytest.fail('git/subprocess forbidden'))
    return phone, P.push([str(tmp_path / s) for s in sessions], **kw)


def test_push_copies_only_the_layout(tmp_path, monkeypatch):
    build_session(tmp_path, 'range-self-0101')
    phone, pushed = push_phone(tmp_path, monkeypatch, tmp_path, 'range-self-0101')
    assert pushed == ['range-self-0101']
    target = 'files/range_pc/range-self-0101/'
    rels = sorted({p[len(target):] for p in phone.files if p.startswith(target)})
    assert 'session.json' in rels and 'spec.json' in rels and 'labels.jsonl' in rels
    assert any(r.endswith('.wav') and 'takes/' in r for r in rels)
    assert not any('trash/' in r or 'run-1' in r or 'report.md' in r for r in rels)
    assert not any(p.startswith('files/range_pc/.staging-') for p in phone.files)   # staging swapped away


def test_push_refuses_another_speaker(tmp_path, monkeypatch):
    build_session(tmp_path, 'range-bob-0101', speaker='bob')
    phone = PushPhone()
    monkeypatch.setattr(measure, 'adb', phone.adb)
    with pytest.raises(SystemExit) as e:
        P.push([str(tmp_path / 'range-bob-0101')])
    assert e.value.code == 2
    assert not phone.files


def test_push_refuses_a_tracked_root(tmp_path, monkeypatch):
    phone = PushPhone()
    monkeypatch.setattr(measure, 'adb', phone.adb)
    with pytest.raises(ValueError, match='private'):
        P.push([str(L.HERE / 'tracked')])


def test_push_replace_and_size_check(tmp_path, monkeypatch):
    build_session(tmp_path, 'range-self-0101')
    phone, _ = push_phone(tmp_path, monkeypatch, tmp_path, 'range-self-0101')
    # already on the phone: refused without --replace, replaced with it
    with pytest.raises(ValueError, match='--replace'):
        P.push([str(tmp_path / 'range-self-0101')])
    P.push([str(tmp_path / 'range-self-0101')], replace=True)
    assert 'files/range_pc/range-self-0101/session.json' in phone.files


def test_push_list_and_remove(tmp_path, monkeypatch):
    build_session(tmp_path, 'range-self-0101')
    build_session(tmp_path, 'range-self-0102')
    push_phone(tmp_path, monkeypatch, tmp_path, 'range-self-0101', 'range-self-0102')
    phone = PushPhone()  # a fresh fake shares nothing; rebuild by pushing again
    monkeypatch.setattr(measure, 'adb', phone.adb)
    monkeypatch.setattr(P, 'ask', lambda _: False)
    P.push([str(tmp_path / 'range-self-0101'), str(tmp_path / 'range-self-0102')])
    assert P._pushed_names() == ['range-self-0101', 'range-self-0102']
    assert P.remove_pushed('range-self-0101', yes=True) is True
    assert P._pushed_names() == ['range-self-0102']
    assert not P.remove_pushed('range-self-0102', yes=False)   # no typed yes
    assert P._pushed_names() == ['range-self-0102']


def test_cli_push_parses(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(P, 'push', lambda sessions, replace=False: seen.update(sessions=sessions, replace=replace) or ['s'])
    monkeypatch.setattr(P, '_pushed_names', lambda: [])
    monkeypatch.setattr(sys, 'argv', ['range_phone.py', 'push', str(tmp_path / 's')])
    P.main()
    assert seen['sessions'] == [tmp_path / 's']
