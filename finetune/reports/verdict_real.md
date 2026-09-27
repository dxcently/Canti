# Verdict on real screens (v1a–v1e)

Run on 2026-09-26. Data: `data/real-targets-v2/` (split rules and amendments in `SPLIT.md`). Runs: `students/verdict/runs/verdict-bi-real-v1*`. Eval: `students/verdict/eval_real.sh`, `students/verdict/baselines_real.sh`, per-set JSON in `sweeps/eval/real-v2.*.json`.

## Summary

- **Recommended: `verdict-bi-real-v1d`, no none bias.** It uses frozen embeddings. It ties v1e on val (acc 0.817, none recall 0.803) and was chosen on val before looking at test.
- **New-extraction test (Wikipedia, AntennaPod, Tasks; 344 rows), from the current Verdict to v1d:**
  - accuracy 0.616 → **0.738**
  - false-none 0.174 → **0.041**
  - ECE 0.35 with the stored T, 0.095 with T refit → **0.094**
- **Old-extraction test (308 rows):** accuracy 0.643 → **0.838**, none recall **0.818**.
- **Synthetic targets-v2, no regression:**
  - test_iid 1.000 → 0.9995
  - test_unseen_apps 0.974 → 0.983
  - test_unseen_phrasing **0.545 → 0.675**
- **At the 0.8 confidence threshold (new test):** coverage 0.645, accuracy 0.905. Taps: 198 rows at 0.919. Nones: 24 rows at 0.792. 9.8 % of gold-none rows still get a confident tap.
- **The none-recall floor (≥ 0.8) is met on val (0.803) and the old test (0.818), but not on the new test (0.529).** The 24 missed nones:
  - 6 `HIDDEN-OPTIONS` rows: Canti still lists an element that an overlay hides, e.g. "More options" under Wikipedia's search mode. The model taps it at about 0.96.
  - 4 name an unboxed element.
  - 4 describe icons that aren't on the screen.
  - 10 are real "not on this screen" requests. Recall on those is 24/34 = 0.71.
- **A none bias fitted on val doesn't close the gap.** Checked after test had been seen, so post hoc:
  - bias +0.7 → recall 0.569 at acc 0.733
  - bias +1.75 → recall 0.667 at acc 0.727
- **The main fix is upstream:** Canti should not list hidden elements.
- **ONNX int8:** `runs/verdict-bi-real-v1d/onnx/encoder_int8.onnx`, 118 MB, acc 0.745 on 200 test rows.
  - On this workstation (4 threads, option embeddings cached): p50 2.1 ms, p99 2.4 ms.
  - Torch on CPU without the cache: p50 362 ms.
  - These are not phone numbers.

## Data

- **Emulator:** 4,648 rows, 613 screens, 57 packages.
  - Phrases by DeepSeek V4 Pro, labels by Opus (42 batches).
  - Labellers dropped 59 rows, and 33 none rows caused by FABs were dropped.
  - Tasks.org was re-harvested with the Compose-fix build: 14 screens.
- **Z Flip:** 160 rows (YT Music, Obsidian, Fennec, YouTube), with Opus phrases and Opus labels, split 140 train / 20 val. The 40 X rows (Opus) are diagnostic only.
- **Social-app Z Flip harvest:** dropped. No social rows are in any split. A later v1f may add them; see "Next".
- **The DeepSeek boundary is enforced two ways:**
  - Z Flip rows live only in the `zflip/` manifests.
  - The `phrases` stage checks that every screen is from the emulator: the path is under `emulator/`, there is no `zf` id and no `serial` field, and it is not X.
- **Kinds overall:** name 1021, position 931, function 885, appearance 664, casual 617, none 614 (12.8 %), near_none 76.
- **Extraction:** pre-occlusion 2,836 rows, occlusion 1,812, vision (Z Flip) 160.
  - 23 rows carry `HIDDEN-OPTIONS` notes, 8 of them in test.
  - 64 rows mention an unboxed element.

### Splits by source and kind

