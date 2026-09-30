# REPORT — r8-swipes-canti (Phase A)

Branch base: main after r8-chains merge (this worktree). Phase A only this turn.

## Phase A

### JVM test results

`cd android && ./dev env gradle testDebugUnitTest -q` — **841 tests, 0 failures, 0 errors** (75 suites).

New test classes (all green):

| Class | Tests | Note |
|---|---|---|
| `ItemSwipeGrammarTest` | 7 | A1 grammar |
| `SwipeHoldTest` | 5 | A1 hold (incl. freeze/resume) |
| `ItemSwipeGeometryTest` | 3 | A1 geometry |
| `CantiTalkTest` | 10 | A3 detection |
| `CantiNotesTest` | 4 | A4 file store |
| `PhraseGrammarTest` additions | +7 | A2 system pulls + chain; class now 65 tests |

Existing `PhraseGrammarTest` (58 → 65), `SwipeTest` (7), `ChainQueueTest`, `ChainControlTest`, `FollowupTest` and all others remain green.

### What changed (Phase A, pure Kotlin + JVM)

1. **`ItemSwipe.kt`** (new): `ItemRef` (`Deictic` / `Label` / `Ordinal`), `ItemSwipeGrammar.parse`, `ItemSwipeGeometry.gesture`, and `SwipeHold` (fire/cancel/zero/tick + the W3 speech `freeze`/`resume`).
2. **`PhraseGrammar.kt`**: added `SpeechCommand.ItemSwipe` and `SpeechCommand.SystemAction` subtypes (+ `describe()`), and `ItemSwipe`/`SystemAction` into `concrete()` and `rank()`; wired `ItemSwipeGrammar.parse` **after** `SwipeGrammar.parse` in `single()`.
3. **`Swipes.kt`**: system pulls matched **before** `EXPLICIT` (so "swipe up for recents" no longer falls through) — `recents` → `Nav("recent apps")`; `quick_settings` / `close_shade` / `pull_refresh` → `SpeechCommand.SystemAction`.
4. **`CantiTalk.kt`** (new): `CantiTalk.detect(hyps, cantiUiUp)` → `Result(fix, note)`.
5. **`CantiNotes.kt`** (new): `CantiNotes(dir, max=200)` — add / read (skips corrupt lines) / delete, cap drops oldest.
6. **Compile-only branches** so the exhaustive `when(c)` sites stay complete: `AudioFileAsr.command` (item_swipe/system JSON), `SpokenPick.concrete`, and `VoxService.runCommand` (`systemAction` implemented; `itemSwipe` is a Phase-B stub — see below).

### Files touched
- new: `ItemSwipe.kt`, `CantiTalk.kt`, `CantiNotes.kt`, `ItemSwipeGrammarTest.kt`, `SwipeHoldTest.kt`, `ItemSwipeGeometryTest.kt`, `CantiTalkTest.kt`, `CantiNotesTest.kt`
- edited: `PhraseGrammar.kt`, `Swipes.kt`, `AudioFileAsr.kt`, `SpokenPick.kt`, `VoxService.kt`, `PhraseGrammarTest.kt`

### Open questions / judgement calls

