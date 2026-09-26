// Awake / asleep, the pairing window, the wait for a phone after a wake, and what the button does
// (android/PROTOCOL.md "BLE GATT link (v1)": The button, Sleep and wake, Pairing, Disconnect).
//
// Sleep: send {"armed":false,"sleeping":true,...} (if a phone is subscribed), drop the link, power the CYW43 radio
// chip down, stop the mic's I2S. The CPU keeps running at a low duty cycle (WFE between button samples every
// SLEEP_POLL_MS) so that USB serial and the button keep working; see README.md "Sleep" for the current draw.
// A VOX_SLEEP_STAYS_AWAKE build only disarms instead (power banks).
#pragma once
#include <Arduino.h>

void power_poll(uint32_t now);
bool power_asleep();
bool power_pairing_window();
void power_sleep(const char *why);      // "turn off": the same for the button, the app and the timeouts
void power_disarmed();                  // any disarm: a pending arm-on-subscribe (after a 5-press wake) is dropped
void power_wake_plain(const char *why);  // wake without arming and without a pairing window (serial `wake`)
void power_status();                    // prints the "power: ..." status line

// BLE hooks, forwarded from the sketch
void power_ble_ready();                 // a phone subscribed to EVENT: arm if woken with 5 presses, send the state
void power_ble_bonded();                // a new bond: the pairing window closes
