# Prior art: controlling a cursor with non-speech vocal sounds (hums, vowels, pitch, clicks, pops, hisses)

Scope note: this covers foundational work (2001–2012) and what is current as of September 2026. Items marked **[CURRENT 2026]** are shipping or recently updated. Items marked **[FOUNDATIONAL]** are older research that still sets the benchmarks. Numbers come from the primary papers wherever I could get the full text (Vocal Joystick ASSETS'06 and CHI'09, Igarashi & Hughes UIST'01, Sporka et al. UAIS 2006 and ASSETS'06, Mahmud et al. INTERACT'07, MacKenzie & Ware CHI'93). Everything else is marked as coming from an abstract or secondary source.

## 1. The Vocal Joystick (University of Washington, ~2005–2009) [FOUNDATIONAL]

### Takeaway
The Vocal Joystick (VJ) is the reference system. It mapped vowel quality to direction (4 or 8 directions), loudness to speed, and short consonant bursts ("k"/"ck", "ch") to discrete actions. It processed audio every 10 ms. Expert throughput was 1.65 bits/s, which is about 30% of a mouse and about 70% of a hand-operated velocity-control joystick. Over 10 sessions, users without motor impairments reached expert level and users with motor impairments reached 70% of it. The weakest part was the mapping from loudness to speed, not the vowel-to-direction mapping.

