#include "status_led.h"
#include "ble_link.h"
#include "config.h"
#include "power.h"

static int s_override = -1;   // -1 = automatic (Bluetooth status), 0 = forced off, 1 = forced on

void led_begin() {
    pinMode(PIN_LED_BT, OUTPUT);
    digitalWrite(PIN_LED_BT, LOW);
    pinMode(LED_BUILTIN, OUTPUT);
}

void led_set_override(int on) {
    s_override = on < 0 ? -1 : (on ? 1 : 0);
}

void led_update(uint32_t now) {
    static uint32_t last = 0xFFFFFFFF;
    static bool hb = false;
    // Heartbeat on the on-board LED. It is driven through the radio chip, so only touch it on a change, and never
    // while the chip is powered down (asleep: it is off by itself then).
    if (ble_powered()) {
        bool hb_on = (now % 1000) < 50;
        if (hb_on != hb) {
            hb = hb_on;
            digitalWrite(LED_BUILTIN, hb ? HIGH : LOW);
        }
    } else {
        hb = false;
    }
    if (now - last < 10) return;
    last = now;

    bool on;
    if (s_override >= 0) on = s_override;
    else if (power_asleep()) on = false;                                          // asleep: off
    else if (power_pairing_window()) on = (now % LED_FAST_PERIOD_MS) < LED_FAST_ON_MS;   // pairing window open
    else if (!ble_connected()) on = (now % LED_SLOW_PERIOD_MS) < LED_SLOW_ON_MS;   // advertising, waiting
    else if (!ble_ready()) on = (now % LED_FAST_PERIOD_MS) < LED_FAST_ON_MS;       // pairing / encrypting
    else on = false;                                                               // connected: off
    static int prev = -1;
    if ((int)on != prev) {
        digitalWrite(PIN_LED_BT, on ? HIGH : LOW);
        prev = on;
    }
}
