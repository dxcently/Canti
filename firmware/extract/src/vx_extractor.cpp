#include "vx_impl.h"
#include "vx_extractor.h"
#include "vx_vocab.h"
#include <string.h>

bool vx_is_contour_label(int label) { return label >= VX_L_RISE && label <= VX_L_FLAT; }

const char *vx_extractor_init(VxExtractor *ex, const VxConfig *cfg, int input_rate) {
    if (cfg) ex->cfg = *cfg;
    else vx_config_default(&ex->cfg);
    const char *err = vx_config_check(&ex->cfg);
    if (err) return err;
    if (input_rate != 16000 && input_rate != 48000) return "input rate must be 16000 or 48000";
    ex->input_rate = input_rate;
    ex->keep_dropped = false;
    ex->on_frame = NULL;
    ex->frame_user = NULL;
    ex->on_hold = NULL;
    ex->hold_user = NULL;
    ex->cycles = NULL;
    ex->tick = NULL;
    ex->on_tick = NULL;
    ex->tick_user = NULL;
    vx_frontend_init(&ex->fe, &ex->cfg);
    vx_extractor_reset(ex);
    return NULL;
}

void vx_extractor_reset(VxExtractor *ex) {
    vx_decim_reset(&ex->decim);
    vx_frontend_reset(&ex->fe);
    vx_seg_reset(&ex->seg, &ex->cfg);
    vx_hold_init(&ex->hold, &ex->cfg);
    ex->fe.floor_db = (vx_real)ex->seg.floor_db;
    ex->has_last = false;
    ex->last_end_ms = 0;
    ex->last_talky = false;
    memset(&ex->stats, 0, sizeof(ex->stats));
    if (ex->tick) vx_tick_reset(ex->tick);
}

static void emit(VxExtractor *ex, VxEventFn fn, void *user) {
    const VxSegStats *s = &ex->seg.seg;
    const VxConfig *cfg = &ex->cfg;
    // the hold end (if held) goes out before the event, and every sound is numbered, even a dropped one (hold.py)
    VxHold hm;
    int sound;
    bool held;
    if (vx_hold_closed(&ex->hold, s, &hm, &sound, &held) && ex->on_hold) ex->on_hold(&hm, ex->hold_user);
    if (s->n < cfg->min_segment_frames) return;
    uint32_t c0 = ex->cycles ? ex->cycles() : 0;
    VxContext ctx = {ex->has_last, ex->has_last ? s->t_start_ms - ex->last_end_ms : 0.0, ex->last_talky};
    VxEvent *ev = &ex->event;
    vx_classify(s, cfg, &ctx, ev);
    ev->sound = sound;
    ev->held = held;
    vx_fingerprint(s, &ev->raw);
    if (!vx_is_contour_label(ev->label)) ev->raw.n_pitch16 = 0;
    ex->stats.segments++;
    if (ev->emit) {
        ex->has_last = true;
        ex->last_end_ms = ev->t_end_ms;
        const VxRaw *r = &ev->raw;
        double exc = r->has_shape ? r->excursion_st : 0.0;
        ex->last_talky = ev->like == VX_LIKE_TALKING || ev->like == VX_LIKE_LAUGHING ||
                         (r->voiced_frac >= 0.3 && r->dur_ms <= cfg->train_max_ms && ev->label != VX_L_POP &&
                          ev->label != VX_L_CLICK && ev->label != VX_L_HISS && exc < cfg->exc_large_st);
        ex->stats.events++;
    } else {
        ex->stats.dropped++;
    }
    if (ex->cycles) {
        uint32_t d = ex->cycles() - c0;
        ex->stats.seg_last = d;
        if (d > ex->stats.seg_max) ex->stats.seg_max = d;
    }
    if (fn && (ev->emit || ex->keep_dropped)) fn(ev, user);
}

static void push16(VxExtractor *ex, const vx_real *x, int n, VxEventFn fn, void *user) {
    VxTickOut to;
    for (int i = 0; i < n; i++) {
        if (ex->tick && vx_tick_push(ex->tick, x[i], &to) && ex->on_tick) ex->on_tick(&to, ex->tick_user);
        if (!vx_frontend_push(&ex->fe, x[i])) continue;
        uint32_t c0 = ex->cycles ? ex->cycles() : 0;
        vx_frontend_frame(&ex->fe, &ex->frame);
        double floor_before = ex->seg.floor_db;   // what Extractor.floors records (exported as floor_db_after)
        bool done = vx_seg_push(&ex->seg, &ex->frame);
        ex->fe.floor_db = (vx_real)ex->seg.floor_db;   // the flux floor of the next frame follows the noise floor
        ex->stats.hops++;
        if (ex->cycles) {
            uint32_t d = ex->cycles() - c0;
            ex->stats.hop_last = d;
            ex->stats.hop_sum += d;
            if (d > ex->stats.hop_max) ex->stats.hop_max = d;
        }
        if (ex->on_frame) ex->on_frame(&ex->frame, floor_before, ex->frame_user);
        if (done) emit(ex, fn, user);
        VxHold hm;
        bool open = ex->seg.open;
        uint32_t h0 = ex->cycles ? ex->cycles() : 0;
        bool due = vx_hold_frame(&ex->hold, open ? &ex->seg.seg : NULL, open && ex->seg.n_pending == 0, &hm);
        if (ex->cycles) {
            uint32_t d = ex->cycles() - h0;
            ex->stats.hold_sum += d;
            if (d > ex->stats.hold_max) ex->stats.hold_max = d;
        }
        if (due && ex->on_hold) ex->on_hold(&hm, ex->hold_user);
    }
}

void vx_extractor_push(VxExtractor *ex, const vx_real *x, int n, VxEventFn fn, void *user) {
    if (ex->input_rate == 16000) {
        push16(ex, x, n, fn, user);
        return;
    }
    vx_real out[VX_MAX_HOP / 2 + 2];
    while (n > 0) {
        int k = n > 3 * (VX_MAX_HOP / 2) ? 3 * (VX_MAX_HOP / 2) : n;
        int m = vx_decim_push(&ex->decim, x, k, out);
        push16(ex, out, m, fn, user);
        x += k;
        n -= k;
    }
}

void vx_extractor_flush(VxExtractor *ex, VxEventFn fn, void *user) {
    if (vx_seg_flush(&ex->seg)) emit(ex, fn, user);
}
