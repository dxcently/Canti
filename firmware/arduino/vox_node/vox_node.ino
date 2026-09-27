// VOX node: the Pico 2 W side of VOX (android/PROTOCOL.md, "BLE GATT link (v1)").
// One button + blue Bluetooth LED + BLE feature messages + sleep/wake + pairing window + canned test sounds +
// INMP441 mic diagnostics + the on-device feature extractor (ext.h: firmware/extract on core 1; each sound goes out
// as a feature message with its fp1 `features`).
// Build with tools/build.sh (it regenerates test_sounds.h from the Python extractor first, and compiles
// firmware/extract as a library).
// Board: rp2040:rp2040:rpipico2w with ipbtstack=ipv4btcble (Bluetooth on).
#include "ble_link.h"
#include "config.h"
#include "console.h"
#include "controls.h"
#include "ext.h"
#include "mic.h"
#include "out.h"
#include "power.h"
#include "status_led.h"
#include "test_player.h"
#include "vox_state.h"

static void update_info() {
    char info[200];
    const char *fpv = ext_fp_version();   // "fp1" while the extractor sends features, else null
    snprintf(info, sizeof(info), "{\"v\":1,\"fw\":\"%s\",\"mic\":\"%s\",\"fp_version\":%s%s%s%s}", VOX_FW_VERSION,
             mic_present() ? "inmp441" : "none", fpv ? "\"" : "null", fpv ? fpv : "", fpv ? "\"" : "",
             VOX_INSECURE ? ",\"insecure\":true" : "");
    ble_set_info(info);
}

void info_changed() { update_info(); }

void mic_changed(bool present) {
    (void)present;
    update_info();
}

// ---- BLE hooks (run from loop via ble_poll) ----
void on_ble_ready() {
    power_ble_ready();    // state on connect (armed:true after a 5-press wake)
}

void on_ble_bonded() {
    power_ble_bonded();
}

void on_ble_disconnected() {
    // PROTOCOL.md "Disconnect": the device is disarmed, and stays disarmed when the phone reconnects.
    player_cancel();
    if (g_state.armed) {
        g_state.armed = false;
        out_line("state: paused (link lost)");
    }
}

// Minimal JSON scanning for CONFIG.
static const char *skip_ws(const char *p) {
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    return p;
}

static const char *skip_string(const char *p) {  // p at the opening quote; returns past the closing quote
    for (p++; *p; p++) {
        if (*p == '\\' && p[1]) p++;
        else if (*p == '"') return p + 1;
    }
    return nullptr;
}

