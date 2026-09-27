# Phone mic echo: can a reference echo canceller stop media from triggering gestures?

[Index](index.md) · [App plan](app.md) · [Signal processing](signal-processing.md) · [Latency and risks](latency-and-risks.md) · [Decisions](decisions.md)

**Question (2026-09-27).** On the Z Flip, Android's built-in AEC (`VOICE_COMMUNICATION` + `AcousticEchoCanceler`)
still let a playing YouTube Short cause 30–35 "would act" sounds a minute (43–47 without it). The app-side idea is to
capture the phone's own playback with `AudioPlaybackCapture` and use it as the reference for WebRTC AEC3 (or similar)
before the extractor. A desktop test was run to decide whether that is worth building.

**Pass mark.** GO if media causes ≤ 2 would-act groups a minute **and** ≥ 90 % of the user's true gestures survive the
canceller. PARTIAL means some of the numbers are close. Anything else is NO-GO.

## Status and verdict

**Acoustic run: not done. This desktop has no audible speaker.** Pink noise played at −24 and −12 dBFS on both outputs
(the Ryzen analog "Speakers" port, and the HDMI monitor at 40 %). The sink monitor captured it at about −12 dBFS, but
the mic stayed at the −49 dBFS room floor. The mic never heard it. The script's `record` step is ready (about 9 minutes
of sound, including a live PipeWire `module-echo-cancel` pass). It needs a speaker plugged in or switched on.

**What ran instead: a simulated echo path, clearly labelled.** The echo was built as a room impulse response applied to
a speaker model of the file. It was added to **real** room noise recorded from the Q9 mic. The reference was the clean
file, which is what AudioPlaybackCapture would give. Two models were used:

- **desk:** mild saturation, RT60 0.35 s, echo at −30 dBFS.
- **phone:** 350 Hz – 8 kHz band-limit, driven into asymmetric compression, strong direct path, echo at −18 dBFS.

The simulated path is linear and time-invariant, with no clock drift. That makes it kinder to the cancellers than any
real room, and much kinder than a phone.

**Provisional verdict: NO-GO, on survival.**

- **Survival fails, even in simulation.** The best canceller kept the same deliberate labels on only **42–46 %** of the
  gestures, and still detected **≤ 85 %** of them. This is far below 90 %. A real speaker (nonlinear, time-varying)
  can only lower these numbers, so the acoustic run would not rescue the result.
- **The false-trigger half could not be tested.** With the desktop Python extractor, raw media already gave only
  0.2–1.4 would-act groups a minute. The ≤ 2/min bar was already met *before* any cancelling, so on this material the
  bar tells the cancellers apart from nothing. The phone's 43–47/min is not reproduced on the desktop.

## Results (SIMULATED echo path, real room noise; aggregate numbers only)

Four 60 s clips were used, all from public datasets:

- music with vocals (MUSAN jamendo pop);
- a two-reader podcast (MUSAN LibriVox);
- a busy short-video mix: speech, a music bed, ESC-50 clicks/knocks/claps/etc., and MLEnd whistles and hums;
- "gesturelike", the worst case: other people's tongue clicks and lip pops (Deeply Nonverbal), hums and whistles
  (MLEnd) and sung fragments (VocalSet) over a quiet bed.

A room minute with nothing playing gave 8.6 events a minute and 0 would-act groups a minute.

**Media only.** Values are per minute, as the mean over the 4 clips.

- **Would-act:** groups the default profile acts on (`policy.action_for`, the same as `mic_live.py`).
- **Deliberate:** groups in which every sound passes the not-deliberate gate, whether the group is bound or not.

