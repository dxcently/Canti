"""Desktop go/no-go: does a reference-based echo canceller stop media from triggering gestures?

The phone idea: capture the phone's own playback (AudioPlaybackCapture) and give it to an echo canceller
(WebRTC AEC3 or similar) as the reference, before the extractor. This script tests that idea on the
desktop, where the playback is known exactly:

  1. make    public-dataset media clips, 60 s each: MUSAN music with vocals; MUSAN speech (two readers, a
             podcast); a busy short-video mix (speech + music bed + ESC-50 effects + MLEnd whistles/hums);
             "gesturelike", the worst case: other people's clicks / pops (Deeply Nonverbal), hums / whistles
             (MLEnd) and sung fragments (VocalSet) over a quiet music bed.
  2. record  plays each clip through the default sink and records, at the same time, the USB mic
             (CMEDIA Q9) and the sink's monitor (pw-record, 48 kHz). Also 60 s of the room with nothing
             playing. --live-ec also plays the clips through PipeWire's module-echo-cancel (webrtc).
  3. eval    aligns mic / monitor / file (cross-correlation), runs the cancellers offline
             (WebRTC APM AEC3 and AECM via a C++ harness, SpeexDSP, an FDAF-NLMS baseline) with several
             tail / suppression settings, runs the extractor on raw vs cleaned audio (events, would-act as
             the app counts it: vox_extract.sequencer_sim, pop-pop, per minute), measures ERLE, and runs the survival check: the user's
             own quiet gesture takes (recordings/khoa-guided-1, clicks + whistles) mixed on top of the mic
             recording and scored for detection and label match against the same takes on the quiet room.

Privacy: every recording stays under recordings/aec-desktop-*/ (gitignored). Results written to the repo
are aggregate numbers only (no per-take rows).

Reproduce (all from /home/khoa/VOX/extractor):
    ./run python eval_real/aec_desktop.py build                       # compile the harnesses (nix, no sudo)
    ./run python eval_real/aec_desktop.py make   --session recordings/aec-desktop-1
    ./run python eval_real/aec_desktop.py record --session recordings/aec-desktop-1 [--live-ec]   # plays sound!
    ./run python eval_real/aec_desktop.py eval   --session recordings/aec-desktop-1
No audible speaker? (2026-09-27: this desktop had none.) A SIMULATED echo path over real recorded room noise:
    ./run python eval_real/aec_desktop.py sim  --session recordings/aec-desktop-sim-desk  --model desk    # or phone
    ./run python eval_real/aec_desktop.py eval --session recordings/aec-desktop-sim-desk
The eval writes <session>/results.json and <session>/results.md (aggregate tables); the wiki table
(wiki/phone-mic-echo.md) is copied from results.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, ROOT, pmap  # noqa: E402

from vox_extract import Config  # noqa: E402
from vox_extract.extractor import extract_array  # noqa: E402
from vox_extract.policy import action_for, group, not_deliberate  # noqa: E402
from vox_extract.sequencer_sim import app_actions, would_act  # noqa: E402

SR = 48000
HERE = Path(__file__).resolve().parent
AEC_DIR = HERE / "aec"
BUILD = AEC_DIR / "build"
MIC = "alsa_input.usb-CMEDIA_Q9-1-00.mono-fallback"
CLIPS = ["music_vocals", "podcast", "shortvideo", "gesturelike"]
MEDIA_RMS_DBFS = -20.0          # clip loudness in the file (active frames); playback gain is set by the level check
TARGET_ECHO_DBFS = -30.0        # wanted echo level at the mic (active RMS); the user's gestures peak near -12 dBFS
MAX_FILE_GAIN_DB = 6.0          # never push the files louder than -14 dBFS RMS, whatever the level check says
LABELS = {"rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss"}
TAKES_SESSION = ROOT / "recordings" / "khoa-guided-1"


# ============================================================================== build

def _nix_out(attr: str) -> str:
    r = subprocess.run(["nix", "build", "--no-link", "--print-out-paths", f"nixpkgs#{attr}"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip().splitlines()[-1]


def cmd_build(_a) -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    w, wdev, src = _nix_out("webrtc-audio-processing"), _nix_out("webrtc-audio-processing.dev"), _nix_out("webrtc-audio-processing.src")
    ab, abdev = _nix_out("abseil-cpp"), _nix_out("abseil-cpp.dev")
    sp, spdev = _nix_out("speexdsp"), _nix_out("speexdsp.dev")
    gcc = Path(_nix_out("gcc")) / "bin"
    # the WebRTC header set in -dev lacks aec3/echo_canceller3.h: take it from the same version's source tree
    # (needed to tune the AEC3 filter length / suppressor). Defines match the library's meson build.
    subprocess.run([str(gcc / "g++"), "-O2", "-std=c++17", "-DWEBRTC_APM_DEBUG_DUMP=0", "-DWEBRTC_LIBRARY_IMPL",
                    "-DWEBRTC_POSIX", "-DWEBRTC_LINUX", "-DNDEBUG", f"-I{wdev}/include/webrtc-audio-processing-2",
                    f"-I{src}/webrtc", f"-I{abdev}/include", str(AEC_DIR / "aec_webrtc.cc"), "-o", str(BUILD / "aec_webrtc"),
                    f"-L{w}/lib", "-lwebrtc-audio-processing-2", f"-Wl,-rpath,{w}/lib", f"-L{ab}/lib", f"-Wl,-rpath,{ab}/lib"],
                   check=True)
    subprocess.run([str(gcc / "gcc"), "-O2", f"-I{spdev}/include", str(AEC_DIR / "aec_speex.c"), "-o", str(BUILD / "aec_speex"),
                    f"-L{sp}/lib", "-lspeexdsp", f"-Wl,-rpath,{sp}/lib", "-lm"], check=True)
    print("built", sorted(p.name for p in BUILD.iterdir()))


# ============================================================================== media

def _load(path, sr=SR) -> np.ndarray:
    from scipy.signal import resample_poly
    x, r = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if r != sr:
        g = np.gcd(r, sr)
        x = resample_poly(x, sr // g, r // g).astype(np.float32)
    return x


def _act_rms(x: np.ndarray, within_db=30.0) -> float:
    n = len(x) // 480
    e = np.mean(x[: n * 480].astype(np.float64).reshape(n, 480) ** 2, axis=1) + 1e-12
    edb = 10 * np.log10(e)
    return float(np.sqrt(np.mean(e[edb >= edb.max() - within_db])))


def _norm(x: np.ndarray, dbfs: float) -> np.ndarray:
    y = x * (10 ** (dbfs / 20) / (_act_rms(x) + 1e-12))
    pk = np.max(np.abs(y))
    if pk > 0.9:                                     # soft-limit peaks (keeps the busy mix loud but unclipped)
        y = np.tanh(y / 0.9) * 0.9
    return y.astype(np.float32)


def _fade(x: np.ndarray, ms=15) -> np.ndarray:
    n = min(len(x) // 2, int(SR * ms / 1000))
    x = x.copy()
    r = np.linspace(0, 1, n, dtype=np.float32)
    x[:n] *= r
    x[-n:] *= r[::-1]
    return x


def make_media(seed: int = 20260927) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = 60 * SR
    out = {}
    # 1) music with vocals: MUSAN jamendo/fma tracks annotated vocals=Y, 60 s from 30 s in
    ann = []
    for sub in ("jamendo", "fma"):
        for line in (DATA / "musan/musan/music" / sub / "ANNOTATIONS").read_text().splitlines():
            p = line.split()
            if len(p) >= 3 and p[2] == "Y" and "pop" in p[1]:
                ann.append(DATA / "musan/musan/music" / sub / f"{p[0]}.wav")
    ann = sorted(ann)
    x = np.zeros(0, np.float32)
    for f in [ann[i] for i in rng.permutation(len(ann))]:
        y = _load(f)
        if len(y) > 95 * SR:
            x = y[30 * SR: 30 * SR + n]
            out["music_vocals_src"] = f.name
            break
    out["music_vocals"] = _norm(x, MEDIA_RMS_DBFS)
    # 2) podcast: English LibriVox speech, alternating a male and a female reader in 8-15 s turns
    spk = {"m": [], "f": []}
    for line in (DATA / "musan/musan/speech/librivox/ANNOTATIONS").read_text().splitlines():
        p = line.split()
        if len(p) >= 3 and p[2] == "english" and p[1] in spk:
            spk[p[1]].append(DATA / "musan/musan/speech/librivox" / f"{p[0]}.wav")
    fm, ff = sorted(spk["m"])[int(rng.integers(len(spk["m"])))], sorted(spk["f"])[int(rng.integers(len(spk["f"])))]
    ym, yf = _load(fm), _load(ff)
    ym, yf = _norm(ym, MEDIA_RMS_DBFS), _norm(yf, MEDIA_RMS_DBFS)
    parts, pos, turn, om, of = [], 0, 0, 5 * SR, 5 * SR
    while pos < n:
        L = int(rng.uniform(8, 15) * SR)
        src, o = (ym, om) if turn % 2 == 0 else (yf, of)
        seg = np.resize(src[o:], L) if o + L > len(src) else src[o:o + L]
        if turn % 2 == 0:
            om += L
        else:
            of += L
        parts.append(_fade(seg))
        parts.append(np.zeros(int(rng.uniform(0.2, 0.6) * SR), np.float32))
        pos += L
        turn += 1
    out["podcast"] = _norm(np.concatenate(parts)[:n], MEDIA_RMS_DBFS)
    # 3) short-video mix: fast speech + music bed (-12 dB) + ESC-50 effects every 1-3 s + MLEnd whistles / hums
    sp_files = sorted(spk["f"] + spk["m"])
    speech = _norm(_load(sp_files[int(rng.integers(len(sp_files)))])[10 * SR:], MEDIA_RMS_DBFS)
    from scipy.signal import resample_poly
    speech = resample_poly(speech, 10, 11).astype(np.float32)[:n]            # ~10 % faster, a bit higher pitched
    speech = np.pad(speech, (0, max(0, n - len(speech))))
    bed_src = sorted((DATA / "musan/musan/music/fma").glob("*.wav"))
    bed = _load(bed_src[int(rng.integers(len(bed_src)))])
    bed = np.resize(bed[20 * SR:] if len(bed) > 30 * SR else bed, n)
    mix = speech + _norm(bed, MEDIA_RMS_DBFS - 12)
    meta = (DATA / "esc50/ESC-50-master/meta/esc50.csv").read_text().splitlines()[1:]
    cats = {"mouse_click", "keyboard_typing", "door_wood_knock", "clapping", "footsteps", "glass_breaking",
            "can_opening", "clock_tick", "water_drops", "laughing", "dog", "cat", "drinking_sipping", "crow"}
    fx = sorted(DATA / "esc50/ESC-50-master/audio" / r.split(",")[0] for r in meta if r.split(",")[3] in cats)
    hw = sorted((DATA / "mlend_hums_whistles/MLEndHWD_audiofiles").glob("*.wav"))
    t = 1.0
    while t < 58:
        if rng.random() < 0.2:
            y = _load(hw[int(rng.integers(len(hw)))])[: int(rng.uniform(1.0, 3.0) * SR)]
            lvl = MEDIA_RMS_DBFS - 3
        else:
            y = _load(fx[int(rng.integers(len(fx)))])
            y = y[: int(rng.uniform(0.4, 2.0) * SR)]
            lvl = MEDIA_RMS_DBFS + rng.uniform(-6, 2)
        if _act_rms(y) < 1e-5:
            continue
        y = _fade(_norm(y, lvl))
        a = int(t * SR)
        b = min(n, a + len(y))
        mix[a:b] += y[: b - a]
        t += rng.uniform(1.0, 3.0) + len(y) / SR * 0.5
    out["shortvideo"] = _norm(mix, MEDIA_RMS_DBFS)
    # 4) gesture-like: the worst case, media that contains the gesture sounds themselves (other people's tongue
    #    clicks / lip pops / smacks from Deeply Nonverbal, MLEnd hums and whistles, VocalSet sung fragments)
    #    every 1.5-3.5 s over a quiet music bed.
    nv = DATA / "nonverbal/NonverbalVocalization"
    nvf = sorted(p for d in ("tongue-clicking", "lip-popping", "lip-smacking") for p in (nv / d).glob("*.wav"))
    vs = sorted(p for p in (DATA / "vocalset/FULL").rglob("*.wav")
                if any(k in p.parts for k in ("arpeggios", "scales", "long_tones")))
    bed = _load(bed_src[int(rng.integers(len(bed_src)))])
    bed = np.resize(bed[20 * SR:] if len(bed) > 30 * SR else bed, n)
    mix = _norm(bed, MEDIA_RMS_DBFS - 15)
    t, kinds = 1.0, Counter()
    while t < 58:
        u = rng.random()
        if u < 0.45:
            f, k, L = nvf[int(rng.integers(len(nvf)))], "mouth", 2.0
        elif u < 0.75:
            f, k, L = hw[int(rng.integers(len(hw)))], "hum_whistle", rng.uniform(0.8, 2.0)
        else:
            f, k, L = vs[int(rng.integers(len(vs)))], "sung", rng.uniform(0.8, 2.0)
        y = _load(f)[: int(L * SR)]
        if _act_rms(y) < 1e-5:
            continue
        kinds[k] += 1
        y = _fade(_norm(y, MEDIA_RMS_DBFS + rng.uniform(-4, 2)))
        a = int(t * SR)
        b = min(n, a + len(y))
        mix[a:b] += y[: b - a]
        t += len(y) / SR + rng.uniform(1.5, 3.5)
    out["gesturelike"] = _norm(mix, MEDIA_RMS_DBFS)
    out["gesturelike_kinds"] = dict(kinds)
    return out


def cmd_make(a) -> None:
    s = Path(a.session)
    (s / "media").mkdir(parents=True, exist_ok=True)
    m = make_media()
    srcs = {"music_vocals_src": m.pop("music_vocals_src", None), "gesturelike_kinds": m.pop("gesturelike_kinds", None)}
    for k, x in m.items():
        sf.write(s / "media" / f"{k}.wav", x, SR, subtype="FLOAT")
        print(k, f"{len(x) / SR:.1f} s", f"act rms {20 * np.log10(_act_rms(x)):.1f} dBFS")
    (s / "media" / "sources.json").write_text(json.dumps(srcs))


# ============================================================================== record

def _default_sink() -> str:
    return subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, check=True).stdout.strip()


def _rec(target: str, path: Path, channels: int, monitor: bool = False) -> subprocess.Popen:
    cmd = ["pw-record", "--target", target, "--rate", str(SR), "--channels", str(channels), "--format", "f32"]
    if monitor:
        cmd += ["-P", "{ stream.capture.sink = true }"]
    return subprocess.Popen(cmd + [str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _stop(p: subprocess.Popen) -> None:
    p.send_signal(signal.SIGINT)
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        p.kill()


def _play_and_record(wav: Path, sink: str, out_mic: Path, out_mon: Path | None, mic: str = MIC,
                     mon_target: str | None = None, pre=1.5, post=2.0) -> dict:
    recs = [_rec(mic, out_mic, 1)]
    if out_mon is not None:
        recs.append(_rec(mon_target or sink, out_mon, 2, monitor=True))
    time.sleep(pre)
    t0 = time.time()
    if wav is not None:
        subprocess.run(["pw-play", "--target", sink, str(wav)], check=True)
    else:
        time.sleep(60)
    dur = time.time() - t0
    time.sleep(post)
    for p in recs:
        _stop(p)
    return {"play_s": round(dur, 2), "pre_s": pre, "post_s": post}


def cmd_record(a) -> None:
    s = Path(a.session)
    rec = s / "rec"
    rec.mkdir(parents=True, exist_ok=True)
    sink = _default_sink()
    n_clips = len(CLIPS)
    minutes = 0.2 + n_clips * 1.1 + (n_clips * 1.1 if a.live_ec else 0)
    print(f"SOUND: the desktop speakers will play test media for about {minutes:.0f} minutes (moderate volume), "
          f"plus 1 silent room minute.", flush=True)
    meta = {"sink": sink, "mic": MIC, "rate": SR, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    # --- level check: 3 s of pink noise at -30 dBFS, measure the echo at the mic
    rng = np.random.default_rng(1)
    w = np.fft.irfft(np.fft.rfft(rng.standard_normal(3 * SR)) / np.sqrt(np.maximum(np.arange(3 * SR // 2 + 1), 1)))
    w = _fade(_norm(w.astype(np.float32), -30.0), 50)
    sf.write(rec / "levelcheck_play.wav", np.stack([w, w], 1), SR, subtype="FLOAT")
    _play_and_record(rec / "levelcheck_play.wav", sink, rec / "levelcheck_mic.wav", None, pre=1.0, post=0.5)
    x, _ = sf.read(rec / "levelcheck_mic.wav", dtype="float32")
    room = 20 * np.log10(np.sqrt(np.mean(x[int(0.2 * SR): int(0.9 * SR)] ** 2)) + 1e-12)
    echo = 20 * np.log10(np.sqrt(np.mean(x[int(1.5 * SR): int(3.5 * SR)] ** 2)) + 1e-12)
    coupling = echo - (-30.0)
    gain_db = float(np.clip(TARGET_ECHO_DBFS - (MEDIA_RMS_DBFS + coupling), -30, MAX_FILE_GAIN_DB))
    meta.update(levelcheck_room_dbfs=round(float(room), 1), levelcheck_echo_dbfs=round(float(echo), 1),
                coupling_db=round(float(coupling), 1), playback_gain_db=round(gain_db, 1))
    print(f"level check: room {room:.1f} dBFS, echo {echo:.1f} dBFS for a -30 dBFS file -> coupling {coupling:.1f} dB, "
          f"playback gain {gain_db:+.1f} dB (media at {MEDIA_RMS_DBFS + gain_db:.1f} dBFS in the file)", flush=True)
    if echo - room < 6:
        print("the mic does not hear the speakers (no speaker on this sink, or it is off/muted): stopping", flush=True)
        (s / "record.json").write_text(json.dumps(meta, indent=1))
        return
    g = 10 ** (gain_db / 20)
    for c in CLIPS:
        x, _ = sf.read(s / "media" / f"{c}.wav", dtype="float32")
        y = np.clip(x * g, -1, 1)
        sf.write(rec / f"{c}_play.wav", np.stack([y, y], 1), SR, subtype="FLOAT")
    # --- room minute (nothing plays)
    meta["room"] = _play_and_record(None, sink, rec / "room_mic.wav", rec / "room_mon.wav")
    print("room minute recorded", flush=True)
    for c in CLIPS:
        meta[c] = _play_and_record(rec / f"{c}_play.wav", sink, rec / f"{c}_mic.wav", rec / f"{c}_mon.wav")
        print(c, "recorded", meta[c], flush=True)
    if a.live_ec:
        meta["live_ec"] = _live_ec(rec, sink)
    (s / "record.json").write_text(json.dumps(meta, indent=1))


def _live_ec(rec: Path, sink: str) -> dict:
    """PipeWire's own module-echo-cancel (webrtc backend, its default AEC3 + NS settings), live."""
    args = ["pactl", "load-module", "module-echo-cancel", "aec_method=webrtc", f"source_master={MIC}",
            f"sink_master={sink}", "source_name=vox_ec_source", "sink_name=vox_ec_sink"]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print("module-echo-cancel did not load:", r.stderr.strip(), flush=True)
        return {"error": r.stderr.strip()}
    mod = r.stdout.strip()
    out = {"module": mod}
    try:
        time.sleep(2)
        for c in CLIPS:
            out[c] = _play_and_record(rec / f"{c}_play.wav", "vox_ec_sink", rec / f"{c}_liveec.wav", rec / f"{c}_liveec_rawmic.wav",
                                      mic="vox_ec_source", mon_target=MIC)
            # (second recorder = the raw mic during the live pass; pw-record of a source ignores stream.capture.sink)
            print(c, "live-ec recorded", flush=True)
    finally:
        subprocess.run(["pactl", "unload-module", mod], capture_output=True)
    return out