| split | source | rows | screens | apps | name | position | function | appearance | casual | none | near_none |
|---|---|---|---|---|---|---|---|---|---|---|---|
| train | emulator | 3589 | 475 | 52 | 766 | 681 | 665 | 495 | 470 | 455 | 57 |
| val | emulator | 407 | 56 | 32 | 81 | 82 | 76 | 57 | 48 | 59 | 4 |
| test (new extraction) | emulator | 344 | 43 | 3 | 75 | 72 | 60 | 39 | 40 | 51 | 7 |
| test_old (pre-occlusion) | emulator | 308 | 39 | 3 | 68 | 64 | 52 | 43 | 40 | 33 | 8 |
| train | Z Flip | 140 | 14 | 4 | 27 | 28 | 28 | 26 | 17 | 14 | 0 |
| val | Z Flip | 20 | 2 | 2 | 4 | 4 | 4 | 4 | 2 | 2 | 0 |
| diag X (Opus) | Z Flip | 40 | 5 | 1 | 10 | 5 | 5 | 9 | 5 | 6 | 0 |

### Per app


| app | package | train | val | test (new extraction) | test_old (pre-occlusion) | zflip train | zflip val | extraction |
|---|---|---|---|---|---|---|---|---|
| aegis | com.beemdevelopment.aegis | 24 | 0 | 0 | 0 | 0 | 0 | occlusion 24 |
| antennapod | de.danoeh.antennapod | 0 | 0 | 48 | 64 | 0 | 0 | occlusion 48, pre-occlusion 64 |
| appmanager | io.github.muntashirakon.AppManager | 97 | 16 | 0 | 0 | 0 | 0 | occlusion 113 |
| auxio | org.oxycblt.auxio | 31 | 16 | 0 | 0 | 0 | 0 | occlusion 47 |
| batterybot | com.darshancomputing.BatteryIndicatorPro | 51 | 8 | 0 | 0 | 0 | 0 | occlusion 59 |
| bestclock | com.best.deskclock | 111 | 0 | 0 | 0 | 0 | 0 | occlusion 111 |
| breezy | org.breezyweather | 8 | 8 | 0 | 0 | 0 | 0 | occlusion 16 |
| browser | org.chromium.webview_shell | 0 | 12 | 0 | 0 | 0 | 0 | pre-occlusion 12 |
| calendar | com.android.calendar | 35 | 11 | 0 | 0 | 0 | 0 | pre-occlusion 46 |
| catima | me.hackerchick.catima | 24 | 8 | 0 | 0 | 0 | 0 | occlusion 32 |
| clock | com.android.deskclock | 96 | 26 | 0 | 0 | 0 | 0 | pre-occlusion 122 |
| contacts | com.android.contacts | 93 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 93 |
| dialer | com.android.dialer | 40 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 40 |
| fcalendar | org.fossify.calendar | 103 | 8 | 0 | 0 | 0 | 0 | pre-occlusion 111 |
| fclock | org.fossify.clock | 88 | 24 | 0 | 0 | 0 | 0 | pre-occlusion 112 |
| fcontacts | org.fossify.contacts | 101 | 8 | 0 | 0 | 0 | 0 | pre-occlusion 109 |
| fdroid | org.fdroid.fdroid | 103 | 0 | 0 | 0 | 0 | 0 | occlusion 103 |
| feeder | com.nononsenseapps.feeder | 103 | 8 | 0 | 0 | 0 | 0 | occlusion 111 |
| fennec | org.mozilla.fennec_fdroid | 100 | 15 | 0 | 0 | 30 | 0 | pre-occlusion 115, vision 30 |
| ffiles | org.fossify.filemanager | 8 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 8 |
| files | android | 0 | 4 | 0 | 0 | 0 | 0 | pre-occlusion 4 |
| files | com.android.documentsui | 103 | 16 | 0 | 0 | 0 | 0 | pre-occlusion 119 |
| fixture | ai.vox.fixture | 25 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 25 |
| fmath | org.fossify.math | 32 | 8 | 0 | 0 | 0 | 0 | pre-occlusion 40 |
| fmessages | com.android.permissioncontroller | 16 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 16 |
| fmusic | org.fossify.musicplayer | 112 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 112 |
| fnotes | org.fossify.notes | 96 | 16 | 0 | 0 | 0 | 0 | pre-occlusion 112 |
| fpaint | org.fossify.paint | 76 | 8 | 0 | 0 | 0 | 0 | pre-occlusion 84 |
| fphone | org.fossify.phone | 110 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 110 |
| frecorder | org.fossify.voicerecorder | 63 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 63 |
| gallery | org.fossify.gallery | 122 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 122 |
| gallery3d | com.android.gallery3d | 49 | 16 | 0 | 0 | 0 | 0 | pre-occlusion 65 |
| gh4a | com.gh4a | 8 | 0 | 0 | 0 | 0 | 0 | occlusion 8 |
| jellyfin | org.jellyfin.mobile | 24 | 0 | 0 | 0 | 0 | 0 | occlusion 24 |
| k9 | com.fsck.k9 | 16 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 16 |
| kdeconnect | org.kde.kdeconnect_tp | 24 | 0 | 0 | 0 | 0 | 0 | occlusion 24 |
| keepass | com.kunzisoft.keepass.libre | 64 | 0 | 0 | 0 | 0 | 0 | occlusion 64 |
| launcher | com.android.launcher3 | 24 | 6 | 0 | 0 | 0 | 0 | pre-occlusion 30 |
| launcher | com.android.systemui | 12 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 12 |
| libretube | com.github.libretube | 96 | 16 | 0 | 0 | 0 | 0 | occlusion 112 |
| markor | net.gsantner.markor | 24 | 8 | 0 | 0 | 0 | 0 | pre-occlusion 32 |
| mastodon | org.joinmastodon.android | 40 | 8 | 0 | 0 | 0 | 0 | occlusion 48 |
| messages | com.android.messaging | 27 | 23 | 0 | 0 | 0 | 0 | pre-occlusion 50 |
| mfiles | me.zhanghai.android.files | 96 | 16 | 0 | 0 | 0 | 0 | occlusion 112 |
| newpipe | org.schabi.newpipe | 91 | 28 | 0 | 0 | 0 | 0 | pre-occlusion 119 |
| noice | com.github.ashutoshgngwr.noice | 104 | 8 | 0 | 0 | 0 | 0 | occlusion 112 |
| obsidian | md.obsidian | 0 | 0 | 0 | 0 | 30 | 10 | vision 40 |
| organicmaps | app.organicmaps | 86 | 15 | 0 | 0 | 0 | 0 | pre-occlusion 101 |
| pfanotes | org.secuso.privacyfriendlynotes | 66 | 0 | 0 | 0 | 0 | 0 | occlusion 66 |
| pfatodo | org.secuso.privacyfriendlytodolist | 67 | 0 | 0 | 0 | 0 | 0 | occlusion 67 |
| settings | com.android.settings | 358 | 19 | 0 | 0 | 0 | 0 | pre-occlusion 377 |
| suntimes | com.forrestguice.suntimeswidget | 95 | 8 | 0 | 0 | 0 | 0 | occlusion 103 |
| tasks | org.tasks | 0 | 0 | 104 | 74 | 0 | 0 | occlusion 104, pre-occlusion 74 |
| tusky | com.keylesspalace.tusky | 56 | 8 | 0 | 0 | 0 | 0 | occlusion 64 |
| uhabits | org.isoron.uhabits | 87 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 39, occlusion 48 |
| vlc | org.videolan.vlc | 94 | 8 | 0 | 0 | 0 | 0 | pre-occlusion 102 |
| vox | ai.vox.companion | 10 | 0 | 0 | 0 | 0 | 0 | pre-occlusion 10 |
| wikipedia | org.wikipedia | 0 | 0 | 192 | 170 | 0 | 0 | occlusion 192, pre-occlusion 170 |
| youtube | app.rvx.android.youtube | 0 | 0 | 0 | 0 | 30 | 10 | vision 40 |
| ytmusic | app.rvx.android.apps.youtube.music | 0 | 0 | 0 | 0 | 50 | 0 | vision 50 |

