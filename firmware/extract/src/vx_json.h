// JSON text for events: the host CLI's event lines (the same fields as the Python Event.to_dict(), raw included)
// and the per-sound `features` entry of a PROTOCOL.md message. Numbers are printed the way Python prints the
// reference's rounded values: round(x, n) then the shortest form, so 1.2 not 1.2000, and -3.0 keeps its ".0".
#pragma once
#include <stddef.h>
#include "vx_classify.h"
#include "vx_hold.h"

struct VxJson {
    char *buf;
    size_t cap, n;     // n may exceed cap (the output is then truncated; check n < cap)
};

void vx_json_init(VxJson *j, char *buf, size_t cap);
void vx_json_raw(VxJson *j, const char *s);
void vx_json_num(VxJson *j, double v, int decimals);   // Python repr of round(v, decimals)
void vx_json_int(VxJson *j, long v);
void vx_json_str(VxJson *j, const char *s);             // quoted; escapes " and backslash

// {"t_start_ms": ..., "label": ..., "text": ..., "raw": {...}} (one line). t_offset_ms is added to both times.
void vx_json_event(VxJson *j, const VxEvent *ev, bool with_raw);
// {"fp":[24],"fp_version":"fp1","pitch16":[16 or 0]}
void vx_json_features(VxJson *j, const VxEvent *ev);
// A hold message as Hold.to_dict(): {"hold": "start", "sound": 3, "t_start_ms": ..., "t_ms": ..., "f0_hz": ..., "flat": ...};
// a glide-and-hold start adds "from": "glide", "dir": "up" | "down". pitch: hold, sound, t_ms, f0_hz; end: hold, sound,
// t_start_ms, t_ms. Stream times (the glue adds the device clock).
void vx_json_hold(VxJson *j, const VxHold *h);