| canceller | desk: events | desk: would-act | desk: deliberate | desk: ERLE dB | phone: events | phone: would-act | phone: deliberate | phone: ERLE dB |
|---|---|---|---|---|---|---|---|---|
| raw mic | 35.2 | 1.4 | 1.4 | – | 38.3 | 0.2 | 0.7 | – |
| WebRTC AEC3 (defaults, natural ref timing) | 4.7 | 1.2 | 1.4 | 20.5 | 5.4 | 1.2 | 1.9 | 29.3 |
| AEC3 + noise suppression (PipeWire's default set) | 7.1 | 0.7 | 0.9 | 32.3 | 9.0 | 0.9 | 1.2 | 39.8 |
| AEC3, filter 25 blocks (100 ms) | 5.4 | 0.9 | 1.2 | 20.0 | 8.0 | 0.9 | 1.9 | 27.7 |
| AEC3, stronger suppressor | 4.7 | 0.9 | 1.4 | 20.7 | 4.0 | 0.9 | 1.7 | 29.7 |
| AEC3, reference pre-aligned to 10 ms | 64.5 | **6.4** | 11.6 | 15.1 | 77.5 | **3.3** | 5.4 | 12.2 |
| AECM (APM mobile mode) | 18.2 | 0.7 | 0.7 | 14.2 | 18.9 | 2.8 | 3.5 | 15.8 |
| SpeexDSP, 250 ms tail (±residual suppression) | 11.1 | 1.7 | 1.9 | 15.3 | 53.4 | 1.2 | 4.0 | 15.2 |
| FDAF-NLMS, 250 ms, no double-talk detector | 21.7 | 0.5 | 0.7 | 8.6 | 39.9 | 1.4 | 4.0 | 12.6 |

Pop-pop groups were 0–0.2 a minute everywhere, except the pre-aligned AEC3 (2.4 a minute on desk). The echo-to-room-noise
ratio was about 18 dB (desk) and 29 dB (phone), and that caps the measurable ERLE. Per clip, the counts are 0–7 groups,
so a single group moves the mean by 0.25.

**Survival.** The user's 65 quiet gesture takes from `khoa-guided-1` (clicks, pops, their pairs and runs, and whistled
contours) were mixed digitally onto the media recordings at their natural level (+0 dB) and 10 dB quieter.

- Only deliberate events count: the takes also carry gated breath and "hiss / background noise" sounds.
- **Kept** is measured against the same take laid on the quiet room. Of the 65 takes, 43 (+0 dB) / 51 (−10 dB) gave at
  least one deliberate event there, so 172 and 204 take×clip trials count.
- **Label kept** = exactly the same deliberate label sequence as on the quiet room.

| canceller | desk +0 dB: detection kept | desk +0 dB: label kept | desk −10 dB: detection kept | desk −10 dB: label kept | phone +0 dB: detection kept | phone +0 dB: label kept | phone −10 dB: detection kept | phone −10 dB: label kept |
|---|---|---|---|---|---|---|---|---|
| raw mic | 53 % | 15 % | 39 % | 8 % | 40 % | 6 % | 24 % | 5 % |
| AEC3 | 83 % | 42 % | 71 % | 36 % | 62 % | 28 % | 56 % | 20 % |
| AEC3 + NS | 85 % | 45 % | 70 % | 40 % | 62 % | 28 % | 51 % | 20 % |
| AEC3, 100 ms filter | 85 % | 43 % | 77 % | 42 % | 64 % | 30 % | 58 % | 19 % |
| AEC3, stronger suppressor | 80 % | 40 % | 67 % | 33 % | 60 % | 27 % | 50 % | 16 % |
| AEC3, pre-aligned | 86 % | 17 % | 80 % | 13 % | 73 % | 9 % | 77 % | 10 % |
| AECM (mobile) | 45 % | 17 % | 28 % | 8 % | 37 % | 7 % | 19 % | 4 % |
| SpeexDSP 250 ms, −40 dB | 78 % | 46 % | 91 % | 65 % | 71 % | 25 % | 62 % | 19 % |
| FDAF-NLMS 250 ms | 57 % | 24 % | 65 % | 31 % | 53 % | 15 % | 53 % | 19 % |

**Cost.** CPU on this x86 desktop was measured at 48 kHz mono, including the harness's file I/O:

- AEC3: 0.007 × real time;
- SpeexDSP with a 250 ms tail: 0.07 × real time;
- NLMS (numpy): 0.02 × real time.

## What the numbers say

1. **Cancelling helps a lot, but not enough.** It raises survival from 5–15 % (raw mic) to 28–46 %. A canceller is
   much better than nothing when media plays, but it does not get near the 90 % mark. The losses come from two places:
   - the residual echo adds or changes deliberate sounds inside the gesture;
   - the suppressor eats parts of the gesture during double talk (the "strong" suppressor loses more).
2. **Total events drop 5–8×, but acting groups do not.** For example, desk goes from 35 to 5 events a minute. What
   survives the cancelling is mostly chopped-up residual echo, and it is classed as short pops, clicks and short
   flats. In the phone model, AEC3 *raised* would-act from 0.2 to 1.2 a minute, because long "talking" sounds, which
   the gate ignores, turned into short fragments that pass the gate.
3. **The reference timing is critical.** The playback must lead the echo, and AEC3 must find the delay itself.
   - Forcing the reference to 10 ms ahead broke AEC3: would-act went up 3–5×, and label survival fell to 9–17 %.
   - On a phone, AudioPlaybackCapture's own buffering could make the reference arrive *late*. Delaying the mic to
     compensate would add latency to every gesture.
