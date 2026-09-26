"""Per-hop feature extraction at 16 kHz.

Every 160 samples (10 ms) the processor looks at the latest 512-sample window and produces one
Frame. All features of a frame describe the same instant: the centre of the window. Energy and
zero crossings use the central part of the window, the spectral features and pitch the whole
window. That puts a frame's "hop span" (for timing) at

    samples [ (j+1)*hop - win/2 - hop/2 , (j+1)*hop - win/2 + hop/2 )  ->  t_ms = 10*j - 11

State (what a C port must keep): input high-pass biquad (2 floats), the 512-sample window, a partial hop,
the previous frame's log spectrum (for flux, 257 floats), and a frame counter.

Pitch: MPM (McLeod & Wyvill 2005), NSDF computed through an FFT autocorrelation of the
un-windowed frame (zero-padded to acf_fft). Clarity = NSDF height at the chosen peak.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Config


@dataclass
class Frame:
    index: int
    t_ms: float        # start of this frame's hop span; may be negative for the first two frames
    e_db: float        # mean-square energy of the central hop, dBFS (full-scale square wave = 0 dB)
    zcr: float         # zero crossings per sample over the central 2 hops
    centroid: float    # Hz, over spec_lo..spec_hi
    flatness: float    # geometric / arithmetic mean of the band power spectrum, 0..1
    flux: float        # mean positive log-spectral change vs the previous frame, dB
    lf_ratio: float    # share of band energy below lf_split_hz
    hf_ratio: float    # share of band energy above hf_split_hz
    f0: float          # Hz; 0 when MPM found no peak
    clarity: float     # NSDF peak height (MPM clarity), 0..1
    # fingerprint sums (fp1), from the same 512-point power spectrum; not part of as_list() / the C vectors yet
    mel8: tuple = ()   # power in 8 triangular mel bands, 60-7600 Hz
    p_band: float = 0.0   # power in spec_lo..spec_hi (the centroid band)
    p_1k6: float = 0.0    # ... of which 1-6 kHz
    p_voiced: float = 0.0  # band power if the frame is pitched (f0 > 0, clarity >= voiced_clarity), else 0
    p_hi35: float = 0.0    # ... of which above 3.5 x this frame's f0

    def as_list(self) -> list[float]:
        return [self.index, self.t_ms, self.e_db, self.zcr, self.centroid, self.flatness, self.flux,
                self.lf_ratio, self.hf_ratio, self.f0, self.clarity]


FRAME_FIELDS = ["index", "t_ms", "e_db", "zcr", "centroid", "flatness", "flux", "lf_ratio", "hf_ratio", "f0", "clarity"]


def mel_filterbank(n_mels: int, nfft: int, sr: int, lo: float, hi: float) -> np.ndarray:
    """Triangular mel filters (HTK mel scale) on the rfft bins, peak 1. Shape (n_mels, nfft // 2 + 1)."""
    def mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def imel(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)
    pts = imel(np.linspace(mel(lo), mel(hi), n_mels + 2))
    f = np.arange(nfft // 2 + 1) * sr / nfft
    fb = np.zeros((n_mels, f.size))
    for i in range(n_mels):
        a, c, b = pts[i], pts[i + 1], pts[i + 2]
        fb[i] = np.clip(np.minimum((f - a) / (c - a), (b - f) / (b - c)), 0.0, None)
    return fb


def mpm_pitch(x: np.ndarray, sr: int, f0_min: float, f0_max: float, k: float, nfft: int) -> tuple[float, float]:
    """McLeod Pitch Method on one frame. Returns (f0_hz, clarity); (0, 0) if no key maximum."""
    n = x.size
    tau_min = max(2, int(np.floor(sr / f0_max)))
    tau_max = min(n - 2, int(np.ceil(sr / f0_min)))
    spec = np.fft.rfft(x, nfft)
    r = np.fft.irfft(spec.real * spec.real + spec.imag * spec.imag, nfft)[: tau_max + 2]
    # m'(tau) = sum_{j=0}^{n-1-tau} (x_j^2 + x_{j+tau}^2). A C port uses the O(1) recursion
    # m'(tau) = m'(tau-1) - x[tau-1]^2 - x[n-tau]^2 with m'(0) = 2*sum(x^2); this is the same sum.
    x2 = x * x
    c = np.cumsum(x2)
    taus = np.arange(tau_max + 2)
    head = c[n - 1 - taus]
    tail = c[n - 1] - np.concatenate(([0.0], c[taus[1:] - 1]))
    m = head + tail
    if m[0] <= 1e-20:
        return 0.0, 0.0
    nsdf = 2.0 * r / np.maximum(m, 1e-20)

    # key maxima: the highest point of each positive lobe after the first negative-going zero crossing
    peaks: list[int] = []
    t = 1
    while t <= tau_max and nsdf[t] > 0:  # leave the lobe around tau = 0
        t += 1
    best = -1
    while t <= tau_max:
        if nsdf[t] > 0:
            if best < 0 or nsdf[t] > nsdf[best]:
                best = t
        elif best >= 0:  # lobe ended
            peaks.append(best)
            best = -1
        t += 1
    if best >= 0 and best < tau_max:  # unfinished last lobe: keep only an interior maximum
        peaks.append(best)
    peaks = [p for p in peaks if tau_min <= p <= tau_max]
    if not peaks:
        return 0.0, 0.0
    vals = [nsdf[p] for p in peaks]
    thr = k * max(vals)
    p = next(pp for pp, v in zip(peaks, vals) if v >= thr)
    a, b, cc = nsdf[p - 1], nsdf[p], nsdf[p + 1]
    den = a - 2.0 * b + cc
    delta = 0.5 * (a - cc) / den if abs(den) > 1e-12 else 0.0
    delta = float(np.clip(delta, -0.5, 0.5))
    tau = p + delta
    clarity = float(min(1.0, b - 0.25 * (a - cc) * delta))
    return float(sr / tau), clarity


class FrameProcessor:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        n = cfg.win
        self.buf = np.zeros(n, dtype=np.float64)
        self.pending = np.zeros(0, dtype=np.float64)
        from scipy.signal import butter
        self.hpf_b, self.hpf_a = butter(2, cfg.hpf_hz / (cfg.sample_rate / 2), btype="high")
        self.hpf_z = np.zeros(2)
        self.index = 0
        self.floor_db = cfg.floor_min_db  # updated by the segmenter each frame (for the flux floor)
        i = np.arange(n)
        self.window = 0.5 - 0.5 * np.cos(2.0 * np.pi * i / n)  # periodic Hann
        self.win_pow = float(np.sum(self.window ** 2))
        df = cfg.sample_rate / n
        self.k_lo = int(np.ceil(cfg.spec_lo_hz / df))
        self.k_hi = int(np.floor(cfg.spec_hi_hz / df))
        self.k_lf = int(np.floor(cfg.lf_split_hz / df))
        self.k_hf = int(np.ceil(cfg.hf_split_hz / df))
        self.freqs = np.arange(n // 2 + 1) * df
        self.prev_logp: np.ndarray | None = None
        self.k_1k = int(np.ceil(1000.0 / df))
        self.k_6k = int(np.floor(6000.0 / df))
        self.mel_fb = mel_filterbank(8, n, cfg.sample_rate, 60.0, 7600.0)

    def _highpass(self, x: np.ndarray) -> np.ndarray:
        # one biquad, transposed direct form II (the state carries across calls, so any chunking
        # gives the same output). Coefficients: scipy butter(2, hpf_hz), exported for the C port.
        from scipy.signal import lfilter
        y, self.hpf_z = lfilter(self.hpf_b, self.hpf_a, x, zi=self.hpf_z)
        return y

    def push(self, samples: np.ndarray) -> list[Frame]:
        """Feed 16 kHz mono float samples (any count). Returns the frames completed."""
        return list(self.push_iter(samples))

    def push_iter(self, samples: np.ndarray):
        """Like push(), but yields each frame before computing the next, so the caller can update
        floor_db in between (the flux floor then follows the noise floor frame by frame, exactly
        as a C loop would, whatever the chunk size). Consume it fully."""
        x = np.asarray(samples, dtype=np.float64)
        if x.size == 0:
            return
        x = self._highpass(x)
        data = np.concatenate([self.pending, x])
        self.pending = np.zeros(0)
        hop = self.cfg.hop
        pos = 0
        while data.size - pos >= hop:
            self.buf = np.concatenate([self.buf[hop:], data[pos:pos + hop]])
            pos += hop
            if data.size - pos < hop:
                self.pending = data[pos:].copy()
            yield self._frame()
        self.pending = data[pos:].copy()

    def _frame(self) -> Frame:
        cfg = self.cfg
        n, hop = cfg.win, cfg.hop
        x = self.buf
        c = n // 2
        central = x[c - hop // 2: c + hop // 2]
        e = float(np.mean(central * central))
        e_db = 10.0 * np.log10(e + 1e-12)
        z = x[c - hop: c + hop]
        zcr = float(np.count_nonzero(np.signbit(z[1:]) != np.signbit(z[:-1]))) / (z.size - 1)

        spec = np.fft.rfft(x * self.window)
        p = spec.real * spec.real + spec.imag * spec.imag
        band = p[self.k_lo:self.k_hi + 1]
        total = float(np.sum(band))
        if total > 1e-20:
            centroid = float(np.sum(self.freqs[self.k_lo:self.k_hi + 1] * band) / total)
            flatness = float(np.exp(np.mean(np.log(band + 1e-30))) / (total / band.size))
            lf = float(np.sum(p[self.k_lo:self.k_lf]) / total)
            hf = float(np.sum(p[self.k_hf:self.k_hi + 1]) / total)
        else:
            centroid = flatness = lf = hf = 0.0
        # flux floor: expected per-bin power of white noise at the tracked floor, +3 dB
        floor_p = 2.0 * (10.0 ** (max(self.floor_db, cfg.flux_floor_db) / 10.0)) * self.win_pow
        logp = 10.0 * np.log10(band + floor_p)
        flux = 0.0 if self.prev_logp is None else float(np.mean(np.maximum(0.0, logp - self.prev_logp)))
        self.prev_logp = logp

        f0, clarity = mpm_pitch(x, cfg.sample_rate, cfg.f0_min_hz, cfg.f0_max_hz, cfg.mpm_k, cfg.acf_fft)
        mel8 = tuple(float(v) for v in self.mel_fb @ p)
        p_1k6 = float(np.sum(p[self.k_1k:self.k_6k + 1]))
        p_voiced = p_hi35 = 0.0
        if f0 > 0 and clarity >= cfg.voiced_clarity:
            p_voiced = total
            k35 = max(self.k_lo, int(np.floor(3.5 * f0 / (cfg.sample_rate / n))) + 1)
            p_hi35 = float(np.sum(p[k35:self.k_hi + 1])) if k35 <= self.k_hi else 0.0
        j = self.index
        t_ms = ((j + 1) * hop - n / 2 - hop / 2) * 1000.0 / cfg.sample_rate
        self.index += 1
        return Frame(j, t_ms, e_db, zcr, centroid, flatness, flux, lf, hf, f0, clarity,
                     mel8, total, p_1k6, p_voiced, p_hi35)
