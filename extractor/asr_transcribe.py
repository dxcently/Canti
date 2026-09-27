#!/usr/bin/env python3
"""Local word-timestamped transcription of guided-session takes (faster-whisper on the CPU).

Runs ONLY in the separate ASR venv (.venv-asr: faster-whisper + CTranslate2, no torch), never in .venv:
  ./run .venv-asr/bin/python asr_transcribe.py --out recordings/<session>/asr/<model>.jsonl takes/phrases/*.wav
Normally it is called by segment_takes.py, not by hand.

PRIVATE: the audio and the transcripts stay on this machine (recordings/ is gitignored). Nothing here talks to a
network service except the one-time model weight download from Hugging Face (weights in, never audio out).

Output: one JSON line per file, {"file", "model", "asr_prompt", "dur_s", "words": [{"w", "s", "e", "p"}], "text",
"secs"}; files already in --out (same model + prompt) are skipped, so a rerun only does new takes.
--pieces LIST.json: transcribe slices instead, [{"id", "file", "start_ms", "end_ms"}] (file relative to --root);
output rows carry "id", "start_ms", "end_ms" too, word times relative to the slice start.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# The initial prompt only nudges Whisper to KEEP disfluencies (it drops "um"/"uh" and restarts by default) and spells
# the names. It holds no command words and never a take's own prompt text: on noise Whisper can echo its prompt
# (seen on the synthetic session), so a prompt with commands in it would invent tries.
PROMPTS = {
    "neutral": "Um, uh, hmm, so, like, okay. I- I mean, wait... Canti, Instagram, TikTok, WhatsApp, YouTube, Discord, "
               "Pinterest, LinkedIn, Telegram, Chrome.",
    "none": None,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--pieces", help="JSON list of slices to transcribe instead of whole files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="medium.en")
    ap.add_argument("--root", default=".", help="file names in the output are relative to this folder")
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--prompt", default="neutral", choices=sorted(PROMPTS), help="Whisper initial prompt style")
    a = ap.parse_args()
    from faster_whisper import WhisperModel, decode_audio

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    root = Path(a.root).resolve()
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("model") == a.model and r.get("asr_prompt") == a.prompt:
                    done.add((r.get("id"), r["file"], r.get("start_ms"), r.get("end_ms")))
    if a.pieces:
        items = [(x["id"], x["file"], x["start_ms"], x["end_ms"]) for x in json.loads(Path(a.pieces).read_text())]
    else:
        items = [(None, str(Path(f).resolve().relative_to(root)), None, None) for f in a.files]
    todo = [x for x in items if x not in done]
    if not todo:
        print(f"asr: all {len(items)} {'pieces' if a.pieces else 'files'} already transcribed with {a.model} / "
              f"prompt {a.prompt}", flush=True)
        return
    t0 = time.monotonic()
    model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=a.threads)
    print(f"asr: {a.model} loaded in {time.monotonic() - t0:.1f} s; {len(todo)} {'pieces' if a.pieces else 'files'}",
          flush=True)
    cache: dict[str, object] = {}
    t_all = time.monotonic()
    with out.open("a") as fo:
        for i, (pid, fname, s_ms, e_ms) in enumerate(todo):
            t1 = time.monotonic()
            if fname not in cache:
                cache = {fname: decode_audio(str(root / fname), sampling_rate=16000)}
            audio = cache[fname]
            if s_ms is not None:
                audio = audio[int(s_ms * 16): int(e_ms * 16)]
            segs, _info = model.transcribe(audio, language="en", beam_size=a.beam, word_timestamps=True,
                                           vad_filter=False, condition_on_previous_text=False,
                                           initial_prompt=PROMPTS[a.prompt], temperature=0.0)
            words = []
            for s in segs:
                for w in s.words or []:
                    words.append({"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3),
                                  "p": round(w.probability, 3)})
            row = {**({"id": pid, "start_ms": s_ms, "end_ms": e_ms} if a.pieces else {}), "file": fname,
                   "model": a.model, "asr_prompt": a.prompt, "dur_s": round(len(audio) / 16000, 3), "words": words,
                   "text": " ".join(w["w"] for w in words), "secs": round(time.monotonic() - t1, 2)}
            fo.write(json.dumps(row) + "\n")
            fo.flush()
            print(f"asr: {i + 1}/{len(todo)} {pid or fname}  {row['secs']:.1f} s", flush=True)
    print(f"asr: {len(todo)} {'pieces' if a.pieces else 'files'} in {time.monotonic() - t_all:.1f} s", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