# ============================================================================== alignment

def _xcorr_lag(a: np.ndarray, b: np.ndarray, max_lag: int, phat: bool = True) -> tuple[int, float]:
    """Lag L (samples) maximising sum a[n] b[n-L], i.e. a is b delayed by L. GCC-PHAT by default."""
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    A, B = np.fft.rfft(a, n), np.fft.rfft(b, n)
    R = A * np.conj(B)
    if phat:
        R = R / (np.abs(R) + 1e-12)
    r = np.fft.irfft(R, n)
    r = np.concatenate([r[-max_lag:], r[: max_lag + 1]])
    i = int(np.argmax(np.abs(r)))
    return i - max_lag, float(np.abs(r[i]) / (np.sum(np.abs(r)) / len(r) + 1e-20))


def _mono(path: Path) -> np.ndarray:
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    assert sr == SR, (path, sr)
    return x.mean(axis=1)


def align(rec: Path, clip: str) -> dict:
    mic, mon = _mono(rec / f"{clip}_mic.wav"), _mono(rec / f"{clip}_mon.wav")
    ply = _mono(rec / f"{clip}_play.wav")
    n = min(len(mic), len(mon))
    mic, mon = mic[:n], mon[:n]
    # monitor vs file: where the file starts in the monitor recording, and how exact the copy is
    lag_f, _ = _xcorr_lag(mon[: 20 * SR], ply[: 20 * SR], 6 * SR)
    seg = mon[lag_f: lag_f + len(ply)]
    m = min(len(seg), len(ply))
    g = float(np.dot(seg[:m], ply[:m]) / (np.dot(ply[:m], ply[:m]) + 1e-20))
    resid = seg[:m] - g * ply[:m]
    file_match_db = 10 * np.log10(np.mean(seg[:m] ** 2) / (np.mean(resid ** 2) + 1e-20))
    # mic vs monitor: bulk delay at the start and at the end of the clip (drift)
    a0 = lag_f + 2 * SR
    b0 = lag_f + len(ply) - 17 * SR
    d0, c0 = _xcorr_lag(mic[a0: a0 + 15 * SR], mon[a0: a0 + 15 * SR], SR // 2)
    d1, c1 = _xcorr_lag(mic[b0: b0 + 15 * SR], mon[b0: b0 + 15 * SR], SR // 2)
    drift_ppm = (d1 - d0) / ((b0 - a0) / 1e6)
    return {"file_offset_in_monitor_s": round(lag_f / SR, 4), "monitor_vs_file_gain": round(g, 4),
            "monitor_vs_file_match_db": round(float(file_match_db), 1),
            "mic_delay_ms_start": round(d0 / SR * 1000, 2), "mic_delay_ms_end": round(d1 / SR * 1000, 2),
            "drift_ppm": round(float(drift_ppm), 1), "peak_ratio": [round(c0, 1), round(c1, 1)],
            "delay_samples": int(round((d0 + d1) / 2)), "play_start": int(lag_f), "play_len": int(len(ply))}


def shift(x: np.ndarray, d: int) -> np.ndarray:
    """y[n] = x[n - d] (delay by d samples; negative d advances)."""
    y = np.zeros_like(x)
    if d >= 0:
        y[d:] = x[: len(x) - d]
    else:
        y[:d] = x[-d:]
    return y


# ============================================================================== cancellers

MARGIN = 240  # 5 ms: the pre-aligned reference still leads the echo a little, so the causal filters can see it
# AEC3 gets the reference with its natural timing (the playback leads the mic echo by the output latency + the
# acoustic path, as AudioPlaybackCapture would give on the phone) and finds the delay itself; pre-aligning it to
# within 2 ms made AEC3 worse (its delay estimator wants headroom). Speex / NLMS have no delay estimator, so they
# get the pre-aligned reference (on a phone the delay would have to be estimated first).


def _run_bin(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {r.stderr}")


def webrtc(ref, mic, tmp: Path, mode="aec3", fblocks=0, delay_ms=0, ns=0, supp="default") -> np.ndarray:
    tag = f"{os.getpid()}_{time.monotonic_ns()}"
    fr, fm, fo = tmp / f"r{tag}.f32", tmp / f"m{tag}.f32", tmp / f"o{tag}.f32"
    ref.astype(np.float32).tofile(fr)
    mic.astype(np.float32).tofile(fm)
    _run_bin([str(BUILD / "aec_webrtc"), str(fr), str(fm), str(fo), str(SR), mode, str(fblocks), str(delay_ms), str(ns), supp])
    y = np.fromfile(fo, np.float32)
    for f in (fr, fm, fo):
        f.unlink()
    return y


def speex(ref, mic, tmp: Path, tail_ms=200, supp=0, supp_act=0) -> np.ndarray:
    tag = f"{os.getpid()}_{time.monotonic_ns()}"
    fr, fm, fo = tmp / f"r{tag}.f32", tmp / f"m{tag}.f32", tmp / f"o{tag}.f32"
    ref.astype(np.float32).tofile(fr)
    mic.astype(np.float32).tofile(fm)
    _run_bin([str(BUILD / "aec_speex"), str(fr), str(fm), str(fo), str(SR), "480", str(tail_ms), str(supp), str(supp_act)])
    y = np.fromfile(fo, np.float32)
    for f in (fr, fm, fo):
        f.unlink()
    return y


def nlms(ref, mic, tail_ms=200, mu=0.2, N=512, floor=0.1) -> np.ndarray:
    """Partitioned-block frequency-domain NLMS (constrained, overlap-save), no double-talk detector.
    Per-bin step normalised by the regressor energy, floored at `floor` x its mean over bins (without the
    floor it diverged on speech pauses: weak bins got huge steps)."""
    P = int(np.ceil(tail_ms / 1000 * SR / N))
    nb = len(mic) // N
    X = np.zeros((P, N + 1), complex)
    W = np.zeros((P, N + 1), complex)
    prev = np.zeros(N)
    out = np.zeros(len(mic), np.float32)
    for k in range(nb):
        xk = ref[k * N:(k + 1) * N].astype(np.float64)
        X = np.roll(X, 1, axis=0)
        X[0] = np.fft.rfft(np.concatenate([prev, xk]))
        prev = xk
        y = np.fft.irfft((W * X).sum(axis=0))[N:]
        e = mic[k * N:(k + 1) * N] - y
        out[k * N:(k + 1) * N] = e
        E = np.fft.rfft(np.concatenate([np.zeros(N), e]))
        pw = (np.abs(X) ** 2).sum(axis=0)             # regressor energy per bin over the whole filter (NLMS norm)
        pw = np.maximum(pw, floor * pw.mean())
        G = mu * np.conj(X) * E / (pw + 1e-2 * N)
        g = np.fft.irfft(G, axis=1)[:, :N]
        W += np.fft.rfft(np.concatenate([g, np.zeros_like(g)], axis=1), axis=1)
    return out


# name -> (family, callable(ref_aligned, ref_raw, mic, delay_samples, tmp))
VARIANTS = {
    "raw":               ("none",   lambda ra, rr, m, d, t: m),
    "aec3":              ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t)),
    "aec3_prealigned":   ("webrtc", lambda ra, rr, m, d, t: webrtc(shift(ra, 480 - MARGIN), m, t)),   # ref leads by 10 ms
    "aec3_ns":           ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t, ns=1)),
    "aec3_f25":          ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t, fblocks=25)),
    "aec3_f50":          ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t, fblocks=50)),
    "aec3_strong":       ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t, supp="strong")),
    "aec3_f25_strong":   ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t, fblocks=25, supp="strong")),
    "aec3_f25_strong_ns": ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t, fblocks=25, supp="strong", ns=1)),
    "aec3_gentle":       ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t, supp="gentle")),
    "aecm_mobile":       ("webrtc", lambda ra, rr, m, d, t: webrtc(rr, m, t, mode="mobile", delay_ms=int(d / SR * 1000))),
    "speex_t100":        ("speex",  lambda ra, rr, m, d, t: speex(ra, m, t, 100)),
    "speex_t250":        ("speex",  lambda ra, rr, m, d, t: speex(ra, m, t, 250)),
    "speex_t250_s40":    ("speex",  lambda ra, rr, m, d, t: speex(ra, m, t, 250, -40, -15)),
    "speex_t250_s60":    ("speex",  lambda ra, rr, m, d, t: speex(ra, m, t, 250, -60, -40)),
    "speex_t500_s60":    ("speex",  lambda ra, rr, m, d, t: speex(ra, m, t, 500, -60, -40)),
    "nlms_t100":         ("nlms",   lambda ra, rr, m, d, t: nlms(ra, m, 100)),
    "nlms_t250":         ("nlms",   lambda ra, rr, m, d, t: nlms(ra, m, 250)),
}