4. **Only AEC3 is worth considering.** AECM (the old mobile canceller, which is close to what many phones ship) is the
   worst option. SpeexDSP matched AEC3 only in the gentle desk case, and its residual-suppression setting made no
   difference. The FDAF-NLMS baseline, with no double-talk handling, kept few gestures.
5. **The desktop extractor does not reproduce the phone's 43–47/min.** Played straight through the desktop extractor,
   these clips give 0–7 acting groups a minute. Something in the phone path makes media far more trigger-happy. It
   could be the phone mic's own processing or AGC, the Kotlin port, how `mic_live.py` counts while media plays, or the
   Short itself. That should be found before more echo work, because it may be the cheaper fix. **Update:** it was
   partly a counting difference, and partly a ~7 kHz "mouth hiss" that only the phone hears. See the next section.

## Why the phone's 43–47/min did not show up on the desktop (offline, 2026-09-27)

This was worked out from the round 4 logs (`android/suite/out/zflip/echo_cancel_r4*.jsonl`, events 640–969 = the five
60 s runs) and the simulated sessions. The phone was not touched. All numbers are aggregates.

**1. The two numbers counted different things.**

- The round 4 table's "would have acted" (43 / 47 / 33 / 30 / 35) is **a count of sounds**: each sound that was not
  touch-dropped and passed PhoneGate. A recount from the event log gives exactly those numbers.
- The desktop's 0.2–1.4 is **a count of groups**: `policy.group`, which puts up to three sounds together within 600 ms,
  and then `action_for` on the whole group.
- The app does neither. Its `Sequencer` **acts at once** unless a longer bound sequence starts with the sounds so far.
  So a lone `hiss` is `back` straight away, and `hiss hiss click` gives two backs, not one unbound group.

The same logs and clips, under one definition (default bindings from the app's `Vocab.kt`; PhoneGate on; MicPopGate's
lone-pop rule), in would-act per minute:

| definition | phone auto/off | phone VR/platform | phone VC/platform | phone VC/aec | phone VC/aec_ns | desktop sim, desk model (4 clips) | desktop sim, phone model (4 clips) |
|---|---|---|---|---|---|---|---|
| sounds that pass PhoneGate (the round 4 table) | 43 | 47 | 33 | 30 | 35 | 8.5–22 | 0.9–25 |
| `policy.group` groups (what `aec_desktop.py` and `mic_live.py` report) | 6 | 4 | 4 | 5 | 6 | 0–2.8 | 0–0.9 |
| **app Sequencer replica** | **38** | **42** | **18** | **15** | **24** | **0–3.8 (mean 1.7)** | **0–6.6 (mean 2.6)** |

With the app's rules, the real gap is about **40 vs 2.5 a minute (~15×)**. `policy.group` undercounts the app about
10× on hiss-heavy input, so both `mic_live.py`'s `would_act_per_min` and `aec_desktop.py`'s would-act figures are too
low. Also, the Python `vocab.DEFAULT_BINDINGS` is out of date: it still binds `click pop` (the app now binds `pop pop`)
and lacks the app-only `click hiss` → forward.

**2. One kind of sound on the phone explains the gap: a high "hiss" around 7 kHz.**

| | phone VR / auto, media | desktop sim (both models) | phone mic, quiet room |
|---|---|---|---|
| labels / min | hiss 43–47, click 52–53, nothing else | hums 70–80 % (mostly "talking"), hiss 13–25 % | mixed |
| hiss centroid, p10 / p50 | 6.6 / 6.9 kHz | 0.5–1.0 / 1.0–1.6 kHz | 0.6–1.0 / 0.9–4.2 kHz |
| hiss "sounds like" | 100 % mouth sound (so deliberate) | 90 % background noise (so gated) | mostly background noise |
| click | always 10 ms (one frame), 7.2 kHz, onset flux 0.7 dB | rare | 20–30 ms, 2.5–5.5 kHz |
| noise floor | −36.5 dBFS | −32 to −48 dBFS | −52 to −63 dBFS |
| level over floor (median) | hiss 9.5 dB, click 11 dB | 12–23 dB | 11–18 dB |

- With PhoneGate on, **every** would-act in the default preset is `back` from a lone hiss: 38 of 38 (auto) and 42 of
  42 (VR).
