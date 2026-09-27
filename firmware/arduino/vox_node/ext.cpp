#include "ext.h"
#include <vox_extract.h>
#include "out.h"
#include "power.h"
#include "vox_state.h"

void info_changed();   // vox_node.ino: refresh INFO (fp_version)

// core 1 gets its own 8 KB stack (arduino-pico), so the extractor's calls cannot run into core 0's stack
bool core1_separate_stack = true;

// ---- sample ring: core 0 produces, core 1 consumes. Indices only grow; a power-of-two size wraps them ----
static const uint32_t RING = 8192;    // 512 ms at 16 kHz (the extractor's worst hop is far below that)
static int16_t s_ring[RING];
static uint32_t s_head;               // written by core 0 only
static uint32_t s_tail;               // written by core 1 only

// ---- control: core 0 asks, core 1 acknowledges ----
static uint32_t s_req_gen, s_ack_gen;     // a new stream: core 1 re-initialises and empties the ring
static int s_req_rate = 16000;
static uint32_t s_flush_req, s_flush_ack; // end of a fed stream: core 1 flushes once the ring is empty

// ---- finished sounds and hold messages (vx_hold.h), in emission order: core 1 produces, core 0 consumes ----
struct ExtOut {
    uint32_t gen;
    bool is_hold;                          // a hold message (only `hold` below is valid), else a finished sound
    VxHold hold;                           // stream times; sound already numbered per boot
    int32_t sound;                         // the sound's id per boot (1, 2, ...), shared with its hold messages
    bool held;
    int32_t t_start_ms, t_end_ms;          // stream time
    uint8_t label;
    uint32_t seg_cycles;
    char text[VX_LINE_MAX];
    char feat[512];                        // {"fp":[...],"fp_version":"fp1","pitch16":[...]}
    char json[1024];                       // the event without raw (feed mode prints it)
};
static const uint32_t QN = 4;
static ExtOut s_q[QN];
static uint32_t s_qh;                     // written by core 1
static uint32_t s_qt;                     // written by core 0

// ---- core 1 state ----
static VxExtractor s_ex;
static uint32_t s_gen1;
static int32_t s_sound_base;              // sounds of the earlier streams since boot: ids go on across wakes
static bool s_init_ok;
static vx_real s_x[160];

// ---- stats (each counter written by one core; read unsynchronised for display) ----
struct ExtCounters {
    uint32_t mic_samples, overflow, dropped_reset, ring_high, queue_drops;   // core 0 (ring_high: fill level)
    uint64_t busy_cycles;                                                     // core 1: inside the extractor
    uint32_t busy_t0_us;                                                      // core 1: when counting started
    uint32_t busy_max_chunk;                                                  // core 1: one 160-sample push
};
static ExtCounters s_c;
static uint32_t s_q_drops1;               // core 1

// ---- core 0 state ----
static bool s_enabled = true;
static bool s_features = true;
static bool s_stream_on = false;          // between ext_stream_start and ext_stream_stop
static bool s_have_base = false;
static uint32_t s_base_ms;
static uint32_t s_events_sent;
// feed
static bool s_feeding = false;
static uint32_t s_feed_left;              // samples still to come
static int s_feed_rate;
static bool s_feed_half;                  // a low byte is waiting for its high byte
static uint8_t s_feed_lo;
static bool s_feed_flush_sent;
static uint32_t s_feed_events;
static uint32_t s_feed_t0;