# ============================================================================== scoring

def score_events(ev: list[dict], seconds: float) -> dict:
    """would_act_pm: as the app counts it (vox_extract.sequencer_sim: act-at-once Sequencer, the app's bindings,
    MicPopGate's lone pop) with PhoneGate as shipped for media on the speaker (pop / hum 14 dB + clarity, hiss centroid
    > 6.5 kHz); would_act_nogate_pm: the same without PhoneGate; would_act_group_pm: the old policy.group count
    (up to 3 sounds per 600 ms group, one lookup per group), which undercounts the app ~10x on hiss-heavy input and is
    kept only to compare with the results written before 2026-09-27."""
    groups = group(ev)
    acts = [action_for([(e["label"], e["text"]) for e in g]) for g in groups]
    app = would_act(ev, seconds / 60, gate={})
    nogate = would_act(ev, seconds / 60)
    deliberate = [g for g in groups if all(e["label"] in LABELS and not not_deliberate(e["label"], e["text"]) for e in g)]
    popop = [g for g in groups if [e["label"] for e in g] == ["pop", "pop"]]
    popop_d = [g for g in popop if all(not not_deliberate(e["label"], e["text"]) for e in g)]
    mins = seconds / 60
    return {"events_pm": len(ev) / mins, "would_act_pm": app["would_act_pm"],
            "would_act_nogate_pm": nogate["would_act_pm"], "would_act_group_pm": sum(a != "none" for a in acts) / mins,
            "deliberate_groups_pm": len(deliberate) / mins, "poppop_pm": len(popop) / mins,
            "poppop_deliberate_pm": len(popop_d) / mins,
            "gesture_label_events_pm": sum(e["label"] in LABELS for e in ev) / mins,
            "actions": app["actions"]}


