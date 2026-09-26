# Prior art: twenty years of vocal pointers

[Index](index.md) · [Hardware](hardware.md) · [Signal processing](signal-processing.md) · [Gestures and phrases](gesture-vocabulary.md) · [Decision models](decision-models.md) · [Phone control](phone-control.md) · [Prior art](prior-art.md) · [Latency and risks](latency-and-risks.md) · [Roadmap](roadmap.md) · [Sources](sources.md)

**Summary.** The evidence favours:

- hums over whistles
- pitch relative to each sound's start, not absolute notes
- local 10 ms control loops
- discrete speed rather than loudness-to-speed
- recursive grids when latency is high

Shipping products converged on "sound as switch, something else as pointer". No one publishes false-trigger rates.

## Continuous vocal pointing

The **Vocal Joystick** (University of Washington) mapped vowel quality to direction, loudness to speed and consonant bursts to clicks, with 10 ms updates. Expert throughput was **1.65 bits/s**, about **30% of a mouse** (5.48 bits/s) ([Harada et al., ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)). In a 10-session study, users without motor impairments matched the experts. Motor-impaired users reached 1.17 bits/s, and two of them matched or beat their own mouse ([Harada et al., CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)). **Loudness-to-speed was the weak link**: the authors called a better loudness mapping "one of the most important areas of improvement" (same source). VOX drops loudness from gestures and uses speed buckets in cursor mode.

| Method (novices, target acquisition) | Result | Source |
|---|---|---|
| Vocal Joystick | Baseline; 49 s on a 600-px circle | [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf) |
| Dragon Mouse Grid (recursive 3×3) | **Not significantly slower** than the Vocal Joystick | same |
| Speech Cursor (constant velocity until "stop") | Worst; 155 s on the circle | same |
| Dragon cursor | "Jerky", updating roughly four times a second | same |

**For Jev cursor mode:** 2–4 decisions per second with a model-issued stop is Speech Cursor territory. The recursive grid is the latency-tolerant precedent that worked. See [Decision models](decision-models.md#jev-cursor-mode-is-design-b-applied-to-pointing).

## Pitch and hum control

| Study | Finding | Implication for VOX |
|---|---|---|
| Hummed Tetris | Pitch moving about **2 semitones** counted; hummed control **2.5× faster than speech** (3.5 vs 1.4 cells/s); a "short soft click" fixed short/long confusion ([Sporka et al., ASSETS'06](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-sigaccess-nsi-paper.pdf)) | Contours work; audible tick at the long-hum threshold |
| Orthogonal vs melodic pointer | Relative pitch **1.4 s vs 2.6 s** per target; every user overshot in melodic mode; 3 of 4 preferred humming to whistling ([Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)) | Relative pitch; no "low tone = down" |
| Longitudinal hum vs VJ | **Hum click 578 ms vs VJ "k" 857 ms**; hummers re-picked their threshold pitch daily; users asked for noise filters and cursor recovery ([Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)) | Hums as clicks; recentre command |
| Voice as sound | Detector deliberately "does not calculate the absolute pitch" ([Igarashi & Hughes 2001](https://www-ui.is.s.u-tokyo.ac.jp/~takeo/papers/voice.pdf)) | Same conclusion in 2001 |
| Hums preferred for continuous input | Least tiring sound ([Funk et al., CHI 2020](https://dl.acm.org/doi/10.1145/3313831.3376816)) | Core input choice |

## Shipping systems

| System | What it does | Source |
|---|---|---|
| Talon | "pop" and "hiss" noises alongside eye tracking | [Hands-Free Coding](https://handsfreecoding.org/2021/12/12/talon-in-depth-review/) |
| Talon 1.0 (20 Sep 2026) | `noise(pop)`, `noise(dental_click)` bindings | [Talon changelog](https://talonvoice.com/dl/latest/changelog.html) |
| Parrot.py | Stacked false-trigger checks: percentage, power, times, throttle, continual threshold; 4 frames ≈ 65 ms | [PATTERNS.md](https://raw.githubusercontent.com/chaosparrot/parrot.py/master/docs/PATTERNS.md) |
| Apple Sound Actions | AssistiveTouch "taps, pinches, and scrolling" from sounds | [AbilityNet](https://mcmw.abilitynet.org.uk/how-to-perform-actions-on-your-iphone-or-ipad-using-sounds-as-part-of-assistivetouch-in-ios-18) |
| Project Gameface | Face-driven Android cursor; VOX's app template | [Google Developers Blog](https://developers.googleblog.com/project-gameface-launches-on-android/) |
| PiPePoPo | Flute-driven USB mouse, YIN on RP2040 | [GitHub](https://github.com/JorenSix/PiPePoPo) |

**No shipping product uses pitch contours.** Recent research has moved to silent teeth clicks, because voice is "intrusive and non-discreet" ([arXiv 2408.11346](https://arxiv.org/abs/2408.11346)).

## Latency research

In the mouse lag study, errors rose from **3.6% to 11.3% at 225 ms**, lag cost grew with task difficulty, and users fell into "wait-and-see" ([MacKenzie & Ware 1993](https://www.yorku.ca/mack/CHI93b.html)). Nielsen puts 0.1 s at "instant" and 1 s at "flow kept" ([NN/g](https://www.nngroup.com/articles/response-times-3-important-limits/)).

## Gaps the prior art leaves

- **No false-trigger rates per hour** for Talon, Parrot or Sound Actions.
- Every study used **headsets in quiet rooms** ([Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)).
- **No peer-reviewed study since 2020** on hum-driven phone control.
- Performance improved across days, so **one-session tests understate** ([CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)).
- **No audio-native decision models** ([Decision models](decision-models.md#audio-native-jev-likes-do-not-exist-yet)).

## Open questions / to verify on hardware

- Does the 1.4 vs 2.6 s relative-pitch advantage hold for **phone swipes** rather than a desktop pointer?
- Is VOX's Fitts' throughput in cursor mode anywhere near the Vocal Joystick's **1.65 bits/s**?
- Measure false triggers with a **collar or desk mic** rather than a headset.
- Test over **multiple sessions**, not one.
