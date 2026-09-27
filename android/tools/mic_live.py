"""Measure the LIVE phone-mic source on a device: per-hop time, CPU, level/floor, and sound latency.

Switches the sound source (op `config`), lets it listen for --seconds, and reads `mic_status` every 2 s:
- hop_us p50/p90/p99/max, push_us: the extractor's own timing on the audio thread (native, since the capture opened);
- thread_cpu_pct: the audio thread's CPU time / wall time; process CPU from `top` (the whole app, one sample per poll);
- level (dBFS rms/peak of the last second), floor_db, gate_open, silent_input, the routed input and the clock;
- latency_ms: end of each sound -> handed to the service (includes the extractor's 100 ms hangover by design).
- every phone-mic sound (`mic_sound` from logcat): per-label counts, touch drops, and would-act per minute as the
  app counts it (extractor/vox_extract/sequencer_sim.py: the Sequencer's act-at-once rule, the app's bindings,
  RuleDecider's not-deliberate gate, MicPopGate's lone pop), split by whether media was playing: the false-trigger
  rate for the echo A/B. (Before 2026-09-27 this used policy.group, which undercounts the app ~10x on hiss-heavy
  input; that number is still reported as `would_act_policy_group` for comparison with older runs.)
- the gate numbers of each label (centroid_hz, peak_centroid_hz, hf_ratio, lf_ratio, zcr, snr_db: p10 / p50 / p90)
  and the 8-band input level (mic_status `bands`, dBFS per 1 kHz band, mean over the polls), media vs quiet: is a
  6-8 kHz band acoustic (it scales with the volume and is gone when muted) or a device artefact?
Finally the previous `sound_source`/`mic_*` settings are restored (unless --keep).

    VOX_SERIAL=R5CX62H7PNJ ./dev python3 tools/mic_live.py --source phone --seconds 60 --rate 16000 --preset auto

Echo A/B (a video playing on the phone's speaker, nothing acted on: --dry-run):
    VOX_SERIAL=R5CX62H7PNJ ./dev /home/khoa/VOX/extractor/run python /home/khoa/VOX/android/tools/mic_live.py \
        --dry-run --seconds 180 --preset voice_communication --effects platform --json /tmp/ab_vc.json
(--media-gate off for the raw extractor's false triggers; the default `speaker` is what ships.)

Needs RECORD_AUDIO granted (by the user) and, on Android 14, a visible Canti screen when the mic's foreground service
first starts (the status says "open Canti to start the mic"; --open starts MainActivity for that). Nothing is
recorded: only the numbers above leave the phone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "suite"))
from voxlib import SERIAL, EventStream, Vox, sh  # noqa: E402

KEYS = ("sound_source", "mic_rate", "mic_preset", "mic_read_ms", "mic_while_disarmed", "mic_effects", "mic_dry_run",
        "mic_touch_guard", "mic_media_gate", "hiss_media_max_centroid_hz")
GATE_NUMS = ("centroid_hz", "peak_centroid_hz", "hf_ratio", "lf_ratio", "zcr", "snr_db")


def app_cpu() -> float | None:
    pid = sh("pidof ai.vox.companion", check=False).strip().split()
    if not pid:
        return None
    out = sh(f"top -b -n 1 -p {pid[0]} -o %CPU", check=False)
    nums = [float(x) for x in re.findall(r"^\s*([\d.]+)\s*$", out, re.M)]
    return nums[-1] if nums else None


def _pct(xs: list[float]) -> list[float] | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return [round(xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))], 3) for p in (0.1, 0.5, 0.9)]


def gate_numbers(part: list[dict]) -> dict:
    """Per label: n and p10 / p50 / p90 of the extractor's gate numbers (mic_sound.gate)."""
    out = {}
    for lab in sorted({s["label"] for s in part}):
        L = [s for s in part if s["label"] == lab]
        out[lab] = {"n": len(L), **{k: _pct([(s.get("gate") or {}).get(k) for s in L]) for k in GATE_NUMS}}
    return out


def band_levels(polls: list[dict]) -> dict:
    """Mean of the once-a-second 8-band levels (mic_status `bands`), split by media playing at the poll."""
    out = {}
    for media in (True, False):
        rows = [p["status"]["bands"]["dbfs"] for p in polls
                if (p["status"].get("bands") or {}).get("dbfs") and bool((p["status"].get("media_gate") or {}).get("media_playing")) == media]
        if rows:
            out["media" if media else "quiet"] = {"polls": len(rows),
                                                  "dbfs": [round(sum(r[i] for r in rows) / len(rows), 1) for i in range(len(rows[0]))]}
    return out