def extract(x: np.ndarray) -> list[dict]:
    return [e.to_dict() for e in extract_array(np.asarray(x, np.float32), SR, Config())]


def erle_db(mic: np.ndarray, out: np.ndarray, ref: np.ndarray, room_rms: float) -> dict:
    """ERLE over 10 ms frames where the (aligned) reference is active; also the echo-to-room-noise ratio,
    which caps what ERLE can show (the residual cannot go below the room noise)."""
    n = min(len(mic), len(out), len(ref)) // 480 * 480
    f = lambda z: np.mean(z[:n].astype(np.float64).reshape(-1, 480) ** 2, axis=1)  # noqa: E731
    em, eo, er = f(mic), f(out), f(ref)
    erdb = 10 * np.log10(er + 1e-15)
    act = erdb > erdb.max() - 30
    return {"erle_db": float(10 * np.log10(em[act].sum() / (eo[act].sum() + 1e-20))),
            "enr_db": float(10 * np.log10(em[act].mean() / (room_rms ** 2 + 1e-20)))}


# ------------------------------------------------------------------------------ jobs (process pool)

def _job_media(j: dict) -> dict:
    tmp = Path(j["tmp"])
    mic, ra, rr = np.load(j["mic"]), np.load(j["ref_al"]), np.load(j["ref_raw"])
    import resource
    ch0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.process_time()
    y = VARIANTS[j["variant"]][1](ra, rr, mic, j["delay"], tmp)
    ch1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    # own CPU (NLMS) + the harness subprocess (WebRTC / Speex, including its float32 file I/O)
    cpu = time.process_time() - t0 + (ch1.ru_utime - ch0.ru_utime) + (ch1.ru_stime - ch0.ru_stime)
    y = np.asarray(y, np.float32)[: len(mic)]
    if len(y) < len(mic):
        y = np.pad(y, (0, len(mic) - len(y)))
    ev = extract(y)
    r = {"clip": j["clip"], "variant": j["variant"], "seconds": len(mic) / SR, **score_events(ev, len(mic) / SR)}
    if j["variant"] != "raw":
        r.update(erle_db(mic, y, ra, j["room_rms"]))
    r["cpu_x_realtime"] = cpu / (len(mic) / SR)
    return r


