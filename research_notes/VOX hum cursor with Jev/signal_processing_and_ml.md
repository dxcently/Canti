# Signal Processing and Tiny ML for Non-Speech Vocal Control on RP2350 (Pico 2 W), with a Raspberry Pi Upgrade Path

Scope: real-time feature extraction (pitch, contour, energy, duration, onsets) and a small on-device classifier for hums, tones, whistles, tongue clicks and pitch glides on the RP2350 (2x Cortex-M33 @ 150 MHz, 520 KB SRAM), plus what changes on a Pi 4/5. Numbers are cited where a source gives them. Anything marked **[EST]** is my own arithmetic or extrapolation, not a measurement.

Note on sources: some primary PDFs (YIN paper, an MDPI Pico 2 KWS paper) could not be retrieved; those are listed under Gaps. The RP2350 datasheet, Pico 2 W datasheet, MPM paper, "Hello Edge" (DS-CNN) paper and the Arm DSP white paper were read directly.

---

## 1. Pitch detection for hums and whistles: which algorithm, at what cost

### Takeaway
Use a time-domain difference/autocorrelation tracker, either YIN (CMNDF) or McLeod MPM (NSDF), computed through an FFT-based autocorrelation. Run it on a 16 kHz stream with a 25–40 ms window and a 10 ms hop, and use the algorithm's built-in aperiodicity or "clarity" value as the voicing gate. Keep FFT peak picking with parabolic interpolation as a cheap second path for whistles, which are nearly pure tones. Don't rely on it alone for hums: they are rich in harmonics, and the strongest peak can sit an octave or more above the fundamental. Only one directly relevant embedded precedent turned up: an open-source YIN-based pitch-to-mouse controller on an RP2040.

