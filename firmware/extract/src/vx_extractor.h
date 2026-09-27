// The streaming extractor, as extractor/vox_extract/extractor.py: samples in (16 kHz, or 48 kHz through
// Decimator3), one VxEvent out per sound when it ends (after the hangover). Fixed memory: everything lives in
// the VxExtractor struct (about 30 KB) plus the static FFT and classify scratch; nothing is allocated.
//
//   static VxExtractor ex;
//   vx_extractor_init(&ex, NULL, 16000);             // NULL = default Config
//   vx_extractor_push(&ex, samples, n, on_event, user);   // any chunk size; floats in [-1, 1)
//   vx_extractor_flush(&ex, on_event, user);             // end of stream
//   ex.on_hold = on_hold;                                 // optional: hold messages, in order with the events
#pragma once
#include "vx_classify.h"
#include "vx_config.h"
#include "vx_decim.h"
#include "vx_fingerprint.h"
#include "vx_frontend.h"
#include "vx_hold.h"
#include "vx_segmenter.h"
#include "vx_tick.h"

typedef void (*VxEventFn)(const VxEvent *ev, void *user);
typedef void (*VxFrameFn)(const VxFrame *f, double floor_after, void *user);
typedef void (*VxHoldFn)(const VxHold *h, void *user);   // hold start / pitch / end (vx_hold.h)
typedef uint32_t (*VxCyclesFn)();   // a free-running cycle (or ns) counter, for the stats; may be NULL
typedef void (*VxTickFn)(const VxTickOut *t, void *user);   // a joystick tick (vx_tick.h)

struct VxStats {
    uint32_t hops;                  // frames computed
    uint32_t segments, events, dropped;
    uint32_t hop_max, hop_last;     // counter ticks for one hop (front end + segmenter)
    uint64_t hop_sum;
    uint32_t seg_max, seg_last;     // ticks at a sound's end (classify + fingerprint)
    uint32_t hold_max;              // ticks for the hold test after a hop (vx_hold_frame; only while a sound is open)
    uint64_t hold_sum;
};

struct VxExtractor {
    VxConfig cfg;
    int input_rate;
    bool keep_dropped;
    VxDecim3 decim;
    VxFrontend fe;
    VxSegmenter seg;
    VxFrame frame;
    VxEvent event;
    bool has_last;
    double last_end_ms;
    bool last_talky;
    VxFrameFn on_frame;             // optional per-frame tap (host vectors)
    void *frame_user;
    VxHoldTracker hold;             // numbers the sounds; hold messages go to on_hold (NULL: none, events still numbered)
    VxHoldFn on_hold;
    void *hold_user;
    VxCyclesFn cycles;
    VxStats stats;
    VxTick *tick;                   // optional joystick ticks on the same 16 kHz samples (NULL: none; caller-owned)
    VxTickFn on_tick;
    void *tick_user;
};

// cfg NULL = defaults. Returns NULL, or why the config does not fit (vx_config_check).
const char *vx_extractor_init(VxExtractor *ex, const VxConfig *cfg, int input_rate);
void vx_extractor_reset(VxExtractor *ex);   // a new stream: all state and the stats cleared, config kept
void vx_extractor_push(VxExtractor *ex, const vx_real *x, int n, VxEventFn fn, void *user);
void vx_extractor_flush(VxExtractor *ex, VxEventFn fn, void *user);
bool vx_is_contour_label(int label);