def _job_survival(j: dict) -> dict:
    tmp = Path(j["tmp"])
    mic, ra, rr = np.load(j["mic"]), np.load(j["ref_al"]), np.load(j["ref_raw"])
    add = np.load(j["takes"])
    x = mic + add * j["gain"]
    y = np.asarray(VARIANTS[j["variant"]][1](ra, rr, x, j["delay"], tmp), np.float32)[: len(x)]
    ev = extract(y)
    res = []
    for pl in j["placements"]:
        a, b = pl["t0_ms"] - 150, pl["t1_ms"] + 250
        inside = [e for e in ev if a <= e["t_start_ms"] <= b]
        # only the sounds the phone would not gate (not_deliberate is None): the takes also carry gated breath /
        # room "hiss (background noise)" events that no profile acts on, and they must not decide the match
        labels = [e["label"] for e in inside if e["label"] in LABELS and not not_deliberate(e["label"], e["text"])]
        # what the app would do with the take (sequencer_sim, no PhoneGate: the canceller is the question here)
        acts = [a for _, a in app_actions(inside)] if inside else []
        res.append({"take": pl["take"], "detected": bool(labels), "labels": labels,
                    "actions": [x for x in acts if x != "none"]})
    return {"clip": j["clip"], "variant": j["variant"], "gain_db": j["gain_db"], "pass": j["pass"], "res": res}


