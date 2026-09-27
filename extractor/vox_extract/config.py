"""Every tunable number of the VOX extractor, in one dataclass.

The C port should mirror this struct field for field. The defaults were tuned on SYNTHETIC audio (synth.py),
then checked on real audio (eval_real/, results/real_*.md); the only changes from real audio are the live-bug
fixes (floor_startup_*, floor_rise_open_db_s, discrete_tonal_*). A threshold set tuned on the real-audio TUNE
split is kept separately in results/real_tuned_config.json (load it with --config); it is not the default.
Load/save as JSON so a recording session can store the exact config it ran with.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Config:
    # ---- front end -------------------------------------------------------------------------
    sample_rate: int = 16000          # internal rate; 48 kHz input is decimated by 3 (resample.py)
    hop: int = 160                    # 10 ms
    win: int = 512                    # 32 ms analysis window (spectral features and pitch)
    acf_fft: int = 1024               # FFT size for the MPM autocorrelation (>= win + tau_max)
    hpf_hz: float = 60.0              # 2nd-order Butterworth high-pass at the input (DC + rumble)
    spec_lo_hz: float = 90.0          # band used for flatness / flux / centroid
    spec_hi_hz: float = 7600.0
    lf_split_hz: float = 1000.0       # "low band" ratio = energy below this / total
    hf_split_hz: float = 3500.0       # "high band" ratio = energy above this / total
    flux_floor_db: float = -95.0      # per-bin power floor (dB) before log, so silent bins don't create flux

    # ---- pitch (MPM, McLeod & Wyvill 2005) -----------------------------------------------------
    f0_min_hz: float = 75.0
    f0_max_hz: float = 2600.0         # covers whistles
    mpm_k: float = 0.88               # choose the first NSDF key maximum >= k * highest key maximum
    voiced_clarity: float = 0.60      # clarity needed for a frame to count as voiced
    voiced_min_db_over_floor: float = 6.0

    # ---- noise floor (minimum statistics over blocks) -------------------------------------------
    floor_block_frames: int = 40      # 0.4 s blocks
    floor_blocks: int = 8             # floor = min over the last 8 blocks (3.2 s) of each block's mean dB
    floor_bias_db: float = 0.0        # added to that estimate
    floor_min_db: float = -85.0       # clamp: digital silence must not give a -inf floor
    warmup_frames: int = 25           # gate held closed for the first 250 ms while the floor settles
    floor_startup_blocks: int = 2     # the first 2 blocks (0.8 s) use a robust level (a sound present at start-up
    floor_startup_sub_frames: int = 5 #   must not become the floor): this quantile of 50 ms sub-block means
    floor_startup_pct: float = 0.25
    floor_startup_keep_db: float = 3.0     # ... "background-like" sub-blocks: within this of that quantile
    floor_startup_trigger_db: float = 10.0 # use them only if the plain block mean is this far above their mean
                                          # (a loud sound at start-up; babble fluctuates only 3-6 dB)
    floor_rise_open_db_s: float = 3.0 # while a sound is open the floor rises at most this fast (dB/s)

    # ---- gate and segmentation ------------------------------------------------------------------
    gate_open_db: float = 9.0         # open when hop energy > floor + this
    gate_close_db: float = 5.0        # a frame stays "active" while energy > floor + this (hysteresis)
    gate_open_sigma: float = 2.5      # ... but at least this many "spreads" (median block std of the
    gate_close_sigma: float = 1.5     #     background's hop energy, dB) above the floor
    open_frames: int = 1              # consecutive frames over the open threshold to open
    hangover_frames: int = 10         # 100 ms below the close threshold ends the sound
    max_segment_frames: int = 400     # 4 s: force-close (event flagged truncated) - bounds RAM
    min_segment_frames: int = 1

    # ---- contour --------------------------------------------------------------------------------
    median_frames: int = 5            # median filter on the semitone track
    jump_limit_st: float = 7.0        # frame-to-frame jump that marks an outlier (after octave fix)
    contour_db: float = 12.0          # contour uses voiced frames within this many dB of the sound's level
    edge_frames: int = 5              # start / end pitch = median of the first / last 5 voiced frames
    smooth_frames: int = 5            # moving average before shape analysis (tames vibrato)
    flat_max_range_st: float = 1.5    # max(|net|, hump, valley) of the smoothed contour below this -> flat
    shape_min_st: float = 1.0         # a hump / valley must be at least this to be arch / dip
    arch_ratio: float = 1.0           # arch if hump >= ratio * |net change| (dip likewise)
    exc_medium_st: float = 2.0        # EXCURSION bucket edges
    exc_large_st: float = 4.0

    # ---- buckets --------------------------------------------------------------------------------
    dur_short_ms: int = 150           # DURATION bucket edges
    dur_medium_ms: int = 400
    dur_long_ms: int = 1000
    tone_clear: float = 0.80          # median clarity over all frames of the sound for "clear tone"
    tone_breathy: float = 0.60        # ... for "breathy"; below -> "noisy"
    tone_min_voiced_frac: float = 0.5 # fewer voiced frames than this -> at best "breathy"
    # loudness: level = 90th percentile hop energy of the sound (dBFS)
    loud_quiet_over_floor_db: float = 18.0   # floor mode: level - ref < this -> quiet
    loud_loud_over_floor_db: float = 40.0    # floor mode: level - ref >= this -> loud
    loud_ref_min_db: float = -80.0           # floor mode reference = max(floor, this)
    loud_calib_db: float | None = None       # calibrated "normal" level (dBFS); set by record.py --calibrate
    loud_calib_span_db: float = 8.0          # calibrated mode: +-span around the calibrated level

    # ---- discrete sounds ------------------------------------------------------------------------
    discrete_max_ms: int = 200        # pop / click: gate-active time at most this (a loud pop's tail is long)
    discrete_core_ms: int = 60        # ... and at most this long within discrete_core_db of its peak
    discrete_core_db: float = 15.0
    discrete_max_voiced: int = 4      # ... and fewer voiced frames than this, or
    discrete_peak_pos: float = 0.4    # ... its energy peak in the first 40 % (a decaying resonant pop)
    pop_onset_flux_db: float = 6.0    # impulsive if onset flux (max over first 3 frames) >= this, or
    pop_attack_frames: int = 3        # ... the energy peak is within the first 3 frames of the sound
    click_centroid_hz: float = 1800.0 # peak-frame centroid above this -> click, else pop
    discrete_tonal_voiced_frac: float = 0.5  # a short sound this voiced AND this clear is a tone fragment
    discrete_tonal_clarity: float = 0.8      #   (e.g. a whistle's top), never pop / click (live bug 105053)
    hiss_min_ms: int = 100
    hiss_max_voiced_frac: float = 0.25
    hiss_centroid_hz: float = 2200.0
    hiss_zcr: float = 0.18            # zero crossings per sample
    hiss_bg_lf_ratio: float = 0.20    # low-band share above this -> "background noise" (fan / air, not "sss")
    hiss_bg_steady_ms: int = 1500     # a hiss this long with a steady envelope -> "background noise"
    hiss_steady_db: float = 3.0       # "steady" = interquartile range of hop energy below this

    # ---- "sounds like" heuristics ---------------------------------------------------------------
    whistle_min_hz: float = 600.0
    syllable_prominence_db: float = 6.0   # an energy peak must stand this far above its surrounding dips
    syllable_min_gap_frames: int = 8      # peaks closer than 80 ms are merged
    # talking = at least talk_min_cues of the three speech cues (classify.speech_cues):
    talk_min_cues: int = 2
    talk_max_voiced_frac: float = 0.85    # 1 broken voicing: voiced fraction below this, or
    talk_min_runs: int = 3                #   at least this many voiced runs (>= 2 frames each)
    talk_centroid_spread_oct: float = 0.45  # 2 consonant / formant changes: std of log2(centroid) over the sound
    talk_strong_centroid_spread_oct: float = 0.7  # ... this much alone is enough (vowel / consonant alternation)
    talk_min_peaks: int = 2               # 3 syllable-like loudness: energy peaks ...
    talk_min_rate_hz: float = 2.0         #   ... at a syllable rate, or
    talk_max_rate_hz: float = 9.0
    talk_min_iqr_db: float = 8.0          #   an interquartile range of hop energy above this
    train_gap_ms: int = 300               # a voiced sound starting this soon after a talking / laughing
    train_max_ms: int = 400               # sound, and short or with any speech cue, is talking too
    laugh_min_peaks: int = 3
    laugh_rate_lo_hz: float = 3.0
    laugh_rate_hi_hz: float = 8.0
    laugh_max_interval_cv: float = 0.30   # regular bursts
    laugh_max_clarity: float = 0.88
    cough_onset_flux_db: float = 5.0
    cough_max_voiced_frac: float = 0.6
    cough_decay_db: float = 10.0          # energy at the end at least this far below the peak
    cough_peak_pos: float = 0.35          # the peak comes in the first 35 % of the sound
    cough_max_ms: int = 900
    music_min_ms: int = 900
    music_max_clarity: float = 0.90       # chords: tonal spectrum but no single clear period
    music_max_flatness: float = 0.12
    music_min_jumps_hz: float = 0.8       # pitch steps (> 1.5 st) per second between stable notes
    machine_max_pitch_std_st: float = 0.04  # a perfectly steady tone (fan motor) is not a human hum
    machine_min_ms: int = 900
    max_gesture_ms: int = 3000        # a voiced sound longer than this (or truncated) is not a gesture:
                                      # "background noise" if steady, else "background music"

    # ---- hold (hold-to-scroll: a message while a steady tone is still going; hold.py) -----------
    # A sound that has lasted hold_start_ms and whose last hold_start_ms look like one steady tone sends
    # `hold start` once; its end sends `hold end` (before its event). Tested on frames above the close
    # threshold, over the sound's last hold_start_ms of frames; voiced = as classify.
    # See README "Hold messages" (and android/PROTOCOL.md) for the measured hold / false-hold rates.
    hold_start_ms: int = 300          # window and earliest time; 0 = no hold messages
    hold_min_voiced_frac: float = 0.8 # voiced frames in the window (speech windows: median 0.77)
    hold_min_clarity: float = 0.85    # median clarity of the window (motor hum / chords: ~0.7)
    hold_max_drift_st: float = 1.0    # |median pitch of the later half - earlier half| of the voiced frames
    hold_max_mad_st: float = 0.5      # median |pitch - median pitch| (wobble, vibrato, intonation); a pitch
                                      # std below machine_max_pitch_std_st is a machine: no hold either
    hold_flat_st: float = 1.5         # `flat` in the message: the window's median pitch is within this of the
                                      # sound's start pitch (median of its first edge_frames voiced frames)
    hold_pitch_ms: int = 200          # while held: a `hold pitch` report every this many ms of the sound (after
                                      # `hold start`), for the phone's pitch throttle; 0 = none
    hold_pitch_min_voiced_frac: float = 0.5   # a report needs this share of voiced frames in its window, else
                                      # it is skipped (the next one tries again)
    hold_glide_ms: int = 250          # glide-and-hold: a rise / fall whose END note is then held steady this long
                                      # (same steadiness test as above, over the last hold_glide_ms) sends `hold
                                      # start` with from = "glide" and dir = up / down, before the flat test; 0 = off
    hold_glide_min_st: float = 2.0    # ... if the held note is at least this far from the sound's start pitch (a
                                      # glide, not a wobble; arch / dip back to the start fail it)
    hold_glide_peak_st: float = 1.5   # ... and within this of the sound's highest (up) / lowest (down) voiced pitch so
                                      # far: the held note is where the glide went, not the way back of an arch / dip
                                      # that ends off its start pitch; 0 = no such test
    hold_glide_quiet_ms: int = 700    # ... only for a sound after at least this much quiet (from the previous sound's
                                      # end; a stream's first sound counts as quiet): talk and music run sounds
                                      # together, a deliberate glide starts from silence; 0 = no such test
    hold_glide_delay_ms: int = 300    # ... and only once the test has passed on every frame for this much longer (late
                                      # start): released sooner, the sound is a plain rise / fall (a full swipe,
                                      # no hold, held = False); 0 = at once

    # ---- output ---------------------------------------------------------------------------------
    cooldown_ms: int = 0              # optional refractory time after an emitted event (wiki: ~300)

    @property
    def frame_ms(self) -> float:
        return 1000.0 * self.hop / self.sample_rate

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**d)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json() + "\n")