- The clicks are already stopped by PhoneGate's 14 dB rule. Without that rule they would add 8–13 `home` a minute.
- The VC presets drop the floor to about −80 dBFS. They cut the hiss count and let hums of the music through
  (flat / rise / fall 8–18 a minute).
- The desktop simulation never makes this narrow band just below the 8 kHz Nyquist limit, so it cannot reproduce the
  phone. The band only appears on the phone while media plays. It is also in an earlier media stretch (7.1 kHz clicks
  and hisses). Is it the Short's treble through the phone's micro-speaker, or an electrical or resampling artefact?
  **The logs cannot tell.**

**3. The configs do not explain it.** The Python `Config` and the C++ `vx_config.h` agree on all 116 fields. The phone
passes no overrides (`VxNative.open(rate)`, the Pico defaults) at 16 kHz. Running the simulated clips at 16 kHz instead
of 48 kHz moved counts by ≤ 1 a minute. The gap (600 ms) and the floor, gate, clarity and tone thresholds are the same.
In the shipped `auto` preset (VOICE_RECOGNITION here), the app adds no AGC. The only app-side differences are
PhoneGate (pops and hums only, hiss never gated), MicPopGate and the Sequencer's act-at-once rule.

**4. The gap can be closed for this case.** The candidate rule adds one PhoneGate rule while speaker media plays: a
hiss with a spectral centroid over 6.5 kHz → `unknown`.

| rule (media on speaker only) | phone auto / VR / VC / VC-aec / VC-aec_ns, acts per min | user's mouth hisses kept (Q9, n=69) | phone quiet mouth hisses kept (n=175) |
|---|---|---|---|
| none (today) | 38 / 42 / 18 / 15 / 24 | 100 % | 100 % |
| **hiss centroid ≤ 6.5 kHz** | **4 / 0 / 7 / 3 / 5** | **100 %** | **98 %** |
| hiss centroid ≤ 6.0 kHz | 1 / 0 / 5 / 3 / 4 | 100 % | 86 % |
| hiss ≥ 14 dB over floor (like pops) | 0 / 0 / 13 / 14 / 22 | 54 % | 23 % |
| hiss onset flux ≥ 1.5 dB | 7 / 3 / 15 / 15 / 22 | 90 % | 96 % |
| hiss ≥ 150 ms | 27 / 28 / 12 / 11 / 18 | 81 % | 59 % |

Survival was checked on `khoa-guided-1`: 85 takes (45 clicks and pops, 20 quiet whistles, 20 whistles over a video)
were run through the desktop extractor. The 6.5 kHz rule changed the actions of **0 / 85** takes. None of their
66 stray hisses is over 6.5 kHz. The guided set has **no hiss takes**, so a hiss "back" is covered only by unlabelled
mouth hisses: 69 from the Q9 live sessions (centroid p90 4.7 kHz) and 175 from the phone in quiet rooms.

Limits:

- This rests on **one Short on one phone**, and the source of the band is unexplained, so the rule is fitted to it.
- It does nothing for a Short whose treble sits lower.
- The `media_lock` default (MediaGate: drop everything while media plays, except `pop pop`) already covers the shipped
  path. The rule matters inside an unlock window, or with the lock off.

**Phone capture needed to confirm the cause** (not done; it needs the user and a small debug addition, since the app
never stores audio):

- **Option A:** a debug `mic_record` op: N seconds of raw PCM from the same `MicCapture` path, in app-private storage,
  pulled with adb and then deleted.
- Record 60 s each, `auto` preset, effects off, dry run, same Short, nobody speaking:
  - **(a)** MUSIC 3/15;
  - **(b)** the same Short muted (MUSIC 0);
  - **(c)** MUSIC 6/15;
  - **(d)** nothing playing.
- What would settle it:
  - The 6–8 kHz band scales with volume and is gone at (b): the echo is acoustic, and the centroid rule is sound.
  - The band is present at (b) or (d): an artefact of the device or its resampling. Then look at 48 kHz capture or at
    a low-pass before the extractor.
- **Option B:** no audio at all. Export `hf_ratio`, `lf_ratio`, `zcr` and `peak_centroid_hz` in `mic_sound.gate`, plus
  a once-a-second 8-band input level in `mic_status`, and re-run the same (a)–(d) with `mic_live.py`.