# ------------------------------------------------------------------------------ takes

def expected_labels(kind: str) -> list[str]:
    if kind.startswith("whistle_"):
        return [kind.split("_")[1]]
    if kind == "click_run":
        return None  # any run of clicks
    return kind.split("_")


def load_takes() -> list[dict]:
    takes = {}
    for line in (TAKES_SESSION / "labels.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["block"] in ("clicks", "whistles") and r.get("cond") != "video" and r["status"] == "kept":
            takes[r["pid"]] = r     # last line per prompt id wins
    out = []
    for pid, r in sorted(takes.items()):
        x, sr = sf.read(str(TAKES_SESSION / r["file"]), dtype="float32", always_2d=True)
        assert sr == SR
        out.append({"id": pid, "kind": r["kind"], "x": _fade(x.mean(axis=1), 20)})
    return out


def label_ok(kind: str, labels: list[str]) -> bool:
    exp = expected_labels(kind)
    if exp is None:
        return len(labels) >= 3 and all(l == "click" for l in labels)
    return labels == exp


# ============================================================================== eval

def cmd_eval(a) -> None:
    s = Path(a.session)
    rec = s / "rec"
    work = s / "work"
    work.mkdir(exist_ok=True)
    tmp = work / "tmp"
    tmp.mkdir(exist_ok=True)
    meta = json.loads((s / "record.json").read_text())
    room = _mono(rec / "room_mic.wav")
    room = room[int(0.5 * SR):]
    room_rms = float(np.sqrt(np.mean(room.astype(np.float64) ** 2)))
    variants = a.variants or list(VARIANTS)
    # --- alignment + per-clip arrays
    al, jobs = {}, []
    for c in CLIPS:
        al[c] = align(rec, c)
        mic, mon = _mono(rec / f"{c}_mic.wav"), _mono(rec / f"{c}_mon.wav")
        n = min(len(mic), len(mon))
        mic, mon = mic[:n], mon[:n]
        d = al[c]["delay_samples"]
        np.save(work / f"{c}_mic.npy", mic)
        np.save(work / f"{c}_ref_al.npy", shift(mon, d - MARGIN))
        np.save(work / f"{c}_ref_raw.npy", mon)
        print(c, al[c], flush=True)
        for v in variants:
            jobs.append({"clip": c, "variant": v, "mic": str(work / f"{c}_mic.npy"), "ref_al": str(work / f"{c}_ref_al.npy"),
                         "ref_raw": str(work / f"{c}_ref_raw.npy"), "delay": d, "tmp": str(tmp), "room_rms": room_rms})
    room_ev = extract(room)
    room_score = score_events(room_ev, len(room) / SR)
    print("room:", {k: round(v, 2) if isinstance(v, float) else v for k, v in room_score.items()}, flush=True)
    media = pmap(_job_media, jobs, workers=a.workers, chunksize=1)
    # live PipeWire echo-cancel pass, if recorded
    live = {}
    for c in CLIPS:
        p, q = rec / f"{c}_liveec.wav", rec / f"{c}_liveec_rawmic.wav"
        if p.exists():
            y = _mono(p)
            live[c] = {"seconds": len(y) / SR, **score_events(extract(y), len(y) / SR)}
            if q.exists():
                z = _mono(q)
                live[c]["rawmic"] = score_events(extract(z), len(z) / SR)
    # --- survival
    surv = []
    if not a.no_survival:
        takes = load_takes()
        base = np.zeros(len(room), np.float32)
        slot = int(7.0 * SR)
        per = (len(base) - SR) // slot
        n_pass = int(np.ceil(len(takes) / per))
        passes = []
        for p in range(n_pass):
            sub = takes[p * per:(p + 1) * per]
            passes.append(sub)
        sjobs = []
        sv = a.survival_variants or ["raw", "aec3", "aec3_ns", "aec3_f25", "aec3_strong", "aec3_f25_strong",
                                     "aec3_f25_strong_ns", "aec3_prealigned", "aecm_mobile", "speex_t250", "speex_t250_s40",
                                     "speex_t250_s60", "nlms_t250"]
        for c in ["room"] + CLIPS:
            if c == "room":
                np.save(work / "room_mic.npy", room)
                np.save(work / "room_ref.npy", np.zeros_like(room))
            for p, sub in enumerate(passes):
                L = len(room) if c == "room" else len(np.load(work / f"{c}_mic.npy", mmap_mode="r"))
                add = np.zeros(L, np.float32)
                pls = []
                off = SR if c == "room" else al[c]["play_start"] + SR
                for i, t in enumerate(sub):
                    st = off + i * slot
                    if st + len(t["x"]) >= L:
                        break
                    add[st:st + len(t["x"])] += t["x"]
                    pls.append({"take": t["id"], "t0_ms": st / SR * 1000 + 800, "t1_ms": (st + len(t["x"])) / SR * 1000})
                np.save(work / f"takes_{c}_{p}.npy", add)
                for gdb in a.gains:
                    for v in (["raw"] if c == "room" else sv):
                        mic_p = work / ("room_mic.npy" if c == "room" else f"{c}_mic.npy")
                        ra = work / ("room_ref.npy" if c == "room" else f"{c}_ref_al.npy")
                        rr = work / ("room_ref.npy" if c == "room" else f"{c}_ref_raw.npy")
                        sjobs.append({"clip": c, "variant": v, "pass": p, "gain_db": gdb, "gain": 10 ** (gdb / 20),
                                      "mic": str(mic_p), "ref_al": str(ra), "ref_raw": str(rr), "takes": str(work / f"takes_{c}_{p}.npy"),
                                      "placements": pls, "delay": al.get(c, {}).get("delay_samples", 0), "tmp": str(tmp)})
        surv = pmap(_job_survival, sjobs, workers=a.workers, chunksize=1)
        kinds = {t["id"]: t["kind"] for t in takes}
    out = {"record": meta, "alignment": al, "room_rms_dbfs": 20 * np.log10(room_rms), "room": room_score,
           "media": media, "live_ec": live}
    if surv:
        out["survival"] = summarise_survival(surv, kinds)
    (s / "results.json").write_text(json.dumps(out, indent=1, default=float))
    md = report(out)
    (s / "results.md").write_text(md)
    print(md)
    shutil.rmtree(tmp, ignore_errors=True)


def summarise_survival(surv: list[dict], kinds: dict[str, str]) -> dict:
    """Aggregate only. Reference = the same takes on the quiet room (no media, no canceller)."""
    ref = {}
    for r in surv:
        if r["clip"] == "room":
            for x in r["res"]:
                ref[(r["gain_db"], x["take"])] = x
    agg = {}
    for r in surv:
        if r["clip"] == "room":
            continue
        k = (r["variant"], r["gain_db"])
        A = agg.setdefault(k, {"n": 0, "det": 0, "lab_abs": 0, "ref_det": 0, "ref_lab": 0, "kept_det": 0, "kept_lab": 0,
                               "act": 0, "ref_act": 0, "kept_act": 0, "per_clip": {}})
        pc = A["per_clip"].setdefault(r["clip"], {"ref_lab": 0, "kept_lab": 0, "ref_det": 0, "kept_det": 0})
        for x in r["res"]:
            q = ref.get((r["gain_db"], x["take"]))
            kind = kinds[x["take"]]
            ok = label_ok(kind, x["labels"])
            A["n"] += 1
            A["det"] += x["detected"]
            A["lab_abs"] += ok
            A["act"] += bool(x["actions"])
            if q is not None and q["detected"]:
                A["ref_det"] += 1
                A["kept_det"] += x["detected"]
                pc["ref_det"] += 1
                pc["kept_det"] += x["detected"]
            if q is not None and q["labels"]:          # kept = the same deliberate label sequence as on the quiet room
                A["ref_lab"] += 1
                A["kept_lab"] += x["labels"] == q["labels"]
                pc["ref_lab"] += 1
                pc["kept_lab"] += x["labels"] == q["labels"]
            if q is not None and q["actions"]:
                A["ref_act"] += 1
                A["kept_act"] += x["actions"] == q["actions"]
    room = {}
    for (g, _t), q in ref.items():
        R = room.setdefault(g, {"n": 0, "det": 0, "lab": 0})
        R["n"] += 1
        R["det"] += q["detected"]
        R["lab"] += label_ok(kinds[_t], q["labels"])
    return {"by_variant": {f"{v}@{g:+.0f}dB": A for (v, g), A in agg.items()}, "room_reference": room}


def report(o: dict) -> str:
    L = []
    rm = o["record"]
    L.append(f"Room: {o['room_rms_dbfs']:.1f} dBFS; level check coupling {rm.get('coupling_db')} dB, playback gain "
             f"{rm.get('playback_gain_db')} dB. Room minute alone: {o['room']['events_pm']:.1f} events/min, "
             f"{o['room']['would_act_pm']:.1f} would-act/min.")
    L.append("")
    L.append("| clip | monitor = file (dB match) | mic delay start / end (ms) | drift (ppm) |")
    L.append("|---|---|---|---|")
    for c, a in o["alignment"].items():
        L.append(f"| {c} | {a['monitor_vs_file_match_db']} | {a['mic_delay_ms_start']} / {a['mic_delay_ms_end']} | {a['drift_ppm']} |")
    L.append("")
    by = {}
    for r in o["media"]:
        by.setdefault(r["variant"], []).append(r)
    L.append("Media only (per minute, mean over the clips; per-clip would-act in brackets: " + ", ".join(CLIPS) + ")")
    L.append("")
    L.append("| canceller | events | would-act (app Sequencer + PhoneGate) | without PhoneGate | old policy.group count | deliberate-looking groups | pop pop (all / deliberate) | ERLE dB (mean, min) | CPU x realtime |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for v, rs in by.items():
        rs = sorted(rs, key=lambda r: CLIPS.index(r["clip"]))
        m = lambda k: np.mean([r[k] for r in rs])  # noqa: E731
        er = f"{m('erle_db'):.1f}, {min(r['erle_db'] for r in rs):.1f}" if "erle_db" in rs[0] else "-"
        per = " / ".join(f"{r['would_act_pm']:.0f}" for r in rs)
        L.append(f"| {v} | {m('events_pm'):.1f} | **{m('would_act_pm'):.1f}** [{per}] | {m('would_act_nogate_pm'):.1f} | "
                 f"{m('would_act_group_pm'):.1f} | {m('deliberate_groups_pm'):.1f} | "
                 f"{m('poppop_pm'):.1f} / {m('poppop_deliberate_pm'):.1f} | {er} | {m('cpu_x_realtime'):.3f} |")
    if o["media"] and "enr_db" in o["media"][1]:
        enr = {r["clip"]: r["enr_db"] for r in o["media"] if "enr_db" in r}
        L.append("")
        L.append("Echo-to-room-noise ratio at the mic (caps the measurable ERLE): " +
                 ", ".join(f"{c} {v:.1f} dB" for c, v in enr.items()))
    if o.get("live_ec"):
        L.append("")
        L.append("PipeWire module-echo-cancel (webrtc), live: " + ", ".join(
            f"{c} {r['would_act_pm']:.1f} would-act/min ({r['events_pm']:.1f} events)"
            + (f" vs raw mic in the same pass {r['rawmic']['would_act_pm']:.1f}" if 'rawmic' in r else "") for c, r in o["live_ec"].items()))
    if "survival" in o:
        S = o["survival"]
        L.append("")
        L.append("Survival: the user's quiet gesture takes mixed onto the media recordings (aggregate over takes x clips).")
        L.append("Only deliberate (ungated) gesture events count. Kept = among the takes that gave >= 1 deliberate event / "
                 "acted on the quiet room: still >= 1 deliberate event / exactly the same deliberate label sequence / the same "
                 "actions. Absolute = the deliberate sequence equals the prompted gesture.")
        L.append("")
        rr = S["room_reference"]
        L.append("Quiet-room reference: " + ", ".join(f"at {g:+.0f} dB: >= 1 deliberate event {R['det']}/{R['n']}, prompted gesture {R['lab']}/{R['n']}"
                                                     for g, R in sorted(rr.items(), key=lambda kv: -float(kv[0]))))
        L.append("")
        L.append("| canceller @ gesture gain | detection kept | label kept | action kept | label right (absolute) |")
        L.append("|---|---|---|---|---|")
        for k, A in S["by_variant"].items():
            f = lambda a, b: f"{100 * a / b:.0f} % ({a}/{b})" if b else "-"  # noqa: E731
            L.append(f"| {k} | {f(A['kept_det'], A['ref_det'])} | **{f(A['kept_lab'], A['ref_lab'])}** | "
                     f"{f(A['kept_act'], A['ref_act'])} | {f(A['lab_abs'], A['n'])} |")
    return "\n".join(L) + "\n"


# ============================================================================== simulated echo path (no speaker)

def _rir(rng, rt60: float, drr_db: float, direct_ms: float) -> np.ndarray:
    """Synthetic room impulse response: a direct tap + an exponentially decaying noise tail."""
    L = int(rt60 * 1.2 * SR)
    t = np.arange(L) / SR
    tail = rng.standard_normal(L) * np.exp(-6.9 * t / rt60)
    d0 = int(direct_ms / 1000 * SR)
    tail[: d0 + int(0.002 * SR)] = 0
    h = tail / np.sqrt(np.sum(tail ** 2)) * 10 ** (-drr_db / 20)
    h[d0] += 1.0
    return h


def _speaker(x: np.ndarray, kind: str) -> np.ndarray:
    from scipy.signal import butter, sosfilt
    if kind == "desk":        # a small desktop speaker: 80 Hz - 16 kHz, mild saturation
        y = sosfilt(butter(2, [80, 16000], "bandpass", fs=SR, output="sos"), x)
        k = 0.8
    else:                     # a phone speaker: 350 Hz - 8 kHz, driven into compression, asymmetric
        y = sosfilt(butter(4, [350, 8000], "bandpass", fs=SR, output="sos"), x)
        k = 3.0
    y = y / (np.max(np.abs(y)) + 1e-9)
    z = np.tanh(k * y) / np.tanh(k) + (0.08 * y * y if kind == "phone" else 0.0)
    return sosfilt(butter(2, 60, "highpass", fs=SR, output="sos"), z)


SIMS = {  # name: speaker model, RIR (rt60 s, direct-to-reverb dB, direct path ms), echo level at the mic (dBFS act. RMS)
    "desk":  {"speaker": "desk",  "rt60": 0.35, "drr_db": 3.0,  "direct_ms": 1.5, "echo_dbfs": -30.0, "delay_ms": 45},
    "phone": {"speaker": "phone", "rt60": 0.30, "drr_db": 15.0, "direct_ms": 0.1, "echo_dbfs": -18.0, "delay_ms": 25},
}


def cmd_sim(a) -> None:
    """SIMULATED acoustics, for when no speaker is available: echo = RIR * speaker(file), plus the real room
    noise recorded from the mic (rec/room_long_mic.wav of --room-from). Writes a session in the same layout as
    `record`, so `eval` runs unchanged. The monitor (reference) is the clean file, as AudioPlaybackCapture gives."""
    s, src = Path(a.session), Path(a.room_from)
    P = SIMS[a.model]
    rng = np.random.default_rng(7)
    rec = s / "rec"
    rec.mkdir(parents=True, exist_ok=True)
    room = _mono(src / "rec" / "room_long_mic.wav")[SR:]
    pre, post = int(1.5 * SR), int(2.0 * SR)
    h = _rir(rng, P["rt60"], P["drr_db"], P["direct_ms"])
    d = int(P["delay_ms"] / 1000 * SR)
    L0 = pre + 60 * SR + post
    # room minute: the first L0 samples of the room recording; clips use other, circular offsets
    sf.write(rec / "room_mic.wav", room[:L0], SR, subtype="FLOAT")
    sf.write(rec / "room_mon.wav", np.zeros((L0, 2), np.float32), SR, subtype="FLOAT")
    meta = {"simulated": True, "model": a.model, **P, "room_from": str(src), "rate": SR}
    from scipy.signal import fftconvolve
    for i, c in enumerate(CLIPS):
        x = _mono(src / "media" / f"{c}.wav")
        sig = np.zeros(L0)
        sig[pre:pre + len(x)] = x
        e = fftconvolve(_speaker(sig, P["speaker"]), h)[:L0]
        e = shift(e, d)
        e *= 10 ** (P["echo_dbfs"] / 20) / (_act_rms(e.astype(np.float32)) + 1e-12)
        off = int((i + 1) * len(room) / (len(CLIPS) + 1))
        noise = np.roll(room, -off)[:L0] if len(room) >= L0 else np.resize(np.roll(room, -off), L0)
        mic = (e + noise).astype(np.float32)
        sf.write(rec / f"{c}_mic.wav", mic, SR, subtype="FLOAT")
        sf.write(rec / f"{c}_mon.wav", np.stack([sig, sig], 1).astype(np.float32), SR, subtype="FLOAT")
        sf.write(rec / f"{c}_play.wav", np.stack([x, x], 1), SR, subtype="FLOAT")
        meta[c] = {"echo_dbfs": P["echo_dbfs"], "room_offset_s": off / SR}
    (s / "record.json").write_text(json.dumps(meta, indent=1))
    print("simulated session written:", s, meta)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    for name in ("make", "record", "eval", "sim"):
        p = sub.add_parser(name)
        p.add_argument("--session", required=True)
        if name == "record":
            p.add_argument("--live-ec", action="store_true")
        if name == "sim":
            p.add_argument("--model", choices=list(SIMS), required=True)
            p.add_argument("--room-from", default=str(ROOT / "recordings" / "aec-desktop-1"),
                           help="session holding media/ and rec/room_long_mic.wav")
        if name == "eval":
            p.add_argument("--workers", type=int, default=8)
            p.add_argument("--variants", nargs="*")
            p.add_argument("--survival-variants", nargs="*")
            p.add_argument("--gains", nargs="*", type=float, default=[0.0, -10.0])
            p.add_argument("--no-survival", action="store_true")
    a = ap.parse_args()
    if a.cmd != "build":
        sp = Path(a.session).resolve()
        if not sp.name.startswith("aec-desktop-") or sp.parent != (ROOT / "recordings").resolve():
            sys.exit("--session must be recordings/aec-desktop-* (private, gitignored)")
    {"build": cmd_build, "make": cmd_make, "record": cmd_record, "eval": cmd_eval, "sim": cmd_sim}[a.cmd](a)


if __name__ == "__main__":
    main()