### Cited Findings
**How it works**
- The system continuously controls the cursor "by varying vocal parameters such as vowel quality, loudness and pitch." It processes vocal characteristics "every audio frame (10ms)," so a change in the voice "is reflected immediately upon the interface" — [Harada et al., ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Vowel quality is classified by a multi-layer perceptron adapted to each user. The result is mapped onto the 2-D vowel space: vowels map to directions on an 8-way "compass" (IPA vowels around the periphery of the vowel chart). A 4-way mode uses only the vowels on the horizontal and vertical axes. This "increases the tolerance to slight deviations from the expected vowel sounds, albeit at the expense of sacrificing the number of directions" — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Adaptation: the user "simply holds each of the vowel sounds for two seconds at their normal loudness." Speed: "the softer the sound, the slower the cursor movement and vice versa" — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Loudness is mapped to velocity with "an exponential mapping between the power of the audio signal ... and the resulting pointer velocity" (Malkin, Li & Bilmes, ASRU 2005) — [Harada et al., CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- Discrete sounds are "short sounds starting with a consonant." "The consonant 'k' is used to issue a mouse click," so "the system can respond to the command with minimal processing delay" — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- The system also tracks loudness, pitch, and "discrete non-vowel sounds such as 'ck' and 'ch.'" A "neutral" vowel (as in "but") changes loudness or pitch without changing direction — [Harada, Wobbrock & Landay, IBM overview ~2009](https://faculty.washington.edu/wobbrock/pubs/ibm-09.pdf)
- The authors argue this avoids the "Midas touch" problem of eye trackers, because "the cursor moves only while the user is vocalizing and stops as soon as the vocalization is stopped" — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)

**Fitts' law / expert study (ASSETS'06)**
- Participants: 4 "expert" users, all from the research team, none motor-impaired, each with more than a month of use. Design: 2×4×3×8 (modality × ID {2,3,4,5 bits} × width {12,24,32 px} × 8 approach angles) — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Regression: VJ MT = 606.15·ID + 411.63 ms (R² = 0.986), IP = 1.65 bits/s. Mouse MT = 182.64·ID + 324.9 ms (R² = 0.965), IP = 5.48 bits/s — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- IP relative to the mouse: eye tracker 0.71, ultrasonic head pointer 0.61, isometric joystick 0.43, displacement joystick 0.42, **Vocal Joystick 0.30** — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf). The later overview restates this as "roughly 70% of the performance of hand-operated joysticks" — [IBM overview](https://faculty.washington.edu/wobbrock/pubs/ibm-09.pdf)

**Novice comparison with speech-based cursor methods (ASSETS'06)**
- 9 novices (ages 18–25, no impairments) used the 4-way VJ, Dragon "Mouse Grid" (MG, recursive 3×3 grid), and "Speech Cursor" (SC: "mouse move <direction>" at constant velocity). SC was significantly slower than VJ and MG. VJ and MG did not differ significantly — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Tracing a 600-px circle took an average of 49 s with VJ versus 155 s with Speech Cursor — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Users rated Speech Cursor significantly more frustrating than VJ. Five of the nine had about 5 unrecognized direction words per trial. VJ needed only about 8 s of acoustic training in total, against 3 min for the Dragon methods — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Dragon's constant-velocity cursor is "jerky, updating its position roughly four times a second," with a default of about 4 px/s — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Earlier "Voice Mouse" (Siena, 2001) used /a/ up, /e/ right, /i/ down, /o/ left, with inertial motion and /a-e/ for click. Recognizing the vowel before movement began "could take around four seconds" — [ASSETS'06 related work](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)

**Longitudinal study with motor-impaired users (CHI'09)**
- 9 participants finished (5 motor-impaired [MI]: MS, idiopathic neuropathy, muscular dystrophy, CP + fibromyalgia, Parkinson's; 4 not impaired [NMI]). Each did 10 sessions of about 1 h over 2.5 weeks, 99 hours of data in total. Fitts reciprocal task used IDs of 1.52–3.37 bits. Steering task used IDs of 4.49–12.57 bits — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- By the 5th session, all participants could recall all 8 vowel-to-direction mappings without the compass — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- Movement time improved 25–49% for NMI and 21–40% for MI from first to last session — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- Final throughput averaged 1.64 bits/s for NMI (about equal to the 1.65 expert level; 2 NMI participants beat it) and 1.17 bits/s for MI (70% of NMI). Mouse throughput was 3.9–4.6 bits/s for MI and 4.9–6.2 for NMI — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- For two MI participants whose preferred device was a touchpad, VJ throughput "equaled or exceeded their mouse throughput" and reached 75% and 61% of their touchpad throughput. A power-curve projection put them at touchpad parity after another 8 and 11 sessions — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- Failure modes:
  - Many participants could not reliably produce the "a," "ɑ," and "ɨ" vowels, which depend on dialect.
  - Steering was hard for the MI group: speed was inconsistent as vowels changed, and error rates were high.
  - Users did well in VoiceDraw tracing at a *fixed* speed but struggled when loudness controlled speed.
  - Movement was sometimes faster in some directions than others at the same loudness.
  - The system "would temporarily stop responding, or the movement ... became erratic" when users vocalized too loudly or made extraneous sounds at the start of an utterance.
  - The authors call a "better mapping between the loudness of the utterance and the resulting speed" "one of the most important areas of improvement."

  All from [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- Individual observations: a participant with reduced lung capacity made short vocalizations and moved in small segments. A Parkinson's participant's trembling voice lowered recognition accuracy. A ventilator puffing every 10 s did not disturb VJ. Throat-clearing was picked up by the mic but did not move the pointer — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- Feedback need: "explicit and constant feedback ... that reflects the loudness ... as well as the system's confidence ... whether the utterance is one of the vowel sounds or a non-vowel sound" — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- Vocal fatigue: in ASSETS'06, "we have not encountered any major complaints of vocal fatigue" — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf). This contrasts with Mahmud et al. 2007 (Section 2), where users reported VJ as more fatiguing than humming.

**Applications / widgets**
- VoiceDraw (ASSETS'07): vowels steer the brush and loudness sets brush thickness. It was co-designed with a painter who has had a spinal cord injury for over 30 years. A vocal marking menu is opened with "ck," steered with vowels, and confirmed with "ch." Continuous undo uses "aaa" to erase and "ooo" to restore — [IBM overview](https://faculty.washington.edu/wobbrock/pubs/ibm-09.pdf)
- The group was integrating VJ with Windows Vista Speech Recognition through a bar that switches between command/dictation mode and non-speech mode — [IBM overview](https://faculty.washington.edu/wobbrock/pubs/ibm-09.pdf)
- Other uses: VoicePen (a vowel pair drives a 1-D slider alongside a stylus) and VoiceBot (robot arm) — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)

### Inferences
- Vowel-to-direction mapping is learnable (recall was perfect by session 5). Production accuracy is the bottleneck, not memory. For VOX, a 4-way vowel set is the safer default; 8-way adds dialect failure points.
- Loudness-to-speed was the part users struggled with most, and cheap mics with varying distance and gain will make it worse. VOX should consider fixed-speed or stepwise speed with discrete accelerate/decelerate, or relative-pitch speed (see Section 2), rather than absolute loudness.
- VJ's advantage came from responding every 10 ms, i.e. feedback inside the motor loop. Any system that puts a slow decision stage inside that loop gives up the main reason VJ beat speech cursors.
- For target acquisition, VJ was not significantly faster than Mouse Grid for novices. A discrete, grid-like strategy is competitive for clicking targets. The continuous approach only wins clearly on paths (tracing, drawing, dragging).

### Gaps
- I did not retrieve the HLT/EMNLP 2005 engine paper (Bilmes et al.) or the ASRU 2005 loudness paper, so I have no exact vowel classifier accuracy or loudness curve parameters.
- End-to-end latency from voice onset to cursor movement is not reported in ms, beyond the 10 ms frame rate.
- How pitch was actually used for cursor control in VJ (as opposed to being extracted and exposed) is not quantified in the papers I read.

## 2. Other academic work: humming, whistling, pitch, tonguing, and recent non-verbal input

### Takeaway
Since 2001, the research has converged on a few points:
- Non-verbal sounds beat word commands for continuous control because they can be acted on while the sound is still going.
- Humming is easier and less tiring than whistling or vowel articulation. Whistling gives a purer pitch. Hissing is poor for pitch control.
- Relative pitch (the change from the starting pitch) works better than absolute pitch.
- Discrete events are best signaled by short bursts or tone length, backed by feedback.

Research after 2020 has moved toward discreet signals (teeth and tongue clicks sensed by IMU or bone conduction) and toward humming as the preferred continuous input in hands-busy settings.

### Cited Findings
**Igarashi & Hughes, "Voice as Sound," UIST 2001 [FOUNDATIONAL]**
- Three techniques:
  - "Control by continuous voice": voice acts as an on/off button, e.g. "Volume up, ahhhhhh" keeps raising the volume while the sound lasts.
  - "Rate-based parameter control by pitch": a 1-D joystick. "Move up, ahhhh" scrolls the map, and raising the pitch scrolls faster.
  - "Discrete control by tonguing": "Channel up, ta ta ta" steps the channel up by 3. Claps or finger snaps also work, because the system only detects peaks.

  [Igarashi & Hughes 2001 (PDF)](https://www-ui.is.s.u-tokyo.ac.jp/~takeo/papers/voice.pdf)
- Implementation: 16-bit / 22 kHz audio, STFT with a 2024-sample Hanning window, 256-sample hop (12 ms step). Voice is detected from total volume, and content below 375 Hz is removed to reduce background noise. Pitch *transitions* are detected by comparing time-shifted, frequency-shifted (±43 Hz) spectra; "our algorithm does not calculate the absolute pitch." Voice and tonguing detection were "fairly robust," but "pitch detection does not work well for some users" — [Igarashi & Hughes 2001](https://www-ui.is.s.u-tokyo.ac.jp/~takeo/papers/voice.pdf)
- Limitations: "requires an unnatural way of using the voice"; "Continuously making vocal sound also tires the throat. We found that breathed sound is less straining for long-term interaction and less annoying for other people." Claimed advantages: immediate continuous control, language independence, simplicity and robustness from simple signal processing. Positioned as a complement to speech recognition, not a replacement — [Igarashi & Hughes 2001](https://www-ui.is.s.u-tokyo.ac.jp/~takeo/papers/voice.pdf)
- No formal user study (prototype only) — [Igarashi & Hughes 2001](https://www-ui.is.s.u-tokyo.ac.jp/~takeo/papers/voice.pdf)

**Sporka, Kurniawan & Slavík, "Acoustic control of mouse pointer" (Whistling User Interface, U3I), UAIS 2006 [FOUNDATIONAL]**
- 1024-sample FFT frames. Pitch is the frequency with the highest energy. A tone counts when volume exceeds a user-set threshold. "No noise cancelling filters," so the method only works in low noise — [Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)
- *Orthogonal mode*: the starting pitch chooses the axis (below threshold ft = horizontal, above = vertical). The difference between current and starting pitch sets direction and speed, so users can slow down near the target or reverse. A tone shorter than tt (about 0.2 s) is a click — [Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)
- *Melodic mode*: absolute pitch within a user-chosen control octave maps to direction (e.g. C = up, E = right), at fixed speed — [Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)
- Results with 4 users: whistling took 1.4 s per target+click in orthogonal mode and 2.6 s in melodic. Humming took 1.8 s and 3 s. All users overshot in melodic mode. Two of four could not hiss properly, and the other two could not even reach the first target with melodic hissing. 3 of 4 preferred humming because whistling was more tiring; 1 preferred whistling for control. Conclusion: "whistling, which provides better control, is more strenuous than humming" — [Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)

**Mahmud, Sporka, Kurniawan & Slavík, "A Comparative Longitudinal Study of Non-verbal Mouse Pointer," INTERACT 2007 (U3I humming vs VJ) [FOUNDATIONAL]**
- 10 novices over 5 consecutive days, 96 trials per day. U3I was better on error rate and click emulation; VJ was better on the path-quality measures (target re-entry, axis crossing, movement variability/error). U3I approached VJ's performance by day 5, and VJ showed almost no learning effect — [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)
- **Click reaction time: humming click 578 ms (SD 84) vs VJ "k" click 857 ms (SD 129)**, a significant difference. When users raised their voice, "the sound 'k' was easily distorted and thus not recognized" — [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)
- Qualitative findings:
  - VJ was reported as more fatiguing because of vowel articulation over long distances. The ratings contradicted this (VJ was rated *less* tiring), possibly because U3I caused more overshoot.
  - Some users "could not reach the target in one continuous movement because of short[ness] of breath."
  - One user noticed "a noticeable delay between the voice and the corresponding cursor movement."
  - Users could not recover once the cursor went off-screen.
  - Both systems were "very sensitive" to background noise, and users asked for a filter for unwanted noises and the user's own stray vocalizations.
  - U3I users had to re-select their threshold pitch every day.

  [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)

**Sporka et al., "Non-speech input and speech recognition for real-time control of computer games" (Tetris), ASSETS 2006 [FOUNDATIONAL]**
- Humming gestures: a falling pitch = left, rising = right (the tone must move at least about 2 semitones to count, which filters small fluctuations). A flat tone under about 0.3 s = rotate; a longer flat tone = drop when released. Speech recognition (MS SAPI 5.1) had "significant delay of recognition (about 0.5 sec)" — [Sporka et al. ASSETS'06](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-sigaccess-nsi-paper.pdf)
- 12 participants. Hummed movement averaged 3.5 cells/s against 1.4 cells/s for speech (about 2.5× faster), with the gap growing over longer distances. Humming was up to 3× more accurate at high descent speeds. Users confused short and long tones, so the authors added "a short soft click" once the tone passed the duration threshold, which users received well — [Sporka et al. ASSETS'06](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-sigaccess-nsi-paper.pdf)

**Other voice-assisted cursor systems (from related-work sections)**
- Migratory Cursor (Mihara et al., ASSETS'05): a spoken command plus a numbered row of "ghost cursors" for coarse positioning, then a sustained "ahhhh" for fine movement. SUITEKeys: "move mouse down … stop." Grid-based cursors (Dai et al.): the 9-cursor grid was faster than the 1-cursor grid — [ASSETS'06 related work](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- A humming-grid cursor (i-CREATe 2010): two hum pitches plus a short alveolar fricative select grid cells and click. The abstract claims higher accuracy, shorter response time, and better preference than a spoken-digit Mouse Grid (abstract only; not verified) — [ACM DL abstract](https://dl.acm.org/doi/abs/10.5555/1926058.1926106)

**Recent work, 2020–2026**
- Funk et al., CHI 2020, "Non-Verbal Auditory Input for Controlling Binary, Discrete, and Continuous Input in Automotive User Interfaces": an online survey (N=100) followed by a driving-simulator study (N=16) measuring accuracy, distraction, and social acceptability. Finger snapping was preferred for binary and discrete input; **humming was the preferred modality for continuous input**; hand-clapping was preferred in the survey but not in practice (secondary summary of the abstract) — [ACM DL](https://dl.acm.org/doi/10.1145/3313831.3376816); [SIGCHI program](https://programs.sigchi.org/chi/2020/program/content/32454)
- STEALTHsense (Meta Reality Labs authors, arXiv Aug 2024): accelerometers in smart glasses detect 2 teeth-click patterns, with 0.93 average cross-person accuracy over 21 participants and an 88K-parameter model. The stated motivation is that voice "may not function well in noisy acoustic conditions" and is "intrusive and non-discreet" — [arXiv 2408.11346](https://arxiv.org/abs/2408.11346)
- TongueTap (ICMI 2023): 8 closed-mouth tongue gestures at 94% accuracy on head-worn devices, silent and invisible (search summary) — [ACM](https://dl.acm.org/doi/fullHtml/10.1145/3577190.3614120)
- Tongue micro-gestures via bone-conduction sound (UIST Adjunct 2024) — [ACM](https://dl.acm.org/doi/10.1145/3672539.3686336)

### Inferences
- The evidence favors humming as VOX's primary continuous signal: easiest to produce, least fatiguing, preferred for continuous input as recently as 2020, and faster for click emulation than a consonant. Whistling gives the cleanest pitch but tires users. Hissing is unreliable for pitch but was usable in Talon as a sustained on/off (see Section 3).
- Relative pitch (Igarashi: pitch transitions; Sporka orthogonal mode: current minus starting pitch; Tetris: at least 2 semitones of change) avoids daily recalibration of absolute pitch, which U3I users found burdensome. This suits a cheap mic on a Pico or Pi.
- Every system that worked needed low compute: 12 ms FFT hops and 1024-sample frames on 2001–2006 PCs. Feature extraction for pitch, energy, and onset on an RP2350 or a Pi is in line with this prior art. The heavy parts (VJ's per-user MLP vowel classifier) are the parts that can be dropped.
- The move after 2023 toward silent teeth and tongue clicks shows that social acceptability and noise robustness are still unsolved for audible non-speech input.

### Gaps
- I could not access "Hands Free Mouse: Comparative Study on Mouse Clicks Controlled by Humming" (CHI EA 2010; ACM returned 403) or the Humsher hummed text-entry work. Their click-timing results are missing.
- I found no peer-reviewed 2020–2026 study specifically on *hum- or vowel-driven cursor control on phones*. Recent work targets smart glasses, earables, and cars instead. This may be a real gap in the literature or a limit of my search.
- VoiceDraw's ASSETS'07 quantitative results were not retrieved (only the summary in the IBM overview).

## 3. Current tools: Talon, Parrot.py, Apple Sound Actions / Vocal Shortcuts, Voice Access, Project Activate, eViacam

### Takeaway
Shipping products use non-speech sounds almost entirely as **discrete switches** (pop = click, click/cluck/"ee" = switch actions). The one continuous use is a **sustained hiss held to scroll or drag** (Talon). None of them ships a vowel or pitch joystick. Continuous pointing is left to eye or head tracking, or to spoken grid and number overlays. False triggers are controlled with a small, distinct sound vocabulary, per-user practice or training, and multi-frame confidence, loudness, and throttle thresholds (Parrot.py).

### Cited Findings
**Talon Voice [CURRENT 2026]**
- Built-in noise recognition covers "pop" (click) and "hiss" (click-and-drag or text selection). Beta users could train custom noises through the parrot.py integration — [Hands-Free Coding review, 2021](https://handsfreecoding.org/2021/12/12/talon-in-depth-review/)
- With Tobii eye tracking, "popping sounds to zoom in on the screen and then to click" is the out-of-the-box mouse replacement. The review says Talon's command latency is lower than Dragon's — [Hands-Free Coding review](https://handsfreecoding.org/2021/12/12/talon-in-depth-review/)
- Community mouse plugin: a pop can left-click, end a drag, or stop a continuous scroll. `user.mouse_enable_hiss_scroll` lets "a prolonged 'hiss' sound ... continuously scroll" in a preset direction, with acceleration settings — [community docs](https://wolfmanstout.github.io/wolfmanstout_talon/plugin/mouse/)
- Changelog: "Fix issue where hiss noise could get stuck" (0.3.1, Jul 2022); "Parrot.py integration" (0.2.0, Jul 2021); "Add f0 frequency estimation for Parrot" (0.2.1, Sep 2021); **Talon 1.0 (dated Sep 20, 2026) adds `noise(pop)` and `noise(dental_click)` bindings in .talon files** and a third-generation eye-tracking algorithm — [Talon changelog](https://talonvoice.com/dl/latest/changelog.html). Talon runs a crowdsourced noise-collection site for training its noise model — [noise.talonvoice.com](https://noise.talonvoice.com/)

**Parrot.py (chaosparrot) [CURRENT, open source]**
- Workflow: record → train (PyTorch neural nets on MFCC features, with audiomentations augmentation) → analyse → map sounds to keyboard/mouse. It works with eye tracking for pointer movement — [parrot.py README](https://github.com/chaosparrot/parrot.py)
- "Any sound which is not part of normal speech can be used": pops, clicks, hisses, even non-human sounds. The motivation was that Talon then supported only pop and hiss — [TALON_VOICE.md](https://github.com/chaosparrot/parrot.py/blob/master/docs/TALON_VOICE.md)
- False-trigger controls in pattern configs:
  - `percentage`: model confidence, e.g. 85.
  - `power`: loudness floor, e.g. 10000, depending on the mic.
  - `frequency`: pitch floor.
  - `ratio`: between two classes, e.g. hiss vs whistle.
  - `continual_threshold`: lower thresholds to *keep* a sustained sound active once started.
  - `times`: N consecutive frames required.
  - `throttle`: e.g. 0.3 s before re-triggering, including across actions to suppress echoes.

  [PATTERNS.md](https://raw.githubusercontent.com/chaosparrot/parrot.py/master/docs/PATTERNS.md)
- Latency: detection runs about 60×/s (about 15 ms frames). Requiring `times: 4` raises latency from about 20 ms to about 65 ms, trading speed for fewer false positives — [PATTERNS.md](https://raw.githubusercontent.com/chaosparrot/parrot.py/master/docs/PATTERNS.md)
- Research notes: 30 ms frames with 15 ms overlap. Stop consonants are the shortest detectable sounds, about 45 ms including the pause. Real-world ambient noise usually sits above −70 dBFS. Breathing and coughing "resist effective modeling." A single dBFS threshold can separate sound from noise reliably — [RESEARCH.md](https://raw.githubusercontent.com/chaosparrot/parrot.py/master/docs/RESEARCH.md)

**Apple [CURRENT 2026]**
- Sound Actions for Switch Control (announced May 2021, shipped in iOS 15): "replaces physical buttons and switches with mouth sounds — such as a click, pop, or 'ee' sound — for users who are non-speaking and have limited mobility" — [Apple Newsroom, May 2021](https://www.apple.com/newsroom/2021/05/apple-previews-powerful-software-updates-designed-for-people-with-disabilities/)
- iOS 18 extended Sound Actions to AssistiveTouch (Settings → Accessibility → Touch → AssistiveTouch → Sound Actions). Sounds can trigger "taps, pinches, and scrolling," Control Centre, Camera, volume, and accessibility toggles. There is a Practice mode in which the device shows a tick when it detects the sound and can play an example of "what your device is listening for" — [AbilityNet, iOS 18](https://mcmw.abilitynet.org.uk/how-to-perform-actions-on-your-iphone-or-ipad-using-sounds-as-part-of-assistivetouch-in-ios-18)
- visionOS Sound Actions can trigger Tap, Recenter apps, Capture, Control Center, volume, screenshot, scroll up/down, and Siri, with a Practice option. Switch Control on Vision Pro accepts "voiced and voiceless sounds such as 'Oo' or a pop" — [Apple Vision Pro guide](https://support.apple.com/guide/apple-vision-pro/perform-actions-with-sounds-tan319fb0f99/visionos)
- The sound set: secondary sources list about 14 sounds including click, cluck, pop, uh, muh, la, eh, e, k, t, sh/"ss," and "oo." A consumer how-to advises choosing sounds "noticeably different from one another," noting that "short, sharp sounds such as a tongue click or 'tsk' are often easier ... to detect than soft or drawn-out sounds," and to "avoid assigning actions to sounds you commonly make during conversation, laughter, coughing, or eating" (low-quality secondary source; not Apple's own wording) — [GeekChamp](https://geekchamp.com/how-to-enable-and-use-sound-actions-on-iphone/)
- Vocal Shortcuts (iOS 18, 2024): users record a custom trigger utterance that runs a Shortcut or accessibility action without saying "Siri," processed on-device. Press coverage says it can be a word, phrase, or distinctive sound, aimed at people with cerebral palsy, ALS, or stroke — [9to5Mac](https://9to5mac.com/2024/08/09/ios-18-can-perform-actions-based-on-any-voice-command-you-set/); [Macworld](https://www.macworld.com/article/2334546/apple-to-bring-eye-tracking-vocal-shortcuts-music-haptics-and-more-accessibility-features-to-iphone-and-ipad.html)

**Microsoft Windows Voice Access [CURRENT]**
- Pointer control is spoken, not non-verbal: "show grid" with recursive numbered zoom, "show numbers" with click overlays, and continuous motion in 8 directions with speed-up/slow-down commands — [Microsoft Support](https://support.microsoft.com/en-us/accessibility/windows/voice-access/use-the-mouse-with-voice)

**Google Project Activate / Camera Switches / Gameface [CURRENT]**
- Camera Switches and Project Activate (2021) use *facial gestures* (smile, raised eyebrows, open mouth, look left/right/up), processed on-device, not sounds — [Google blog](https://blog.google/outreach-initiatives/accessibility/making-android-more-accessible/); [TechCrunch](https://techcrunch.com/2021/09/23/google-powers-up-assistive-tech-in-android-with-facial-gesture-powered-shortcuts-and-switches/). Project Gameface (face-driven cursor) came to Android in 2024 — [Google Developers Blog](https://developers.googleblog.com/project-gameface-launches-on-android/)

**Enable Viacam / EVA Facial Mouse [maintained as of 2023]**
- Webcam head-tracking mouse with dwell clicking, free under GPL3. v2.1.0 runs on Windows and Linux; EVA Facial Mouse is the Android version — [eViacam site](https://eviacam.crea-si.com/index.php/en/)

### Inferences
- The industry pattern is **sound = switch, something else = pointer**: Talon uses eyes plus pop, Apple uses scanning plus sound switch, Google uses the face. VOX's vocal-joystick pointer is closer to 2005–2009 research than to any current product. That is a novelty claim, but also a warning that the continuous voice pointer never became a product.
- A small sound vocabulary is the main false-trigger defense in shipping products: Talon shipped only 2 noises for years, and Apple's sounds were chosen to be acoustically distinct and practiced per user. Parrot's layered thresholds are a directly reusable recipe (confidence + power + N frames + throttle + a separate "continuation" threshold for sustained sounds).
- Hiss as a hold-to-act (scroll or drag) matches Sporka's finding that hissing is bad for *pitch*: hiss is used as an on/off hold, not as a modulated signal.

### Gaps
- I found no official Apple page listing the full Sound Actions sound set; the list above is from secondary sources. Apple's detection thresholds and false-trigger rates are not published.
- I found no evidence of non-speech sound triggers in Android Voice Access, macOS Voice Control, or Windows Voice Access. This is absence of evidence from the docs I searched, not a confirmed negative.
- There are no published false-trigger rates (per hour) for Talon pop/hiss, Parrot, or Apple Sound Actions.

## 4. Latency and usability: thresholds, fatigue, false triggers, Midas touch

### Takeaway
Continuous pointing is very sensitive to lag. Mouse Fitts' tasks show measurable cost at 75 ms, and at 225 ms movement time rises 64%, errors rise 214%, and throughput falls 46%. The general UI limits are 0.1 s (feels instant) and 1 s (flow kept). Discrete commands tolerate delays of several hundred ms (speech recognizers ran at about 0.5 s). Continuous steering does not. Sustained vocalization causes throat fatigue and breath limits, and background noise sensitivity has been the most common complaint since 2006.

### Cited Findings
- MacKenzie & Ware (INTERCHI'93), mouse Fitts' task at 8.3 / 25 / 75 / 225 ms lag: MT 911 / 934 / 1059 / 1493 ms; errors 3.6 / 3.6 / 4.9 / 11.3%; bandwidth 4.3 / 4.1 / 3.5 / 2.3 bits/s. "At 75 ms lag, the effect is easily measured, and at 225 ms performance is degraded substantially." Model: MT = 230 + (169 + 1.03·LAG)·ID, so each ms of lag adds about 1 ms/bit. At 500 ms lag and ID = 7 bits, the predicted time is 5.9 s, against about 1.4 s with no lag — [MacKenzie & Ware 1993](https://www.yorku.ca/mack/CHI93b.html)
- The performance cost of lag grows with task difficulty, "particularly at 75 ms and 225 ms." Lag breaks users' "natural tendency to anticipate motions," pushing them into a slower "wait-and-see" strategy — [MacKenzie & Ware 1993](https://www.yorku.ca/mack/CHI93b.html)
- Jota et al. (touch): users perceive latency in the 20–100 ms range, and dragging performance degrades above about 25 ms (search summary) — [Jota et al.](https://www.researchgate.net/publication/262361986_How_fast_is_fast_enough_A_study_of_the_effects_of_latency_in_direct-touch_pointing_tasks)
- Nielsen's limits: 0.1 s feels instant, 1 s keeps flow, 10 s holds attention — [NN/g](https://www.nngroup.com/articles/response-times-3-important-limits/)
- Speech recognition must wait for the utterance to end; non-speech features "can be processed and interpreted on-the-fly." SAPI recognition delay was about 0.5 s — [Sporka et al. ASSETS'06](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-sigaccess-nsi-paper.pdf). Speech recognition's query-response model is "inconvenient ... in real-time continuous tasks, including mouse pointer movement, where the minimum delay ... is a critical feature of the feedback loop" — [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)
- Click latency by sound type: hum 578 ms vs "k" 857 ms in simple reaction time, human production included — [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf). Parrot detection latency is about 20 ms, or about 65 ms with 4-frame confirmation — [PATTERNS.md](https://raw.githubusercontent.com/chaosparrot/parrot.py/master/docs/PATTERNS.md)
- Fatigue:
  - "Continuously making vocal sound also tires the throat"; breathed sound is less straining — [Igarashi & Hughes 2001](https://www-ui.is.s.u-tokyo.ac.jp/~takeo/papers/voice.pdf)
  - Whistling is more tiring than humming — [Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)
  - Users ran out of breath before finishing a movement, and VJ was reported as more fatiguing (contradicted by ratings) — [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)
  - No major vocal-fatigue complaints among VJ experts and novices — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
  - Reduced lung capacity led to short segmented moves — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- False triggers and noise:
  - Both U3I and VJ were "very sensitive" to background noise, and users asked for filters for stray vocalizations — [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)
  - U3I had no noise cancelling and "is very sensitive to acoustic interferences" — [Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)
  - Loud or extraneous onsets made VJ erratic — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
  - All studies used headset mics in quiet rooms: Sennheiser/Andrea in [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf), Plantronics DSP400 in [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf), headsets in [Sporka 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)
- Midas touch: eye trackers "often involve extra steps ... to work around the 'Midas touch' problem" (Jacob 1990). VJ avoids it because it acts only while the user vocalizes — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf). Dwell clicking (eViacam) is the classic example of a Midas-touch-prone click — [eViacam](https://eviacam.crea-si.com/index.php/en/)
- Discrete vs continuous: for novice target acquisition, VJ ≈ Mouse Grid, and both beat Speech Cursor. For path following, VJ took 49 s against 155 s for Speech Cursor, and a grid cannot do paths at all — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)

### Inferences
- **This matters most for VOX:** a cloud decision model (Jev) round trip will very likely be in the hundreds of ms to over a second (not measured here; see Gaps). Putting it inside the continuous cursor loop would place VOX beyond MacKenzie & Ware's 225 ms condition, where errors tripled. The prior art supports a split architecture:
  - A **local, frame-rate (~10–20 ms) loop** turns hum, pitch, and energy directly into cursor velocity and discrete click events on the Pico or Pi.
  - **Jev handles only what tolerates about 1 s**: mode switches, choosing a macro action (e.g. "jump to next target," grid cell, scroll page), error recovery, and adapting thresholds.
- If Jev *must* choose every action, the design becomes a discrete command interface, i.e. Speech Cursor or Mouse Grid territory. Mouse Grid-style recursive selection is the best discrete precedent (matched VJ on targets). A constant-velocity "move until stop" is the worst precedent (slowest, most frustrating), because every stop decision pays the full latency and causes overshoot.
- The BLE HID report interval and the Pi or Pico audio buffer add more lag. The whole budget for continuous control should target under 75 ms, voice onset to cursor motion.

### Gaps
- I did not retrieve the numbers from Forch et al. 2017, "Are 100 ms Fast Enough? Characterizing Latency Perception Thresholds in Mouse-Based Interaction" (Springer paywall).
- No study measured end-to-end voice-onset-to-cursor latency for VJ or U3I in ms.
- I found no published false-trigger rate per hour for any audible non-speech system.
- Jev's actual round-trip latency is unknown to me and should be measured before architecture decisions.

## 5. Design lessons: learnable mappings, hybrid continuous + discrete control, mode switching

### Takeaway
The mappings that worked:
- sustain a sound = hold a button
- relative pitch change = direction and speed on one axis
- 4 vowels = 4 directions (learned in about 5 sessions)
- short burst or short tone = click
- tone length with an audible threshold cue = choose between two discrete commands

Hybrid designs work because continuous control needs millisecond feedback while discrete events need to be robust. Mode switching between speech and non-speech was always explicit (a spoken prefix, a toolbar mode, or a dedicated sound).

### Cited Findings
- The hybrid spoken-prefix-plus-sustained-sound pattern ("Move up, ahhhh"; "Channel up, ta ta ta") — [Igarashi & Hughes 2001](https://www-ui.is.s.u-tokyo.ac.jp/~takeo/papers/voice.pdf). The Migratory Cursor combines verbal coarse positioning with non-verbal fine adjustment — [ASSETS'06 related work](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)
- Orthogonal (one axis at a time, variable speed from the relative pitch change) was faster and preferred over melodic (absolute pitch = direction, fixed speed; 1.4 s vs 2.6 s, universal overshoot in melodic) — [Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)
- A 4-way vowel mode was used for novices "to accommodate for the limited amount of time available to train the required vowels" — [ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf). The vowel mapping was learned by session 5, but some vowels could not be produced depending on dialect. People with music or voice training did better — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
- Feedback design:
  - The vowel feedback tool (hear/see the target sound plus a live recognition arrow) was "especially helpful" — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)
  - An audible click at the duration threshold fixed short/long tone confusion — [Sporka ASSETS'06](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-sigaccess-nsi-paper.pdf)
  - A pitch gauge was needed for humming — [Sporka ASSETS'06](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-sigaccess-nsi-paper.pdf)
  - Apple's Practice mode confirms detection with a tick — [AbilityNet](https://mcmw.abilitynet.org.uk/how-to-perform-actions-on-your-iphone-or-ipad-using-sounds-as-part-of-assistivetouch-in-ios-18)
- VJ widgets reuse the same vocabulary across contexts. A "ck" opens a marking menu, vowels steer it, and "ch" selects; learned mappings "can be transferred to other analogous mappings" — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf); [IBM overview](https://faculty.washington.edu/wobbrock/pubs/ibm-09.pdf)
- Mode switching: a VJ bar next to Vista Speech Recognition to "seamlessly switch between the standard command-and-control/dictation mode and non-speech vocalization mode" — [IBM overview](https://faculty.washington.edu/wobbrock/pubs/ibm-09.pdf). Talon noises are bound in context-specific .talon files, and pop's behavior depends on state (click / end drag / stop scroll) — [community docs](https://wolfmanstout.github.io/wolfmanstout_talon/plugin/mouse/); [Talon changelog](https://talonvoice.com/dl/latest/changelog.html)
- Recovery: users lost the cursor off-screen and could not get it back by voice, and asked for "cues that would help them recover from errors" — [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)
- Longitudinal evaluation matters. Opinions and performance improved day by day, and one-session tests understate these systems — [Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf); the CHI'09 authors' violin analogy argues against half-hour novice tests — [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)

### Inferences (VOX-specific design lessons)
1. **Continuous channel = hum.** Use the change in pitch from the tone's starting pitch for direction and speed on one axis (Sporka's orthogonal mode), or a 4-vowel direction set if a vowel classifier fits the device. Avoid mapping absolute loudness to speed; it was VJ's weakest link and cheap mics make it worse. Prefer fixed or stepped speed.
2. **Discrete channel = short, distinct, unvoiced or plosive events** (pop, tongue click, "t"/"k"), or short-vs-long hum with an audible threshold cue. Keep the vocabulary to 2–4 sounds at first (Talon shipped 2; Apple advises distinct, non-conversational sounds).
3. **False-trigger stack:** power floor + classifier confidence + N consecutive frames (about 45–65 ms) + per-action throttle (about 300 ms) + a separate lower "keep-alive" threshold for sustained sounds (Parrot recipe). Add a dedicated arm/disarm sound or "sleep" mode so coughs, laughs, and speech don't move the cursor.
4. **Keep Jev out of the ≤100 ms loop.** Use it for the choices that tolerate about 1 s: modes, macro jumps, grid picks, and recovery (e.g. "cursor lost → recentre"). This also fits the class-project framing: the novel part is an LLM choosing among discrete actions from serialized features, while a local controller does the millisecond work.
5. **Always show state:** live energy/pitch meter, recognized class and confidence, and current mode. Give audio feedback at duration thresholds.
6. **Plan for fatigue and breath:** support short repeated bursts (segmented movement) rather than requiring long sustains. Prefer hums or breathy sounds over whistles and vowel sustains for long sessions.
7. **Evaluate like the literature:** Fitts' reciprocal task (report throughput in bits/s against a mouse baseline of about 4–6 bits/s and the VJ benchmark of 1.65 bits/s), a steering task, and at least a few sessions per participant.

### Gaps
- No study directly compares a cloud-in-the-loop controller with a local controller for voice pointing. The latency conclusions are extrapolated from the MacKenzie & Ware mouse-lag data.
- No study was found on non-speech cursor control *through a BLE HID peripheral to a phone*. All studies were on a desktop OS with a headset mic.
- Social acceptability of audible hums and pops in public is covered only indirectly (Funk et al. 2020 measured it for cars; the teeth/tongue-click papers cite discreetness as their motivation).
