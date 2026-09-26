"""The streaming extractor: samples in, events out.

    ex = Extractor(Config(), input_rate=48000)
    for chunk in audio:                 # any chunk size
        for event in ex.push(chunk):
            print(event.label, event.text)
    tail = ex.flush()

Events are returned when a sound ENDS (after the hangover), so latency after the end of a sound
is hangover_frames * 10 ms + the 16 ms half-window.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .classify import Event, classify
from .config import Config
from .fingerprint import CONTOUR_LABELS, FP_VERSION, fingerprint
from .frontend import Frame, FrameProcessor
from .resample import Decimator3, to_16k
from .segmenter import Segmenter


class Extractor:
    def __init__(self, cfg: Config | None = None, input_rate: int = 16000, keep_frames: bool = False,
                 keep_dropped: bool = False) -> None:
        self.cfg = cfg or Config()
        if input_rate not in (16000, 48000):
            raise ValueError("streaming input must be 16 kHz or 48 kHz (use resample.to_16k for files)")
        self.decim = Decimator3() if input_rate == 48000 else None
        self.fp = FrameProcessor(self.cfg)
        self.seg = Segmenter(self.cfg)
        self.keep_frames = keep_frames
        self.keep_dropped = keep_dropped
        self.frames: list[Frame] = []
        self.floors: list[float] = []
        self.last_end_ms: float | None = None   # context for the next sound (speech trains)
        self.last_talky = False

    def push(self, samples: np.ndarray) -> list[Event]:
        x = np.asarray(samples, dtype=np.float32)
        if self.decim is not None:
            x = self.decim.push(x)
        out: list[Event] = []
        for f in self.fp.push_iter(x):   # frame by frame: the floor update below reaches the next frame's flux
            if self.keep_frames:
                self.frames.append(f)
                self.floors.append(self.seg.floor_db)
            s = self.seg.push(f)
            self.fp.floor_db = self.seg.floor_db
            if s is not None:
                self._emit(s, out)
        return out

    def flush(self) -> list[Event]:
        out: list[Event] = []
        s = self.seg.flush()
        if s is not None:
            self._emit(s, out)
        return out

    def _emit(self, s, out: list[Event]) -> None:
        if s.n < self.cfg.min_segment_frames:
            return
        ctx = {}
        if self.last_end_ms is not None:
            ctx = {"gap_ms": s.t_start_ms - self.last_end_ms, "prev_talky": self.last_talky}
        ev = classify(s, self.cfg, ctx)
        ev.raw["fp_version"] = FP_VERSION
        ev.raw["fp"] = fingerprint(s, ev.raw)
        if ev.label not in CONTOUR_LABELS:
            ev.raw["pitch16"] = []
        else:
            ev.raw.setdefault("pitch16", [])
        if ev.emit:
            self.last_end_ms = ev.t_end_ms
            self.last_talky = ev.sounds_like in ("talking", "laughing") or (
                ev.raw.get("voiced_frac", 0) >= 0.3 and ev.raw.get("dur_ms", 0) <= self.cfg.train_max_ms
                and ev.label not in ("pop", "click", "hiss") and ev.raw.get("excursion_st", 0) < self.cfg.exc_large_st)
        if ev.emit or self.keep_dropped:
            out.append(ev)

    @property
    def floor_db(self) -> float:
        return self.seg.floor_db


def extract_array(x: np.ndarray, sr: int, cfg: Config | None = None, chunk: int = 1600,
                  keep_dropped: bool = False) -> list[Event]:
    """Run the streaming extractor over an in-memory signal, in chunks (to exercise streaming)."""
    if sr not in (16000, 48000):
        x, sr = to_16k(x, sr), 16000
    ex = Extractor(cfg, input_rate=sr, keep_dropped=keep_dropped)
    events: list[Event] = []
    for i in range(0, len(x), chunk):
        events += ex.push(x[i:i + chunk])
    return events + ex.flush()


def load_wav(path: str | Path) -> tuple[np.ndarray, int]:
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1).astype(np.float32)
    return x, int(sr)


def extract_file(path: str | Path, cfg: Config | None = None) -> list[Event]:
    x, sr = load_wav(path)
    return extract_array(x, sr, cfg)
