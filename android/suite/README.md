# suite: emulator lifecycle, setup, tests and harvest

Host-side code that runs the app on a headless Android emulator. It boots and stops the emulator, installs VOX, the
fixture app and pinned F-Droid stand-in apps, then sends real feature messages through the app's debug socket. The
tests assert on the app's own tree dump, screenshots and event log. Everything runs inside the nix dev shell (`../dev`);
`run.sh` enters it for you.

| File | What it does |
|---|---|
| `run.sh` | The single entry point: `build`, `boot`, `setup`, `test`, `harvest`, `stop`, `jev start\|stop\|status`, `all` (`all` stops the emulator even on failure). |
| `emu.sh` | Creates the AVD `vox35` (API 35, x86_64, 1080x2400, no camera) and boots it headless under KVM. `stop` kills only the emulator it started. It refuses to start a second emulator. |
| `apks.py`, `apks.lock.json` | The stand-in apps: `lock` resolves each app from F-Droid's index into the lockfile (URL, sha256, size); `fetch` downloads them into `apks/` and verifies the hashes. |
| `setup_device.py` | Installs VOX, the fixture and the locked stand-ins; seeds 5 photos; downloads Organic Maps' world map; enables the VOX accessibility service. |
| `test_suite.py` | The emulator tests (34): every default gesture on the fixture, the timing rule, device timestamps, the confirmer, cursor mode, the model decider against a fake server, the real local Jev server, intent cursor mode, personalization, the BLE ops without a device, one gesture in each stand-in, and VOX's own Flutter status screen read and operated through the accessibility tree. |
| `voxlib.py` | Helpers: `adb`, the debug-socket client `Vox` (messages and control ops), the event-log reader `EventStream`, screenshots and their diff, app launch, first-run dialog dismissal. |
| `servers.py` | `FakeSystemOne`, a deterministic `/v1/systemone` on port 8767 that records requests, and `WebServer`, which serves `www/` for the browser stand-in. Both reach the emulator through `adb reverse`. |
| `harvest.py` | Walks the launcher, the fixture and the stand-ins. Writes what the screen summariser sees to `out/harvest-*.jsonl`, and the intent cursor option lists to `out/targets-harvest-*.jsonl`. |
| `enroll.py` | Pushes personalization examples (JSONL: `kind`, `name`, `fp`, `fp_version`, `pitch16`) to the app's active profile; also `list`, `delete` and `clear`. |
| `ctl.py` | Sends one control op and prints the reply: `ctl.py ble_status`, `ctl.py ble_connect address=auto` (key=value, JSON values). Used for manual tests on a real phone (`VOX_SERIAL=<serial>`), e.g. the BLE end-to-end test in `../README.md`. |
| `harvest_real.py` | Walks the emulator apps for the real-screen test set (`finetune/data/real-targets-v1`). For each screen it saves a screenshot and the app's own `targets` op reply (options, bounds, screen line, state template). |
| `tree_targets.py` | A Python port of `Targets.kt` / `ScreenSummarizer.kt` over `uiautomator dump` XML, for phones where the VOX service is off. Its known gaps are listed at the top of the file. |
| `harvest_device.py`, `harvest_device.sh` | Capture from a USB phone (`status`, `cap <app>/<state>`, `open <package>`). Writes a PNG, the uiautomator XML and the option list to the gitignored `finetune/data/real-targets-v1/zflip/raw`. The options come from the app's `targets` op when its service is on, and from `tree_targets.py` otherwise. Nothing is tapped. |
| `www/long.html` | A long page for the Fennec scroll test. |

Not tracked: `apks/` (downloaded APKs, about 284 MB) and `out/` (results, harvests, logs).

## Commands

Run these from `android/`.

```sh
suite/run.sh all                 # build, boot, setup, test, harvest, stop
suite/run.sh boot                # VOX_WIPE=1 for a factory-fresh device
suite/run.sh setup
suite/run.sh test                # all tests; results in suite/out/results-<time>.json
suite/run.sh test -k personal    # only tests whose name contains "personal"
suite/run.sh harvest
suite/run.sh jev start           # the real local /v1/systemone on :8765 (for jev_local_systemone_vox_jevlike; SKIP without it)
suite/run.sh jev stop
suite/run.sh stop                # always stop the emulator when done
```

A test that cannot run in this environment reports `SKIP`, not a pass. The run is successful when every test passed or was skipped.