static const char *skip_value(const char *p) {
    p = skip_ws(p);
    if (*p == '"') return skip_string(p);
    if (*p == '{' || *p == '[') {
        int depth = 0;
        while (*p) {
            if (*p == '"') {
                p = skip_string(p);
                if (!p) return nullptr;
                continue;
            }
            if (*p == '{' || *p == '[') depth++;
            if (*p == '}' || *p == ']') {
                if (--depth == 0) return p + 1;
            }
            p++;
        }
        return nullptr;
    }
    const char *s = p;
    while (*p && *p != ',' && *p != '}' && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') p++;
    return p > s ? p : nullptr;
}

// CONFIG (PROTOCOL.md "App commands" and "Replies"): {"v":1,"armed":true|false}, {"v":1,"mode":"gesture"|"cursor"}
// (armed and mode may come together), {"v":1,"sleep":true}; also {"v":1,"test_sounds":true|false}. Unknown keys are
// ignored. A write reaches this only on an encrypted link (the GATT permission; a VOX_INSECURE build needs none)
// while awake and connected.
// Every write that reaches this gets exactly one no-sound state message in reply, with a fresh id, even if nothing
// changed. For sleep the reply is the "sleeping":true message. A refused write (not a JSON object, malformed JSON,
// a bad value for a known key) changes nothing and its reply carries "rejected":"<reason>".
static bool is_lit(const char *v0, const char *v1, const char *lit) {
    size_t n = strlen(lit);
    return (size_t)(v1 - v0) == n && !strncmp(v0, lit, n);
}

static void config_reject(const char *reason) {
    out_printf("CONFIG: rejected (%s); nothing changed", reason);
    state_send_rejected(reason);
}

void on_ble_config(const char *json, size_t len) {
    out_printf("CONFIG write (%u bytes): %.*s", (unsigned)len, (int)(len > 200 ? 200 : len), json);
    if (power_asleep()) {                 // cannot happen (the radio is off then), but never act on it
        out_line("CONFIG: ignored while asleep");
        return;
    }
    const char *p = skip_ws(json);
    if (*p != '{') {
        out_line("CONFIG: not a JSON object");
        config_reject("not a JSON object");
        return;
    }
    int armed = -1, mode = -1, sleep = -1, test = -1;   // -1 = not given
    const char *bad_value = nullptr;
    bool malformed = false;
    p = skip_ws(p + 1);
    if (*p != '}') {
        for (;;) {
            if (*p != '"') { malformed = true; break; }
            const char *k0 = p + 1;
            const char *k1 = skip_string(p);
            if (!k1) { malformed = true; break; }
            size_t klen = k1 - 1 - k0;
            p = skip_ws(k1);
            if (*p != ':') { malformed = true; break; }
            const char *v0 = skip_ws(p + 1);
            const char *v1 = skip_value(v0);
            if (!v1) { malformed = true; break; }
            if (klen == 11 && !strncmp(k0, "test_sounds", 11)) {
                if (is_lit(v0, v1, "true")) test = 1;
                else if (is_lit(v0, v1, "false")) test = 0;
                else bad_value = "bad value for test_sounds";
            } else if (klen == 5 && !strncmp(k0, "armed", 5)) {
                if (is_lit(v0, v1, "true")) armed = 1;
                else if (is_lit(v0, v1, "false")) armed = 0;
                else bad_value = "bad value for armed";
            } else if (klen == 4 && !strncmp(k0, "mode", 4)) {
                if (is_lit(v0, v1, "\"gesture\"")) mode = (int)VoxMode::Gesture;
                else if (is_lit(v0, v1, "\"cursor\"")) mode = (int)VoxMode::Cursor;
                else bad_value = "bad value for mode";
            } else if (klen == 5 && !strncmp(k0, "sleep", 5)) {
                if (is_lit(v0, v1, "true")) sleep = 1;
                else bad_value = "bad value for sleep";      // only true is a command
            } else if (klen == 1 && k0[0] == 'v') {
                if (!is_lit(v0, v1, "1")) out_printf("CONFIG: v=%.*s, expected 1 (applied anyway)", (int)(v1 - v0), v0);
            } else {
                out_printf("CONFIG: ignoring unknown key '%.*s'", (int)klen, k0);
            }
            p = skip_ws(v1);
            if (*p == ',') {
                p = skip_ws(p + 1);
                continue;
            }
            if (*p != '}') malformed = true;
            break;
        }
    }
    if (malformed) {
        out_line("CONFIG: malformed JSON");
        config_reject("malformed JSON");
        return;
    }
    if (bad_value) {
        config_reject(bad_value);
        return;
    }
    if (test >= 0) state_set_test_sounds(test == 1, "CONFIG");
    if (sleep == 1) {
        if (armed >= 0 || mode >= 0) out_line("CONFIG: sleep goes alone; armed/mode in the same write are ignored");
        power_sleep("CONFIG sleep");      // its reply is the "sleeping":true message
        return;
    }
    if (armed >= 0) {
        g_state.armed = armed == 1;
        g_state.stopped = false;
        if (!g_state.armed) {
            player_cancel();
            power_disarmed();
        }
    }
    if (mode >= 0) g_state.mode = (VoxMode)mode;
    out_printf("state: %s, %s mode (CONFIG)", g_state.armed ? "armed" : "paused", mode_name(g_state.mode));
    state_send_current("CONFIG");
}

static const char *reset_reason() {
    switch (rp2040.getResetReason()) {
    case RP2040::PWRON_RESET: return "power-on";
    case RP2040::RUN_PIN_RESET: return "RUN pin";
    case RP2040::SOFT_RESET: return "software (reboot / flash)";
    case RP2040::WDT_RESET: return "WATCHDOG: the firmware hung and restarted itself";
    case RP2040::DEBUG_RESET: return "debug port";
    case RP2040::GLITCH_RESET: return "power glitch";
    case RP2040::BROWNOUT_RESET: return "brownout";
    default: return "unknown";
    }
}

void setup() {
    Serial.begin(115200);
    led_begin();
    controls_begin();
    ext_begin();          // the extractor's core-0 side (core 1 runs setup1/loop1 in ext.cpp)
    mic_begin();          // ~0.3 s: presence check for INFO
    update_info();
    ble_begin();
    rp2040.wdt_begin(WATCHDOG_MS);   // a hang restarts the device instead of leaving it dead until a power cycle
    uint32_t t0 = millis();
    while (!Serial && millis() - t0 < 1500) delay(10);   // give a terminal a moment, never block without one
    out_printf("VOX node %s (%s build%s) - `help` for commands", VOX_FW_VERSION,
               VOX_INSECURE ? "INSECURE debug" : "secure", VOX_SLEEP_STAYS_AWAKE ? ", power-bank: sleep only disarms" : "");
    out_printf("reset reason: %s", reset_reason());
    if (g_state.test_sounds) out_line("test-sound trigger ON: 2 presses of the button send the next canned sound");
}

void loop() {
    rp2040.wdt_reset();
    uint32_t now = millis();
    controls_poll(now);
    console_poll();
    if (!power_asleep()) {
        player_poll(now);
        mic_poll(now);
    }
    ext_poll(now);        // finished sounds from core 1 -> BLE
    ble_poll();
    power_poll(now);
    led_update(now);
    if (power_asleep()) delay(SLEEP_POLL_MS);   // WFE until the next button sample (USB interrupts still run)
}
