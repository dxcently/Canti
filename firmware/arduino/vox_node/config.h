// VOX node: pins, version and compile-time switches. See firmware/README.md and firmware/HARDWARE.md.
#pragma once

#define VOX_FW_VERSION "0.1.0"

// ---- compile-time switches (pass e.g. -DVOX_INSECURE=1 via tools/build.sh --insecure) ----

// 1 = DEBUG build: EVENT/CONFIG need no encryption and no pairing (for PC tests). INFO then says "insecure":true.
#ifndef VOX_INSECURE
#define VOX_INSECURE 0
#endif

// 1 = boot armed. Default 0: the device boots awake and disarmed (5 presses, the app, or `arm` on serial arm it).
#ifndef VOX_BOOT_ARMED
#define VOX_BOOT_ARMED 0
#endif

// 1 = test-sound button trigger always on (normally: hold the button at power-on, CONFIG test_sounds, or `test on`).
#ifndef VOX_TEST_SOUNDS_DEFAULT
#define VOX_TEST_SOUNDS_DEFAULT 0
#endif

// 1 = POWER-BANK build: "sleep" (5 presses while armed, hold 1 s, CONFIG sleep, the pairing window closing) only
// disarms; the device stays awake and connected. Some power banks switch off when the draw becomes very small.
#ifndef VOX_SLEEP_STAYS_AWAKE
#define VOX_SLEEP_STAYS_AWAKE 0
#endif

// ---- pins (GPn numbers). Physical pin numbers are in HARDWARE.md ----
#define PIN_MIC_BCLK 18   // INMP441 SCK. arduino-pico I2S: WS must be BCLK + 1
#define PIN_MIC_WS 19     // INMP441 WS (not set in code: implied by BCLK + 1)
#define PIN_MIC_DATA 20   // INMP441 SD
#define PIN_BTN 14        // the one button, to GND (internal pull-up). GP15 is free: button 2 was removed
#define PIN_LED_BT 13     // blue Bluetooth-status LED: GP13 -> 100 ohm -> anode, cathode to GND, active high
                          // (GP11 and GP12 are free: the RGB LED was replaced by this single LED)

// ---- button and power timing (PROTOCOL.md "The button", "Sleep and wake", "Pairing") ----
#define BTN_DEBOUNCE_MS 25       // the level must be stable this long
#define BTN_SERIES_GAP_MS 400    // presses are one series while each starts within this long of the previous
                                 // release; a series acts this long after its last release (so a click waits too)
#define BTN_HOLD_STOP_MS 1000    // held this long: disarm at once (fires while held); sleep on release
#define BTN_HOLD_PAIR_MS 5000    // held this long: open the pairing window instead of sleeping (fires while held)
#define PAIRING_WINDOW_MS 60000  // new bonds only while this window is open; it closes early on a new bond
#define WAKE_WAIT_MS 60000       // after a 5-press wake: no bonded phone subscribed within this long = sleep again
#define SLEEP_POLL_MS 5          // asleep: the CPU idles (WFE) this long between button samples
#define WATCHDOG_MS 8000         // no loop() pass for this long (a hang) = the device restarts

// ---- LED ----
#define LED_SLOW_PERIOD_MS 1000  // BT LED, awake and no phone connected (advertising): slow blink, about 1 Hz ...
#define LED_SLOW_ON_MS 80        // ... with a short on-time
#define LED_FAST_PERIOD_MS 200   // BT LED, pairing window open, or pairing / encrypting / not yet subscribed: 5 Hz
#define LED_FAST_ON_MS 100

// ---- BLE ----
#define BLE_MAX_MTU 517          // what we accept in the MTU exchange (console `ble mtu N` lowers it)
#define BLE_TX_SLOTS 12          // queued messages
#define BLE_MSG_MAX 4096         // PROTOCOL.md: a message is at most 4096 bytes of UTF-8
