# ui: VOX's Flutter screens (`vox_ui`)

This module holds the phone app's screens. For now there is one, the **status screen**. It shows:
- whether the accessibility service runs, and the device: `listening`, `awake – paused`, `asleep` or
  `pairing needed`;
- mode, foreground app, Bluetooth link and decider; when pairing failed, the hint ("Hold the VOX button 5 s until the
  light blinks fast, then connect.", with the "forget VOX-XXXX" line for a stale bond) and a **Connect** button;
- a **Pause Canti / Resume Canti** button. With a BLE device ready it pauses or arms the device (the device owns
  `armed`); without one it is the app-side pause;
- while the device is connected, a **Gesture / Cursor** mode toggle and **Sleep device**. Commands the device does not
  confirm within 1.5 s show as an error;
- **Legacy settings** (the old native screen);
- the live event log.

It is a Flutter *module*, built into the Android app `ai.vox.companion` (`../android`) from source, and also runnable
as a Linux desktop window against a fake backend (`desktop/`).

Flutter 3.47.4 / Dart 3.13.3, from the pinned nix shell in `../android/nix`. Run every command through `../android/dev`,
whose wrappers keep Flutter's and pub's state in `android/.state` instead of the home directory.

## Layout

| path | what it is |
|---|---|
| `lib/vox_ui.dart` | The library entry point; it exports `lib/src`. |
| `lib/main.dart` | The Android entry point: `VoxUiApp(backend: ChannelBackend())`. |
| `lib/src/backend.dart` | `VoxStatus` (the state shown), `VoxEvent` (one event-log line), and `VoxBackend`, the interface the screens use: `status`, `events`, `setPaused`, `deviceCommand`, `connectDevice`, `hasLegacySettings`, `openLegacySettings`. `DeviceResult` is a command's outcome. |
| `lib/src/channel_backend.dart` | `ChannelBackend`: the real backend over the platform channels `ai.vox/backend` and `ai.vox/events` (`../android/PROTOCOL.md` "UI channel"; the Kotlin side is `UiBridge.kt`). |
| `lib/src/fake_backend.dart` | `FakeBackend`: in memory, for tests and the desktop runner. It simulates a connected device that confirms each command (or, with `confirmDevice: false`, times out) and goes to sleep on `sleep`. With `demo: true` it plays a loop of msg → decision → confirm events (or `ignored` while paused). |
| `lib/src/status_screen.dart` | The status screen. It refetches the status on events that change it (`arm`, `pause`, `mode`, `service`, `ble`, `reset`, `app`, `source`, `device_cmd`). |
| `lib/src/calibration.dart` | The voice cursor calibration models (`CalibStatus`, `CalibResult`, `CursorSettings`) and `CalibFlow`, the setup screen's state over the `calib_*` commands and `calib_status` pushes. |
| `lib/src/calibration_screen.dart` | The calibration setup screen (intro, hum, glide, vowels, pops, result), per mic source, with Retry/Skip on a failed step. |
| `lib/src/voice_cursor.dart` | The Voice cursor window: cursor speed, pitch sensitivity, which mics are calibrated, the saved result, Recalibrate. |
| `lib/src/app.dart` | `VoxUiApp`: MaterialApp titled Canti, with the light and dark themes (`themeMode`, default: the platform's) built for the screen's pixel scale (`PxScope`), the dot-field backdrop under the navigator, and the Press Start 2P and Tiny5 licences in the licence registry. |
| `lib/src/theme/pixel.dart` | The pixel scale `Px` (an *art pixel* is k = round(2 x devicePixelRatio) device px, about 2 dp), `PixelPaint` / `PixelArt` / `PixelCanvas` (whole-pixel drawing, origin snapped to the device grid), `PixelSnap`, `PixelGlyph` and the text styles. |
| `lib/src/theme/kit.dart` | The 1-bit kit: `PixelWindow`, `InvertedPanel`, `StatRow`, `NameBar`, `GlyphGrid`, `PixelPager`, `PixelScrollbar`, `PipMeter`, `SignalLamp` / `Signal`, `HatchBox`, `PixelIconButton`, `PixelToggle`, and `ButtonArt` for the themed Material buttons. |
| `lib/src/theme/glyphs.dart` | 1-bit bitmap glyphs: the eight gesture glyphs (12x12), row and button icons (7x7), marks (5x5). |
| `lib/src/theme/canti_theme.dart` | The brand tokens (`CantiColors`), `CantiTheme` (the two tones: ink and paper, swapped in dark) and `cantiTheme(brightness, px)`, the Material ThemeData for the kit. |
| `lib/src/theme/dither_background.dart` | `DitherBackground`: the dot-field shader behind every screen (below, "Background"). |
| `lib/src/theme/clearing.dart` | `DitherClearing` / `ClearingInk` / `ClearingShape`: clearings in the dot field around text and art on it (below, "Background"). |
| `lib/src/theme/sprite.dart` | `CantiSprite`: the badge character from its sheet and manifest (`BadgeSprite`, `BadgePlayer`: the Android badge's format and player, ported), pixel-exact. |
| `lib/src/canti_head.dart` | `CantiHead`: the header's Canti, driven by the service's badge state and the executed actions. |
| `lib/src/theme/motion.dart` | `Flicker`: the headline and the newest event switch on like a pixel screen (off, on, off, on). |
| `lib/src/theme/assets.dart` | `BrandArt` (the brand PNGs at a whole number of device px per dot, below) and `CantiAssets` (asset keys: plain in the Android module, `packages/vox_ui/` in the desktop runner). |
| `shaders/dither_field.frag` | The background's fragment shader. |
| `assets/brand/` | The icon (on/off) and the wordmark (ink, light) as pixel-exact PNGs, one per whole-pixel scale (`name@n.png`), made by `../brand/tools/stipple.py app`. Don't edit; regenerate. |
| `assets/badge/` | The Canti character sheet and manifest (made by `../brand/tools/canti_sprite.py`), the only copy: the header plays it and the Android floating badge (`CantiBadgeView`) reads it from the APK's `flutter_assets/`. `test/sprite_test.dart` checks it is declared. |
| `assets/fonts/` | Press Start 2P and Tiny5, and their licences (SIL OFL 1.1). |
| `test/status_screen_test.dart` | Widget tests of the status screen (15), below. |
| `test/calibration_test.dart` | The calibration models, `CalibFlow`, the setup screen, the first-run prompt, the Voice cursor window (recalibration nudge, level gate), the fake's `calib_*` contract and the channel's `calib_*` calls (33). |
| `test/brand_art_test.dart` | The brand PNGs' whole-pixel scale at 1x, 1.5x, 2.625x, 3x and 4x (6), below. |
| `test/sprite_test.dart` | The badge manifest, the player, and the header's state mapping (5), below. |
| `test/clearing_test.dart` | The clearings rendered for real on a Z Flip-sized screen, and the Bayer matrix and distance field (3), below. |
| `desktop/` | A thin Linux desktop app (`vox_ui_desktop`) that depends on this package by path and runs the status screen on `FakeBackend(demo: true)`. Its own `test/desktop_test.dart`. |
| `.android/`, `.ios/`, `.dart_tool/`, `build/` | Generated by `flutter pub get` / builds; git-ignored. `.android/include_flutter.groovy` is what `../android/settings.gradle.kts` applies. |

## How it gets into the Android app

The integration is from source ("add-to-app", option B):
- `../android/settings.gradle.kts` applies `ui/.android/include_flutter.groovy`, which adds the `:flutter` project,
  and `app/build.gradle.kts` depends on it;
- `MainActivity` is a `FlutterActivity` with the default engine and entry point.

One `gradle assembleDebug` therefore builds the Kotlin and the Dart, with no AAR publishing step and no local
Maven repository. The cost is that `flutter pub get` must have run here first, because it generates `.android/`.
`../android/suite/run.sh build` does that.

Why not a prebuilt AAR: it needs a separate `flutter build aar` step, and its versions must be kept in step by hand.
That suits a team that ships the Android app without Flutter installed, which is not the case here.

## Commands

From `~/VOX/android` (the dev shell cds there):

```sh
./dev bash -c 'cd ../ui && flutter pub get'            # after checkout or pubspec changes; generates .android/
./dev bash -c 'cd ../ui && flutter analyze && flutter test'
./dev bash -c 'cd ../ui/desktop && flutter test'
suite/run.sh build                                      # pub get + the Android build with this module inside
suite/run.sh test -k ui_flutter                         # the emulator test of this screen (needs suite/run.sh boot setup)
```

**Desktop window** (fake backend, demo events every few seconds):

```sh
cd ~/VOX/android && ./dev bash -c 'cd ../ui/desktop && flutter run -d linux'
```

Or build once and run the binary:

```sh
cd ~/VOX/android && ./dev bash -c 'cd ../ui/desktop && flutter build linux --release'
~/VOX/ui/desktop/build/linux/x64/release/bundle/vox_ui_desktop
```

Environment for the desktop runner: `VOX_THEME=light|dark` forces a theme; `VOX_FRAME_STATS=N` (with a
`--profile` build) prints frame-time percentiles after N seconds and exits.

`VOX_PREVIEW=calibrate|cursor|settings` opens the voice cursor screens on the fake's made-up `calib_status` stream
(`desktop/lib/preview.dart`): `calibrate` walks the setup screen from Begin to the result, `cursor` is the status
screen in cursor mode on an uncalibrated phone mic (the first-run prompt), `settings` the Voice cursor window alone.
`VOX_PREVIEW_HOLD=intro|waiting|hum|glide|vowels|pops|clicks|whistle|hiss|room|failed|result` stops there and holds
still (clicks once two are heard, hiss once one is); `VOX_PREVIEW_FAIL=STEP` fails that step once (the preview skips
it; with `HOLD=failed` it holds the failure, the glide by default); `VOX_PREVIEW_POPS=N` sets the pops heard.
`VOX_PREVIEW_SAVED=1` gives the phone mic a saved profile (all eight steps), `VOX_PREVIEW_SAVED=v1` one saved before
calibration v2 (the settings window then shows the "4 new steps" nudge). With `VOX_PREVIEW_SAVED=v1`,
`VOX_PREVIEW_STEPS=missing` makes `calibrate` record only its missing steps (`calib_start {source, steps}`).

`VOX_PREVIEW=train` opens the Train gestures screen on the in-memory `FakeTrainBackend` (`desktop/lib/train_preview.dart`):
live by default (a take records for about 2 s with a made-up pitch trace; the first arch take is heard as a dip), or
held still with `VOX_PREVIEW_HOLD=grid|recording|failed|finished`.

`VOX_PREVIEW=recorder` opens the in-app test recorder on the in-memory `FakeRecorderBackend`
(`desktop/lib/recorder_preview.dart`, dev builds only on the phone): live by default, or held still with
`VOX_PREVIEW_HOLD=start|hub|ready|countdown|recording|longest|room|saved|no_sound|rate|done` (`longest` records the
spec's longest cue). `VOX_PREVIEW=quickrec` is the quick record screen on a snapshot, `VOX_PREVIEW=shape` the
heard-vs-expected plot's variants. `test/recorder_layout_test.dart` renders every recorder and quick record screen
at Z Flip size, light and dark; `VOX_SHOTS_DIR=<dir>` also writes them there as PNGs.

To run it headless (no window on your desktop), for example for a screenshot, force X11 under Xvfb:
`env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run -a <the binary>`. Without that, GTK uses the Wayland session even
inside `xvfb-run`.

## Look: the Canti pixel kit

The brand is `../brand` (colours, shape language, the stipple rules). Here it becomes a 1-bit pixel kit, after a 1-bit
RPG UI kit, reduced to what the app needs:

- **Two tones.** Each theme has an ink and a paper: visor-navy on mint-cream (light), the same pair swapped (dark).
  Everything is one or the other; there are no greys, gradients, tints or shadows. The only other colours are the
  brand art and the status lamp. `cantiTheme(brightness, px)` builds the Material ThemeData from them, and widgets read
  `CantiTheme.of(context)`; screens never hard-code a colour.
- **One pixel grid.** Frames, glyphs and fonts are drawn in *art pixels* (`Px`): k = round(2 x devicePixelRatio)
  whole device pixels each, about 2 dp (1.905 dp on a 2.625x phone). `PixelPaint` draws rects on that grid with no
  anti-aliasing and snaps its origin to the device grid, so nothing is resampled. The pixel faces are only used at 8 x
  the scale (both are drawn on an 8-unit em): Press Start 2P for titles, labels and buttons, Tiny5 for body text. The
  platform text scale is applied in whole steps.
- **The kit's pieces.** Windows with a double-line frame, notched corners, a title tab in capitals and an optional
  close box; inverted panels (ink fill) with stat rows (a framed icon, a LABEL, a dotted leader, the value); the
  bindings grid with a corner-bracket cursor and a name bar; a pager, a pixel scrollbar, a status lamp. Buttons stay
  plain `FilledButton` / `OutlinedButton` / `IconButton` (keys, semantics and tests are unchanged), themed as square
  framed boxes: a double frame for the main action, inverted while pressed or selected, a dotted frame when disabled,
  corner brackets on hover and focus. No elevation, no ripples.
- **Signals.** The status lamp is the only coloured UI: orange while sounds act (listening), yellow while something is
  pending (a device command, connecting, pairing needed), red when stopped by a fault (service off, a device error),
  dark (an empty frame) when idle or paused.
- **Brand art.** The header has Canti, the stipple wordmark (the mint-cream one in dark) and refresh, in a clearing of
  the dot field (below, "Background"). `BrandArt` draws the wordmark at a whole number of device pixels per dot, from
  the PNG made for that scale, 1:1 with `FilterQuality.none`, snapped to the device grid: one dot per art pixel (k
  device px, so its dots share the kit's grid; 178 x 82 dp at 1x and 3x, 169.5 x 78 dp at 2.625x). An image scaled by a
  fraction would make every few dots a pixel wider than the rest. (`BrandArt.icon`, the static icon at
  n = round(devicePixelRatio) px per dot, is kept for other screens.)
- **Canti.** The floating badge's character, docked in the header while the app is in front (the service hides the
  floating one while a Canti activity is resumed, so the two never show at once). `CantiSprite` reads the same sheet
  and manifest as the Android `CantiBadgeView` (frame grid; per state the frames, ms per frame, loop, and a still
  frame) and plays them with a port of its `BadgePlayer`: one sheet art pixel per kit art pixel (34 x 47 art px, 64.8 x 89.5 dp
  at 2.625x, centred in a 40-art-px slot so the wordmark keeps its place), nearest-neighbour, one timer for the next frame change and none while the frame can't change, still
  frames when the platform asks for reduced motion, in the background and under `flutter test`. `CantiHead` drives
  it: the held state is the service's (`VoxStatus.badge`, then `badge{event: state}` events), or, from an older
  service or the desktop, worked out from the status (off, paused, error, cursor, idle); each `exec{action, ok}`
  event plays its one-shot (scroll up or down, back, forward, home; error on failure; a beat of hearing for `none`).
- **Motion.** Two tones allow no fades: the headline and the newest event flicker on (off, on, off, on in 240 ms).
  A plain AnimationController.

### Background

`DitherBackground` draws a one-colour, 1-bit ordered-dither dot field behind every screen, after the FLCL-style
isometric pixel art: a dot field along the top that thins out downward (a 50% checker, then scattered dots, the edge
drifting slowly), and a row of EQ bars along the bottom (3 cells wide, a solid cap over a body that fades upward) that
shows what Canti is doing. It is one fragment shader (`shaders/dither_field.frag`, 4x4 Bayer
computed from the cell index, no textures) on one full-screen rect:

- in its own layer (`RepaintBoundary`), so nothing above repaints it and it repaints nothing above;
- a dot every 2 art pixels (2k device px) with a gap of about 0.4 art px in whole device pixels, so the dots are
  square and crisp and share the windows' grid;
- animated by one uniform (`uTime`), advanced by a timer 6 times a second through a `ValueNotifier` the painter
  listens to: no widget rebuilds;
- paused when the app isn't visible (`AppLifecycleListener`), off when the platform asks for reduced motion, and off
  under `flutter test`. If the shader can't load, nothing is drawn.

**EQ bars.** A `BackdropMood` (in `dither_background.dart`, handed down by `BackdropScope` above the navigator)
picks the motif, the shader's `uMode`:

- **ticks** (idle, cursor, error): a calm row of short ticks, 1 or 2 cells high;
- **bars** (hearing, pending, hold-scroll; or a screen recording a take): level bars up to 12 cells, a peak dot
  over every other one, all within the band (`eqBandCells`, 14 cells), moving with `uTime`. Their height is the
  live mic level (`uLevel`, -60..-15 dBFS -> 0..1) when one reaches the UI: the calibration screen's
  `calib_status.live.level_db` while a step waits or records, the training screen's `train_status` take level from
  a phone or USB mic. Otherwise (a sound in normal use, a take on the Canti device) a made-up level;
- **flat** (off, paused, tap-to-wake): no bars at all and the top field thinned to a quarter, and the timer stops:
  the screen goes quiet, so a disabled Canti shows at a glance.

`CantiHead` (the status screen's header) writes its held state into the mood (status and `badge{event: state}`
events); the calibration and training screens set `listen(on, levelDb:)` while they record and clear it when they
close. Only the background listens: no widget rebuilds.

The status screen fills the page with windows, so it keeps a strip of `eqBandCells` cells clear above the navigation
bar (its scroll view ends there): the band always shows on the home page, on the phone and the desktop.

**Clearings.** Text and art straight on the field get a clearing, not a plate: the dots thin out to clear paper in the
field's own terms, whole cells of its grid ordered by its Bayer matrix.

- Under the system bars: the app is edge-to-edge on Android, so the field would run under the status bar and hide
  the clock and icons. `DitherBackground(insets:)` gets the view padding; the shader keeps the cells under the top and
  bottom bars clear, starts the top field below the status bar, stands the EQ bars on the navigation bar, and fades
  in from both edges over 3 cells (the allowed density rising to the field's 50% tone). On the desktop the insets are
  0, so the field fades in from the window's edges.
- Around ink: a `DitherClearing` paints the cells it clears in the paper colour before its child (over the field's
  layer, under the ink). Its inks are the `ClearingInk`s below it, each a pixel shape (`ClearingShape`: a chamfer
  distance field of a PNG's opaque pixels, for example the wordmark's letters and subtitle, or every pixel any frame
  of the Canti sheet uses) or its box (the refresh button). A cell is clear within 3 art px of the ink; over the next
  6 its dot comes back while its Bayer threshold is under the ramp (0 to 50%); beyond that the field is untouched.
  Cells are placed from the screen position at paint time, so the clearing scrolls with the header and never splits a
  dot, whatever the scroll offset; the path is cached while nothing moves.
- Everything else on the field sits in windows (paper-filled, framed), including their title tabs and the pager.

### Libraries

No third-party packages. The UI elements are Material 3's (in the SDK), themed; the rest is the small code in
`lib/src/theme`. What was tried and why it went:

- `flutter_svg` / `vector_graphics` (+ its build-time compiler) drew the brand SVGs. Replaced by PNGs: the brand art is
  pixel art, and an SVG of squares drawn at an arbitrary size is resampled, so the dots blur and seam. PNG variants per
  device-pixel ratio, drawn with `FilterQuality.none`, stay 1:1; they are also smaller than the compiled vectors and
  need no build-time transformer (whose path optimisers need a library the nix Flutter lacks).
- `flutter_animate`: its zero-delay timers stay pending at the end of widget tests, which then fail. The one effect
  used is 33 lines in `motion.dart`.
- `google_fonts`: not used. It fetches fonts at run time; Press Start 2P and Tiny5 are bundled instead
  (`assets/fonts`, OFL, listed in the app's licences).
- `cupertino_icons`: removed (unused; 257 KB).

### Performance

Measured on 2026-09-26 on the first restyle (the cartoon-edged look, with a slide-in for the newest event),
before the pixel kit; not re-measured since. The structure below is the same in the kit.

**Frame times.** Desktop runner, `--profile`, 420 x 820 window, `FakeBackend(demo: true)` (an event burst every 1.5 s,
the headline flicker, the newest-event slide-in) and the animated background; 20 s with
`VOX_FRAME_STATS=20`:

| | frames | build p50 / p90 / p99 | raster p50 / p90 / p99 | total p50 / p99 |
|---|---|---|---|---|
| Wayland, GPU (Strix Halo) | 296 | 0.18 / 0.43 / 2.54 ms | 0.96 / 1.43 / 2.10 ms | 2.81 / 6.46 ms |
| Xvfb, software GL (llvmpipe) | 255 | 0.21 / 0.33 / 2.40 ms | 5.71 / 6.85 / 9.07 ms | 7.58 / 18.20 ms |

The maxima (11-57 ms raster) are the first frames (shader and font loading). About 15 frames a second in total: 6
from the background, the rest from the demo events; with the background still and no events the app draws nothing.

What keeps it cheap: `const` constructors throughout; the event log is a bounded `ListQueue` (50) behind a
`ChangeNotifier` that only the `ListView.builder` listens to, so an event rebuilds the list, not the screen; status
refreshes are coalesced (one in flight, at most one queued); the themes are built once (static), not per build; the
background is its own layer, driven by a uniform; the kit paints its frames as rects in a `PixelArt` on one render
object per piece, not as widgets.

**APK size.** `:app:assembleRelease` (unsigned, three ABIs, minify off), before this restyle and after:

| | before | after |
|---|---|---|
| APK | 52,438,006 B | 52,364,583 B (-73 KB) |
| arm64-only estimate (without the x86_64 and armv7 libraries) | 22.79 MB | 22.45 MB |
| MaterialIcons (compressed in the APK) | 556 KB (not tree-shaken) | 1.5 KB (`tree-shake-icons=true` in `../android/gradle.properties`) |
| CupertinoIcons | 116 KB | removed |
| libapp.so (Dart code, arm64) | 3.74 MB | 3.87 MB |

That restyle added about 110 KB of brand PNGs (four ratios), 22 KB of fonts and a 6 KB shader, and 128 KB of Dart
per ABI. `classes.dex` grew 41 KB, most of it other work in the same build. In the pixel kit the brand PNGs (24, one
per whole-pixel scale) are 130 KB and the two fonts 250 KB.

## Tests

`test/status_screen_test.dart`:
- the status fields from the backend;
- without a device, pause and resume are the app-side pause;
- with a device, the main button pauses and arms the device, and resume also lifts an app-side pause;
- the mode toggle and **Sleep device** send device commands; asleep (from a command or from the service) is shown
  as asleep, not as an error;
- a command the device never confirms shows its failure;
- live events, newest first, capped at 50, and the status refetched on an `arm` event;
- service off: the pause button is disabled;
- pairing needed: the hint, and **Connect** tries again;
- the legacy-settings button;
- **accessibility**, with Flutter's guidelines:
  - every tap target is labelled and at least 48x48 dp (Android), and text contrast passes in light and dark;
  - the exact semantics Android sees: `Pause Canti` is a button with a tap action, `Refresh status` is a tooltip
    button, `Legacy settings`, `Sleep device` and the Gesture/Cursor segments are buttons;
- `ChannelBackend` against mocked channels: method names and arguments (including `deviceCommand` and
  `connectDevice`), map parsing, the event stream, and the
  service-off answer.

`test/sprite_test.dart`: the ui copy of the badge sheet matches the Android one byte for byte; the manifest has every
state the header uses and fails the same checks as Kotlin's; the player loops, hands a one-shot back to the held loop,
plays hold-scroll in the last scroll's direction and shows still frames with reduced motion; the held state and the
one-shots come from the status and the actions as in Badge.kt.

`test/clearing_test.dart`: `bayer4` is the shader's 4x4 matrix; the distance field; and, rendered with the real shader
on a 1080 x 2640 px screen at 2.625x with a 94 px status bar, light and dark, scrolled by a fraction of a pixel: every
field cell around the header is whole (one colour over its dot), the header has cleared and kept cells, the rows under
the subtitle are clear, and nothing is drawn under the status bar.

`test/brand_art_test.dart`: at 1x, 1.5x, 2.625x, 3x and 4x the wordmark and the icon come from the PNG for their
scale (k and round(devicePixelRatio) device px per dot), are exactly that many device pixels, are drawn with
`FilterQuality.none` and are painted on the device grid; and which PNG and whole magnification a scale above the
largest PNG uses.

The Android side of the same question, whether VOX's own accessibility service can read and operate these widgets, is
the emulator test `ui_flutter_status_screen_is_readable_and_pausable` (`../android/suite/test_suite.py`). Its
`targets` op lists `Pause Canti (button, left)`, `Refresh status (button, top right)` and
`Legacy settings (button, center)`. It taps them at the listed bounds, and checks pause, resume and the legacy screen
through the event log.

Sizes and start times of the app with this module inside are in `../android/README.md` "Flutter UI".
