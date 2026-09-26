"""Sample-rate handling.

Decimator3: the reference 48 kHz -> 16 kHz path (the Pico's I2S mic will likely run at 48 kHz).
A fixed 63-tap linear-phase FIR low-pass (Kaiser, cutoff 7.2 kHz) evaluated only at every 3rd
input sample: 63 MACs per output sample, 62 samples of state. The taps are a pure function of
the constants below, and export_vectors.py writes them out for the C port.

to_16k(): offline conversion for WAV files at other rates (44.1 kHz etc.) via scipy's polyphase
resampler. That path is for convenience only and is NOT part of the portable reference.
"""

from __future__ import annotations

from functools import lru_cache
from math import gcd

import numpy as np

DECIM_TAPS = 63
DECIM_CUTOFF_HZ = 7200.0
DECIM_KAISER_BETA = 8.0


@lru_cache(maxsize=1)
def decim_taps() -> np.ndarray:
    from scipy.signal import firwin
    h = firwin(DECIM_TAPS, DECIM_CUTOFF_HZ, window=("kaiser", DECIM_KAISER_BETA), fs=48000.0)
    return h.astype(np.float32)


class Decimator3:
    """Streaming 48k -> 16k. push() any number of samples; returns the 16 kHz samples produced."""

    def __init__(self) -> None:
        self.h = decim_taps().astype(np.float64)
        self.hist = np.zeros(DECIM_TAPS - 1, dtype=np.float64)  # previous input samples
        self.phase = 0  # index (within the next block) of the next input sample that yields an output

    def push(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if x.size == 0:
            return np.zeros(0, dtype=np.float32)
        buf = np.concatenate([self.hist, x])
        # output at input index n (in x coordinates) uses buf[n : n + TAPS] reversed
        idx = np.arange(self.phase, x.size, 3)
        # same arithmetic as a per-sample loop: out[i] = sum_k buf[n+k] * h[TAPS-1-k]
        out = np.lib.stride_tricks.sliding_window_view(buf, DECIM_TAPS)[idx] @ self.h[::-1]
        self.hist = buf[-(DECIM_TAPS - 1):]
        self.phase = (self.phase - x.size) % 3
        return np.asarray(out, dtype=np.float32)


def to_mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x if x.ndim == 1 else x.mean(axis=1).astype(np.float32)


def to_16k(x: np.ndarray, sr: int) -> np.ndarray:
    """Mono float32 at any rate -> 16 kHz. 48 kHz goes through the reference Decimator3."""
    x = to_mono(x)
    if sr == 16000:
        return x
    if sr == 48000:
        return Decimator3().push(x)
    from scipy.signal import resample_poly
    g = gcd(int(sr), 16000)
    return resample_poly(x, 16000 // g, int(sr) // g).astype(np.float32)
