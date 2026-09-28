"""Offline near-field measurement analysis; NumPy only, no device connection.

Keep this beside measure.py: stream-clock alignment, prompt labels and gate
semantics belong to the Android measurement protocol, not the extractor API.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import re
import wave
from pathlib import Path

import numpy as np

FEATURES = ("low_band_ratio", "level_above_floor_db", "onset_ms", "decay_ms",
            "ild_db", "tmpl_distance", "tmpl_ratio")


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels, rate, frames = wav.getnchannels(), wav.getframerate(), wav.getnframes()
        if wav.getsampwidth() != 2 or channels not in (1, 2) or wav.getcomptype() != "NONE":
            raise ValueError(f"{path}: expected PCM16 mono/stereo")
        raw = wav.readframes(frames)
        if len(raw) != frames * channels * 2:
            raise ValueError(f"{path}: truncated WAV")
    return np.frombuffer(raw, dtype="<i2").reshape(-1, channels).astype(float) / 32768, rate


def cut(audio, rate, wav_t0_ms, start_ms, end_ms):
    a = math.floor((start_ms - wav_t0_ms) * rate / 1000)
    b = math.ceil((end_ms - wav_t0_ms) * rate / 1000)
    return audio[max(0, min(len(audio), a)):max(0, min(len(audio), b))]


def rms_db(x):
    return float(10 * np.log10(max(float(np.mean(x * x)), 1e-20))) if len(x) else None


def low_band_ratio(x, rate):
    """Welch power, 40 ms Hann windows, 50% overlap; numerator 50..<300 Hz."""
    n = min(len(x), max(8, round(rate * 0.04)))
    if n < 8:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::max(1, n // 2)]
    power = np.mean(abs(np.fft.rfft(frames * np.hanning(n), axis=1)) ** 2, axis=0)
    hz = np.fft.rfftfreq(n, 1 / rate)
    band = (hz >= 50) & (hz <= 8000)
    total = power[band].sum()
    return float(power[band & (hz < 300)].sum() / total) if total > 1e-20 else None


def envelope_times(x, rate):
    """5 ms RMS envelope; missing crossings are censored, represented by null."""
    hop = max(1, round(rate * 0.005))
    n = len(x) // hop
    if n < 2:
        return None, None
    env = np.sqrt(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1))
    peak = int(np.argmax(env))
    if env[peak] <= 1e-10:
        return None, None
    scaled = env / env[peak]
    # Last 10% crossing before the first 90% crossing on the approach to the peak.
    high = np.flatnonzero(scaled[:peak + 1] >= 0.9)
    low = np.flatnonzero(scaled[:high[0] + 1] <= 0.1)
    onset = (int(high[0]) - int(low[-1])) * hop * 1000 / rate if len(low) else None
    tail = np.flatnonzero(scaled[peak + 1:] <= 0.1)
    decay = (int(tail[0]) + 1) * hop * 1000 / rate if len(tail) else None
    return onset, decay


def features(audio, rate, start, event):
    a, b = event["t_start_ms"], event["t_end_ms"]
    if b < a:
        raise ValueError("event ends before it starts")
    t0 = start["wav_t0_ms"]
    clip = cut(audio, rate, t0, a - 50, b + 50)
    history = cut(audio, rate, t0, a - 2000, a)[:, 0]
    frame = max(1, round(rate * 0.02))
    count = len(history) // frame
    floor = None
    if count:
        powers = np.mean(history[:count * frame].reshape(count, frame) ** 2, axis=1)
        floor = float(20 * np.log10(max(float(np.percentile(np.sqrt(powers), 10)), 1e-10)))
    gate = event.get("gate") or {}
    # The event's own RMS from the WAV, on the floor's scale (gate.level_db is the extractor's 16 kHz, high-passed
    # level: a different reference; it stays in the gate_level_db column).
    level = rms_db(cut(audio, rate, t0, a, b)[:, 0])
    onset, decay = envelope_times(clip[:, 0], rate)
    tmpl = event.get("tmpl") or {}
    distance, threshold = tmpl.get("distance"), tmpl.get("threshold")
    ild = None
    if len(clip) and audio.shape[1] == 2:
        ild = rms_db(clip[:, 0]) - rms_db(clip[:, 1])
    result = dict(low_band_ratio=low_band_ratio(clip[:, 0], rate),
                  level_above_floor_db=level - floor if level is not None and floor is not None else None,
                  onset_ms=onset, decay_ms=decay, ild_db=ild,
                  tmpl_distance=distance,
                  tmpl_ratio=distance / threshold if distance is not None and threshold and threshold > 0 else None,
                  floor_10_db=floor, history_ms=len(history) * 1000 / rate,
                  clip_truncated=a - 50 < t0 or b + 50 > t0 + len(audio) * 1000 / rate,
                  tmpl_nearest=tmpl.get("nearest"), tmpl_kind=tmpl.get("kind"),
                  gate_json=json.dumps(gate, sort_keys=True))
    result.update({f"gate_{key}": value if not isinstance(value, (dict, list)) else json.dumps(value)
                   for key, value in gate.items()})
    return result


def prompt_for(t, prompts, before=-100, after=1500):
    hits = [p for p in prompts if p["t_ms"] + before <= t <= p["t_ms"] + after]
    return min(hits, key=lambda p: abs(t - p["t_ms"])) if hits else None


def label(phase, t, prompts, before=-100, after=1500):
    if phase.startswith("1-"):
        return "media", None
    prompt = prompt_for(t, prompts, before, after)
    if phase.startswith("2-"):
        return "user", prompt
    if phase.startswith("3-"):
        return ("user", prompt) if prompt else ("media", None)
    raise ValueError(f"unknown measurement phase: {phase}")


def would_act(event):
    """Would this sound act if the media lock were off? The lock never marks mic_sound (it logs media_gate later),
    so: not dropped (level gate, touch, joystick, calibrating, a merged duplicate) and not gated (the media gate and
    media-hiss rule turn it into `unknown`). dry_run is a test switch applied after every guard, so it still counts."""
    return event.get("dropped") in (None, "dry_run") and not event.get("gated")


def volume(phase):
    if phase.startswith("2-"):
        return "clean"
    match = re.search(r"(?:^|-)(30|60|90)(?:-|$)", phase)
    if not match:
        raise ValueError(f"phase needs a volume: {phase}")
    return match[1] + ("-noisy" if "noisy" in phase else "")


def window_ms(prompts, lo, hi, before, after):
    end, total = lo, 0.0
    for p in sorted(prompts, key=lambda p: p["t_ms"]):
        a, b = max(lo, p["t_ms"] + before), min(hi, p["t_ms"] + after)
        total += max(0, b - max(end, a))
        end = max(end, b)
    return total


def load(directory, before=-100, after=1500):
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines() if line.strip()]
    for e in events:
        if e.get("sid") is not None:
            e["sid"] = str(e["sid"])   # the app's sids are ints
    starts = {e["sid"]: e for e in events if e.get("ev") == "measure_start"}
    stops = {e["sid"]: e for e in events if e.get("ev") == "measure_stop"}
    if not starts:
        raise ValueError("no measurement sessions")
    rows, groups = [], {}
    for sid, start in starts.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
            raise ValueError("unsafe session id")
        if start.get("wav_t0_ms") is None:
            raise ValueError(f"{sid}: no wav_t0_ms (recorded with record=false?)")
        audio, rate = read_wav(directory / sid / "audio.wav")
        if rate != start["rate"] or audio.shape[1] != start["channels"]:
            raise ValueError(f"{sid}: WAV does not match start event")
        if sid not in stops or stops[sid]["samples"] != len(audio):
            raise ValueError(f"{sid}: missing stop or sample count mismatch")
        phase = start["phase"]
        group = volume(phase)
        meta = groups.setdefault(group, dict(media_minutes=0, prompts=set()))
        session = [e for e in events if e.get("sid") == sid]
        prompts = [e for e in session if e.get("ev") == "measure_prompt"]
        lo, hi = start["wav_t0_ms"], start["wav_t0_ms"] + len(audio) * 1000 / rate
        if phase.startswith(("2-", "3-")):
            # A prompt whose reaction window runs past the recording's end could not be answered: not a miss.
            meta["prompts"].update((sid, p["n"]) for p in prompts if p["t_ms"] + after <= hi)
        if phase.startswith(("1-", "3-")):
            excluded = window_ms(prompts, lo, hi, before, after) if phase.startswith("3-") else 0
            meta["media_minutes"] += max(0, hi - lo - excluded) / 60000
        for event in session:
            if event.get("ev") != "mic_sound":
                continue
            kind, prompt = label(phase, event["t_start_ms"], prompts, before, after)
            rows.append(dict(sid=sid, phase=phase, volume=group, label=kind,
                             t_start_ms=event["t_start_ms"], t_end_ms=event["t_end_ms"],
                             prompt_n=prompt["n"] if prompt else None,
                             prompt_gesture=prompt["gesture"] if prompt else None,
                             would_act=would_act(event), dropped=event.get("dropped"), gated=event.get("gated"),
                             **features(audio, rate, start, event)))
    return rows, groups


def candidates(rows, steps):
    for feature in FEATURES:
        values = [r[feature] for r in rows if r[feature] is not None and np.isfinite(r[feature])]
        if not values:
            continue
        thresholds = np.unique(np.quantile(values, np.linspace(0, 1, steps)))
        thresholds = np.unique(np.r_[np.nextafter(thresholds[0], -np.inf), thresholds,
                                     np.nextafter(thresholds[-1], np.inf)])
        for threshold in thresholds:
            for direction in (">=", "<="):
                yield feature, direction, float(threshold)


def rule_mask(rows, rule):
    feature, direction, threshold = rule
    return np.array([r["would_act"] and r[feature] is not None and np.isfinite(r[feature]) and
                     (r[feature] >= threshold if direction == ">=" else r[feature] <= threshold)
                     for r in rows], dtype=bool)


def score(rows, meta, mask):
    negatives = sum(bool(keep) and r["label"] == "media" for r, keep in zip(rows, mask))
    kept = {(r["sid"], r["prompt_n"]) for r, keep in zip(rows, mask)
            if keep and r["label"] == "user" and r["prompt_n"] is not None}
    rate = negatives / meta["media_minutes"] if meta["media_minutes"] else None
    recall = 100 * len(kept & meta["prompts"]) / len(meta["prompts"]) if meta["prompts"] else None
    return rate, recall


def verdict(rate, recall):
    return "GO" if rate is not None and recall is not None and rate <= 1 and recall >= 90 else "NO-GO"


def rule_text(rule):
    return f"{rule[0]} {rule[1]} {rule[2]!r}"


def report(rows, groups, steps=21):
    print("Exploratory sweep on these recordings (not held-out validation). Missing features reject events.")
    print("Kept = unique prompts with at least one surviving event / all prompts; missed prompts count as misses.")
    print("Clean positives are separate; GO requires both media exposure and prompted positives at that volume.")
    print("Media minutes exclude phase-3 prompt windows. Would-act: not dropped (dry_run aside) and not gated; the media lock is ignored.")
    print("\n| Volume | Rule | Media/min | Prompts kept % | Result |")
    print("|---|---|---:|---:|---|")
    def emit(group, name, result):
        rate, recall = result
        print(f"| {group} | {name} | {rate if rate is None else f'{rate:.3f}'} | "
              f"{recall if recall is None else f'{recall:.2f}'} | {verdict(rate, recall)} |")
    for group, meta in sorted(groups.items()):
        subset = [r for r in rows if r["volume"] == group]
        emit(group, "level gate only", score(subset, meta, [r["would_act"] for r in subset]))
        rules = list(candidates(subset, steps))
        masks = [rule_mask(subset, rule) for rule in rules]
        for feature in FEATURES:
            if not any(rule[0] == feature for rule in rules):
                emit(group, feature + " unavailable", (None, None))
        for rule, mask in zip(rules, masks):
            emit(group, rule_text(rule), score(subset, meta, mask))
        best = None
        for i, j in itertools.combinations(range(len(rules)), 2):
            if rules[i][0] == rules[j][0]:
                continue
            result = score(subset, meta, masks[i] & masks[j])
            rate, recall = result
            # Prefer meeting both targets, then recall at <=1/min; otherwise minimum rate.
            feasible = rate is not None and rate <= 1
            kept = recall if recall is not None else -1
            false_rate = -rate if rate is not None else -math.inf
            key = (verdict(rate, recall) == "GO", feasible,
                   kept if feasible else false_rate, false_rate if feasible else kept)
            if best is None or key > best[0]:
                best = key, i, j, result
        if best:
            _, i, j, result = best
            emit(group, "best AND: " + rule_text(rules[i]) + " AND " + rule_text(rules[j]), result)
        else:
            emit(group, "best AND unavailable (fewer than two measured features)", (None, None))


def analyze(directory, before=-100, after=1500, steps=21):
    if before > after or steps < 2:
        raise ValueError("require window-start-ms <= window-end-ms and sweep-steps >= 2")
    rows, groups = load(directory, before, after)
    fields = list(dict.fromkeys(["sid", "phase", "volume", "label", *FEATURES] +
                               [key for row in rows for key in row]))
    with (directory / "features.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Prompt window: [{before}, {after}] ms; {len(rows)} events. CSV: features.csv")
    report(rows, groups, steps)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", type=Path)
    ap.add_argument("--window-start-ms", type=float, default=-100)
    ap.add_argument("--window-end-ms", type=float, default=1500)
    ap.add_argument("--sweep-steps", type=int, default=21, help="quantile thresholds per feature, both directions")
    args = ap.parse_args()
    analyze(args.directory, args.window_start_ms, args.window_end_ms, args.sweep_steps)


if __name__ == "__main__":
    main()
