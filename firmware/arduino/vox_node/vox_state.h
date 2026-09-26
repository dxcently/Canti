// Device state (armed / paused / stopped, gesture / cursor mode) and the PROTOCOL.md feature messages.
// Every state change is sent at once as a message with no sounds:
//   {"v":1,"id":7,"mode":"gesture","armed":false,"sounds":[],"sequence":[]}
// The last message before sleep says so:
//   {"v":1,"id":8,"mode":"gesture","armed":false,"sleeping":true,"sounds":[],"sequence":[]}
// A sound goes out in its own message, with device-clock timing (ms since boot), in the extractor's key order:
//   {"v":1,"id":9,"mode":"gesture","armed":true,"sounds":[line],"sequence":[label],
//    "timing":[{"t_start_ms":a,"t_end_ms":b}],"phrase":null,"cursor":null}
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
void state_set_mode(VoxMode m, const char *why);
void state_toggle_mode(const char *why);
uint32_t state_send_current(const char *why);   // (re-)send the current state; message id or 0
uint32_t state_send_sleeping(const char *why);  // disarm and send the "sleeping":true message; id or 0
uint32_t state_send_rejected(const char *reason); // reply to a refused CONFIG command: the state + "rejected"
void state_set_test_sounds(bool on, const char *why);

// Sound messages. Returns the message id, or 0 if not sent (reason printed).
uint32_t send_sound(const char *label, const char *line, uint32_t t_start_ms, uint32_t t_end_ms);
// A protocol-valid no-sound state message, padded with JSON whitespace to `total_len` bytes (fragmentation test).
uint32_t send_padded_state(size_t total_len);

uint32_t last_msg_id();
uint32_t last_sound_ms();   // millis() of the last sound actually queued (0 = none yet)
const char *mode_name(VoxMode m);
