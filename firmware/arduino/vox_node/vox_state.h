// Device state (armed / paused / stopped, gesture / cursor mode) and the PROTOCOL.md feature messages.
// Every state change is sent at once as a message with no sounds:
//   {"v":1,"id":7,"mode":"gesture","armed":false,"sounds":[],"sequence":[]}
// The last message before sleep says so:
//   {"v":1,"id":8,"mode":"gesture","armed":false,"sleeping":true,"sounds":[],"sequence":[]}
// A sound goes out in its own message, with device-clock timing (ms since boot), in the extractor's key order:
//   {"v":1,"id":9,"mode":"gesture","armed":true,"sounds":[line],"sequence":[label],
//    "timing":[{"t_start_ms":a,"t_end_ms":b[,"sound":n[,"held":true]]}],"phrase":null,"cursor":null[,"features":[{fp1 entry}]]}
// Hold messages (PROTOCOL.md "Hold messages", "Hold pitch"), device clock, compact:
//   {"v":1,"id":10,"hold":"start","sound":57,"t_start_ms":a,"t_ms":b,"f0_hz":145.2,"flat":true}
//     (glide-and-hold: ...,"flat":false,"from":"glide","dir":"up"|"down")
//   {"v":1,"id":11,"hold":"pitch","sound":57,"t_ms":b,"f0_hz":151.3}           (every 200 ms of the held sound)
//   {"v":1,"id":12,"hold":"end","sound":57,"t_start_ms":a,"t_ms":b}
#pragma once
#include <Arduino.h>

enum class VoxMode : uint8_t { Gesture, Cursor };

struct VoxState {
    bool armed;
    bool stopped;       // disarmed by the button's fast stop (hold 1 s), as opposed to paused. Only for the log
    VoxMode mode;
    bool test_sounds;   // 2 presses of the button send the next canned sound
};

extern VoxState g_state;

// State changes. `why` is for the serial log. Each one sends a no-sound message (if the link is up).
void state_arm(const char *why);
void state_pause(const char *why);
void state_stop(const char *why);           // always sends, even if already disarmed
void state_toggle_armed(const char *why);
// by: "button" when the user pressed the Pico's button (the state message then carries "by":"button", and the app
// keeps that mode as the user's own choice); nullptr for console, app commands and the rest.
void state_set_mode(VoxMode m, const char *why, const char *by = nullptr);
void state_toggle_mode(const char *why, const char *by = nullptr);
uint32_t state_send_current(const char *why, const char *by = nullptr);   // (re-)send the current state; id or 0
uint32_t state_send_sleeping(const char *why);  // disarm and send the "sleeping":true message; id or 0
uint32_t state_send_rejected(const char *reason); // reply to a refused CONFIG command: the state + "rejected"
void state_set_test_sounds(bool on, const char *why);

// Sound messages. Returns the message id, or 0 if not sent (reason printed). `features`: one PROTOCOL.md features
// entry ({"fp":[...],"fp_version":"fp1","pitch16":[...]}) or NULL for none (the canned test sounds).
// `sound` > 0: the extractor's sound id (shared with its hold messages), `held`: a hold start was sent for it.
uint32_t send_sound(const char *label, const char *line, uint32_t t_start_ms, uint32_t t_end_ms,
                    const char *features = nullptr, int32_t sound = 0, bool held = false);
// A hold message; kind "start" | "pitch" | "end" (f0_hz: start and pitch; flat: start). Only while armed. Returns the
// id or 0. Disarming (pause, stop, sleep) while a hold is open sends its "end" first (PROTOCOL.md: SHOULD).
uint32_t send_hold(const char *kind, int32_t sound, uint32_t t_start_ms, uint32_t t_ms, double f0_hz, bool flat,
                   int dir = 0);   // dir: start only, glide-and-hold +1 up / -1 down ("from":"glide"), 0 = a steady hum
// A protocol-valid no-sound state message, padded with JSON whitespace to `total_len` bytes (fragmentation test).
uint32_t send_padded_state(size_t total_len);

uint32_t last_msg_id();
uint32_t last_sound_ms();   // millis() of the last sound actually queued (0 = none yet)
const char *mode_name(VoxMode m);
