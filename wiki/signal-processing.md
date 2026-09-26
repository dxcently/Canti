# Signal processing: under a tenth of a core, RAM is the tighter budget

[Index](index.md) · [Hardware](hardware.md) · [Signal processing](signal-processing.md) · [Gestures and phrases](gesture-vocabulary.md) · [Decision models](decision-models.md) · [Phone control](phone-control.md) · [Prior art](prior-art.md) · [Latency and risks](latency-and-risks.md) · [Roadmap](roadmap.md) · [Sources](sources.md)

**Summary.** Use FFT-based MPM for pitch, since its clarity value doubles as a check that a sound is tonal. Compute an eight-feature bank from the same spectrum, and keep everything in float32 on core 1. No neural network is needed on the Pico.

## Pitch: MPM with a clarity gate

**MPM (McLeod Pitch Method, the normalized square difference function) computed through an FFT-based autocorrelation** needs as little as two periods in the window. It returns a built-in **clarity** value, the NSDF peak height, which "falls toward zero" as the signal becomes noise-like ([McLeod & Wyvill 2005](https://www.cs.otago.ac.nz/graphics/Geoff/tartini/papers/A_Smarter_Way_to_Find_Pitch.pdf)). On one library's degraded-audio test, MPM made 26 correct detections to YIN's 22 ([sevagh/pitch-detection](https://github.com/sevagh/pitch-detection)). Plain FFT peak-picking is too coarse for low hums: at 16 kHz with 512 points, one bin is about 3.5 semitones at 150 Hz [EST]. Harmonics also cause octave errors. The closest embedded precedent runs YIN on an RP2040 flute mouse ([JorenSix/PiPePoPo](https://github.com/JorenSix/PiPePoPo)).

| Parameter | Starting value |
|---|---|
| Sample rate | 16 kHz |
| Window | 512 samples (32 ms) |
| Hop | 160 samples (10 ms) |
| f0 floor | ~80 Hz |
| Smoothing | 3–5-frame median filter |
| Jump limit | ~7 semitones per 10 ms |

These are design values, to be tuned on recordings.

## Feature bank

On every hop, compute from the same spectrum: **log-energy, zero-crossing rate, spectral flatness, centroid, positive spectral flux, clarity, f0 and f0 slope**. This is the standard energy-plus-flatness-plus-ZCR voice-activity recipe ([US patent 10872620](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10872620)).

| Sound | Signature |
|---|---|
| Hum | High clarity, low flatness, stable f0 |
| Pop | Flux spike, low clarity, short |
| Hiss | High flatness, high ZCR |
| Speech | Rapid voicing changes, small pitch excursions, formant motion. Rejected by the gates in [Gestures](gesture-vocabulary.md) |

The noise gate opens at floor + 6–10 dB, with hysteresis and about 100 ms of hangover [design]. In cursor mode the Pico also streams a 10–30 Hz summary (pitch offset from start in semitones, voicing, loudness bucket) on the STREAM characteristic ([Phone control](phone-control.md)).

## Compute budget

On the RP2350's M33, 100 float multiply-accumulates took **6 µs**, the same as fixed-point ([Cornell ECE4760](https://people.ece.cornell.edu/land/courses/ece4760/RP2350/arithmetic/index_arithmetic.html)). So use float32 for the pitch path and Q15 only for audio buffers. There is no Helium vector unit ([RP2350 datasheet](https://pip.raspberrypi.com/documents/RP-008373-DS-rp2350-datasheet.pdf)). Using Cortex-M4 counts as a proxy, a 512-point real FFT takes 30,457 cycles ([Arm white paper](https://community.arm.com/cfs-file/__key/communityserver-blogs-components-weblogfiles/00-00-00-21-42/7563.ARM-white-paper-_2D00_-DSP-capabilities-of-Cortex_2D00_M4-and-Cortex_2D00_M7.pdf)).

| Stage | Cost per 10 ms hop |
|---|---|
| FFT-based MPM | ~0.75 ms [EST] |
| Whole feature bank | < 10% of one core [EST] |
| Direct-sum YIN (for comparison) | ~60% of one core [EST] |
| DTW per event (not per hop) | ~0.1–0.3 ms [EST] |

## RAM budget

| Item | Size |
|---|---|
| BLE stack | ~20 KB ([arduino-pico docs](https://arduino-pico.readthedocs.io/en/latest/bluetooth.html)) |
| 1 s audio ring buffer | 32 KB |
| DSP scratch | ~10 KB [EST] |
| 40 DTW templates | ~8–30 KB [EST] |
| CYW43 blob if `copy_to_ram` | ~220 KB ([RPi forums](https://forums.raspberrypi.com/viewtopic.php?t=384445)); avoid |

Put audio, FFT, features, gates and DTW on **core 1** with its code in SRAM, and BTstack on **core 0**.

## Toolchain traps

- Linking a prebuilt CMSIS-DSP library caused float-ABI errors. **Build it from source** ([RPi forum](https://forums.raspberrypi.com/viewtopic.php?t=389775)).
- `pico-tflmicro` has an **open, unanswered RP2350 issue since August 2024** ([pico-tflmicro #18](https://github.com/raspberrypi/pico-tflmicro/issues/18)). VOX needs no NN on the Pico. If one is added later, DS-CNN-S keyword spotting is about **38.6 KB at 8-bit** ([Hello Edge](https://arxiv.org/pdf/1711.07128)), at about 40–70 ms per inference [EST] ([pico-person-detection](https://github.com/KrystofBo/pico-person-detection)).

## Datasets

- **VocalSound**: coughs, sniffs and laughs as negatives ([arXiv 2205.03433](https://arxiv.org/abs/2205.03433)).
- **Nonverbal Vocalization Dataset**: tongue clicks and lip pops ([OpenSLR 99](https://www.openslr.org/99/)).
- **MIR-QBSH**: hummed pitch ([ISMIR 2023](https://archives.ismir.net/ismir2023/paper/000077.pdf)).
- VOX's own gestures must be recorded on the Pico mic chain ([Roadmap](roadmap.md) Phase 0).

## Open questions / to verify on hardware

- Measure real DWT cycle counts for FFT + MPM + features on the RP2350. The M4 figures are only a proxy.
- Does clarity ≥ ~0.8 separate hums from voiced speech on this mic? Tune it on negatives.
- Is the octave-error rate after the median filter and jump limit low enough for 4-semitone contour decisions?
- How does the pop detector (flux spike) hold up against keyboard clicks and door knocks?
- Does the noise-floor tracker stay stable when a TV or conversation is running?
- The float Python pipeline (Phase 0) and the CMSIS port must agree frame for frame. Set a tolerance.