- **J1 (deictic left/right):** An existing `PhraseGrammarTest` asserts `"swipe it right"` → screen `Swipe`, so I kept the grammar output unchanged and wired `ItemSwipeGrammar` **after** `SwipeGrammar`. Deictic left/right stays a screen `Swipe`; `ItemSwipeGrammar` only claims deictic for `away`/`off`. The deictic→item upgrade (Swipe with an "it/this/that" subject + a deictic target present) is deferred to VoxService in Phase B, exactly as the J1 note directs.
- **ChainQueue.kt name:** the `ChainQueue` class lives in `Chain.kt` (not a file named `ChainQueue.kt`), and `chain_state` exists as an op in `VoxService`. Chains are present; no re-implementation. Reporting the file-name mismatch only.
- **`itemSwipe` in `VoxService`** is a stub that logs `"how": "phase b"` (needed only so the exhaustive `runCommand` `when` compiles). Phase B (W2/W3/W5) fills in target resolution, the hold, the preview arrow, and `recordLast(Last.ItemSwipe)`.
- **`systemAction`** performs the executor key directly via `executor.perform(action, "listening")`. The three keys (`quick_settings`, `close_shade`, `pull_refresh`) are **not yet** in `Executor.perform` (that is B1), so until then they return "unknown action" gracefully.
- **System-action representation:** `quick_settings`/`close_shade`/`pull_refresh` are a new `SpeechCommand.SystemAction` (executor-only, never in Vocab); `recents` reuses the existing `Nav("recent apps")` phrase. `pull down notifications` is untouched (still `Nav("show notifications")` via the existing NAV list).
- **SwipeHold freeze:** added `freeze()`/`resume()` beyond the sketched `start/cancel/running` (the W3 speech-freeze decision requires it). Freeze reports the frozen remaining ms; resume continues from where it froze. The `why` on `cancel` is currently unused.
- **`off` → `away`:** the grammar's `off` direction maps to `dir = "away"` (both destructive), matching the `"left"|"right"|"away"` result type.
- **Ordinal words:** `first`…`tenth` plus `last` (fromEnd). Bare "last one" (no "the") is an ordinal, to match the `swipe_last_one_away_from_end` test.

### Not done this turn (Phase B onward)
Executor keys (`quick_settings`/`close_shade`/`pull_refresh`), item-swipe resolution/hold/undo in VoxService, the about-Canti step in `onHeard`, `settings.swipeHoldMs`, `canti_notes` socket op, `HideWhy`/log redaction, the fixture Swipe screen, suite tests, and PROTOCOL.md (W11/W12).

## Phase B

### JVM test results

`cd android && ./dev env gradle testDebugUnitTest -q` — **832 tests, 0 failures, 0 errors** (75 suites).

The count fell from 841 → 832 because the 10 separate `CantiTalkTest` methods were consolidated into one 30-case table (per the K1–K6 review).

### K1–K6 CantiTalk rework (review fix)

`CantiTalk` was far too eager (any "badge"/"strip"/"queue" noun triggered it, blocking real commands). Rewritten to consult the grammar:

- **A phrase that parses into a concrete command is a command** (`PhraseGrammar.concrete`, now `internal`), unless it explicitly targets Canti.
- **FIX_NOUNS alone never decide**: a Canti noun needs a fix verb ("move"/"hide"/"get rid of"/"remove"/"dismiss") or a complaint ("in the way"/"covering"/…) **and** that piece's chrome up (or a possessive marker).
- **`candy` dropped from SELF** ("open candy crush" opens the app).
- **`the numbers`** only about Canti while the picker (number overlay) is up.
- **Wake/politeness** ("hey canti could you open youtube", "canti please scroll down", "canti can you go back") are commands because `PhraseGrammar.parse` already strips the wake/politeness and yields a concrete command.
- Signature now `detect(hyps, CantiUi)` with a granular `CantiUi(badge, strip, queue, preview, picker)` (the K-rules gate fixes on specific chrome).

`CantiTalkTest` is a single 30-phrase table (commands vs fixes/notes), covering every K1–K6 case plus item swipes and chains.

### What changed (Phase B)

