# fixture: a test app with known screens (`ai.vox.fixture`)

A small Android app whose screens behave in a fixed, observable way, so the emulator tests can check that a VOX action
had exactly the intended effect. Every observable state is a TextView with a resource id. The tests read it through
the VOX app's own `dump` control op, not uiautomator.

`src/main/java/ai/vox/fixture/Fixture.kt` holds these activities:

| Activity | What it shows and how it reacts |
|---|---|
| `MenuActivity` | Buttons that open each screen. |
| `FeedActivity` | A vertical "video" feed ("Video 1 of 20"):<br>• swipe up/down: next/previous item;<br>• swipe left/right: next/previous page (finger moving left = next);<br>• tap: play/pause;<br>• double-tap: like;<br>• long press: increments a counter;<br>• back: returns to the menu. |
| `ListActivity` | A ListView of 100 rows (the scroll tests). |
| `ControlsActivity` | A centred toggle button (tap toggles "State: ON/OFF", long press counts) and a text field (the cursor and target tests). |
| `StaticActivity` | Nothing interactive. Any gesture here must be reported as "no visible change". |

`src/main/res/values/ids.xml` declares the resource ids.

## Commands

Run these from `android/`.

```sh
./dev gradle :fixture:assembleDebug     # fixture/build/outputs/apk/debug/fixture-debug.apk
suite/run.sh setup                      # installs it on the emulator together with VOX
./dev adb shell am start -n ai.vox.fixture/.FeedActivity
```