**2026-09-27, built (source only, not yet on a phone):** the rule ships as `hiss_media_max_centroid_hz` (default 6500,
0 = off; `PhoneGate.hissReason`, media on the speaker only, phone/USB mic only, reason in `mic_sound.gated`); Option B
is in (`mic_sound.gate` now carries `peak_centroid_hz`, `zcr`, `lf_ratio`, `hf_ratio`; `mic_status.bands` gives 8 × 1 kHz
input levels once a second, from the extractor's own spectrum; at 48 kHz the decimator takes ~4–10 dB off 7–8 kHz);
`mic_live.py` and `aec_desktop.py` now count would-act with `vox_extract/sequencer_sim.py` (the app's Sequencer; the
old `policy.group` number is kept beside it). It reproduces the table above exactly (38 / 42 / 18 / 15 / 24 → 4 / 0 / 7
/ 3 / 5). Next: the (a)–(d) Z Flip run with `mic_live.py`.

## Why the phone will be worse than this

A phone speaker is small, driven hard and a few centimetres from the mic, so the desktop result is an upper bound.
Expect these extra losses on the phone:

- **Nonlinear echo.** Speaker distortion and the amp's limiter or speaker protection are not in the reference, and no
  linear filter can remove them.
- **Post-capture effects.** Samsung Dolby Atmos / SoundAlive EQ is applied after AudioPlaybackCapture, so the
  reference no longer matches what the speaker plays.
- **Timing.** The echo path changes as the phone is held or moved. The playback-capture and mic streams also have
  jitter between them.
- **Echo level.** The echo is 10–20 dB louder relative to the voice than on a desk.
- **Built-in processing.** The phone's `VOICE_COMMUNICATION` processing is already in the mic path.

The simulated phone model already cut label survival from the desk's 36–46 % to 20–30 %, and it models only some of
these losses.

## If it is revisited (not a port plan: the verdict is NO-GO)

- **Consent.**
  - AudioPlaybackCapture needs API 29+, a MediaProjection consent dialog, and a `mediaProjection`-type foreground
    service. On Android 14+ that also means `FOREGROUND_SERVICE_MEDIA_PROJECTION`, and the consent is single-use, per
    session.
  - Only `USAGE_MEDIA`, `USAGE_GAME` and `USAGE_UNKNOWN` can be captured.
- **Which apps opt out.** An app blocks capture with `android:allowAudioPlaybackCapture="false"` or with a runtime
  `setAllowedCapturePolicy`. Apps targeting SDK < 29 are blocked by default.
  - **Checked offline** (the local F-Droid APKs in `android/suite/apks` and `android/.state/apks-extra`): NewPipe,
    LibreTube, VLC, Firefox (Fennec), AntennaPod (explicitly `true`), RadioDroid, Auxio, Fossify Music, OuterTune,
    InnerTune, Jellyfin, PeerTube, Tusky, Mastodon, Pachli and Noice. All target SDK ≥ 33 and none sets the manifest
    opt-out, so capture is allowed by the manifest.
  - Most of them contain the `setAllowedCapturePolicy` string. That is probably Media3/ExoPlayer, whose default allows
    capture, so the runtime policy is **unverified**.
  - YouTube, TikTok, Instagram, Spotify and Netflix are not on disk: **unverified**. DRM video apps are the likely
    opt-outs.
- **Latency.** AEC3 works in 10 ms frames with a few ms of filter-bank delay. The unknown part is how long the capture
  path takes to deliver the reference, which needs measuring on the Z Flip.
- **CPU.** CPU is not the blocker. AEC3 used under 1 % of one desktop core, and the WebRTC stack runs in every VoIP app
  on phones.

## Reproduce

```bash
cd /home/khoa/VOX/extractor
./run python eval_real/aec_desktop.py build                                   # nix: webrtc-audio-processing 2.1, speexdsp, gcc
./run python eval_real/aec_desktop.py make   --session recordings/aec-desktop-1
./run python eval_real/aec_desktop.py record --session recordings/aec-desktop-1 --live-ec   # needs an audible speaker
./run python eval_real/aec_desktop.py eval   --session recordings/aec-desktop-1
# the simulated runs on this page (room noise from recordings/aec-desktop-1/rec/room_long_mic.wav):
./run python eval_real/aec_desktop.py sim  --session recordings/aec-desktop-sim-desk  --model desk
./run python eval_real/aec_desktop.py eval --session recordings/aec-desktop-sim-desk
./run python eval_real/aec_desktop.py sim  --session recordings/aec-desktop-sim-phone --model phone
./run python eval_real/aec_desktop.py eval --session recordings/aec-desktop-sim-phone
```

Harnesses are in `extractor/eval_real/aec/` (`aec_webrtc.cc`, `aec_speex.c`). All recordings stay under
`extractor/recordings/aec-desktop-*/` (gitignored), and each session has its own full `results.md`.
