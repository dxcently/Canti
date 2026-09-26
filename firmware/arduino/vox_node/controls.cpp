#include "controls.h"
#include "config.h"
#include "out.h"
#include "vox_state.h"

// debounced state machine
static bool s_raw_last, s_stable;            // true = pressed
static uint32_t s_raw_since, s_press_at, s_release_at;
static bool s_ignore_until_release;          // the power-on press
static int s_series;                         // presses in the current series (0 = none pending)
static bool s_hold_stop_fired, s_hold_pair_fired;

// simulated presses: a script of level segments
#define SIM_MAX 24
static bool s_sim_level[SIM_MAX];
static uint32_t s_sim_ms[SIM_MAX];
static int s_sim_n, s_sim_i;
static uint32_t s_sim_at;                    // start of the current segment
static bool s_sim_down;

static const uint32_t SIM_CLICK_DOWN_MS = 80, SIM_CLICK_UP_MS = 150;

bool controls_raw() { return digitalRead(PIN_BTN) == LOW; }
bool controls_down() { return s_stable; }
bool controls_idle() { return !s_stable && s_series == 0 && s_sim_i >= s_sim_n && !s_sim_down; }

const char *controls_state() {
    static char buf[160];
    snprintf(buf, sizeof(buf), "button (GP%d) %s; debounced %s; series %d; simulation %s", PIN_BTN,
             controls_raw() ? "PRESSED" : "released", s_stable ? "down" : "up", s_series,
             s_sim_i < s_sim_n ? "running" : "idle");
    return buf;
}

void controls_begin() {
    pinMode(PIN_BTN, INPUT_PULLUP);
    delay(20);
    uint32_t now = millis();
    s_raw_last = s_stable = controls_raw();
    s_raw_since = now;
    if (s_stable) {
        // held at power-on: enable the test-sound trigger, and ignore this press
        s_ignore_until_release = true;
        g_state.test_sounds = true;
    }
}

static bool sim_start(int n) {
    s_sim_n = n;
    s_sim_i = 0;
    s_sim_at = millis();
    s_sim_down = s_sim_level[0];
    return true;
}

bool controls_sim_clicks(int n) {
    if (s_sim_i < s_sim_n) return false;
    if (n < 1) n = 1;
    if (n > SIM_MAX / 2) n = SIM_MAX / 2;
    for (int i = 0; i < n; i++) {
        s_sim_level[2 * i] = true;
        s_sim_ms[2 * i] = SIM_CLICK_DOWN_MS;
        s_sim_level[2 * i + 1] = false;
        s_sim_ms[2 * i + 1] = SIM_CLICK_UP_MS;
    }
    return sim_start(2 * n);
}

bool controls_sim_hold(uint32_t ms) {
    if (s_sim_i < s_sim_n) return false;
    s_sim_level[0] = true;
    s_sim_ms[0] = ms;
    s_sim_level[1] = false;
    s_sim_ms[1] = SIM_CLICK_UP_MS;
    return sim_start(2);
}

static void sim_poll(uint32_t now) {
    if (s_sim_i >= s_sim_n) {
        s_sim_down = false;
        return;
    }
    if (now - s_sim_at >= s_sim_ms[s_sim_i]) {
        s_sim_at += s_sim_ms[s_sim_i];
        s_sim_i++;
    }
    s_sim_down = s_sim_i < s_sim_n && s_sim_level[s_sim_i];
}

void controls_poll(uint32_t now) {
    sim_poll(now);
    bool r = controls_raw() || s_sim_down;
    if (r != s_raw_last) {
        s_raw_last = r;
        s_raw_since = now;
    }
    if (r != s_stable && now - s_raw_since >= BTN_DEBOUNCE_MS) {
        s_stable = r;
        if (r) {                                   // pressed
            if (s_series && now - s_release_at > BTN_SERIES_GAP_MS) {
                // cannot normally happen (the series is closed below first), but never merge two series
                on_btn_series(s_series);
                s_series = 0;
            }
            s_press_at = now;
            s_hold_stop_fired = s_hold_pair_fired = false;
        } else {                                   // released
            uint32_t held = now - s_press_at;
            if (s_ignore_until_release) {
                s_ignore_until_release = false;
                out_line("button held at power-on: test-sound trigger ON (2 presses send the next canned sound)");
            } else if (s_hold_stop_fired) {
                on_btn_hold_released(held);
            } else {
                s_series++;
                s_release_at = now;
            }
        }
    }
    if (s_stable && !s_ignore_until_release) {
        uint32_t held = now - s_press_at;
        if (!s_hold_stop_fired && held >= BTN_HOLD_STOP_MS) {
            s_hold_stop_fired = true;
            if (s_series) {
                out_printf("button: %d press(es) before this hold are ignored", s_series);
                s_series = 0;
            }
            on_btn_hold_stop();
        }
        if (!s_hold_pair_fired && held >= BTN_HOLD_PAIR_MS) {
            s_hold_pair_fired = true;
            on_btn_hold_pair();
        }
    }
    if (s_series && !s_stable && now - s_release_at > BTN_SERIES_GAP_MS) {
        int n = s_series;
        s_series = 0;
        on_btn_series(n);
    }
}
