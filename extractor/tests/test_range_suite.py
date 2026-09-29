"""Range contract tests. Synthetic audio only; subprocess/device calls are forbidden except fake CLI."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
import pytest

import range_layout as L
import range_session as D

sys.path.insert(0, str(L.HERE.parent / 'android' / 'suite'))
import measure
import range_phone as P


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    monkeypatch.setattr(measure, 'adb', lambda *a, **k: pytest.fail('unmocked adb'))
    monkeypatch.setattr(P.voxlib, 'Vox', lambda: pytest.fail('unmocked Vox'))
    monkeypatch.setattr(D.R, 'make_source', lambda *a: pytest.fail('real microphone source'))


def spec():
    return L.load_spec()


def args(out, blocks=None):
    return argparse.Namespace(out=out, spec=L.SPEC_PATH, source='fake', auto=True, rate=16000,
                              session='synthetic', block=blocks, device=None)


def write_wav(path, samples, rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1 if samples.ndim == 1 else samples.shape[1], 2, rate, 0, 'NONE', 'not compressed'))
        wav.writeframes(samples.astype('<i2').tobytes())


def bi(s, block_id):
    """A block's index in [s] (tests address blocks by id, not position)."""
    return [b['id'] for b in s['blocks']].index(block_id)


def test_spec_contract_grid():
    s = spec()
    assert s['version'] == 'range_v1'
    assert s['analysis']['pre_roll_s'] == 1
    assert s['analysis']['post_roll_s'] == .5
    assert s['analysis']['f0_min_hz'] < 75
    plan = L.build_plan(s)
    counts = {b['id']: sum(t['block'] == b['id'] for t in plan) for b in s['blocks']}
    assert counts == {'range': 4, 'room': 1, 'contours': 5 * 14 * 2, 'discrete': 3 * 6 * 2,
                      'combos': 4 * 5 * 2, 'backgrounds': 7, 'real-media-60': 12 * 2, 'real-talk': 12 * 2}
    assert len(plan) == 276
    assert len({t['take_id'] for t in plan}) == len(plan)
    assert s['blocks'][0]['id'] == 'range'
    assert [c['anchor'] for c in s['blocks'][0]['cells']] == ['bottom_hz', 'home_hz', 'top_hz', 'whistle_home_hz']
    for t in plan:
        assert t['cue'] and t['rep'] in (1, 2)
        if t['kind'] == 'takes':
            assert set(t['cond']) == set(L.COND_KEYS)
            assert t['cond_id'] == L.cond_id(t['cond'])
            assert t['max_s'] >= t['target_s'] > 0
            assert t['bg'] is None or set(t['bg']) == {'name', 'kind', 'level'}
        else:
            assert t['seconds'] == 60
            assert t['bg_kind'] in ('media', 'tv', 'fan', 'talk', 'other')
    contour = s['blocks'][bi(s, 'contours')]['cells'][:14]
    center = contour[0]['cond']
    assert all(sum(c['cond'][k] != center[k] for k in L.COND_KEYS) == 1 for c in contour[1:10])
    assert [c['cond'] for c in contour[10:]] == [
        dict(center, loud='soft', dist='across', pitch='bottom'), dict(center, loud='loud', pitch='top'),
        dict(center, speed='quick', loud='soft', dist='table'), dict(center, tone='whistle', speed='quick', dist='across')]


def test_cond_id_stable_order():
    c = L.build_plan(spec(), ['contours'])[0]['cond']
    assert L.cond_id(c) == L.cond_id(dict(reversed(list(c.items()))))
    assert L.cond_id(c) == 'hum-home-normal-normal-hand-na'
    with pytest.raises(ValueError):
        L.cond_id(dict(c, surprise='x'))


def test_generated_spec_matches():
    # The generator is a tracked deterministic source, not used by either recorder.
    before = L.SPEC_PATH.read_bytes()
    exec(compile((L.SPEC_PATH.parent / 'make_range_spec.py').read_text(), 'make_range_spec.py', 'exec'),
         {'__file__': str(L.SPEC_PATH.parent / 'make_range_spec.py')})
    assert L.SPEC_PATH.read_bytes() == before


