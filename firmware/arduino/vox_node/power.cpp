#include "power.h"
#include "ble_link.h"
#include "config.h"
#include "controls.h"
#include "mic.h"
#include "out.h"
#include "test_player.h"
#include "vox_state.h"

static bool s_asleep;
static bool s_window;                 // pairing window open
static uint32_t s_window_until;
static bool s_wake_wait;              // woken with 5 presses, no phone subscribed yet
static uint32_t s_wake_until;
static bool s_arm_on_subscribe;       // woken with 5 presses: arm when a phone subscribes

bool power_asleep() { return s_asleep; }
bool power_pairing_window() { return s_window; }
void power_disarmed() { s_arm_on_subscribe = false; }

static void window_open(const char *why) {
    s_window = true;
    s_window_until = millis() + PAIRING_WINDOW_MS;
    s_wake_wait = false;              // the window's own timeout applies now
    ble_set_pairing_window(true);
    out_printf("pairing window OPEN for %lu s (%s): a new phone can pair now; closes on a new bond",
               (unsigned long)(PAIRING_WINDOW_MS / 1000), why);
    if (ble_connected()) {
        out_line("pairing window: dropping the current link");
        ble_disconnect();
    }
}

static void window_close_quiet() {
    if (!s_window) return;
    s_window = false;
    ble_set_pairing_window(false);
}

void power_sleep(const char *why) {
    if (s_asleep) return;
    player_cancel();
    s_arm_on_subscribe = false;
    s_wake_wait = false;
    window_close_quiet();
    g_state.stopped = false;
#if VOX_SLEEP_STAYS_AWAKE
    g_state.armed = false;
    out_printf("sleep (%s): power-bank build, so only disarm and stay awake", why);
    state_send_current(why);
    return;
#else
    out_printf("going to sleep (%s)", why);
    if (ble_ready() && state_send_sleeping(why)) {
        // let the last message reach the phone before the link goes: queue empty, then a few connection intervals
        uint32_t t0 = millis();
        while (!ble_tx_idle() && millis() - t0 < 1000) delay(2);
        delay(300);
    }
    g_state.armed = false;
    ble_power_off();
    mic_end();
    s_asleep = true;
    ble_poll();   // print the BT log, run the disconnect hook
    out_line("asleep: radio and mic off. 5 presses wake it (it arms when the phone subscribes); "
             "holding 5 s wakes it and opens the pairing window");
#endif
}

static void wake(const char *why, bool arm_on_subscribe, bool window) {
    out_printf("waking up (%s)", why);
    uint32_t t0 = millis();
    s_asleep = false;
    if (!ble_power_on()) out_line("wake: the radio did NOT start (see the log above); `reboot` to recover");
    mic_begin();
    out_printf("awake after %lu ms: advertising", (unsigned long)(millis() - t0));
    if (arm_on_subscribe) {
        s_arm_on_subscribe = true;
        s_wake_wait = true;
        s_wake_until = millis() + WAKE_WAIT_MS;
        out_printf("waiting up to %lu s for a bonded phone; it arms when the phone subscribes",
                   (unsigned long)(WAKE_WAIT_MS / 1000));
    }
    if (window) window_open(why);
}

void power_poll(uint32_t now) {
    if (s_window && (int32_t)(now - s_window_until) >= 0) {
        window_close_quiet();
        out_printf("pairing window closed after %lu s without a new bond", (unsigned long)(PAIRING_WINDOW_MS / 1000));
        if (!ble_connected()) {
            power_sleep("pairing window closed without a new bond");
        } else {
            // PROTOCOL.md "Pairing": a (bonded) phone is connected, so stay awake and disarmed
            out_line("a phone is connected: staying awake, disarmed");
            if (g_state.armed) {
                player_cancel();
                power_disarmed();
                state_pause("pairing window closed with a phone connected");
            }
        }
    }
    if (s_wake_wait && (int32_t)(now - s_wake_until) >= 0) {
        s_wake_wait = false;
        power_sleep("no bonded phone subscribed within 60 s of waking");
    }
}

void power_ble_ready() {
    s_wake_wait = false;
    if (s_arm_on_subscribe) {
        s_arm_on_subscribe = false;
        g_state.armed = true;
        g_state.stopped = false;
        out_printf("state: armed, %s mode (woken with 5 presses; the phone subscribed)", mode_name(g_state.mode));
    }
    state_send_current("phone subscribed");
}

void power_ble_bonded() {
    if (!s_window) return;
    window_close_quiet();
    out_line("pairing window closed: new bond made");
}

void power_status() {
    if (s_asleep) {
        out_line("power: asleep (radio and mic off)");
        return;
    }
    char w[64] = "", k[96] = "";
    uint32_t now = millis();
    if (s_window) snprintf(w, sizeof(w), "; pairing window OPEN, %ld s left", (long)(int32_t)(s_window_until - now) / 1000);
    if (s_wake_wait)
        snprintf(k, sizeof(k), "; waiting for a bonded phone, %ld s left%s", (long)(int32_t)(s_wake_until - now) / 1000,
                 s_arm_on_subscribe ? " (arms when it subscribes)" : "");
    out_printf("power: awake%s%s%s", w, k, VOX_SLEEP_STAYS_AWAKE ? " (power-bank build: sleep only disarms)" : "");
}

// ---- the button (PROTOCOL.md "The button") ----
void on_btn_series(int n) {
    if (s_asleep) {
        if (n == 5) wake("5 presses", true, false);
        else out_printf("asleep: %d press%s ignored (5 presses wake it)", n, n == 1 ? "" : "es");
        return;
    }
    if (n == 1) {
        state_toggle_mode("button click");
    } else if (n == 2 && g_state.test_sounds) {
        player_next_in_cycle();
    } else if (n == 5) {
        if (g_state.armed) {
            power_sleep("5 presses while armed");
        } else {
            state_arm("5 presses");
        }
    } else {
        out_printf("button: %d presses do nothing", n);
    }
}

void on_btn_hold_stop() {
    if (s_asleep) {
        out_line("asleep: hold 1 s does nothing (hold 5 s to wake and pair)");
        return;
    }
    player_cancel();
    power_disarmed();
    state_stop("button held 1 s (fast stop)");
}

void on_btn_hold_pair() {
    if (s_asleep) {
        wake("button held 5 s", false, true);
        return;
    }
    // already disarmed at 1 s; open the window instead of sleeping on release
    window_open("button held 5 s");
}

void on_btn_hold_released(uint32_t held_ms) {
    if (s_asleep) return;
    if (held_ms >= BTN_HOLD_PAIR_MS) return;   // the pairing window opened instead
    power_sleep("button hold released");
}

void power_wake_plain(const char *why) {
    if (s_asleep) wake(why, false, false);
}