template <typename T> static inline T ld(const T *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
template <typename T> static inline void st(T *p, T v) { __atomic_store_n(p, v, __ATOMIC_RELEASE); }

static uint32_t cycles() { return rp2040.getCycleCount(); }

// ================================================================= core 1

static void on_event(const VxEvent *ev, void *) {
    uint32_t h = s_qh;
    if (h - ld(&s_qt) >= QN) {
        s_q_drops1++;
        return;
    }
    ExtOut *o = &s_q[h % QN];
    o->gen = s_gen1;
    o->is_hold = false;
    o->sound = ev->sound ? s_sound_base + ev->sound : 0;
    o->held = ev->held;
    o->t_start_ms = ev->t_start_ms;
    o->t_end_ms = ev->t_end_ms;
    o->label = (uint8_t)ev->label;
    o->seg_cycles = s_ex.stats.seg_last;
    memcpy(o->text, ev->text, sizeof(o->text));   // same size, NUL-terminated by vx_classify
    VxJson j;
    vx_json_init(&j, o->feat, sizeof(o->feat));
    vx_json_features(&j, ev);   // every event carries fp1 (Extractor._emit)
    if (j.n >= sizeof(o->feat)) o->feat[0] = 0;
    vx_json_init(&j, o->json, sizeof(o->json));
    vx_json_event(&j, ev, false);
    if (j.n >= sizeof(o->json)) o->json[0] = 0;
    st(&s_qh, h + 1);
}

static void on_hold(const VxHold *hm, void *) {
    uint32_t h = s_qh;
    if (h - ld(&s_qt) >= QN) {
        s_q_drops1++;
        return;
    }
    ExtOut *o = &s_q[h % QN];
    o->gen = s_gen1;
    o->is_hold = true;
    o->hold = *hm;
    o->hold.sound += s_sound_base;
    st(&s_qh, h + 1);
}

void setup1() {
    s_init_ok = vx_extractor_init(&s_ex, NULL, 16000) == NULL;
    s_ex.cycles = cycles;
    s_ex.on_hold = on_hold;
}

void loop1() {
    uint32_t req = ld(&s_req_gen);
    if (req != s_gen1) {
        s_sound_base += s_ex.hold.sound;   // before the re-init clears it (a sound cut off by the reset keeps its id)
        s_init_ok = vx_extractor_init(&s_ex, NULL, s_req_rate) == NULL;
        s_ex.cycles = cycles;
        s_ex.on_hold = on_hold;
        st(&s_tail, ld(&s_head));             // drop what the old stream left
        s_gen1 = req;
        s_c.busy_cycles = 0;
        s_c.busy_max_chunk = 0;
        s_c.busy_t0_us = time_us_32();
        st(&s_ack_gen, req);
    }
    uint32_t flush = ld(&s_flush_req);        // before the head: a flush request is seen after its last samples
    uint32_t t = s_tail, h = ld(&s_head);
    if (h == t) {
        if (flush != s_flush_ack) {
            if (s_init_ok) vx_extractor_flush(&s_ex, on_event, NULL);
            st(&s_flush_ack, flush);
        }
        __wfe();                              // core 0 sends an event (__sev) after each push
        return;
    }
    uint32_t n = h - t;
    if (n > 160) n = 160;
    for (uint32_t i = 0; i < n; i++) s_x[i] = (vx_real)s_ring[(t + i) & (RING - 1)] * VXF(1.0 / 32768.0);
    st(&s_tail, t + n);
    if (!s_init_ok) return;
    uint32_t c0 = cycles();
    vx_extractor_push(&s_ex, s_x, (int)n, on_event, NULL);
    uint32_t d = cycles() - c0;
    s_c.busy_cycles += d;
    if (d > s_c.busy_max_chunk) s_c.busy_max_chunk = d;
}

// ================================================================= core 0

static void request_stream(int rate) {
    s_req_rate = rate;
    st(&s_req_gen, s_req_gen + 1);
    s_have_base = false;
    __sev();
}

static bool ring_ready() { return ld(&s_ack_gen) == s_req_gen; }

// Copies up to n samples into the ring; returns how many fitted.
static uint32_t ring_push(const int16_t *s, uint32_t n) {
    uint32_t h = s_head;
    uint32_t used = h - ld(&s_tail);
    uint32_t room = RING - used;
    if (n > room) n = room;
    for (uint32_t i = 0; i < n; i++) s_ring[(h + i) & (RING - 1)] = s[i];
    st(&s_head, h + n);
    if (used + n > s_c.ring_high) s_c.ring_high = used + n;
    __sev();
    return n;
}

void ext_begin() {
    s_c.busy_t0_us = time_us_32();
    info_changed();
}

void ext_stream_start() {
    s_stream_on = true;
    if (!s_feeding) request_stream(16000);
}

void ext_stream_stop() {
    s_stream_on = false;
    if (s_feeding) {
        s_feeding = false;
        out_line("ext feed: aborted (sleep)");
    }
    request_stream(16000);   // core 1 drops what is left; pending sounds of the old stream are discarded
}

void ext_mic_push(const int16_t *s, int n) {
    if (!s_enabled || s_feeding || !s_stream_on) return;
    s_c.mic_samples += n;
    if (!ring_ready()) {
        s_c.dropped_reset += n;
        return;
    }
    if (!s_have_base) {   // the stream's t = 0 on the device clock (the I2S buffering, up to ~8 ms, is ignored)
        s_have_base = true;
        s_base_ms = millis();
    }
    uint32_t got = ring_push(s, (uint32_t)n);
    if (got < (uint32_t)n) s_c.overflow += n - got;
}

void ext_set_enabled(bool on) {
    if (on == s_enabled) return;
    s_enabled = on;
    if (on) request_stream(16000);
    info_changed();
}

bool ext_enabled() { return s_enabled; }

void ext_set_features(bool on) {
    s_features = on;
    info_changed();
}

bool ext_features() { return s_features; }
const char *ext_fp_version() { return s_enabled && s_features ? VX_FP_VERSION : NULL; }

static void deliver_hold(const VxHold *hm) {
    if (s_feeding) {   // stream times, as vx_cli --holds prints them
        static char js[160], line[180];
        VxJson j;
        vx_json_init(&j, js, sizeof(js));
        vx_json_hold(&j, hm);
        snprintf(line, sizeof(line), "ext hold %s", js);
        out_line(line);
        return;
    }
    uint32_t t0 = s_base_ms + (uint32_t)(hm->t_start_ms < 0 ? 0 : hm->t_start_ms);
    uint32_t t = s_base_ms + (uint32_t)(hm->t_ms < 0 ? 0 : hm->t_ms);
    if (hm->kind != VX_HOLD_PITCH)
        out_printf("ext: hold %s #%ld [%lu..%lu]", VX_HOLD_KINDS[hm->kind], (long)hm->sound, (unsigned long)t0,
                   (unsigned long)t);
    send_hold(VX_HOLD_KINDS[hm->kind], hm->sound, t0, t, hm->f0_hz, hm->flat, hm->dir);
}

static void deliver(const ExtOut *o) {
    if (o->is_hold) {
        deliver_hold(&o->hold);
        return;
    }
    if (s_feeding) {
        s_feed_events++;
        static char line[sizeof(o->json) + 16];   // out_printf stops at 256 characters
        snprintf(line, sizeof(line), "ext event %s", o->json[0] ? o->json : "{\"error\":\"event JSON too long\"}");
        out_line(line);
        if (o->feat[0]) {
            snprintf(line, sizeof(line), "ext features %s", o->feat);
            out_line(line);
        }
        return;
    }
    uint32_t t0 = s_base_ms + (uint32_t)(o->t_start_ms < 0 ? 0 : o->t_start_ms);
    uint32_t t1 = s_base_ms + (uint32_t)(o->t_end_ms < 0 ? 0 : o->t_end_ms);
    static char line[VX_LINE_MAX + 96];
    snprintf(line, sizeof(line), "ext: %s [%lu..%lu] %s (%lu us)", VX_LABELS[o->label], (unsigned long)t0,
             (unsigned long)t1, o->text, (unsigned long)(o->seg_cycles / (F_CPU / 1000000)));
    out_line(line);
    if (send_sound(VX_LABELS[o->label], o->text, t0, t1, s_features && o->feat[0] ? o->feat : NULL, o->sound, o->held)) s_events_sent++;
}

void ext_poll(uint32_t now) {
    (void)now;
    uint32_t t = s_qt;
    uint32_t h = ld(&s_qh);
    while (t != h) {
        const ExtOut *o = &s_q[t % QN];
        if (o->gen == s_req_gen) deliver(o);
        st(&s_qt, ++t);
    }
    if (s_feeding && s_feed_flush_sent && ld(&s_flush_ack) == s_flush_req && ld(&s_qh) == s_qt) {
        s_feeding = false;
        out_printf("ext feed: done, %lu event(s) in %lu ms", (unsigned long)s_feed_events,
                   (unsigned long)(millis() - s_feed_t0));
        ext_stats(false);
        if (s_stream_on) request_stream(16000);   // back to the mic
    }
}

// ---- feed mode ----
bool ext_feed_begin(uint32_t n_samples, int rate) {
    if (rate != 16000 && rate != 48000) return false;
    s_feeding = true;
    s_feed_left = n_samples;
    s_feed_rate = rate;
    s_feed_half = false;
    s_feed_flush_sent = false;
    s_feed_events = 0;
    s_feed_t0 = millis();
    request_stream(rate);
    out_printf("ext feed: send %lu int16 LE samples at %d Hz now", (unsigned long)n_samples, rate);
    if (n_samples == 0) {
        s_flush_req++;
        __sev();
        s_feed_flush_sent = true;
    }
    return true;
}

bool ext_feeding() { return s_feeding && !s_feed_flush_sent; }

size_t ext_feed_room() {
    if (!s_feeding || s_feed_flush_sent || !ring_ready()) return 0;
    uint32_t room = RING - (s_head - ld(&s_tail));                 // samples
    uint32_t want = 2 * s_feed_left - (s_feed_half ? 1 : 0);        // bytes still to come
    uint32_t b = 2 * room - (s_feed_half ? 1 : 0);
    return b < want ? b : want;
}

void ext_feed_bytes(const uint8_t *p, size_t n) {
    int16_t buf[64];
    size_t used = 0;
    while (used < n && s_feed_left > 0) {
        int k = 0;
        while (used < n && k < 64 && s_feed_left > 0) {
            if (!s_feed_half) {
                s_feed_lo = p[used++];
                s_feed_half = true;
            } else {
                buf[k++] = (int16_t)(s_feed_lo | (p[used++] << 8));
                s_feed_half = false;
                s_feed_left--;
            }
        }
        if (k && ring_push(buf, (uint32_t)k) < (uint32_t)k) s_c.overflow++;   // not with n <= ext_feed_room()
    }
    if (s_feed_left == 0 && !s_feed_flush_sent) {
        st(&s_flush_req, s_flush_req + 1);
        __sev();
        s_feed_flush_sent = true;
    }
}

// ---- stats ----
void ext_stats(bool reset) {
    const VxStats &x = s_ex.stats;
    const double mhz = F_CPU / 1e6;
    const double hop_budget = F_CPU / 100.0;   // one 10 ms hop of one core
    double mean = x.hops ? (double)x.hop_sum / x.hops : 0;
    uint32_t el_us = time_us_32() - s_c.busy_t0_us;
    double load = el_us ? (double)s_c.busy_cycles / (el_us * mhz) * 100.0 : 0;
    out_printf("ext: %s, features %s, core 1, input %d Hz; %lu hops, %lu sounds (%lu kept, %lu dropped), %lu sent",
               s_enabled ? "on" : "off", s_features ? "on (fp1)" : "off", s_feeding ? s_feed_rate : 16000,
               (unsigned long)x.hops, (unsigned long)x.segments, (unsigned long)x.events, (unsigned long)x.dropped,
               (unsigned long)s_events_sent);
    out_printf("ext: hop mean %.0f cycles (%.1f us, %.2f%% of a core), max %lu (%.1f us, %.2f%%)", mean, mean / mhz,
               mean / hop_budget * 100, (unsigned long)x.hop_max, x.hop_max / mhz, x.hop_max / hop_budget * 100);
    out_printf("ext: sound end (classify + fp1) max %lu cycles (%.1f us), last %lu; one 160-sample push max %lu "
               "cycles (%.1f us)", (unsigned long)x.seg_max, x.seg_max / mhz, (unsigned long)x.seg_last,
               (unsigned long)s_c.busy_max_chunk, s_c.busy_max_chunk / mhz);
    out_printf("ext: core-1 load %.2f%% over %lu ms; ring high %lu/%lu, overflow %lu, dropped at reset %lu, "
               "event queue drops %lu, mic samples %lu", load, (unsigned long)(el_us / 1000),
               (unsigned long)s_c.ring_high, (unsigned long)RING, (unsigned long)s_c.overflow,
               (unsigned long)s_c.dropped_reset, (unsigned long)s_q_drops1, (unsigned long)s_c.mic_samples);
    if (reset) {
        // core 1 owns VxStats; a new stream (same state as a wake) is the race-free way to clear them
        s_c.ring_high = s_c.overflow = s_c.dropped_reset = s_c.mic_samples = 0;
        if (s_stream_on && !s_feeding) request_stream(16000);
        out_line("ext: stats cleared (the extractor restarted from a clean state)");
    }
}

void ext_status() {
    out_printf("ext: %s, features %s, %lu hops, %lu sounds, %lu sent, hop max %lu cycles, ring overflow %lu",
               s_enabled ? (power_asleep() ? "on (asleep)" : "on") : "off", s_features ? "fp1" : "off",
               (unsigned long)s_ex.stats.hops, (unsigned long)s_ex.stats.events, (unsigned long)s_events_sent,
               (unsigned long)s_ex.stats.hop_max, (unsigned long)s_c.overflow);
}