def test_desktop_fake_cli_full_layout_and_resume(tmp_path):
    out = tmp_path / 'desktop'
    cmd = [sys.executable, str(L.HERE / 'range_session.py'), '--source', 'fake', '--auto', '--out', str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'BELOW EXTRACTOR' in result.stdout
    assert L.validate_session(out, complete=True) == dict(takes=269, backgrounds=7, ratings=8, sittings=1, no_sound=0)
    before = (out / 'labels.jsonl').read_bytes()
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (out / 'labels.jsonl').read_bytes() == before
    assert L.validate_session(out, complete=True)['sittings'] == 2


def test_desktop_single_block(tmp_path):
    out = D.run_session(args(tmp_path / 'one', ['range']))
    result = L.validate_session(out)
    assert result == dict(takes=4, backgrounds=0, ratings=1, sittings=1, no_sound=0)
    meta = json.loads((out / 'session.json').read_text())
    assert meta['range']['bottom_hz'] == pytest.approx(55, abs=.2)
    assert meta['range']['whistle_home_hz'] == pytest.approx(1000, abs=1)
    assert meta['range']['below_f0_min'] is True
    assert meta['sittings'][0]['ended'] >= meta['sittings'][0]['started']
    with pytest.raises(ValueError, match='incomplete'):
        L.validate_session(out, complete=True)


@pytest.mark.parametrize('hz', [40, 55, 70, 100, 240, 1000, 2400])
def test_median_pitch_low_bottom_and_whistle(hz):
    rate = 48000
    x = .15 * np.sin(2 * np.pi * hz * np.arange(rate * 2) / rate)
    assert D.median_pitch(x, rate, spec()) == pytest.approx(hz, rel=.005)


def test_silence_has_no_pitch():
    assert D.median_pitch(np.zeros(32000), 16000, spec()) is None


class BufferedRecorder:
    def __init__(self, audio, rate=16000):
        self.data, self.rate, self.n = audio, rate, 0

    def wait_s(self, seconds):
        return self.wait_until(self.n + round(seconds * self.rate))

    def wait_until(self, sample):
        self.n = min(sample, len(self.data))
        return self.n >= sample

    def audio(self, a, b):
        return self.data[max(0, a):min(b, self.n)]


def test_live_silence_detector_pre_post_and_slow_combo_gap():
    s = spec()
    t = L.build_plan(s, ['combos'])[4]  # slow gap
    rate = 16000
    x = np.zeros(rate * 10, dtype=np.float32)
    x[int(1.4 * rate):int(1.5 * rate)] = .1
    x[int(2.3 * rate):int(2.4 * rate)] = .1
    rec = BufferedRecorder(x)
    clip, start, go = D.capture_live(rec, t, s)
    assert go - start == rate
    assert len(clip) == int(2.4 * rate) + int(.5 * rate) - start
    assert rec.n < rate * 5


def test_live_background_exact_length():
    s = spec()
    t = L.build_plan(s, ['backgrounds'])[0]
    rec = BufferedRecorder(np.ones(63 * 16000, dtype=np.float32) * .01)
    clip, start, go = D.capture_live(rec, t, s)
    assert start == go and len(clip) == 60 * 16000


def test_live_capture_end_rejects_take():
    with pytest.raises(RuntimeError, match='before GO'):
        D.capture_live(BufferedRecorder(np.zeros(10)), L.build_plan(spec(), ['range'])[0], spec())


def test_controls_redo_skip_quit_resume():
    items = L.build_plan(spec(), ['range'])
    actions = iter(['\n', 'r', 's', '\n', 'q'])
    captured = []
    complete, redos = L.operate(items, set(), lambda t: captured.append(t['take_id']), key=lambda _: next(actions))
    assert not complete and redos == 1
    assert captured == [items[0]['take_id'], items[0]['take_id'], items[2]['take_id']]
    pending = []
    L.operate(items, set(captured), lambda t: pending.append(t['take_id']), auto=True)
    assert pending == [items[1]['take_id'], items[3]['take_id']]


def test_desktop_redo_last_line_wins(tmp_path, monkeypatch):
    keys = iter(['\n', 'r', '\n', '\n', '\n', '\n'])
    monkeypatch.setattr(D.G, 'getkey', lambda _: next(keys))
    out = D.run_session(args(tmp_path / 'redo', ['range']))
    raw = L.read_rows(out / 'labels.jsonl')
    assert len(raw) == 5 and raw[1]['redo'] == 1
    assert L.validate_session(out)['takes'] == 4
    assert L.read_rows(out / 'ratings.jsonl')[0]['redos'] == 1


@pytest.mark.parametrize('bad', ['../outside', '/absolute', 'two words', '', 'a/b'])
def test_unsafe_names(bad):
    with pytest.raises(ValueError):
        L.safe_name(bad)


def test_private_output_guard():
    with pytest.raises(ValueError):
        L.private_dir(L.HERE / 'tests' / 'audio')
    assert L.private_dir(L.HERE / 'recordings' / 'test') == L.HERE / 'recordings' / 'test'


def test_mixed_source_rejected(tmp_path):
    out = tmp_path / 'mixed'
    L.open_session(out, spec(), 'desktop', 'fake', 16000, 1, True)
    with pytest.raises(ValueError, match='differs'):
        L.open_session(out, spec(), 'desktop', 'fake', 16000, 1, False)


def test_changed_spec_rejected(tmp_path):
    out = tmp_path / 'changed'
    s = spec()
    L.open_session(out, s, 'desktop', 'fake', 16000, 1, True)
    s['analysis']['open_db'] += 1
    with pytest.raises(ValueError, match='spec differs'):
        L.open_session(out, s, 'desktop', 'fake', 16000, 1, True)


def test_disk_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(L.shutil, 'disk_usage', lambda _: argparse.Namespace(free=30 * 1024**3))
    with pytest.raises(RuntimeError):
        L.disk_guard(tmp_path, 1)


@pytest.mark.parametrize('channels', [1, 2])
def test_phone_exact_sample_cut_with_offset(tmp_path, channels):
    source, target = tmp_path / 'continuous.wav', tmp_path / 'take.wav'
    x = (np.arange(16000 * 5 * channels) % 30000).reshape(-1, channels)
    write_wav(source, x)
    frames, ch, rate = P.cut_wav(source, target, 2500, 4000, 2000)
    assert (frames, ch, rate) == (24000, channels, 16000)
    with wave.open(str(target)) as w:
        assert w.readframes(frames) == x[8000:32000].astype('<i2').tobytes()


@pytest.mark.parametrize('bounds', [(1000, 3000), (2000, 8000), (3000, 2500)])
def test_phone_rejects_missing_window(tmp_path, bounds):
    source = tmp_path / 'source.wav'
    write_wav(source, np.zeros(16000 * 5))
    with pytest.raises(ValueError, match='outside'):
        P.cut_wav(source, tmp_path / 'take.wav', *bounds, 2000)


class Phone:
    """Both Vox and adb mocked; measure.pull itself still verifies actual bytes/events."""
    def __init__(self):
        self.running = False
        self.clock = 10000
        self.sid = 0
        self.n = 0
        self.calls = []
        self.events = []
        self.files = {}
        self.corrupt = False

    def wait(self, seconds):
        self.clock += round(seconds * 1000)

    def control(self, op, **kw):
        self.calls.append((op, kw))
        if op == 'measure_status':
            return dict(ok=True, running=self.running)
        if op == 'measure_start':
            self.sid += 1
            self.n = 0
            self.running = True
            self.t0 = self.clock
            self.events.append(dict(ev='measure_start', sid=self.sid, wav_t0_ms=self.t0, rate=16000, channels=1))
            return dict(ok=True, sid=self.sid)
        if op == 'measure_cue':
            self.n += 1
            self.events.append(dict(ev='measure_prompt', sid=self.sid, n=self.n, t_ms=self.clock,
                                    gesture=kw['id'], text=kw['text']))
            return dict(ok=True, n=self.n, t_ms=self.clock)
        if op == 'measure_stop':
            self.running = False
            count = round((self.clock - self.t0) * 16)
            x = (np.arange(count) % 30000).astype('<i2')
            out = io.BytesIO()
            with wave.open(out, 'wb') as w:
                w.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                w.writeframes(x.tobytes())
            self.files[str(self.sid)] = out.getvalue()
            self.events.append(dict(ev='measure_stop', sid=self.sid, samples=count))
            return dict(ok=True)
        raise AssertionError(op)

    def adb(self, *args, **kw):
        command = ' '.join(args)
        if 'events.1.jsonl' in command:
            return b''
        if 'events.jsonl' in command:
            return ('\n'.join(json.dumps(e) for e in self.events) + '\n').encode()
        if 'ls files/measure' in command:
            return ' '.join(self.files).encode()
        sid = args[-1].split('/')[-2]
        if 'stat' in args:
            return str(len(self.files[sid])).encode()
        if 'cat' in args:
            return self.files[sid][:-2] if self.corrupt else self.files[sid]
        raise AssertionError(args)


def phone_session(tmp_path, monkeypatch):
    out = tmp_path / 'phone'
    L.open_session(out, spec(), 'phone', 'synthetic fixture', 16000, 1)
    phone = Phone()
    monkeypatch.setattr(measure, 'adb', phone.adb)
    # Any accidental git check inside the pull helper must fail the test.
    monkeypatch.setattr(measure.subprocess, 'run', lambda *a, **k: pytest.fail('git/subprocess forbidden'))
    return out, phone


def test_phone_mock_record_pull_and_labels(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    s = spec()
    block = s['blocks'][bi(s, 'combos')].copy()
    # Keep two reps of the first combo, preserving the shared grid identities.
    s['blocks'][bi(s, 'combos')] = block | dict(cells=block['cells'][:1])
    P.run_block(phone, out, s, s['blocks'][bi(s, 'combos')], wait=phone.wait, auto=True)
    assert L.validate_session(out)['takes'] == 2
    rows = L.read_rows(out / 'labels.jsonl')
    assert rows[0]['expect'] == ['click', 'click']
    assert rows[0]['t_go_ms'] == 11000
    assert rows[0]['clip_start_ms'] == 10000
    assert rows[0]['go_offset_ms'] == 1000
    assert rows[0]['dur_ms'] == pytest.approx((1 + .95 + 2 + .5) * 1000)
    with wave.open(str(out / rows[0]['file'])) as w:
        got = w.readframes(w.getnframes())
    assert got == (np.arange(len(got) // 2) % 30000).astype('<i2').tobytes()
    start = next(kw for op, kw in phone.calls if op == 'measure_start')
    assert start == dict(phase='range-combos', prompt=False, record=True, max_s=1200)
    assert [kw['text'] for op, kw in phone.calls if op == 'measure_cue'] == [s['blocks'][bi(s, 'combos')]['cells'][0]['cue']] * 2
    before = (out / 'labels.jsonl').read_bytes()
    P.recover(phone, out, s)
    assert (out / 'labels.jsonl').read_bytes() == before


def test_phone_background_real_bg_and_resume(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    s = spec()
    for index in (bi(s, 'backgrounds'), bi(s, 'real-media-60')):
        s['blocks'][index]['cells'] = s['blocks'][index]['cells'][:1]
        P.run_block(phone, out, s, s['blocks'][index], wait=phone.wait, auto=True)
    assert L.validate_session(out)['backgrounds'] == 1
    rows = L.read_rows(out / 'labels.jsonl')
    assert all(r['bg'] == dict(name='media-60', kind='media', level=60) for r in rows)
    calls = len(phone.calls)
    P.run_block(phone, out, s, s['blocks'][bi(s, 'real-media-60')], wait=phone.wait, auto=True)
    assert len(phone.calls) == calls


def test_phone_transfer_failure_then_recover(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    s = spec()
    s['blocks'][0]['cells'] = s['blocks'][0]['cells'][:1]
    phone.corrupt = True
    with pytest.raises(ValueError, match='byte size mismatch'):
        P.run_block(phone, out, s, s['blocks'][0], wait=phone.wait, auto=True)
    assert not phone.running
    assert not L.read_rows(out / 'labels.jsonl')
    phone.corrupt = False
    P.recover(phone, out, s)
    assert len(L.read_rows(out / 'labels.jsonl')) == 1
    assert list((out / 'imports').glob('*/partial-*'))


def test_phone_cue_mismatch_rejected(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    s = spec()
    s['blocks'][0]['cells'] = s['blocks'][0]['cells'][:1]
    original = phone.control
    def control(op, **kw):
        result = original(op, **kw)
        if op == 'measure_cue':
            result['t_ms'] += 100
        return result
    phone.control = control
    with pytest.raises(ValueError, match='does not match'):
        P.run_block(phone, out, s, s['blocks'][0], wait=phone.wait, auto=True)
    assert not L.read_rows(out / 'labels.jsonl')


def test_phone_quit_stops_and_imports(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    actions = iter(['\n', '\n', 'q'])
    assert not P.run_block(phone, out, spec(), spec()['blocks'][0], key=lambda _: next(actions), wait=phone.wait)
    assert not phone.running
    assert len(L.read_rows(out / 'labels.jsonl')) == 1


def test_phone_stdlib_import_and_defaults():
    code = (f'import sys; sys.path.insert(0, {str(P.Path(P.__file__).parent)!r}); '
            'import range_phone as p; assert "numpy" not in sys.modules; '
            'assert p.os.environ["VOX_SERIAL"] == "emulator-5580"; '
            'assert p.os.environ["ANDROID_ADB_SERVER_PORT"] == "5038"; '
            'assert p.os.environ["VOX_SOCKET_PORT"] == "7789"')
    env = {k: v for k, v in os.environ.items() if k not in ('VOX_SERIAL', 'ANDROID_ADB_SERVER_PORT', 'VOX_SOCKET_PORT')}
    r = subprocess.run([sys.executable, '-S', '-c', code], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize('field,value', [('cond_id', 'bad'), ('rep', 7), ('bg', {}), ('redo', -1), ('dur_ms', 1)])
def test_layout_rejects_bad_label(tmp_path, field, value):
    out = D.run_session(args(tmp_path / 'invalid', ['range']))
    row = L.read_rows(out / 'labels.jsonl')[0]
    row[field] = value
    L.append_row(out / 'labels.jsonl', row)
    with pytest.raises(ValueError):
        L.validate_session(out)


def test_ratings_validation_and_retry(tmp_path):
    answers = iter(['x', '0', '6', '3', 'tiring'])
    L.rating(tmp_path, 'range', 12, 2, spec(), ask=lambda _: next(answers))
    assert L.read_rows(tmp_path / 'ratings.jsonl') == [dict(block='range', rating=3, note='tiring', seconds=12, redos=2)]


def test_phone_interrupt_during_take_leaves_it_pending(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    calls = 0
    def wait(seconds):
        nonlocal calls
        calls += 1
        if calls == 2:
            phone.wait(.1)
            raise KeyboardInterrupt
        phone.wait(seconds)
    with pytest.raises(KeyboardInterrupt):
        P.run_block(phone, out, spec(), spec()['blocks'][0], wait=wait, auto=True)
    assert not phone.running
    assert not L.read_rows(out / 'labels.jsonl')
    pending = json.loads(next((out / 'imports').glob('*/pending.json')).read_text())
    assert pending['imported'] and pending['entries'][0]['incomplete']
    P.recover(phone, out, spec())
    assert not L.read_rows(out / 'labels.jsonl')


def test_phone_redo_last_line_wins(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    s = spec()
    s['blocks'][0]['cells'] = s['blocks'][0]['cells'][:1]
    actions = iter(['\n', '\n', 'r', '\n'])
    P.run_block(phone, out, s, s['blocks'][0], key=lambda _: next(actions), wait=phone.wait, auto=True)
    rows = L.read_rows(out / 'labels.jsonl')
    assert [r['redo'] for r in rows] == [0, 1]
    assert L.validate_session(out)['takes'] == 1
    with wave.open(str(out / rows[-1]['file'])) as w:
        first = np.frombuffer(w.readframes(1), dtype='<i2')[0]
    assert first == round((rows[-1]['clip_start_ms'] - 10000) * 16) % 30000


def test_phone_finalize_real_synthetic_anchors(tmp_path):
    out = tmp_path / 'phone-finalize'
    s = spec()
    L.open_session(out, s, 'phone', 'synthetic fixture', 48000, 1)
    for t in L.build_plan(s, ['range']):
        audio = D.synthetic_audio(t, 48000, s)
        r = L.label_row(t, 0, 9000, 10000, len(audio), 48000)
        write_wav(out / r['file'], audio * 32767, 48000)
        L.append_row(out / 'labels.jsonl', r)
    result = subprocess.run([sys.executable, str(Path(P.__file__)), 'finalize', str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    meta = json.loads((out / 'session.json').read_text())
    assert meta['range']['bottom_hz'] == pytest.approx(55, abs=.1)
    assert meta['range']['below_f0_min']
    assert not meta['range_pending']


def test_desktop_resume_collects_missing_rating(tmp_path, monkeypatch):
    out = tmp_path / 'rating-resume'
    a = args(out, ['range'])
    D.run_session(a)
    (out / 'ratings.jsonl').write_text('')
    before = (out / 'labels.jsonl').read_bytes()
    D.run_session(a)
    assert (out / 'labels.jsonl').read_bytes() == before
    assert len(L.read_rows(out / 'ratings.jsonl')) == 1


def test_single_keys_no_terminal(monkeypatch):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('r\ns\nq\n\n'))
    assert [L.getkey() for _ in range(5)] == ['r', 's', 'q', '\n', 'q']
    assert D.G.getkey is L.getkey


def test_phone_adopts_actual_native_format(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    # A first block adopts native rate; established sessions refuse a later format change.
    original = phone.control
    def control(op, **kw):
        result = original(op, **kw)
        if op == 'measure_start':
            result.update(rate=48000, channels=1)
        return result
    phone.control = control
    s = spec()
    actions = iter(['\n', 'q'])
    # No take in this block, so the fixture's 16 kHz WAV cannot be silently accepted.
    with pytest.raises(ValueError, match='format changed'):
        P.run_block(phone, out, s, s['blocks'][0], key=lambda _: next(actions), wait=phone.wait)
    assert json.loads((out / 'session.json').read_text())['rate'] == 48000


def test_auto_real_source_rejected_before_mic(tmp_path):
    a = args(tmp_path / 'no-real')
    a.source = 'auto'
    with pytest.raises(ValueError, match='requires --source fake'):
        D.run_session(a)


def test_invalid_block_rejected_before_mic(tmp_path):
    with pytest.raises(ValueError, match='unknown block'):
        D.run_session(args(tmp_path / 'bad-block', ['unknown']))


@pytest.mark.parametrize('change', ['duplicate-block', 'duplicate-cell', 'bad-bg-path', 'bad-bg-kind',
                                   'bad-cond-id', 'bad-cond-value', 'bad-reps', 'missing-cue'])
def test_bad_specs_are_rejected(tmp_path, change):
    s = spec()
    cell = s['blocks'][0]['cells'][0]
    if change == 'duplicate-block':
        s['blocks'].append(s['blocks'][0])
    elif change == 'duplicate-cell':
        s['blocks'][0]['cells'].append(cell)
    elif change == 'bad-bg-path':
        s['blocks'][bi(s, 'backgrounds')]['cells'][0]['name'] = '../escape'
    elif change == 'bad-bg-kind':
        s['blocks'][bi(s, 'backgrounds')]['cells'][0]['kind'] = 'unknown'
    elif change == 'bad-cond-id':
        cell['cond_id'] = 'not-canonical'
    elif change == 'bad-cond-value':
        cell['cond']['pitch'] = 'unknown'
        cell['cond_id'] = L.cond_id(cell['cond'])
    elif change == 'bad-reps':
        cell['reps'] = True
    else:
        cell['cue'] = ''
    path = tmp_path / 'invalid-spec.json'
    L.write_json(path, s)
    with pytest.raises(ValueError):
        L.load_spec(path)


# --- profiles and speakers (a short session for a second speaker) -------------------------------------------------

def test_short_profile_counts_and_comparable_ids():
    s = spec()
    short = L.build_plan(s, profile='short')
    counts = {}
    for t in short:
        counts[t['block']] = counts.get(t['block'], 0) + 1
    assert counts == {'range': 4, 'room': 1, 'contours': 5 * 4 * 1, 'discrete': 3 * 3 * 1, 'combos': 4 * 1 * 2}
    full = {t['take_id']: t for t in L.build_plan(s)}
    assert len(full) == 276 and L.build_plan(s, profile='full') == L.build_plan(s)
    # every short take is the full grid's take: same take_id, cell, cond_id
    for t in short:
        assert {k: full[t['take_id']][k] for k in ('cell_id', 'cond', 'cond_id', 'expect', 'rep')} == \
            {k: t[k] for k in ('cell_id', 'cond', 'cond_id', 'expect', 'rep')}
    conds = {t['cond_id'] for t in short if t['block'] == 'contours'}
    assert conds == {'hum-home-normal-normal-hand-na', 'hum-bottom-normal-normal-hand-na',
                     'hum-home-normal-soft-hand-na', 'hum-home-normal-normal-across-na'}
    assert {t['cond_id'] for t in short if t['block'] == 'discrete'} == {
        'na-na-na-normal-hand-na', 'na-na-na-soft-hand-na', 'na-na-na-normal-across-na'}
    assert {t['cond_id'] for t in short if t['block'] == 'combos'} == {'na-na-na-normal-hand-normal'}


def test_profile_selection_is_checked():
    s = spec()
    with pytest.raises(ValueError, match='not in profile'):
        L.build_plan(s, ['backgrounds'], 'short')
    with pytest.raises(ValueError, match='unknown profile'):
        L.build_plan(s, profile='tiny')
    bad = json.loads(json.dumps(s))
    bad['profiles']['short']['blocks'][1]['cells'].append('nope')
    with pytest.raises(ValueError, match='unknown block or cell'):
        _load(bad)


def _load(obj, tmp=L.HERE.parent / 'android' / '.state'):
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f'spec-{os.getpid()}.json'
    path.write_text(json.dumps(obj))
    try:
        return L.load_spec(path)
    finally:
        path.unlink()


def test_desktop_short_profile_second_speaker(tmp_path):
    a = args(tmp_path / 'sis')
    a.profile, a.speaker = 'short', 'sis'
    out = D.run_session(a)
    assert L.validate_session(out, complete=True) == dict(takes=42, backgrounds=0, ratings=5, sittings=1, no_sound=0)
    meta = json.loads((out / 'session.json').read_text())
    assert (meta['profile'], meta['speaker']) == ('short', 'sis')
    assert {r['block'] for r in L.read_rows(out / 'ratings.jsonl')} == {'range', 'room', 'contours', 'discrete', 'combos'}
    a.profile = 'full'
    with pytest.raises(ValueError, match='profile/speaker differs'):
        D.run_session(a)
    assert L.default_session_name('sis').startswith('range-sis-')
    with pytest.raises(ValueError):
        L.default_session_name('../x')


def test_old_sessions_without_profile_read_as_full_self(tmp_path):
    out = D.run_session(args(tmp_path / 'old', ['range']))
    meta = json.loads((out / 'session.json').read_text())
    del meta['profile'], meta['speaker']
    L.write_json(out / 'session.json', meta)
    assert L.validate_session(out)['takes'] == 4
    assert (L.session_profile(meta), L.session_speaker(meta)) == ('full', 'self')


def test_cues_fit_the_phone_prompt_overlay():
    kt = (L.HERE.parent / 'android/app/src/main/java/ai/vox/companion/audio/Measure.kt').read_text()
    limit = int(kt.split('const val MAX_CUE_CHARS = ')[1].split()[0])
    cues = [c['cue'] for b in spec()['blocks'] for c in b['cells']]
    assert max(map(len, cues)) <= limit
    assert 'RISE · centre · about 0.6 s' in cues


def test_phone_short_profile_block_and_cue_retry(tmp_path, monkeypatch):
    out = tmp_path / 'phone-short'
    L.open_session(out, spec(), 'phone', 'synthetic fixture', 16000, 1, profile='short', speaker='sis')
    phone = Phone()
    monkeypatch.setattr(measure, 'adb', phone.adb)
    monkeypatch.setattr(measure.subprocess, 'run', lambda *a, **k: pytest.fail('git/subprocess forbidden'))
    original, refusals = phone.control, iter([True, True])

    def control(op, **kw):
        # the app refuses a cue before the measurement's first sample: the driver retries
        if op == 'measure_cue' and next(refusals, False):
            phone.calls.append((op, kw))
            return dict(ok=False, error='the measurement has no sample yet (retry)')
        return original(op, **kw)
    phone.control = control
    s = spec()
    assert P.run_block(phone, out, s, s['blocks'][bi(s, 'combos')], wait=phone.wait, auto=True)
    assert L.validate_session(out)['takes'] == 8
    assert sum(op == 'measure_cue' for op, _ in phone.calls) == 8 + 2


def test_phone_cue_failure_is_not_retried_forever(tmp_path, monkeypatch):
    class Refuses:
        def control(self, op, **kw):
            return dict(ok=False, error='no measurement running')
    with pytest.raises(RuntimeError, match='no measurement running'):
        P.cue_now(Refuses(), dict(cue='x', take_id='t'), lambda s: None)


# --- the room step (the app's calibration room step: 3 s of quiet) -------------------------------------------------

def test_room_step_in_both_profiles_right_after_range():
    s = spec()
    assert [b['id'] for b in s['blocks']][:3] == ['range', 'room', 'contours']
    for profile in ('full', 'short'):
        plan = L.build_plan(s, profile=profile)
        room = [t for t in plan if t['block'] == 'room']
        assert [t['take_id'] for t in room] == ['room-room-r1']
        assert plan[plan.index(room[0]) - 1]['block'] == 'range'
    t = room[0]
    assert (t['expect'], t['cond_id'], t['cue'], L.is_quiet(t)) == ([], 'na-na-na-na-na-na', 'Stay quiet for 3 seconds', True)
    joy = json.loads((L.HERE / 'prompts' / 'joystick_v1.json').read_text())['calib_v2']['room']
    # the fixed window covers the app's room window + settle
    assert t['max_s'] * 1000 >= joy['window_ms'] + joy['settle_ms']


def test_quiet_cells_expect_nothing_and_gestures_expect_something():
    s = spec()
    s['blocks'][bi(s, 'room')]['cells'][0]['expect'] = ['click']
    with pytest.raises(ValueError, match='invalid take'):
        _load(s)
    s = spec()
    s['blocks'][bi(s, 'discrete')]['cells'][0]['expect'] = []
    with pytest.raises(ValueError, match='invalid take'):
        _load(s)


def test_desktop_room_take_is_a_fixed_window(tmp_path):
    a = args(tmp_path / 'room', ['room'])
    out = D.run_session(a)
    (row,) = L.read_rows(out / 'labels.jsonl')
    t = L.build_plan(spec(), ['room'])[0]
    an = spec()['analysis']
    # never cut short by the silence detector: pre-roll + max_s + post-roll
    assert row['dur_ms'] >= (an['pre_roll_s'] + t['max_s'] + an['post_roll_s']) * 1000 - 60
    assert row['expect'] == [] and row['cond_id'] == 'na-na-na-na-na-na'


def test_phone_room_take_is_a_fixed_window(tmp_path, monkeypatch):
    out, phone = phone_session(tmp_path, monkeypatch)
    s = spec()
    assert P.run_block(phone, out, s, s['blocks'][bi(s, 'room')], wait=phone.wait, auto=True)
    (row,) = L.read_rows(out / 'labels.jsonl')
    t = L.build_plan(s, ['room'])[0]
    an = s['analysis']
    assert row['dur_ms'] == pytest.approx((an['pre_roll_s'] + t['max_s'] + an['post_roll_s']) * 1000, abs=1)
    assert [kw['text'] for op, kw in phone.calls if op == 'measure_cue'] == ['Stay quiet for 3 seconds']
