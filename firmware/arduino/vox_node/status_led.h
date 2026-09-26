// Bluetooth status LED: one blue LED on PIN_LED_BT (GP13 -> 100 ohm -> anode, cathode to GND, active high),
// plus the on-board heartbeat LED. The LED shows ONLY the Bluetooth link and sleep; armed/paused and the mode are
// shown on the phone, not here.
//
//   asleep                                                   off
//   pairing window open (60 s after a 5 s hold)              fast blink: LED_FAST_ON_MS every LED_FAST_PERIOD_MS
//   awake, no phone connected (advertising, waiting for a    slow blink: LED_SLOW_ON_MS every LED_SLOW_PERIOD_MS
//     bonded phone)
//   connected, pairing / encrypting / not yet subscribed     fast blink
//   connected and subscribed (any armed state or mode)       off
//   on-board LED                                             heartbeat: 50 ms every second while awake (it is
//                                                            wired to the radio chip, which is off while asleep)
#pragma once
#include <Arduino.h>

void led_begin();
void led_update(uint32_t now);
void led_set_override(int on);   // console `led on|off|auto` for the wiring test: 1 = on, 0 = off, < 0 = automatic
