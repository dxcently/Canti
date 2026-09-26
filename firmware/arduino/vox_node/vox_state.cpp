#include "vox_state.h"
#include "ble_link.h"
#include "config.h"
#include "out.h"

VoxState g_state = {VOX_BOOT_ARMED != 0, false, VoxMode::Gesture, VOX_TEST_SOUNDS_DEFAULT != 0};

static uint32_t s_next_id = 1;
static uint32_t s_last_id = 0;
static uint32_t s_last_sound_ms = 0;
static char s_msg[BLE_MSG_MAX + 1];

const char *mode_name(VoxMode m) { return m == VoxMode::Cursor ? "cursor" : "gesture"; }
uint32_t last_msg_id() { return s_last_id; }
uint32_t last_sound_ms() { return s_last_sound_ms; }

static const char *state_word() { return g_state.armed ? "armed" : (g_state.stopped ? "stopped" : "paused"); }

// Queue one message; id is consumed only if it was queued, so ids on the air increase by 1.
static uint32_t transmit(size_t len, const char *what) {
    uint32_t id = s_next_id;
    if (!ble_ready()) {
        out_printf("tx %s: not sent (no phone subscribed)", what);
        return 0;
    }
    if (!ble_send(s_msg, len)) {
        out_printf("tx %s: DROPPED (queue full)", what);
        return 0;
    }
    s_last_id = id;
    s_next_id++;
    out_printf("tx id=%lu %s (%u bytes) at %lu ms", (unsigned long)id, what, (unsigned)len, (unsigned long)millis());
    return id;
}

// PROTOCOL.md field order: v, id, mode, armed, sleeping (only when true), rejected (only on a refused CONFIG
// command), sounds, sequence. `rejected` is one of our fixed reason strings: no JSON escaping needed.
static size_t state_json(uint32_t id, bool sleeping = false, const char *rejected = nullptr) {
    char rej[96] = "";
    if (rejected) snprintf(rej, sizeof(rej), "\"rejected\":\"%s\",", rejected);
    return snprintf(s_msg, sizeof(s_msg),
                    "{\"v\":1,\"id\":%lu,\"mode\":\"%s\",\"armed\":%s,%s%s\"sounds\":[],\"sequence\":[]}",
                    (unsigned long)id, mode_name(g_state.mode), g_state.armed ? "true" : "false",
                    sleeping ? "\"sleeping\":true," : "", rej);
}

uint32_t state_send_current(const char *why) {
    size_t n = state_json(s_next_id);
    char what[96];
    snprintf(what, sizeof(what), "state %s %s (%s)", state_word(), mode_name(g_state.mode), why);
    return transmit(n, what);
}

uint32_t state_send_sleeping(const char *why) {
    g_state.armed = false;
    size_t n = state_json(s_next_id, true);
    char what[96];
    snprintf(what, sizeof(what), "state SLEEPING, disarmed, %s (%s)", mode_name(g_state.mode), why);
    return transmit(n, what);
}

uint32_t state_send_rejected(const char *reason) {
    size_t n = state_json(s_next_id, false, reason);
    char what[128];
    snprintf(what, sizeof(what), "state %s %s, REJECTED \"%s\" (CONFIG)", state_word(), mode_name(g_state.mode), reason);
    return transmit(n, what);
}

static void changed(const char *why) {
    out_printf("state: %s, %s mode (%s)", state_word(), mode_name(g_state.mode), why);
    state_send_current(why);
}

void state_arm(const char *why) {
    g_state.armed = true;
    g_state.stopped = false;
    changed(why);
}

void state_pause(const char *why) {
    g_state.armed = false;
    g_state.stopped = false;
    changed(why);
}

void state_stop(const char *why) {
    g_state.armed = false;
    g_state.stopped = true;
    changed(why);
}

void state_toggle_armed(const char *why) {
    if (g_state.armed) state_pause(why);
    else state_arm(why);
}

void state_set_mode(VoxMode m, const char *why) {
    g_state.mode = m;
    changed(why);
}

void state_toggle_mode(const char *why) {
    state_set_mode(g_state.mode == VoxMode::Gesture ? VoxMode::Cursor : VoxMode::Gesture, why);
}

void state_set_test_sounds(bool on, const char *why) {
    g_state.test_sounds = on;
    out_printf("test-sound button trigger %s (%s): %s", on ? "ON" : "off", why,
               on ? "2 presses of the button send the next canned sound" : "2 presses do nothing");
}

uint32_t send_sound(const char *label, const char *line, uint32_t t_start_ms, uint32_t t_end_ms) {
    if (!g_state.armed) {
        out_printf("tx %s: not sent (device is %s; `arm` or 5 presses first)", label, state_word());
        return 0;
    }
    // The lines are plain ASCII without quotes or backslashes (checked by gen_test_sounds.py), so no escaping.
    size_t n = snprintf(s_msg, sizeof(s_msg),
                        "{\"v\":1,\"id\":%lu,\"mode\":\"%s\",\"armed\":true,\"sounds\":[\"%s\"],\"sequence\":[\"%s\"],"
                        "\"timing\":[{\"t_start_ms\":%lu,\"t_end_ms\":%lu}],\"phrase\":null,\"cursor\":null}",
                        (unsigned long)s_next_id, mode_name(g_state.mode), line, label, (unsigned long)t_start_ms,
                        (unsigned long)t_end_ms);
    if (n >= sizeof(s_msg)) {
        out_printf("tx %s: message too long", label);
        return 0;
    }
    char what[64];
    snprintf(what, sizeof(what), "sound %s [%lu..%lu]", label, (unsigned long)t_start_ms, (unsigned long)t_end_ms);
    uint32_t id = transmit(n, what);
    if (id) s_last_sound_ms = millis();
    return id;
}

uint32_t send_padded_state(size_t total_len) {
    size_t n = state_json(s_next_id);
    if (total_len > BLE_MSG_MAX) total_len = BLE_MSG_MAX;
    if (total_len > n) {
        // insert spaces before the closing brace: still one valid JSON object with the same fields
        size_t pad = total_len - n;
        memset(s_msg + n - 1, ' ', pad);
        s_msg[total_len - 1] = '}';
        s_msg[total_len] = 0;
        n = total_len;
    }
    char what[64];
    snprintf(what, sizeof(what), "padded state %s", state_word());
    return transmit(n, what);
}