| File | Change |
|---|---|
| `CantiTalk.kt` | K1–K6 rewrite; `CantiUi` state, marker/fix-verb/complaint logic |
| `PhraseGrammar.kt` | `concrete()` → `internal` |
| `Followup.kt` | `Last.ItemSwipe(label, dir, …)`; RETRY→Nothing; `undoPlan`→`CantUndo("the swipe")` |
| `VoxService.kt` | `last_kind` "item_swipe"; `canti_notes` op; `control(m, source)`; `HideWhy` enum; `hideWhy`/`cantiUi`/`aboutCanti`/`applyCantiFix`/`writeCantiNote`; item-swipe resolution + hold + `recordLast`; `cancelHoldWord`; about-Canti step in `onHeard`; `swipeHold` field |
| `Executor.kt` | `quick_settings`, `close_shade` (API-31 dismiss else back), `pull_refresh` (25%→70% drag at the top scrollable's top), `itemSwipe(box, dir, rtl)` returning a Confirmer watch |
| `Overlay.kt` | `moveBadgeToOtherSide()`, `badgeShown()`, `previewShown()` |
| `TranscriptStrip.kt` | `StripKind.CANTI`, `StripRow.Canti`, `StripModel.setKind` |
| `Settings.kt` | `swipeHoldMs` (default 1500, 0..5000) in `apply`/`describe` |

### W8 / backup

`AndroidManifest.xml` already has `android:allowBackup="false"`, so no `dataExtractionRules`/`fullBackupContent` exclude is needed — the note file is already excluded from backup by that flag (noted, not changed).

### Judgement calls / open items

- **J1** — deictic left/right stays a screen `Swipe` in the grammar; the deictic→item upgrade was *not* implemented (VoxService item-swipe only handles `ItemRef.Deictic` via the last `Last.Pick` target, not a bare "swipe it left").
- **J3** — the destructive hold's cancel calls `SwipeHold.cancel` and shows "not swiped"; it does not cancel a chain. The chain-pause wiring (a running ItemSwipe step's hold counting as the step running) is not integrated.
- **J6** — not investigated (whether item swipes should use the tree baseline instead of `NO_TREE_BASELINE`).
- **J7** — no r8-chains code in `Chain.kt` was changed; `Followup.kt` gained `Last.ItemSwipe` + an `undoPlan` branch (the chain undo path reuses `undoPlan`).

### NOT done this turn (deferred, with the exact gaps)