### Cited Findings
- **YIN**: an autocorrelation-derived method with add-on steps. Implementations commonly use an absolute threshold of 0.1 on the cumulative-mean-normalized difference function, with a 25 ms integration window in the paper's evaluation — [Semantic-Scholar/search summary of de Cheveigné & Kawahara 2002](https://www.semanticscholar.org/paper/YIN%2C-a-fundamental-frequency-estimator-for-speech-Cheveign%C3%A9-Kawahara/34a73fef11c9a47c2a969a9dbcb536829a1ffc61); [paper PDF](http://audition.ens.fr/adc/pdf/2002_JASA_YIN.pdf) (could not be fetched; see Gaps).
- The README of an embedded C YIN port claims YIN's six steps cut the error rate "from 17% to 0.5%" — [toddnguyen/YIN_pitch_detection](https://github.com/toddnguyen/YIN_pitch_detection) (secondary claim; see Gaps).
- Naive YIN is O(N²). Production versions use FFT-based computation for O(N log N) — [Tonalux blog](https://tonalux.org/blog/yin-pitch-detection-algorithm-explained) (secondary source). The window must hold at least two pitch periods — same source.
- An embedded-oriented C YIN library exists, ported from "The Pidato Experiment" (originally for Arduino). It has many forks (ashokfernandez, DingKe, jiemojiemo, faroit) — [ashokfernandez/Yin-Pitch-Tracking](https://github.com/ashokfernandez/Yin-Pitch-Tracking), [DingKe/Yin-Pitch-Tracking](https://github.com/DingKe/Yin-Pitch-Tracking).
- An AMDF pitch detector runs on an 8-bit 16 MHz Arduino Uno with 2 KB SRAM, and an autocorrelation detector exists for Arduino — [Instructables AMDF](https://www.instructables.com/Arduino-Pitch-Detection-Algorithm-AMDF/), [Coert Vonk autocorrelation](http://coertvonk.com/sw/embedded/arduino-pitch-detector-13252).
- **Direct precedent:** *PiPePoPo* ("Pitch perfect pointer positioning") is a flute-driven mouse cursor controller. It runs YIN on an Arduino Nano RP2040 Connect with its onboard microphone, based on the TarsosDSP YIN (itself derived from aubio), and enumerates as a standard USB mouse. It publishes no latency or sample-rate numbers — [JorenSix/PiPePoPo](https://github.com/JorenSix/PiPePoPo).
- **MPM (McLeod & Wyvill 2005)**: uses the Normalized Square Difference Function (NSDF) and picks "key maxima" (the highest peak between positive-going zero crossings). The pitch is the first key maximum above k × (highest maximum), with k "usually in the range 0.8 to 1.0". k must be large enough to skip peaks from strong harmonics but small enough to avoid sub-harmonics; a wrong choice "causes a pitch error, usually a 'wrong octave'." Peak positions are refined by parabolic interpolation — [McLeod & Wyvill, "A Smarter Way to Find Pitch", ICMC 2005](https://www.cs.otago.ac.nz/graphics/Geoff/tartini/papers/A_Smarter_Way_to_Find_Pitch.pdf).
- MPM cost: direct summation is O(W·w). The ACF part can be computed in about O((W+w) log(W+w)) via FFT: zero-pad by w = W/2, FFT, take |X|², inverse FFT. The energy term m′(τ) is updated incrementally — [McLeod & Wyvill 2005](https://www.cs.otago.ac.nz/graphics/Geoff/tartini/papers/A_Smarter_Way_to_Find_Pitch.pdf).
- MPM can extract pitch "with as little as two periods" in the window, which allows smaller windows that track fast pitch changes such as vibrato. It also provides a built-in **clarity** measure: the NSDF value at the chosen peak, which falls toward zero as a signal becomes noise-like. This serves as a voicing/tonality gate — [McLeod & Wyvill 2005](https://www.cs.otago.ac.nz/graphics/Geoff/tartini/papers/A_Smarter_Way_to_Find_Pitch.pdf).
- A C++ library implements MPM, YIN-FFT, pYIN and a probabilistic MPM (SWIPE' was removed in Dec 2023). It uses an FFT the same size as the input. On its degraded-audio test, MPM got 26 correct detections vs YIN's 22 — [sevagh/pitch-detection](https://github.com/sevagh/pitch-detection).
- aubio's `aubiopitch` defaults: buffer 2048, hop 256, method `yinfft` (a YIN variant computing a tapered square-difference function via FFT with spectral weighting), silence threshold −90 dB, tolerance typically 0.2–0.9. Other methods: `yin`, `yinfast`, `mcomb` (spectral flattening + multi-comb + peak histogram), `fcomb`, `specacf`, and `schmitt` ("computationally very inexpensive, but also very sensitive to noise") — [aubiopitch man page](https://aubio.org/manpages/latest/aubiopitch.1.html).
- Float vs fixed point on the RP2350 M33 @150 MHz (Cornell ECE4760, -Ofast): 100 MACs took 6 µs in float, 6 µs in s15.16 and 7 µs in s1.14. That is "no speed advantage to fixed point for the MAC operation", and fixed-point divide and sqrt are slower. Floating point reached about 50 MFLOPS/core on a Mandelbrot test — [Cornell RP2350 arithmetic](https://people.ece.cornell.edu/land/courses/ece4760/RP2350/arithmetic/index_arithmetic.html).
- Another RP2040-vs-RP2350 DSP benchmark (June 2026) found Q15 "faster for some basic operations but slower for others" on the RP2350, with no clear winner vs F32. RP2350 gains over RP2040: Q15 add ≈3.5×, Q15 mul ≈1.7×, Q31 ≈4×. RP2040 F32 performs "very poorly" (software float) — [Wee Noise Makers](https://weenoisemakers.com/blog/2026/06/15/dsp-benchmark-rp2040-vs-rp2350.html).

### Inferences
- **Lag resolution at 16 kHz [EST]:** a 150 Hz hum has a period of 106.7 samples. One sample of lag error is ≈1.4 Hz (≈16 cents) before parabolic interpolation, which is fine for a glide-to-velocity mapping. A 512-point FFT at 16 kHz has 31.25 Hz bins, about 3.5 semitones at 150 Hz, so raw FFT peak picking is too coarse for low hums without interpolation or a longer window. It works for whistles (roughly 1–3 kHz, where a 31 Hz bin is <1 semitone) — whistle range not sourced, see Gaps.
- **Window sizing [EST]:** MPM needs 2 periods. At an 80 Hz floor that is 25 ms (400 samples at 16 kHz), so W=512 (32 ms) with a 160-sample (10 ms) hop is a reasonable default. YIN usually needs a slightly longer window (the integration window plus the maximum lag), e.g. W=512 plus τ_max=200 for an 80 Hz floor.
- **Cost on the M33 [EST]:** direct-sum YIN with W=512 and τ_max=200 is ~102k MACs per frame. The Cornell loop rate (~9 cycles per MAC including loop overhead) puts that at ~0.9 M cycles ≈ 6 ms per frame, i.e. ~60% of one core at a 10 ms hop. The FFT route (1024-point real FFT forward + inverse plus a magnitude pass) is ~2 × 55.5k cycles ≈ 0.75 ms, using Cortex-M4 cycle counts as a proxy (see §3). **Use the FFT formulation, or decimate to 8 kHz for hums only.**
- **Octave errors:** MPM's k and YIN's absolute threshold both choose the first qualifying dip or peak rather than the global one, which is their main defence against sub-harmonic errors. Strong 2nd harmonics can still cause octave-up errors. Median-filtering the pitch track (3–5 frames) and limiting the frame-to-frame jump (e.g. >7 semitones in 10 ms is implausible for a voice) are cheap post-filters. These are design suggestions, not sourced numbers.
- **Q15 vs float:** with the M33 FPU, float MACs cost the same as fixed-point ones (Cornell), and float avoids scaling bugs in the NSDF normalisation. Recommend **float32** for the pitch path and keep Q15 only for raw audio buffers (halves the RAM).
- **Voicing:** use MPM clarity (or YIN's d′(τ) minimum, where lower means more periodic) combined with an energy gate. A hum or whistle gives high clarity, while hiss and clicks give low clarity. This does double duty as a tonal-vs-noise discriminator.

### Gaps
- The YIN paper's per-step gross-error table could not be fetched (the JASA PDF host failed TLS and redirected). The "17% → 0.5%" figure comes from a GitHub README and does not match my recollection that the paper's Table I starts at ~10% for plain ACF and ends at 0.5%. **Verify against the paper before quoting.**
- No published cycle counts found for YIN or MPM on any Cortex-M33 or RP2350. All YIN/MPM costs above are estimates.
- No source found for typical human whistle frequency range or hum F0 range in a cursor-control context. Prior-art papers (Sporka 2006, Vocal Joystick) are covered by another researcher.
- No head-to-head accuracy comparison of YIN vs MPM vs cepstrum vs AMDF on hums or whistles specifically.

---

## 2. Onsets, pulse counting, VAD, noise gate, AGC, and click / hiss detection

### Takeaway
A frame-level "cheap feature bank" is enough to route events before any ML runs. Compute RMS/log-energy, zero-crossing rate, spectral flatness, spectral centroid and a positive spectral-flux onset function on every 10 ms hop from the same FFT used for pitch. Then:
- A tongue click is a short (<~30 ms) broadband transient: large flux spike, low clarity, short duration.
- Hiss is sustained and noise-like: high flatness, high ZCR, low clarity.
- A hum or whistle is sustained and tonal: high clarity, low flatness.

The energy-plus-flatness-plus-ZCR combination is standard in VAD designs.

### Cited Findings
- aubio's onset-detection functions: `energy`, `hfc` (high-frequency content), `complex`, `phase`, `specdiff`, `kl`, `mkl`, `specflux` — [aubio CLI docs](https://aubio.org/manual/latest/cli.html).
- A VAD processor can combine an energy detector, a spectral-flatness detector, a sub-band energy detector and a ZCR/absolute-value detector — [US patent 10872620 "Voice detection method and apparatus"](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10872620).
- Spectral flatness is the geometric mean of the power spectrum divided by its arithmetic mean. It is near 1 for noise-like spectra and near 0 for tonal/peaky spectra. ZCR is higher for noise than for voiced sound — [Medium: Spectral features of speech](https://vtiya.medium.com/spectral-features-of-speech-signals-unveiling-vocal-characteristics-ee2754a3d0c6); ZCR + short-time-energy VAD example: [rymshasaeed/Voice-Activity-Detection](https://github.com/rymshasaeed/Voice-Activity-Detection). (The search-engine summary of these sources garbled the direction of the flatness claim. The definition above is the standard one.)
- Voluntary nonverbal events such as teeth-clicking and tongue-clicking have been detected and classified in real time as a silent, hands-free computer input — ["Detection and classification of human-produced nonverbal audio events", Applied Acoustics (2020)](https://www.sciencedirect.com/science/article/abs/pii/S0003682X20307477) (abstract-level only).
- MPM "clarity" goes toward zero as a signal becomes noise-like, giving a tonality measure for free from the pitch tracker — [McLeod & Wyvill 2005](https://www.cs.otago.ac.nz/graphics/Geoff/tartini/papers/A_Smarter_Way_to_Find_Pitch.pdf).

### Inferences
- **Suggested per-hop feature vector [design, not sourced]:** `logE, ZCR, flatness, centroid, flux+, clarity, f0, f0_slope`. At 16 kHz with a 10 ms hop this is ~8 floats per 10 ms. Everything except f0 comes from the one 512-point magnitude spectrum, so the marginal cost over the FFT is a few thousand cycles **[EST]**.
- **Click / pop detector:** threshold positive spectral flux (or HFC) against an adaptive median of the last ~0.5 s, apply a ~50–80 ms refractory period, and count pulses within a gesture window (e.g. 400 ms) to separate single, double and triple clicks. Energy-envelope onset alone will false-trigger on hum starts; requiring low clarity at the onset frame separates clicks from tonal attacks.
- **Hiss vs hum:** flatness plus clarity is a two-feature rule that should separate these without ML. ZCR adds robustness at very low cost (no FFT needed).
- **Noise gate / VAD:** track a noise floor, e.g. minimum-statistics or a slow EMA of logE during frames with low clarity and low flux, and gate at floor + 6–10 dB with hysteresis and hangover (~100 ms) so glides don't chop.
- **AGC:** for pitch, AGC matters little because NSDF and CMNDF are amplitude-normalised. For energy-driven controls (loudness → speed), use a slow AGC or report energy relative to the running noise floor in dB, so the cloud model (Jev) gets stable numbers across mic distances. Avoid fast AGC, which flattens the energy contour that encodes intent.

### Gaps
- No quantitative accuracy numbers retrieved for click-vs-hum-vs-hiss discrimination with hand-crafted features.
- No specific embedded AGC design with measured behaviour was found for this use case.
- Tongue-click spectral/temporal characteristics (duration, bandwidth) were not sourced; the "<30 ms broadband" description is an assumption to be validated on recordings.

---

## 3. Log-mel / MFCC with CMSIS-DSP on Cortex-M33; is Helium available?

### Takeaway
The RP2350's Cortex-M33 cores have the **DSP (SIMD32/MAC) extension and a single-precision FPU, but no Helium/MVE**. MVE is part of Armv8.1-M (Cortex-M55/M85). CMSIS-DSP builds for M33 and provides `arm_rfft_fast_f32` and `arm_mfcc_f32` with sparse mel filters. Using Cortex-M4 cycle counts as a proxy, a 512-point real float FFT is ~30k cycles (~0.2 ms at 150 MHz), so a full log-mel/MFCC frame costs only a few percent of one core at a 10 ms hop. The practical risk is floating-point ABI mismatches and XIP-flash placement, not compute.

### Cited Findings
- RP2350 datasheet: the two Cortex-M33 cores implement "the Armv8-M Main instruction set" and "are configured with the Security, DSP and FPU extensions, as well as 8× SAU regions, 8× Secure MPU regions and 8× Non-secure MPU regions." MVE/Helium is not listed (a text search of the datasheet finds no "Helium"/"M-profile Vector" mention). Each core also has a **double-precision coprocessor (DCP)** that accelerates double add/sub/mul/div/sqrt and some single-precision operations and conversions — [RP2350 Datasheet §3.1, §3.6.2](https://pip.raspberrypi.com/documents/RP-008373-DS-rp2350-datasheet.pdf).
- Product page: "dual Arm Cortex-M33 cores with hardware single-precision floating point and DSP instructions @ 150MHz" — [Raspberry Pi RP2350](https://www.raspberrypi.com/products/rp2350/).
- A forum answer on RP2350 DSP says "most of DSP information/code (except for instruction cycles) for Cortex-M4 (or M4F) is valid for M33 as well" and recommends CMSIS-DSP and intrinsics — [RPi forum t=381317](https://forums.raspberrypi.com/viewtopic.php?t=381317).
- **CMSIS-DSP cycle counts (Arm white paper, Cortex-M4 / M7):**
  - Real FFT F32: 32 → 1,697 / 962; 64 → 3,487 / 2,044; 128 → 5,909 / 3,675; 256 → 14,285 / 8,726; **512 → 30,457 / 19,297; 1024 → 55,538 / 36,337** cycles.
  - Real FFT Q31 on M4: 256 → 18,623; 512 → 37,536; 1024 → 88,261.
  - Complex FFT Q31 on M4: 1024 → 139,898.
  - On the FPU-equipped M4, F32 real FFT was *faster* than Q31. Q15 gets a bigger SIMD speed-up (numbers not tabulated).

  [Arm white paper "DSP capabilities of Cortex-M4 and Cortex-M7"](https://community.arm.com/cfs-file/__key/communityserver-blogs-components-weblogfiles/00-00-00-21-42/7563.ARM-white-paper-_2D00_-DSP-capabilities-of-Cortex_2D00_M4-and-Cortex_2D00_M7.pdf).
- For contrast, RP2040 (M0+, no FPU) CMSIS-DSP FFTs: f32 512 → 9,125 µs, 1024 → 18,588 µs; q15 512 → 1,557 µs, 1024 → 3,116 µs — [jptrainor/cmsis-sandbox](https://github.com/jptrainor/cmsis-sandbox). No RP2350 table in that repo.
- `arm_mfcc_f32(S, pSrc, pDst, pTmp)`: **pSrc is modified in place**. Specialised init functions exist for FFT lengths 32–4096; the generic `arm_mfcc_init_f32` prevents the linker from dropping unused FFT tables and increases code size. Mel filters are stored sparsely (`filterPos`, `filterLengths`). A Python script in CMSIS-DSP `Scripts/` generates the mel filter, DCT and window arrays — [CMSIS-DSP MFCC F32 docs](https://arm-software.github.io/CMSIS-DSP/latest/group__MFCCF32.html).
- **Toolchain pitfalls:**
  - One developer linking a prebuilt `libCMSISDSP_cortex-m33.a` with `-mcpu=cortex-m33 -mfpu=fpv5-sp-d16 -mfloat-abi=hard -DARM_MATH_CM33` hit "uses VFP register arguments, Project .elf does not". The thread went unanswered — [RPi forum t=389775](https://forums.raspberrypi.com/viewtopic.php?t=389775).
  - A pico-sdk issue asks whether RP2350 builds use softfp (hardware FP ops, but float args passed in integer registers) rather than hard-float ABI — [pico-sdk #1993](https://github.com/raspberrypi/pico-sdk/issues/1993).
  - The DSP-benchmark blog likewise treats F32 on RP2350 as hardware-accelerated — [Wee Noise Makers](https://weenoisemakers.com/blog/2026/06/15/dsp-benchmark-rp2040-vs-rp2350.html).
- KWS feature settings in the canonical MCU paper: 40 MFCCs from 40 ms frames with a 20 ms stride = 49×40 = 1,960 features per 1 s. The appendix models use 10 MFCCs with 40 ms frames. A deployed Cortex-M7 (STM32F746) KWS spent **~12 ms per inference including memory copy, MFCC extraction and a DNN**, at 10 inferences/s. Memory was ~70 KB total: ~66 KB weights, ~1 KB activations, ~2 KB audio I/O + MFCC — ["Hello Edge", Zhang et al. 2017](https://arxiv.org/pdf/1711.07128).

### Inferences
- **RP2350 FFT estimate [EST]:** assuming M33 ≈ M4 cycles for FPU work (the M33 is also single-issue; not measured on RP2350), a 512-point `arm_rfft_fast_f32` ≈ 30k cycles ≈ **0.20 ms** at 150 MHz, and 1024-point ≈ 56k cycles ≈ **0.37 ms**. At a 10 ms hop (1.5 M cycles per core) a 512-point FFT is ≈2% of one core.
- **Log-mel frame [EST]:** FFT (30k) + magnitude (~2–3k) + 40 sparse mel filters over 257 bins (~1–2k MACs) + log (40 calls) + optional DCT-II 40→13 (~520 MACs) ≈ 35–40k cycles ≈ **0.25 ms/frame**, i.e. <3% of one core at a 10 ms hop. This matches the "Hello Edge" M7 result where MFCC plus a small DNN fit in 12 ms per second of audio.
- **RAM for features [EST]:** 512-float FFT buffer (2 KB) + pTmp (2 KB) + window (2 KB) + mel filter coefficients (~2–3 KB sparse) + twiddles (flash) ≈ 8–10 KB. A 1 s log-mel context of 49–100 frames × 40 bins in float is 8–16 KB, or 2–4 KB in int8.
- **Helium absence** means no 8-lane int8 vector MACs. CMSIS-NN on the M33 falls back to the DSP-extension SIMD (2×16-bit MAC per instruction), so NN latency scales like an M4, not an M55.
- **Build advice:** compile CMSIS-DSP from source inside the pico-sdk build (don't link a prebuilt .a) so the float ABI matches. Put hot DSP code and twiddle tables in SRAM (`__not_in_flash_func`, or copy selected sections) to avoid XIP cache misses (§4).

### Gaps
- **No measured `arm_rfft_fast_f32` or `arm_mfcc_f32` cycle counts on RP2350 or any Cortex-M33 were found.** All M33 numbers above are M4-proxied estimates. Measuring with the DWT cycle counter on hardware is the first recommended task.
- Whether CMSIS-DSP provides `arm_mfcc_q15` / `arm_mfcc_q31` in the current release was not confirmed; the fetched page documents only F32.
- The resolution of pico-sdk #1993 (hard vs softfp default on RP2350) was not visible in the fetched page.

---

## 4. Real-time budget on RP2350 / Pico 2 W: cores, SRAM, Wi-Fi/BLE overhead

### Takeaway
Compute is not the bottleneck. At 16 kHz with a 10 ms hop, one M33 core has ~1.5 M cycles per hop. The whole feature bank (FFT, log-mel, MPM/YIN-via-FFT, flux, flatness) is estimated at <10% of core1 **[EST]**. RAM is the tighter budget. The CYW43 Wi-Fi/BT stack plus lwIP takes on the order of 100 KB of the 520 KB, and the 220 KB CYW43 firmware blob **must stay in flash** or it eats nearly half of SRAM. Put DSP and the classifier on core1, and networking, USB-HID and the control loop on core0.

### Cited Findings
- RP2350: 520 kB on-chip SRAM in 10 independent banks: SRAM0–3 and SRAM4–7 are two 256 kB word-striped regions, and SRAM8–9 are 2× 4 kB non-striped banks. Code or data can live in SRAM — [RP2350 Datasheet](https://pip.raspberrypi.com/documents/RP-008373-DS-rp2350-datasheet.pdf).
- Pico 2 W: CYW43439 2.4 GHz 802.11n + Bluetooth 5.2, connected to the RP2350 over SPI. External QSPI flash with XIP and a **16 kB on-chip cache**. 3 PIO blocks / 12 state machines. 3 ADC-capable GPIOs — [Pico 2 W Datasheet](https://datasheets.raspberrypi.com/pico/pico-2-w-datasheet.pdf).
- CYW43 firmware blob ≈ **220 KB**. With `pico_set_binary_type(copy_to_ram)` it lands in RAM, about half of the Pico 2 W's SRAM. Fixes: drop `copy_to_ram`, or tag the blob `__in_flash("CYW43439_FIRMWARE")`. The firmware has to be loaded into the CYW43 even just to blink the LED — [RPi forum t=384445](https://forums.raspberrypi.com/viewtopic.php?t=384445).
- Adding Wi-Fi increases RAM use by ~40 KB (arduino-pico docs), and lwIP "looks like it'd use 70-odd-kB" (forum estimate). That gives roughly **~110 KB** for networking — [arduino-pico WiFi docs](https://arduino-pico.readthedocs.io/en/latest/wifi.html); [RPi forum lwIP](https://forums.raspberrypi.com/viewtopic.php?t=341728) (search-summary level; configuration-dependent).
- Measured neighbour workload: TFLM person detection (MobileNet v1 α=0.25, 7.16 M MACs) on Pico 2 used a 300,568 B flash model and an 82,308 B tensor arena, ~405 KB of 520 KB SRAM in total. Latency was **190.4 ms on one core → 98.9 ms (1.92×)** after splitting CMSIS-NN kernels across both cores and copying the model from XIP flash into SRAM — [KrystofBo/pico-person-detection](https://github.com/KrystofBo/pico-person-detection).

### Inferences
- **Suggested RAM budget [EST]:**

  | Item | Size |
  |---|---|
  | Wi-Fi/BT + lwIP | ~110–130 KB |
  | SDK, stacks, USB-HID | ~20–30 KB |
  | Audio ring buffer, 1 s @ 16 kHz int16 | 32 KB (or 2 s = 64 KB) |
  | DSP scratch | ~10 KB |
  | Feature history, 1–2 s | ~4–16 KB |
  | Small classifier (weights copied to SRAM + arena) | 40–150 KB |
  | **Total** | ~220–370 KB of 520 KB |

  Headroom is comfortable if `copy_to_ram` is avoided.
- **Core split:**
  - core1: audio DMA (I2S/PDM via PIO, or ADC with DMA), framing, FFT, pitch, onset, features, template or NN classifier. It produces a compact feature record every hop and events.
  - core0: CYW43/lwIP (or BTstack), text serialisation to Jev, the local fast-path cursor mapping, USB HID.
  - Use the SDK inter-core FIFO or a lock-free ring buffer. Keep core1 code and data in SRAM so XIP flash stalls from Wi-Fi activity on core0 don't cause jitter.
- **Latency budget for the local fast path [EST]:** 32 ms window + 10 ms hop + ~1 ms compute + 1–8 ms USB HID poll ≈ **≤50 ms** sound-to-cursor. A cloud round-trip adds network RTT plus model latency on top. This supports doing continuous movement (pitch → velocity) locally and sending only discrete gesture decisions or summaries to Jev.
- Placing per-core hot buffers in different SRAM banks (e.g. the 4 KB SRAM8/9 for stacks) reduces bus contention between cores; this follows from the datasheet's bank layout but was not benchmarked.

### Gaps
- No authoritative, measured RAM figure for the pico-sdk `pico_cyw43_arch_lwip_*` or BTstack configuration on the Pico 2 W; the ~40 KB and ~70 KB numbers are community estimates.
- No measurement of CPU load of the CYW43 driver or lwIP on core0 during steady Wi-Fi traffic.
- BLE-HID (BTstack) RAM footprint on the Pico 2 W was not found.

---

## 5. Tiny ML on RP2350: TFLM / LiteRT Micro, Edge Impulse, DS-CNN, int8

### Takeaway
TFLM (now "LiteRT for Microcontrollers") with CMSIS-NN runs on the RP2350 in practice: person detection, a Zephyr micro_speech demo, and a 2026 Polish KWS paper on the Pico 2. However, the official `raspberrypi/pico-tflmicro` has an **open, unresolved RP2350 issue since Aug 2024**. Edge Impulse ships official RP2350 / Pico 2 W firmware, though audio support on it is undocumented. The right-sized model for VOX is a DS-CNN-S-class or smaller int8 CNN over ~0.5–1 s of log-mel (≈20–40 KB weights). Extrapolating from measured person-detection throughput, that should land in the tens of ms per inference.

### Cited Findings
- `raspberrypi/pico-tflmicro` issue #18 "RP2350 support" was opened 15 Aug 2024 with no assignee, linked PR or maintainer response — [pico-tflmicro #18](https://github.com/raspberrypi/pico-tflmicro/issues/18). A search result mentions a community Pico 2 patch that was not merged — [search summary; arduino-pico #3249](https://github.com/earlephilhower/arduino-pico/issues/3249), [tflite-micro #2730](https://github.com/tensorflow/tflite-micro/issues/2730).
- Zephyr + LiteRT for Microcontrollers demo on RP2350 (`west build -b rpi_pico2/rp2350a/m33`) running the micro_speech "yes/no" model. No latency or memory numbers published — [stgloorious/rpi-pico2-litert](https://github.com/stgloorious/rpi-pico2-litert).
- TFLM + CMSIS-NN person detection on Pico 2: 190.4 ms single-core → 98.9 ms dual-core, with an 82 KB arena and 300 KB model (see §4) — [KrystofBo/pico-person-detection](https://github.com/KrystofBo/pico-person-detection).
- A 2026 MDPI paper reports compact KWS architectures, quantization and on-device validation **on the Raspberry Pi Pico 2**. The full text was 403-blocked, so no numbers were extracted — [Applied Sciences 16(15):7844](https://doi.org/10.3390/app16157844).
- Edge Impulse officially supports the RP2350 ("dual Cortex M33 @ 150MHz") with a "Pi Pico 2 (RP2350)" firmware including a Wi-Fi version. The documented sensors are the same as for RP2040 (accelerometers, DHT11, ultrasonic, analog ADC). **Microphone/audio support on RP2350 isn't documented**; the only documented mic is the Arduino Nano RP2040 Connect's MP34DT05 — [Edge Impulse Pico docs](https://docs.edgeimpulse.com/hardware/boards/raspberry-pi-pico). The open-source firmware has build flags for "Raspberry PI Pico 2 (RP2350)" and "Pico 2 WiFi" — [edgeimpulse/firmware-pi-rp2xxx](https://github.com/edgeimpulse/firmware-pi-rp2xxx/blob/main/README.md).
- **DS-CNN sizes ("Hello Edge")**, where memory counts 8-bit weights plus activations and "Ops" counts operations per inference:

  | Budget class | Accuracy | Memory | Ops |
  |---|---|---|---|
  | S (≤80 KB, 6 MOps) | 94.4% | 38.6 KB | 5.4 M |
  | M (≤200 KB, 20 MOps) | 94.9% | 189.2 KB | 19.8 M |
  | L (≤500 KB, 80 MOps) | 95.4% | 497.6 KB | 56.9 M |

  Budgets assume 10 inferences/s. 8-bit quantization gave the same or marginally better test accuracy vs float (e.g. CRNN 95.00% → 95.03%, GRU 94.68% → 94.68%), without retraining — ["Hello Edge", Zhang et al.](https://arxiv.org/pdf/1711.07128). Code and pretrained models: [ARM-software/ML-KWS-for-MCU](https://github.com/ARM-software/ML-KWS-for-MCU); Arm ML-Zoo KWS models (DS-CNN, MicroNet) in int8 TFLite — [Arm ML-Zoo](https://github.com/Arm-Examples/ML-zoo/tree/master/models/keyword_spotting/micronet_small/tflite_int8).
- MLPerf Tiny KWS (DS-CNN on Speech Commands):
  - Syntiant: 5.95 ms vs "the reference system at 181.92 ms".
  - Latent AI: 0.39 ms FP32 / 0.42 ms INT8 (accelerator-class platforms).

  [Embedded.com](https://www.embedded.com/benchmarks-show-ai-performance-on-tiny-systems/). MLPerf Tiny v1.4 closed July 2026 with 9 organisations and 25 systems; v1.3 (2025) added a Streaming Wake Word workload — [MLCommons v1.4](https://mlcommons.org/2026/07/mlperf-tiny-v1-4-results/). ST reports the STM32U3's hardware signal processor reduces image-classification time by up to 76% vs the same Cortex-M33 config (not KWS) — same source.
- TensorFlow blog: end-to-end TinyML audio classification on the RP2040 (the precursor to pico-tflmicro audio examples) — [TensorFlow Blog 2021](https://blog.tensorflow.org/2021/09/TinyML-Audio-for-everyone.html).

### Inferences
- **Latency estimate for DS-CNN-S on RP2350 [EST]:** "Hello Edge" counts ~5.4 M ops (≈2.7 M MACs). Person detection ran 7.16 M MACs in 190 ms single-core ≈ 26.6 ns/MAC ≈ 4 cycles/MAC (including XIP effects). Linear scaling gives **~70 ms single-core, ~40 ms dual-core** for DS-CNN-S, and ~10–15 ms for a ~0.5 M-MAC custom model. Depthwise layers often run less efficiently per MAC than pointwise ones in CMSIS-NN, so treat this as ±2×.
- **What VOX actually needs:** the gesture vocabulary is small (hum, whistle, click, double-click, hiss, up-glide, down-glide, plus background), and continuous control comes from DSP features, not the NN. So a **tiny 1–2 conv-layer CNN or even an MLP over pooled features** is likely enough:
  - a CNN over a 0.5 s × 20–40 mel log-spectrogram, ~10–30k params; or
  - an MLP over the §2 feature bank's per-gesture statistics (duration, mean and slope of f0, clarity, flatness, flux-peak count), which is smaller still.

  Run it only on segments the VAD or onset detector flags, e.g. at gesture end, rather than 10×/s continuously.
- **Toolchain choice:** Edge Impulse gives the fastest path to a trained int8 model plus C++ DSP code, but its RP2350 audio ingestion isn't documented, so plan to feed it your own buffers via the exported C++ library. Plain TFLM + CMSIS-NN built into the pico-sdk project is the more controllable route, and a well-trodden path now exists (pico-person-detection shows the dual-core split and SRAM copy tricks).
- int8 is the right default. Hello Edge shows no accuracy loss, and CMSIS-NN is optimised for int8 on DSP-extension cores. Keep float for DSP features and quantize only the NN input.

### Gaps
- No MLPerf Tiny KWS result specifically for a Cortex-M33 MCU (or RP2350) was retrieved. The v1.4 page didn't include per-device tables in the fetched content.
- The MDPI Pico 2 KWS paper's latency, RAM and accuracy numbers are unknown (403). That paper is the single most relevant measured source and should be read manually.
- Edge Impulse's current state for PDM/I2S microphones on Pico 2 W is unconfirmed.
- Exact Arm ML-Zoo DS-CNN-S int8 .tflite file size was not captured. The search engine's "≈156 KB" claim is arithmetic on float params and is **wrong**: 39k int8 params ≈ 39 KB, consistent with Hello Edge's 38.6 KB.

---

## 6. Few-shot / user-enrolled templates: DTW, nearest prototype, $1-style matching

### Takeaway
For per-user custom gestures, template matching beats training. Store 3–5 enrolment examples per gesture as short sequences: pitch contour in semitones relative to the start, plus energy and voicing flags, resampled to fixed length. Match by banded DTW or a normalised Euclidean distance with a reject threshold. This costs microseconds to a fraction of a millisecond on the M33 **[EST]**, adapts to each voice, and needs no retraining. If an NN embedding is available, nearest-class-mean (prototypes) over embeddings is the literature-standard few-shot KWS approach.

### Cited Findings
- Prototypical few-shot KWS: users provide a few examples at enrolment, class prototypes are the mean embedding, and inference picks the nearest prototype by distance. Open-set variants add rejection ("dummy" prototypes) — [Few-Shot Open-Set Learning for On-Device Customization of KWS (arXiv 2306.02161)](https://arxiv.org/pdf/2306.02161); [Dummy Prototypical Networks (arXiv 2206.13691)](https://axi.lims.ac.uk/paper/2206.13691); [Few-Shot KWS with Prototypical Networks (arXiv 2007.14463)](https://arxiv.org/pdf/2007.14463).
- In the on-device-customisation study, a DSCNN-L feature extractor trained with triplet loss on normalised outputs plus an open-set nearest-class-mean (openNCM) classifier gave the best accuracy, beating prototypical-network training — [arXiv 2306.02161](https://arxiv.org/pdf/2306.02161) (search-summary level).
- On-device learning of user speech characteristics has been shown to fit TinyML budgets: 23.7k parameters and 1 MFLOP per training epoch — [arXiv 2403.07802](https://arxiv.org/pdf/2403.07802) (search-summary level).
- On-device few-shot customisation of tiny KWS models — [IEEE Micro 2023](https://dl.acm.org/doi/abs/10.1109/MM.2023.3311826).
- The Vocal Joystick system extracted continuous vocal parameters (pitch, loudness, vowel quality) in real time and "transformed [them] via adaptation and acceleration" into continuous control signals. A longitudinal study had 5 motor-impaired and 4 non-impaired participants — [Harada et al., Disability & Rehab: AT (PubMed)](https://pubmed.ncbi.nlm.nih.gov/18416516/); [Vocal Joystick engine](https://www.sciencedirect.com/science/article/abs/pii/S0885230810000483).

### Inferences
- **Template representation [design]:**
  - f0 in semitones relative to the gesture's first voiced frame (key-invariant across users and days).
  - Normalised time: resample to 32–64 points, as $1 does with 64 points.
  - Voicing mask, plus optionally logE in dB relative to the noise floor.
  - Clicks are represented as an onset-count/inter-onset-interval vector rather than a contour.
- **$1-recognizer caveat:** $1 normalises rotation, scale and translation. For pitch gestures, **rotation invariance must be dropped**: an up-glide and a down-glide differ by exactly that. Scale invariance should apply only on the time axis, since pitch extent in semitones carries meaning. So "$1-style" in practice means resample to N points, translate to the start pitch, then compare with Euclidean distance or banded DTW. The $1 paper (Wobbrock et al., UIST 2007) wasn't re-fetched this session.
- **Cost [EST]:** DTW on 64×64 with a Sakoe-Chiba band of ±8 is ~1k cells; × 8 gestures × 5 templates = 40k cell updates ≈ 0.1–0.3 ms on the M33. Storage: 64 floats × 3 channels × 40 templates ≈ 30 KB in float or ~8 KB in int8/Q7, which can go in flash via the SDK's flash-write APIs.
- **Rejection:** set a per-class threshold at, say, the max intra-class enrolment distance × 1.3–1.5. Anything beyond it is "unknown" and gets forwarded to Jev with its features, which fits the cloud-arbiter design.
- **Hybrid path:** the local fast path does DSP-driven continuous movement plus a template or prototype classifier for a few discrete actions. Everything ambiguous goes to Jev as serialized features (f0 contour summary, duration, onset count, flatness), so the cloud sees the same features the local classifier used.

### Gaps
- No published work found that applies DTW or $1-style matching specifically to hummed pitch-contour *gestures* for cursor control. Query-by-humming literature (DTW on pitch contours vs melodies) is the nearest analogue and wasn't deep-read here.
- No measured DTW timing on Cortex-M33.

---

## 7. What changes on a Raspberry Pi 4/5

### Takeaway
On a Pi you can drop hand-rolled C for aubio (YIN-FFT, onsets) or librosa, and add neural pitch trackers. **PESTO** is the standout: 130k params, <10 ms latency, streaming VQT, CREPE-level accuracy, pip-installable. CREPE (22.2M params) and SPICE (2.38M) are heavier. YAMNet (3.7M weights, 0.96 s window) is a pretrained audio embedding suited to few-shot matching of *discrete* vocal gestures but too slow-windowed for continuous control. The Pi also allows larger buffers, float64, and Python prototyping of the exact MCU pipeline.

### Cited Findings
- **PESTO (TISMIR 2025 / arXiv 2508.01488):**
  - Self-supervised, transposition-equivariant, Siamese, with a Toeplitz fully-connected layer.
  - **130k parameters** (vs CREPE's 22.2M).
  - Input: VQT with fmin 27.5 Hz and 3 bins per semitone. A streamable VQT uses cached convolutions.
  - **Latency <10 ms**. RTF 0.0354 on an Intel i9-12900H CPU and 0.0032 on an RTX A2000; the authors claim it is ~60% faster than YIN on CPU and 3–5× faster than PENN.
  - RPA: MIR-1K 97.7% (CREPE 97.5%), MDB-stem-synth 97.0% (CREPE 97.3%), PTDB speech 89.7% (CREPE 87.1%).
  - pip package with pretrained models.

  [arXiv 2508.01488 (HTML)](https://arxiv.org/html/2508.01488); [TISMIR article](https://transactions.ismir.net/articles/10.5334/tismir.251). The ~520 KB model size in the fetch summary is an estimate (130k × 4 bytes), not a published figure.
- **CREPE:** 16 kHz input (resampled otherwise), 1024-sample frames, 10 ms default step, 360 pitch bins at 20 cents. Model capacities tiny/small/medium/large/full, optional Viterbi smoothing, and a per-frame voicing-confidence output — [marl/crepe](https://github.com/marl/crepe).
- **SPICE:** self-supervised pitch estimator with 2.38M parameters — [arXiv 1910.11664](https://arxiv.org/pdf/1910.11664); [Google Research blog](https://research.google/blog/spice-self-supervised-pitch-estimation/).
- **YAMNet:** MobileNet-v1 depthwise-separable, ~3.7M weights, 69.2M multiplies per 0.96 s frame, 521 AudioSet classes. Sliding 0.96 s windows with a 0.48 s hop; TFLite versions exist — [YAMNet TFLite fork README](https://github.com/antonyharfield/tflite-models-audioset-yamnet/blob/master/README.md); [TF Hub tutorial](https://www.tensorflow.org/hub/tutorials/yamnet); [transfer-learning tutorial](https://www.tensorflow.org/tutorials/audio/transfer_learning_audio).
- **aubio** provides `yinfft` (default), `yin`, `yinfast`, `mcomb`, `fcomb`, `schmitt`, `specacf` pitch methods and 9 onset functions, with CLI and Python bindings — [aubiopitch man page](https://aubio.org/manpages/latest/aubiopitch.1.html); [aubio Python analysis docs](https://aubio.readthedocs.io/en/latest/py_analysis.html).

### Inferences
- **Pi pipeline [design]:** ALSA/PortAudio at 16 kHz with a 160-sample hop, then aubio `yinfft` or PESTO streaming for f0 and aubio `specflux`/`hfc` for onsets. Discrete gesture classification uses YAMNet embeddings (or a small CNN on log-mel) with nearest-prototype over user enrolment. The same feature text goes to Jev.
- **PESTO vs YIN on a Pi [EST]:** at RTF 0.035 on a desktop i9, a Pi 5 (Cortex-A76) is perhaps 3–5× slower, i.e. RTF ~0.1–0.2, which is still comfortably real-time. Not measured on a Pi.
- **YAMNet's 0.96 s window** adds ≥~1 s of decision latency, fine for "was that a double-click or a sneeze" but not for continuous glides. Its generic AudioSet classes also won't separate "up-glide hum" from "down-glide hum". Use it as an embedding plus prototypes, not as a classifier.
- The Pi path is also the best **development harness** for the MCU: prototype the exact float pipeline in Python (numpy or aubio), freeze parameters, then port to CMSIS-DSP C and compare frame-by-frame.

### Gaps
- No measured PESTO, CREPE-tiny or YAMNet latency on a Raspberry Pi 4/5 was found.
- CREPE per-capacity parameter counts (tiny…full) weren't retrieved; only "full" = 22.2M via the PESTO paper.
- librosa `pyin` cost and real-time suitability were not researched.

---

## 8. Datasets for testing non-verbal vocal gestures

### Takeaway
No public dataset matches VOX's gesture set (hums, whistles, glides, tongue clicks as commands). Combine several:
- MIR-QBSH (hummed melodies, 8 kHz) for pitch tracking on hums.
- The Deeply Nonverbal Vocalization Dataset for tongue-clicks, lip-pops and teeth sounds.
- VocalSound for negatives (coughs, sniffs, throat-clears, sighs, laughs, sneezes).
- MIR-1K / MDB-stem-synth / PTDB as pitch-accuracy benchmarks.

Then record your own per-user enrolment set.

### Cited Findings
- **VocalSound (ICASSP 2022):** 21,024 crowdsourced recordings from 3,365 subjects of laughter, sighs, coughs, throat clearing, sneezes and sniffs, with age, gender, native language, country and health metadata. Adding it to training improved vocal-sound recognition by 41.9% — [arXiv 2205.03433](https://arxiv.org/abs/2205.03433); [YuanGongND/vocalsound](https://github.com/YuanGongND/vocalsound).
- **Deeply Nonverbal Vocalization Dataset:** 56.7 h from 1,419 speakers (South Korea). 16 classes including **tongue-clicking, lip-popping, lip-smacking, teeth-chattering, teeth-grinding**, nose-blowing, coughing, yawning, throat clearing, sighing, panting, crying, laughing, sneezing, moaning, screaming. Metadata includes age, sex, noise level and quality — [GitHub](https://github.com/deeplyinc/Nonverbal-Vocalization-Dataset); [OpenSLR 99](https://www.openslr.org/99/).
- **MIR-QBSH (Jang):** 48 ground-truth monophonic MIDI files plus 4,431 hummed or sung queries of nursery rhymes. Each is 8 s at **8 kHz**, recorded by students over 7 years at Tsing Hua University — [ISMIR 2023 paper describing it](https://archives.ismir.net/ismir2023/paper/000077.pdf); [MIREX QBSH](https://music-ir.org/mirex/wiki/2020:Query_by_Singing/Humming).
- **MNV-17:** 7.55 h of performative Mandarin speech with 17 nonverbal-vocalization classes — [arXiv 2509.18196](https://arxiv.org/pdf/2509.18196).
- **Pitch benchmarks** used by PESTO: MIR-1K, MDB-stem-synth, PTDB (speech) — [arXiv 2508.01488](https://arxiv.org/html/2508.01488).
- Non-verbal vocal interaction (NVVI) modalities include humming, whistling and tongue clicking, per a usability thesis — [Virginia Tech NVVI thesis](https://vtechworks.lib.vt.edu/server/api/core/bitstreams/39bfe071-4df4-44a5-b945-4c28a7965eee/content).
- A related paper on nonverbal sound detection for disordered speech — [arXiv 2202.07750](https://arxiv.org/abs/2202.07750).

### Inferences
- MIR-QBSH's 8 kHz rate matches the "decimate to 8 kHz for hums" option in §1 and lets you test pitch tracking at that rate directly. Its hummed melodies contain real glides and note transitions, which are useful for octave-error and jump-limit tuning.
- The Deeply dataset's tongue-click and lip-pop classes are the only public labelled source found for click-type gestures. Its crowdsourced phone recordings with noise-level metadata make it a good robustness test for the flux-based click detector.
- VocalSound is best used as the **negative/"background" class**, so that coughs, sniffs and throat-clears don't trigger cursor actions. For an always-listening assistive device that false-positive rate matters more than raw accuracy.
- Whistles and deliberate pitch glides have no public labelled dataset found; plan a small in-house recording protocol (per user, several mics and rooms).

### Gaps
- No public dataset of whistles or of deliberate hum-glide gestures for HCI was found. The Vocal Joystick project collected data (vowel quality, pitch, loudness), but public availability wasn't checked.
- MIR-QBSH download location and licence weren't verified in this session.