def sound_stats(sounds: list[dict], seconds: float) -> dict:
    """Per-label counts and would-act per minute as the app counts it, split by media playing or not."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "extractor"))
        from vox_extract.policy import action_for, group
        from vox_extract.sequencer_sim import would_act
    except Exception as e:  # noqa: BLE001  (run through extractor/run for the policy mirror)
        return {"error": f"policy mirror unavailable ({e}); run with extractor/run python"}
    kept = [s for s in sounds if s.get("dropped") in (None, "dry_run")]
    labels: dict[str, int] = {}
    for s in kept:
        labels[s["label"]] = labels.get(s["label"], 0) + 1
    out = {"sounds": len(sounds), "touch_dropped": sum(1 for s in sounds if s.get("dropped") == "touch"),
           "media_gated": sum(1 for s in kept if s.get("gated")),
           "hiss_gated": sum(1 for s in kept if str(s.get("gated") or "").startswith("hiss centroid")),
           "labels": labels, "minutes": round(seconds / 60, 2)}
    for media in (True, False):
        part = [s for s in kept if bool(s.get("media")) == media]
        # a gated sound reaches the service as "unknown" (not deliberate): sequencer_sim reads the `gated` field
        app = would_act(part, seconds / 60)
        raw = would_act([{k: v for k, v in e.items() if k != "gated"} for e in part], seconds / 60)   # without PhoneGate
        pg = [action_for([("unknown" if e.get("gated") else e["label"], e.get("text", "")) for e in g]) for g in group(part)]
        out["media" if media else "quiet"] = {"sounds": len(part), "groups": app["groups"], "would_act": app["would_act"],
                                              "would_act_ungated": raw["would_act"], "actions": app["actions"],
                                              "would_act_policy_group": sum(1 for x in pg if x != "none"),
                                              "why": _whys(part), "gate_numbers": gate_numbers(part)}
    out["would_act_per_min"] = round((out["media"]["would_act"] + out["quiet"]["would_act"]) / max(seconds / 60, 1e-9), 2)
    return out


def _whys(part: list[dict]) -> dict:
    c: dict[str, int] = {}
    for s in part:
        w = (s.get("gate") or {}).get("why", "?")
        c[w] = c.get(w, 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1])[:8])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="phone", choices=["phone", "usb"])
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--rate", type=int, default=16000, choices=[16000, 48000])
    ap.add_argument("--preset", default="auto", choices=["auto", "unprocessed", "voice_recognition", "voice_communication", "mic"])
    ap.add_argument("--effects", default="off", choices=["off", "platform", "aec", "aec_ns"])
    ap.add_argument("--dry-run", action="store_true", help="log the sounds, act on none (for media / noise runs)")
    ap.add_argument("--no-touch-guard", action="store_true")
    ap.add_argument("--media-gate", default="speaker", choices=["speaker", "media", "always", "off"])
    ap.add_argument("--hiss-max-centroid", type=int, default=6500,
                    help="hiss_media_max_centroid_hz: media-on-speaker hiss over this centroid -> unknown (0 = off)")
    ap.add_argument("--read-ms", type=int, default=20)
    ap.add_argument("--open", action="store_true", help="start Canti's status screen if the service needs a visible screen")
    ap.add_argument("--keep", action="store_true", help="leave the source switched on afterwards")
    ap.add_argument("--json", help="write every poll here")
    a = ap.parse_args()

    vox = Vox()
    before = vox.control("ping")["settings"]
    prev = {k: before.get(k) for k in KEYS}
    log = EventStream()
    vox.control("config", sound_source=a.source, mic_rate=a.rate, mic_preset=a.preset, mic_read_ms=a.read_ms,
                mic_effects=a.effects, mic_dry_run=a.dry_run, mic_touch_guard=not a.no_touch_guard,
                mic_media_gate=a.media_gate, hiss_media_max_centroid_hz=a.hiss_max_centroid)
    polls, cpus = [], []
    t0 = time.time()
    opened = False
    try:
        while time.time() - t0 < a.seconds:
            time.sleep(2)
            m = vox.control("mic_status")["mic"]
            if m["state"] == "open Canti to start the mic" and a.open and not opened:
                sh("am start --user 0 -n ai.vox.companion/.MainActivity", check=False); opened = True
            c = app_cpu()
            if c is not None and m.get("capturing"):
                cpus.append(c)
            polls.append({"t": round(time.time() - t0, 1), "status": m, "app_cpu_pct": c})
            st = m.get("stats") or {}
            hop = st.get("hop_us") or {}
            lvl = st.get("level") or {}
            bands = (m.get("bands") or {}).get("dbfs")
            print(f"{time.time() - t0:5.0f}s {m['state']:28s} hop p50 {hop.get('p50', '-')} p99 {hop.get('p99', '-')} us  "
                  f"thread {st.get('thread_cpu_pct', '-')}%  app {c}%  level {lvl.get('rms_dbfs', '-')} dBFS  "
                  f"floor {st.get('floor_db', '-')}  sounds {m.get('sounds')}  lat {m.get('latency_ms')}"
                  + (f"  bands {' '.join(f'{b:.0f}' for b in bands)}" if bands else ""), flush=True)
    finally:
        if not a.keep:
            vox.control("config", **{k: v for k, v in prev.items() if v is not None})
        log.close()
    last = polls[-1]["status"] if polls else {}
    sounds = [e for e in log.since(0) if e.get("ev") == "mic_sound" and e.get("source", "phone-mic") == "phone-mic"]
    capture = [e for e in log.since(0) if e.get("ev") == "mic_capture"]
    st = last.get("stats") or {}
    summary = {"serial": SERIAL, "source": a.source, "rate": a.rate, "preset": a.preset, "read_ms": a.read_ms,
               "state": last.get("state"), "routed": last.get("routed"), "capture": last.get("capture"),
               "unprocessed_supported": last.get("unprocessed_supported"),
               "hop_us": st.get("hop_us"), "push_us": st.get("push_us"), "thread_cpu_pct": st.get("thread_cpu_pct"),
               "app_cpu_pct_mean": round(sum(cpus) / len(cpus), 1) if cpus else None, "app_cpu_samples": len(cpus),
               "floor_db": st.get("floor_db"), "silent_input": st.get("silent_input"), "clock": st.get("clock"),
               "sounds": last.get("sounds"), "latency_ms": last.get("latency_ms"),
               "effects": a.effects, "dry_run": a.dry_run, "touch_guard": last.get("touch_guard"),
               "media_gate": last.get("media_gate"),
               "env": [c.get("info", {}).get(k) for c in capture for k in ("env_before", "env_after") if c.get("info", {}).get(k)],
               "hiss_media_max_centroid_hz": a.hiss_max_centroid,
               "bands_dbfs": band_levels(polls),
               "sound_stats": sound_stats(sounds, a.seconds)}
    print(json.dumps(summary, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summary, "polls": polls}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
