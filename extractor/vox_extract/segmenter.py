"""Noise floor tracking, the gate (hysteresis + hangover) and per-sound accumulation.

NoiseFloor: minimum statistics on block means. Frames are grouped into blocks of
floor_block_frames (0.4 s); each block contributes the MEAN of its hop energies (in dB); the floor
is the lowest block mean among the last floor_blocks blocks (3.2 s), clamped at floor_min_db.
Using block means rather than single-frame minima makes the floor the typical noise level (single
10 ms hops of pink / low-frequency noise dip far below it), so floor + a few dB is a usable close
threshold. It needs one sound-free block (0.4 s) in the last 3.2 s. State: a running block sum and
count and a ring of 8 block means.
A steady sound longer than ~3 s (a fan switching on, continuous music) becomes the new floor and
closes the gate; shorter sounds never move it.
Start-up (the first floor_startup_blocks blocks, 0.8 s): a sound already present when streaming
starts must not become the floor (live bug 105053: a loud transient during warm-up raised the floor
~20 dB, a whistle then stayed under the gate until its top, which came out as a 60 ms "pop"). So a
start-up block whose plain mean is more than floor_startup_trigger_db (10 dB) above its "background-like"
50 ms sub-blocks stores the mean and std of those sub-blocks instead (background-like = within
floor_startup_keep_db of the floor_startup_pct quantile of the sub-block means); before the first block
completes the same rule applies to the sub-blocks so far. The trigger is high on purpose: babble or
music background varies 3-6 dB between 50 ms sub-blocks, and a lower trigger took that variation for
a sound, set the floor several dB low and let the gate open on the background (synthetic cafe babble,
real-audio click trains). While a sound is open the floor may rise by at
most floor_rise_open_db_s dB per second (it can always fall).

Gate: opens when hop energy > floor + max(gate_open_db, gate_open_sigma * spread) for open_frames
frames, where spread is how much the background itself fluctuates (so a babbling cafe needs a
bigger jump than a steady fan). The sound is extended back over up to PREROLL earlier frames that
were above the close threshold (catches the attack). It stays open while frames exceed
floor + max(gate_close_db, gate_close_sigma * spread); hangover_frames frames below that close it.
t_end is the end of the last frame above the close threshold, so the hangover adds latency (the
event is emitted hangover_frames later) but not duration.

SegmentStats: what a C port keeps per sound. Three per-frame arrays (energy, f0, clarity; 400
frames -> 2.4 KB as int16) and running sums for the spectral features. classify.py sees only this.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import Config
from .frontend import Frame

PREROLL = 3


class NoiseFloor:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.block_sum = 0.0
        self.block_sq = 0.0
        self.block_n = 0
        self.means: list[float] = []  # ring of the last floor_blocks block means (dB)
        self.stds: list[float] = []   # ... and block standard deviations (dB)
        self.n = 0
        self.blocks = 0               # completed blocks so far
        # start-up blocks: 50 ms sub-blocks (sum, sum of squares, n) of the current block
        self.sub: list[tuple[float, float, int]] = []
        self.sub_sum = 0.0
        self.sub_sq = 0.0
        self.sub_n = 0

    def _startup(self) -> bool:
        return self.blocks < self.cfg.floor_startup_blocks

    def _robust(self) -> tuple[float, float] | None:
        """Start-up estimate from the sub-blocks so far: (level, spread) of the frames in the
        "background-like" sub-blocks, i.e. those whose mean is within floor_startup_keep_db of the
        floor_startup_pct quantile of the 50 ms sub-block means. A sound covering most of the block is
        left out; on steady background nearly every sub-block is kept, so the estimate is not biased low
        (a plain low quantile runs ~1 dB low and its spread lower still; that merged click trains and
        lengthened sounds on the synthetic and real-audio evaluations)."""
        if not self.sub:
            return None
        ms = sorted(sm / sn for sm, _, sn in self.sub)
        q = ms[int(self.cfg.floor_startup_pct * (len(ms) - 1))] + self.cfg.floor_startup_keep_db
        tot = sq = 0.0
        cnt = 0
        for sm, ss, sn in self.sub:
            if sm / sn <= q:
                tot += sm
                sq += ss
                cnt += sn
        m = tot / cnt
        return m, max(0.0, sq / cnt - m * m) ** 0.5

    def update(self, e_db: float) -> float:
        cfg = self.cfg
        self.n += 1
        self.block_sum += e_db
        self.block_sq += e_db * e_db
        self.block_n += 1
        if self._startup():
            self.sub_sum += e_db
            self.sub_sq += e_db * e_db
            self.sub_n += 1
            if self.sub_n >= cfg.floor_startup_sub_frames:
                self.sub.append((self.sub_sum, self.sub_sq, self.sub_n))
                self.sub_sum = self.sub_sq = 0.0
                self.sub_n = 0
        if self.block_n >= cfg.floor_block_frames:
            m = self.block_sum / self.block_n
            sd = max(0.0, self.block_sq / self.block_n - m * m) ** 0.5
            rob = self._robust() if self._startup() else None
            if rob is not None and m - rob[0] > cfg.floor_startup_trigger_db:
                m, sd = rob
            self.means.append(m)
            self.stds.append(sd)
            self.blocks += 1
            self.sub = []
            self.sub_sum = self.sub_sq = 0.0
            self.sub_n = 0
            if len(self.means) > cfg.floor_blocks:
                self.means.pop(0)
                self.stds.pop(0)
            self.block_sum = self.block_sq = 0.0
            self.block_n = 0
        return self.value

    @property
    def value(self) -> float:
        cands = list(self.means)
        if not cands and self.block_n:  # before the first full block: robust start-up level, else running mean
            rob = self._robust()
            m = self.block_sum / self.block_n
            cands = [rob[0] if rob and m - rob[0] > self.cfg.floor_startup_trigger_db else m]
        if not cands:
            return self.cfg.floor_min_db
        return max(self.cfg.floor_min_db, min(cands) + self.cfg.floor_bias_db)

    @property
    def spread(self) -> float:
        """How much the background's hop energy fluctuates: median of the block std devs (dB).
        Steady noise ~0.5-1 dB, low-frequency rumble ~2 dB, distant babble ~5 dB."""
        if self.stds:
            return float(sorted(self.stds)[(len(self.stds) - 1) // 2])  # lower median
        if self.block_n > 1:
            m = self.block_sum / self.block_n
            sd = max(0.0, self.block_sq / self.block_n - m * m) ** 0.5
            rob = self._robust()
            if rob is not None and m - rob[0] > self.cfg.floor_startup_trigger_db:
                return rob[1]
            return sd
        return 0.0


@dataclass
class SegmentStats:
    start_index: int
    t_start_ms: float
    floor_db: float                 # floor when the sound started
    close_over_floor_db: float = 5.0  # the gate's close threshold above the floor (noise-adaptive)
    e_db: list[float] = field(default_factory=list)
    f0: list[float] = field(default_factory=list)
    clarity: list[float] = field(default_factory=list)
    flux: list[float] = field(default_factory=list)     # only the first ONSET_FRAMES are kept
    # energy-weighted running sums (weight = linear energy above the floor)
    w_sum: float = 0.0
    centroid_sum: float = 0.0
    flatness_sum: float = 0.0
    zcr_sum: float = 0.0
    lf_sum: float = 0.0
    hf_sum: float = 0.0
    flux_sum: float = 0.0           # energy-weighted spectral flux over the whole sound
    cent_sum: float = 0.0           # sums of log2(centroid) over frames above the close threshold:
    cent_sq: float = 0.0            # its spread is large when vowels alternate with consonant noise
    cent_n: int = 0
    # fingerprint (fp1) sums of per-frame power: 8 mel bands, band total, 1-6 kHz, pitched-frame total and above 3.5 f0
    mel8_sum: list = field(default_factory=lambda: [0.0] * 8)
    p_band_sum: float = 0.0
    p_1k6_sum: float = 0.0
    p_voiced_sum: float = 0.0
    p_hi35_sum: float = 0.0
    peak_db: float = -np.inf
    peak_centroid: float = 0.0
    peak_flatness: float = 0.0
    peak_zcr: float = 0.0
    truncated: bool = False

    ONSET_FRAMES = 3

    def add(self, f: Frame) -> None:
        self.e_db.append(f.e_db)
        self.f0.append(f.f0)
        self.clarity.append(f.clarity)
        if len(self.flux) < self.ONSET_FRAMES:
            self.flux.append(f.flux)
        w = max(0.0, 10.0 ** (f.e_db / 10.0) - 10.0 ** (self.floor_db / 10.0))
        self.w_sum += w
        self.centroid_sum += w * f.centroid
        self.flatness_sum += w * f.flatness
        self.zcr_sum += w * f.zcr
        self.lf_sum += w * f.lf_ratio
        self.hf_sum += w * f.hf_ratio
        self.flux_sum += w * f.flux
        if f.e_db > self.floor_db + self.close_over_floor_db and f.centroid > 0:
            lc = float(np.log2(f.centroid))
            self.cent_sum += lc
            self.cent_sq += lc * lc
            self.cent_n += 1
        if f.mel8:
            for i, v in enumerate(f.mel8):
                self.mel8_sum[i] += v
        self.p_band_sum += f.p_band
        self.p_1k6_sum += f.p_1k6
        self.p_voiced_sum += f.p_voiced
        self.p_hi35_sum += f.p_hi35
        if f.e_db > self.peak_db:
            self.peak_db = f.e_db
            self.peak_centroid = f.centroid
            self.peak_flatness = f.flatness
            self.peak_zcr = f.zcr

    @property
    def n(self) -> int:
        return len(self.e_db)

    def wmean(self, s: float) -> float:
        return s / self.w_sum if self.w_sum > 0 else 0.0


class Segmenter:
    """Feed frames; returns a SegmentStats each time a sound ends."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.floor = NoiseFloor(cfg)
        self.floor_db = cfg.floor_min_db
        self.seg: SegmentStats | None = None
        self.pending: list[Frame] = []    # frames after the last active one (hangover), not yet added
        self.recent: list[Frame] = []     # the last PREROLL frames while idle
        self.above = 0
        self.cooldown = 0
        self.fill_frames = -(-cfg.win // cfg.hop)  # ceil(win / hop)

    def _thr(self) -> tuple[float, float]:
        cfg = self.cfg
        sp = self.floor.spread
        return (self.floor_db + max(cfg.gate_open_db, cfg.gate_open_sigma * sp),
                self.floor_db + max(cfg.gate_close_db, cfg.gate_close_sigma * sp))

    def push(self, f: Frame) -> SegmentStats | None:
        cfg = self.cfg
        open_thr, close_thr = self._thr()   # thresholds from the floor before this frame
        done: SegmentStats | None = None
        if self.seg is None:
            if self.cooldown > 0:
                self.cooldown -= 1
            warm = self.floor.n >= cfg.warmup_frames
            self.above = self.above + 1 if (f.e_db > open_thr and warm and self.cooldown == 0) else 0
            if self.above >= cfg.open_frames:
                # opening frames (the last open_frames, including this one) plus a pre-roll of
                # contiguous earlier frames above the close threshold
                opening = (self.recent + [f])[-cfg.open_frames:]
                earlier = (self.recent + [f])[:-cfg.open_frames]
                pre: list[Frame] = []
                for g in reversed(earlier):
                    if g.e_db > close_thr and len(pre) < PREROLL:
                        pre.insert(0, g)
                    else:
                        break
                frames = pre + opening
                self.seg = SegmentStats(frames[0].index, frames[0].t_ms, self.floor_db, close_thr - self.floor_db)
                for g in frames:
                    self.seg.add(g)
                self.pending = []
                self.above = 0
                self.recent = []
            else:
                self.recent.append(f)
                if len(self.recent) > PREROLL + cfg.open_frames:
                    self.recent.pop(0)
        else:
            if f.e_db > close_thr:
                for g in self.pending:
                    self.seg.add(g)
                self.pending = []
                self.seg.add(f)
            else:
                self.pending.append(f)
            if len(self.pending) >= cfg.hangover_frames:
                done = self._close()
            elif self.seg.n + len(self.pending) >= cfg.max_segment_frames:
                self.seg.truncated = True
                done = self._close()
        if f.index >= self.fill_frames:  # frames whose window still holds start-up zeros say nothing about the room
            new = self.floor.update(f.e_db)
            if self.seg is not None and new > self.floor_db:
                # while a sound is open the floor may rise only slowly (the sound must not become its own floor)
                new = min(new, self.floor_db + cfg.floor_rise_open_db_s * cfg.frame_ms / 1000.0)
            self.floor_db = new
        return done

    def _close(self) -> SegmentStats:
        seg = self.seg
        self.seg = None
        self.pending = []
        self.recent = []
        self.cooldown = int(round(self.cfg.cooldown_ms / self.cfg.frame_ms))
        return seg

    def flush(self) -> SegmentStats | None:
        """End of stream: close an open sound as if its hangover had run out."""
        if self.seg is None:
            return None
        return self._close()
