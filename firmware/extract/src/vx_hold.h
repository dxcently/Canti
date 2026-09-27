// Hold messages, as extractor/vox_extract/hold.py: a live report while a steady tone is still going
// (hold-to-scroll, android/PROTOCOL.md "Hold messages" and "Hold pitch").
//   hold start  once per sound, while it is open, when its last hold_start_ms look like one steady voiced tone
//               (glide-and-hold first: its last hold_glide_ms steady and at least hold_glide_min_st from the sound's
//               start pitch -> dir = +1 up / -1 down, flat = false; only for a sound after hold_glide_quiet_ms of
//               quiet, and only once that test has passed on every frame for hold_glide_delay_ms more)
//   hold pitch  after that, every hold_pitch_ms of the sound: the median f0 of the voiced frames since the last one
//   hold end    when the sound closes, before its event (the event then has held = true)
// Every sound gets an id (1, 2, ... per stream; VxExtractor resets it) that its hold messages and event share.
// Reads only the sound's own per-frame arrays (e_db, f0, clarity); no allocation, static scratch (one tracker at a
// time, like vx_classify).
#pragma once
#include "vx_config.h"
#include "vx_segmenter.h"

enum VxHoldKind { VX_HOLD_START, VX_HOLD_PITCH, VX_HOLD_END };
extern const char *const VX_HOLD_KINDS[3];   // "start", "pitch", "end"

struct VxHold {
    int kind;            // VxHoldKind
    int sound;           // the sound's id (its event carries the same)
    int t_start_ms;      // the sound's start (stream time, as its event's t_start_ms)
    int t_ms;            // start / pitch: how far the sound had got; end: the sound's end (its t_end_ms)
    double f0_hz;        // start and pitch: median f0 of the window, rounded to 0.1
    bool flat;           // start only
    int dir;             // start only: 0 = a steady hum, +1 / -1 = glide-and-hold up / down ("from":"glide")
};

struct VxHoldTracker {
    const VxConfig *cfg;
    int w;               // frames in the hold window (0 = hold messages off)
    int wg;              // frames in the glide-and-hold window (0 = glide-and-hold off)
    int dg;              // frames the glide test must keep passing before its hold start (late start; 0 = at once)
    int pk;              // frames between hold pitch reports (0 = none)
    int next_pitch;      // seg n at which the next hold pitch is due
    int sound;           // id of the current (or last) sound
    bool cur;            // a sound is open and numbered
    bool held;           // hold start was sent for the current sound
    bool glide_ok;       // the current sound came after hold_glide_quiet_ms of quiet
    int glide_run;       // frames in a row the glide test has passed
    bool has_last;       // a sound has ended in this stream
    int last_end_ms;     // ... at this time (as its hold end / event t_end_ms)
};

void vx_hold_init(VxHoldTracker *h, const VxConfig *cfg);   // also a new stream: numbering restarts at 1
// After every frame: seg = the open sound or NULL, active = this frame was added to it (not hangover).
// Returns true with *out filled when a hold start or hold pitch is due.
bool vx_hold_frame(VxHoldTracker *h, const VxSegStats *seg, bool active, VxHold *out);
// The sound ended (call before its event, whatever its length). Fills *sound / *held for the event; returns true
// with *out = its hold end if a hold start was sent.
bool vx_hold_closed(VxHoldTracker *h, const VxSegStats *seg, VxHold *out, int *sound, bool *held);