## Runs

**Recipe:**
- Start from targets-v2.
- Real rows ×3, plus 12k synthetic targets-v2 rows (12 % none).
- 3 epochs. The learning rate is 3e-5 for v1a–v1c and 5e-5 for v1d and v1e (per each run's `student.json`), so v1a → v1d changes both the data and the learning rate.
- The epoch is picked on real val with the none floor, and T is refit on val.

| run | change | data | val acc | val none recall | new test acc |
|---|---|---|---|---|---|
| v1a | base recipe | partial | 0.796 | 0.754 | 0.738 |
| v1b | drop-gold 0.15 | partial | 0.782 | 0.852 | 0.735 |
| v1c | none loss weight ×2 | partial | 0.796 | 0.754 | 0.741 |
| **v1d** | base recipe | full | 0.817 | 0.803 | 0.738 |
| v1e | trainable embeddings | full | 0.817 | 0.803 | 0.738 |

- v1b does the same as a none bias.
- Raising the none loss weight had no effect.
- **Baselines:** jevlike scores 0.465 on the new test (false-none 0.437). There is no Ollama baseline because no predictions are cached.
- **X diagnostic (40 Opus rows):** accuracy stays at 0.45, and ECE falls from 0.51 to 0.19.

## Scores

#### test_real
| model | n | acc | acc (acceptable) | none recall | false none | ECE | @0.8 coverage / acc | @0.8 taps n / acc | @0.8 none n / acc | gold-none tapped @0.8 |
|---|---|---|---|---|---|---|---|---|---|---|
| Verdict targets-v2, stored T | 344 | 0.616 | 0.628 | 0.569 | 0.174 | 0.3503 | 0.942 / 0.664 | 247 / 0.757 | 77 / 0.364 | 0.333 |
| Verdict targets-v2, T refit on real val | 344 | 0.616 | 0.628 | 0.569 | 0.174 | 0.0947 | 0.422 / 0.841 | 126 / 0.889 | 19 / 0.526 | 0.078 |
| jevlike targets-v2-e5-small-e3 | 344 | 0.465 | 0.474 | 0.784 | 0.437 | 0.4922 | 0.922 / 0.492 | 159 / 0.736 | 158 / 0.247 | 0.196 |
| v1a (partial data) | 344 | 0.738 | 0.750 | 0.529 | 0.034 | 0.0872 | 0.61 / 0.914 | 193 / 0.912 | 17 / 0.941 | 0.137 |
| v1b (partial, drop-gold 0.15) | 344 | 0.735 | 0.744 | 0.549 | 0.058 | 0.0824 | 0.637 / 0.922 | 200 / 0.925 | 19 / 0.895 | 0.118 |
| v1c (partial, none weight 2) | 344 | 0.741 | 0.753 | 0.549 | 0.044 | 0.0794 | 0.61 / 0.905 | 192 / 0.906 | 18 / 0.889 | 0.157 |
| **v1d (chosen)** | 344 | 0.738 | 0.750 | 0.529 | 0.041 | 0.0945 | 0.645 / 0.905 | 198 / 0.919 | 24 / 0.792 | 0.098 |
| v1e (trainable embeddings) | 344 | 0.738 | 0.750 | 0.529 | 0.048 | 0.0927 | 0.645 / 0.905 | 199 / 0.92 | 23 / 0.783 | 0.098 |

#### test_real_old
| model | n | acc | acc (acceptable) | none recall | false none | ECE | @0.8 coverage / acc | @0.8 taps n / acc | @0.8 none n / acc | gold-none tapped @0.8 |
|---|---|---|---|---|---|---|---|---|---|---|
| Verdict targets-v2, stored T | 308 | 0.643 | 0.649 | 0.788 | 0.215 | 0.3316 | 0.948 / 0.671 | 211 / 0.796 | 81 / 0.346 | 0.182 |
| Verdict targets-v2, T refit on real val | 308 | 0.643 | 0.649 | 0.788 | 0.215 | 0.0553 | 0.344 / 0.896 | 94 / 0.947 | 12 / 0.5 | 0.03 |
| jevlike targets-v2-e5-small-e3 | 308 | 0.506 | 0.513 | 0.879 | 0.393 | 0.4383 | 0.883 / 0.548 | 145 / 0.821 | 127 / 0.236 | 0.091 |
| v1a (partial data) | 308 | 0.805 | 0.805 | 0.727 | 0.033 | 0.0428 | 0.695 / 0.939 | 199 / 0.94 | 15 / 0.933 | 0.121 |
| v1b (partial, drop-gold 0.15) | 308 | 0.805 | 0.808 | 0.697 | 0.044 | 0.0315 | 0.679 / 0.943 | 190 / 0.953 | 19 / 0.842 | 0.061 |
| v1c (partial, none weight 2) | 308 | 0.802 | 0.802 | 0.758 | 0.033 | 0.0529 | 0.685 / 0.934 | 194 / 0.943 | 17 / 0.824 | 0.091 |
| **v1d (chosen)** | 308 | 0.838 | 0.838 | 0.818 | 0.033 | 0.0739 | 0.656 / 0.946 | 183 / 0.956 | 19 / 0.842 | 0.03 |
| v1e (trainable embeddings) | 308 | 0.841 | 0.841 | 0.818 | 0.033 | 0.0721 | 0.646 / 0.95 | 182 / 0.956 | 17 / 0.882 | 0.03 |

#### val (val_real_all: emulator + Z Flip val; used for selection)
| model | n | acc | acc (acceptable) | none recall | false none | ECE | @0.8 coverage / acc | @0.8 taps n / acc | @0.8 none n / acc | gold-none tapped @0.8 |
|---|---|---|---|---|---|---|---|---|---|---|
| Verdict targets-v2, stored T | 427 | 0.597 | 0.611 | 0.656 | 0.246 | 0.3606 | 0.902 / 0.649 | 261 / 0.805 | 124 / 0.323 | 0.295 |
| v1a | 427 | 0.796 | 0.810 | 0.754 | 0.038 | 0.0267 | 0.646 / 0.971 | 249 / 0.984 | 27 / 0.852 | 0.049 |
| v1b | 427 | 0.782 | 0.799 | 0.852 | 0.074 | 0.0461 | 0.628 / 0.974 | 236 / 0.992 | 32 / 0.844 | 0.033 |
| v1c | 427 | 0.796 | 0.810 | 0.754 | 0.038 | 0.0281 | 0.642 / 0.974 | 247 / 0.984 | 27 / 0.889 | 0.049 |
| **v1d** | 427 | 0.817 | 0.829 | 0.803 | 0.044 | 0.0617 | 0.66 / 0.986 | 251 / 0.988 | 31 / 0.968 | 0.033 |
| v1e | 427 | 0.817 | 0.829 | 0.803 | 0.041 | 0.0403 | 0.651 / 0.982 | 248 / 0.988 | 30 / 0.933 | 0.033 |

## Error analysis

- **The current Verdict makes 128 errors on the new test:** 51 false-none, 56 wrong target, 21 missed none. Two causes: the gap between its synthetic option vocabulary and real labels, and a bad temperature (ECE ≈ 0.35).
- **v1d makes 86 errors:** 12 false-none, 51 wrong target, 23 missed none.
- **What's left:**
  - position phrases like "top right corner" or "the middle one" (position accuracy 0.653);
  - near-duplicate controls, such as calendar cells and repeated toggles;
  - hidden or unboxed elements left by extraction.
- **By kind (v1d, new test):** name 0.933, appearance 0.846, function 0.750, casual 0.725, position 0.653, none 0.529.
- **By app:** AntennaPod 0.854, Wikipedia 0.760, Tasks 0.644.

## Caveats

1. **Phrase sources differ.** Every test phrase comes from DeepSeek and every Z Flip phrase from Opus. The user-phrase gold (section C) is still empty, so there is no test on the user's own phrases or on X yet.
2. **61 % of training rows use the old option lists.** Plan with the new-test numbers, since the app uses the new extraction.
3. **The test set was looked at once, early, with a pilot.** That was disclosed at the time. All later choices used val only.
4. **Val has only 61 gold-none rows,** so the 0.8 floor is about ±0.05 noise.
5. **FLAG_SECURE apps have black screenshots** (Aegis, KeePass, Fennec private tabs). Their labels come from the boxes and text only.
6. **One labeller per batch,** so there is no agreement measure.
7. **Synthetic v0–v5 were not used** because they have mislabelled none rows. Only targets-v2 was used.
8. **The builds from 19:07 to 21:12 dropped Compose nodes.** Tasks was re-captured. F-Droid, a training app, lost a few image nodes.

## Next

- **Upstream:** stop listing elements an overlay hides (`HIDDEN-OPTIONS`). This is the biggest lever on none recall.
- **v1f, not started: needs the user's OK.** The plan:
  - add Z Flip social-app screens from `zflip/raw`, captured with Canti gestures only;
  - Opus phrases and labels only, never an external model;
  - split by package; X stays diagnostic;
  - the v1d recipe plus those rows, with a dated `SPLIT.md` amendment.