- **B5 fixture** (the "Swipe" screen) — not written.
- **B6 suite tests** and the **emulator-5580 full suite run** — not run (no suite results to report).
- **W3 speech-freeze on partials** — `SwipeHold.freeze`/`resume` exist and are JVM-tested, but the onWords-partial hook in the live listen window is not wired; `onTick` updates the row but there is no listen-window freeze.
- **preview arrow** (`Overlay.showPreview` optional arrow) — not added; the hold shows a NOW outline only.
- **"several → picker"** for label item-swipe — not implemented (falls back to "no target"/miss).
- **W12 `log_speech_text`** redaction switch — not implemented (out of scope of this turn's push).
- **B7 / PROTOCOL.md (W11)** — not updated.

The code above compiles and the JVM suite is green, but the Android wiring (about-Canti fixes, item-swipe hold, `canti_notes` op, `pull_refresh`) is **not exercised by any JVM test** and needs the emulator suite to validate.

## Phase C

### JVM test results

`cd android && ./dev env gradle testDebugUnitTest -q` — **836 tests, 0 failures, 0 errors** (76 suites).

+4 vs Phase B: new `SpeechTextLogTest`. `PhraseGrammarTest`/`SwipeTest` updated for the J1 `deictic` field and still green.

### Item 1 — W3 speech-freeze during a destructive hold

- `SwipeHold` (already JVM-tested) now wired to the live listen window: a destructive hold opens `listenWindow.open(asr, holdMs + GRACE_MS, onWords = freeze, onDone = holdDone)`.
- `onWords` calls `SwipeHold.freeze()` on the first non-blank partial (idempotent), so the countdown stops and the row shows the frozen seconds.
- `holdDone` cancels on a `no`/`stop`/`cancel` final, else `resume()`s; a `cancelled:` window (a superseding phrase op / disarm) does nothing.
- `CANCEL_WORDS = {"no","stop","cancel"}` shared with the `cancelHoldWord` phrase-op path (kept, so an injected `phrase` op "no" still cancels).

### Item 2 — W12 `log_speech_text` redaction + expiry

- New pure `SpeechTextLog` (`enabled(flag, expiryMs, nowMs)`, `AUTO_EXPIRE_MS = 60 min`, `summary(text)` = "N chars, M words"). JVM-tested with a fake clock (`SpeechTextLogTest`, 4 tests).
- `Settings`: `logSpeechText` (bool, default false), `logSpeechTextExpiryMs` (long expiry); config keys `log_speech_text` and `log_speech_text_ms` (debug, sets an absolute expiry); `describe()` shows both. Turning the switch on in the config op re-arms the expiry (+60 min).
- Redaction applied to the **asr "closed" `n_best`** and the **`phrase_parse` `heard`** + `trace("heard")` fields (summary when off). About-Canti words remain out even when the switch is on (unchanged).

**Partial:** the `phrase_parse` `command`/`parses` fields still carry `describe()` (which can include a cleaned query, e.g. `tap "wifi"`); the strip/followup/target/typing paths are not yet switched on `log_speech_text`. A full "no heard text in any event" suite test would need these closed.

### Item 3 — J3 chain hold

Verified by reading the code path (no new code needed): a running ItemSwipe step is `RUNNING`/`checking` (set by `runNext`); the hold registers no watch until it fires, so it stays "checking". A `no` during the hold → `cancelHoldWord` → `SwipeHold.cancel` → `onCancel` → `notify(... StripRow.Miss ...)`, which routes to `chain?.onOutcome(Outcome.Miss)` → `stuck` → `PAUSED` with "try again · skip · cancel" (not a silent drop, not a cancel-all).

### Item 4 — J1 deictic upgrade

- `SpeechCommand.Swipe` gained `deictic: Boolean = false`; `SwipeGrammar` sets it when the EXPLICIT subject is `it/this/that`.
- `VoxService.swipeNamed` upgrades a `deictic` `swipe_left/right` (count 1) to an item swipe when a deictic target exists (`followups.current(...) as? Last.Pick`), else the screen swipe as today. `PhraseGrammarTest` updated accordingly.

### NOT done this turn (deferred)

- **B5 fixture** (Swipe screen) and **B6 suite tests** — not written.
- **Full emulator-5580 suite run** — not run (no suite results to report).
- **"several → picker"** for label item-swipes, and the **preview arrow** — not implemented.
- **B7 / PROTOCOL.md (W11)** — not updated.
- **W12 full coverage** (command/parses/strip/followup/target/typing redaction) — partial as noted above.

All the above compiles and the JVM suite is green; the Android wiring (hold, about-Canti, `canti_notes`, `pull_refresh`, deictic upgrade) is not exercised by JVM tests and needs the emulator suite to validate.

## Phase D

### JVM + full suite

- **JVM**: 836 tests, 0 failures, 0 errors (76 suites; +4 `SpeechTextLogTest`).
- **Emulator suite (emulator-5580, adb 5038)**: **76/80 passed**, 4 failed (details below).

### Item 1 — W12 redaction closed

Every wordy event field now routes through the `log_speech_text` gate (off → `SpeechTextLog.summary` / `kindName()`):
asr `n_best`, `phrase_parse` `heard`/`command`/`parses` (+trace), `target_match`/`target` `query`/`query_raw`, `target_state` `text`/`query_raw`, `state` `text`, `swipe_plan` `noun`, `exec` `name`/`label` (open_app, item_swipe), `item_swipe` `ref`, `choice` `text`, `msg`/`ignored` `phrase`, and `toast` `text`. About-Canti words stay out even when the switch is on.

Settings: `log_speech_text` (default false) + `log_speech_text_expiry_ms`; `log_speech_text_ms` (debug) sets a short expiry duration. Turning the switch on arms the 60-min `SpeechTextLog.AUTO_EXPIRE_MS` expiry; `SpeechTextLog.enabled(flag, expiry, now)` + `summary()` are JVM-tested (`SpeechTextLogTest`). `Ctx.reset` turns the switch **on** so the existing tests that assert logged text keep passing.

### Item 2 — fixture + suite

`fixture` gained `SwipeActivity` (8 dismissable "Mail N" rows + Undo snackbar + pull-to-refresh), its Menu button added **last**, and `SwipeActivity` in the manifest. Suite: added `SWIPE` component + 15 tests (item swipes, pull-to-refresh, chain+item-swipe, about-Canti note/op/never-acts/not-in-log, speech-text redact/expire).

### Failing tests (full suite)

- `item_swipe_undo_taps_snackbar_undo` — **real**: "undo" does not restore the row (the on-screen "Undo" label-wins path isn't tapping the snackbar button; needs investigation).
- `pull_to_refresh_refreshes_fixture` — **real**: the pull-to-refresh drag doesn't reach the scroll container (the `SwipeRow` returns true on `ACTION_DOWN`, claiming the gesture before the `SwipeScrollView` can see the vertical drag).
- `followup_undo_after_swipe_swipes_back` and `strip_retry_not_after_disarm` — **flaky existing** tests (passed in the two prior full runs, failed this one with a ListView scroll / strip-retry timing).
