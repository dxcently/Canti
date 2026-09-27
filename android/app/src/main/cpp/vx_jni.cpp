// JNI wrapper around the C++ extractor port (firmware/extract/src, compiled from its own path: one codebase for the
// Pico and the phone). Kotlin side: ai.vox.companion.audio.VxNative.
//
// A handle owns one VxExtractor (about 30 KB) plus a small queue of output messages, all allocated once in create().
// push*() feeds samples and returns null (the common case: nothing allocated) or a String[] of messages, one JSON
// object each:
//
//   {"kind":"sound","sound":7,"t_start_ms":839,"t_end_ms":1329,"label":"rise","text":"hum that ...","truncated":false,
//    "gate":{"like":"talking","why":"speech cues: ...","cues":["broken"],"dur_ms":490,"snr_db":14.2,...,
//            "centroid_hz":2100.0,"peak_centroid_hz":2400.0,"zcr":0.21,"lf_ratio":0.12,"hf_ratio":0.31,...},
//    "features":{"fp":[...],"fp_version":"fp1","pitch16":[...]}}          (+ "event":{...} with raw, if with_raw)
//
// Times are stream milliseconds (the first sample pushed after create/reset is t = 0). "kind" leaves room for the
// hold messages ("hold_start" / "hold_end", PROTOCOL.md "Hold messages") once the C++ port has them: they will flow
// through the same queue, in link order, and the Kotlin mapper already dispatches on "kind".
//
// The extractor keeps its FFT tables and classify scratch in static buffers, so every entry point takes one global
// lock: only one extractor runs at a time in the process (the audio thread; a debug feed waits for its turn).
#include <jni.h>
#include <math.h>
#include <mutex>
#include <new>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "vox_extract.h"

namespace {

std::mutex g_lock;

constexpr int kQueue = 8;              // messages per push call (a 20 ms push yields at most one sound)
constexpr int kMsgCap = 8192;          // one message; the full event JSON (with_raw) is about 3-4 KB
constexpr int kConv = 1024;            // conversion chunk (int16 -> float)
constexpr int kHist = 4096;            // hop time histogram: 1 us bins, 0..4095 us, plus overflow
constexpr int kBands = 8;              // stats() band levels: 0 .. sr/2 in 8 equal bands (1 kHz each at 16 kHz)
constexpr int kTickRows = 64;         // joystick ticks queued between takeTicks() calls (1.28 s; a read is 20-40 ms)
constexpr int kTickCols = 10;         // t_ms, f0, f0_raw, clarity, db, floor_db, f1, f2, voiced, why (VxNative.TICK_*)

uint32_t now_ns() {
    timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint32_t)((uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec);
}

struct Handle {
    VxExtractor ex;
    int rate;
    bool with_raw;
    uint32_t sound_no;                 // sounds emitted since create/reset: the "sound" id (1, 2, ...)
    // output queue for the current call
    int n_out;
    int dropped_out;
    char out[kQueue][kMsgCap];
    // conversion buffer
    vx_real conv[kConv];
    // stats (since stats_reset)
    uint32_t hist[kHist];
    uint32_t hist_over;
    uint32_t hops;
    uint64_t hop_sum_ns;
    uint32_t hop_max_ns;
    uint32_t seg_n;
    uint64_t seg_sum_ns;
    uint32_t seg_max_ns;
    uint32_t pushes;
    uint64_t push_sum_ns;
    uint32_t push_max_ns;
    uint64_t samples;
    // level since the last stats() read
    double lvl_sumsq;
    uint64_t lvl_n;
    float lvl_peak;
    // 8-band input level since the last stats() read (diagnostic, mic_status): the extractor's own per-hop power
    // spectrum (high-passed, Hann 512 at 16 kHz), summed per band; no extra FFT
    double band_sum[kBands];
    uint32_t band_frames;
    // joystick ticks (vx_tick.h): off unless enableTicks(); rows since the last takeTicks(), oldest dropped when full
    VxTick tick;
    bool tick_inited;
    double tick_rows[kTickRows][kTickCols];
    int tick_n;
    uint32_t tick_dropped;
    uint32_t tick_count;
};

// Band power of the frame the front end just computed (fe.p = |X|^2 of the Hann-windowed, high-passed window).
// Parseval: mean square of the signal in a band = sum over its bins of w_k |X_k|^2 / (n * sum(window^2)), with
// w_k = 2 (1 for DC and Nyquist). The frame loop already did the FFT; this is n/2 + 1 additions per hop.
void band_frame(Handle *h) {
    const VxFrontend *fe = &h->ex.fe;
    const int half = fe->n / 2;
    const double norm = 1.0 / ((double)fe->n * (double)fe->win_pow);
    for (int b = 0; b < kBands; b++) {
        int k0 = b * half / kBands, k1 = (b + 1) * half / kBands + (b == kBands - 1 ? 1 : 0);
        double s = 0;
        for (int k = k0; k < k1; k++) s += (k == 0 || k == half ? 1.0 : 2.0) * (double)fe->p[k];
        h->band_sum[b] += s * norm;
    }
    h->band_frames++;
}

void on_frame(const VxFrame *, double, void *user) {
    Handle *h = (Handle *)user;
    band_frame(h);
    uint32_t ns = h->ex.stats.hop_last;
    uint32_t us = ns / 1000;
    if (us < (uint32_t)kHist) h->hist[us]++;
    else h->hist_over++;
    h->hops++;
    h->hop_sum_ns += ns;
    if (ns > h->hop_max_ns) h->hop_max_ns = ns;
}

// The measurements the phone-mic gate and the logs use (PhoneGate, mic_sound): why the classifier decided, the
// speech-cue bits and the level / voicing / contour numbers. Always sent (about 500 bytes); the full raw needs with_raw.
void kv(VxJson *j, const char *k, double v, int d) {
    vx_json_raw(j, ",\"");
    vx_json_raw(j, k);
    vx_json_raw(j, "\":");
    vx_json_num(j, v, d);
}

void json_gate(VxJson *j, const VxEvent *ev) {
    const VxRaw *r = &ev->raw;
    static const char *const cue[3] = {"broken", "formant", "syllable"};   // VX_CUE_* bit order
    vx_json_raw(j, "{\"like\":");
    vx_json_str(j, VX_SOUNDS_LIKE[ev->like]);
    vx_json_raw(j, ",\"why\":");
    vx_json_str(j, r->why);
    vx_json_raw(j, ",\"cues\":[");
    bool first = true;
    for (int i = 0; i < 3; i++)
        if (r->has_cues && (r->cues & (1 << i))) {
            if (!first) vx_json_raw(j, ",");
            vx_json_str(j, cue[i]);
            first = false;
        }
    vx_json_raw(j, "],\"dur_ms\":");
    vx_json_int(j, r->dur_ms);
    kv(j, "floor_db", r->floor_db, 2);
    kv(j, "level_db", r->level_db, 2);
    kv(j, "snr_db", r->snr_db, 2);
    kv(j, "voiced_frac", r->voiced_frac, 3);
    kv(j, "strong_voiced_frac", r->strong_voiced_frac, 3);
    kv(j, "clarity_med", r->clarity_med, 3);
    kv(j, "f0_med_hz", r->f0_med_hz, 1);
    kv(j, "onset_flux_db", r->onset_flux_db, 2);
    kv(j, "energy_iqr_db", r->energy_iqr_db, 2);
    kv(j, "centroid_hz", r->centroid_hz, 1);
    kv(j, "peak_centroid_hz", r->peak_centroid_hz, 1);
    kv(j, "centroid_spread_oct", r->centroid_spread_oct, 3);
    kv(j, "zcr", r->zcr, 4);
    kv(j, "lf_ratio", r->lf_ratio, 4);
    kv(j, "hf_ratio", r->hf_ratio, 4);
    kv(j, "pitch_jumps_hz", r->pitch_jumps_hz, 2);
    vx_json_raw(j, ",\"voiced_runs\":");
    vx_json_int(j, r->voiced_runs);
    vx_json_raw(j, ",\"syllable_peaks\":");
    vx_json_int(j, r->syllable_peaks);
    if (r->has_shape) {
        kv(j, "excursion_st", r->excursion_st, 2);
        kv(j, "net_st", r->net_st, 2);
    }
    if (r->has_impulsive) {
        vx_json_raw(j, r->impulsive ? ",\"impulsive\":true" : ",\"impulsive\":false");
        vx_json_raw(j, r->tonal ? ",\"tonal\":true" : ",\"tonal\":false");
    }
    if (r->has_ctx && r->has_gap) kv(j, "gap_ms", r->gap_ms, 1);
    vx_json_raw(j, "}");
}

void on_event(const VxEvent *ev, void *user) {
    Handle *h = (Handle *)user;
    uint32_t seg = h->ex.stats.seg_last;
    h->seg_n++;
    h->seg_sum_ns += seg;
    if (seg > h->seg_max_ns) h->seg_max_ns = seg;
    h->sound_no++;
    if (h->n_out >= kQueue) {
        h->dropped_out++;
        return;
    }
    char *buf = h->out[h->n_out];
    VxJson j;
    vx_json_init(&j, buf, kMsgCap);
    vx_json_raw(&j, "{\"kind\":\"sound\",\"sound\":");
    vx_json_int(&j, (long)h->sound_no);
    vx_json_raw(&j, ",\"t_start_ms\":");
    vx_json_int(&j, ev->t_start_ms);
    vx_json_raw(&j, ",\"t_end_ms\":");
    vx_json_int(&j, ev->t_end_ms);
    vx_json_raw(&j, ",\"label\":");
    vx_json_str(&j, VX_LABELS[ev->label]);
    vx_json_raw(&j, ",\"text\":");
    vx_json_str(&j, ev->text);
    vx_json_raw(&j, ev->truncated ? ",\"truncated\":true" : ",\"truncated\":false");
    vx_json_raw(&j, ",\"gate\":");
    json_gate(&j, ev);
    vx_json_raw(&j, ",\"features\":");
    vx_json_features(&j, ev);
    if (h->with_raw) {
        vx_json_raw(&j, ",\"event\":");
        vx_json_event(&j, ev, true);
    }
    vx_json_raw(&j, "}");
    if (j.n >= j.cap) {   // cannot happen with kMsgCap; never hand out a truncated JSON
        h->dropped_out++;
        return;
    }
    h->n_out++;
}

void on_tick(const VxTickOut *t, void *user) {
    Handle *h = (Handle *)user;
    h->tick_count++;
    if (h->tick_n == kTickRows) {   // the reader fell behind: keep the newest
        memmove(h->tick_rows[0], h->tick_rows[1], sizeof(h->tick_rows[0]) * (kTickRows - 1));
        h->tick_n--;
        h->tick_dropped++;
    }
    double *r = h->tick_rows[h->tick_n++];
    r[0] = t->t_ms;
    r[1] = t->f0;
    r[2] = t->f0_raw;
    r[3] = t->clarity;
    r[4] = t->db;
    r[5] = t->floor_db;
    r[6] = t->f1;
    r[7] = t->f2;
    r[8] = t->voiced ? 1.0 : 0.0;
    r[9] = t->why;
}

void level_f(Handle *h, const vx_real *x, int n) {
    double s = 0;
    float pk = h->lvl_peak;
    for (int i = 0; i < n; i++) {
        float v = (float)x[i];
        s += (double)v * v;
        float a = fabsf(v);
        if (a > pk) pk = a;
    }
    h->lvl_sumsq += s;
    h->lvl_n += (uint64_t)n;
    h->lvl_peak = pk;
}

// Feed float samples in chunks (the extractor takes any chunk size).
void feed(Handle *h, const vx_real *x, int n) {
    level_f(h, x, n);
    vx_extractor_push(&h->ex, x, n, on_event, h);
    h->samples += (uint64_t)n;
}

void feed_i16(Handle *h, const int16_t *x, int n) {
    while (n > 0) {
        int k = n < kConv ? n : kConv;
        for (int i = 0; i < k; i++) h->conv[i] = (vx_real)x[i] / (vx_real)32768;   // as vx_cli --pcm and the Pico
        feed(h, h->conv, k);
        x += k;
        n -= k;
    }
}

void feed_f32(Handle *h, const float *x, int n) {
#ifdef VX_REAL_DOUBLE
    while (n > 0) {
        int k = n < kConv ? n : kConv;
        for (int i = 0; i < k; i++) h->conv[i] = x[i];
        feed(h, h->conv, k);
        x += k;
        n -= k;
    }
#else
    feed(h, x, n);
#endif
}

jobjectArray take_messages(JNIEnv *env, Handle *h) {
    if (h->n_out == 0) return nullptr;
    jclass str = env->FindClass("java/lang/String");
    jobjectArray arr = env->NewObjectArray(h->n_out, str, nullptr);
    for (int i = 0; i < h->n_out; i++) {
        jstring s = env->NewStringUTF(h->out[i]);   // ASCII only (vocabulary lines, numbers)
        env->SetObjectArrayElement(arr, i, s);
        env->DeleteLocalRef(s);
    }
    h->n_out = 0;
    return arr;
}

void stats_clear(Handle *h) {
    memset(h->hist, 0, sizeof(h->hist));
    h->hist_over = 0;
    h->hops = 0;
    h->hop_sum_ns = 0;
    h->hop_max_ns = 0;
    h->seg_n = 0;
    h->seg_sum_ns = 0;
    h->seg_max_ns = 0;
    h->pushes = 0;
    h->push_sum_ns = 0;
    h->push_max_ns = 0;
}

double pct_us(const Handle *h, double p) {
    uint64_t total = (uint64_t)h->hops;
    if (!total) return 0;
    uint64_t want = (uint64_t)ceil(p * (double)total);
    if (want < 1) want = 1;
    uint64_t c = 0;
    for (int i = 0; i < kHist; i++) {
        c += h->hist[i];
        if (c >= want) return i + 0.5;   // bin centre
    }
    return kHist;
}

Handle *H(jlong p) { return reinterpret_cast<Handle *>(p); }

template <typename F> jobjectArray timed_push(JNIEnv *env, Handle *h, F f) {
    uint32_t t0 = now_ns();
    f();
    uint32_t d = now_ns() - t0;
    h->pushes++;
    h->push_sum_ns += d;
    if (d > h->push_max_ns) h->push_max_ns = d;
    return take_messages(env, h);
}

const char *g_err = nullptr;

}   // namespace

extern "C" {

// cfg_json: null = the extractor's defaults (the Pico's config), else a flat JSON object of overrides on top of
// them ({"voiced_min_db_over_floor": 9, ...}; vx_config_load_json: an unknown key is an error, as Config.from_dict).
JNIEXPORT jlong JNICALL Java_ai_vox_companion_audio_VxNative_create(JNIEnv *env, jclass, jint rate, jboolean with_raw,
                                                                    jstring cfg_json) {
    std::lock_guard<std::mutex> g(g_lock);
    VxConfig cfg;
    vx_config_default(&cfg);
    if (cfg_json) {
        const char *s = env->GetStringUTFChars(cfg_json, nullptr);
        const char *e = s ? vx_config_load_json(&cfg, s) : "bad string";
        if (s) env->ReleaseStringUTFChars(cfg_json, s);
        if (e) {
            static char msg[256];
            snprintf(msg, sizeof(msg), "config: %s", e);
            g_err = msg;
            return 0;
        }
    }
    Handle *h = new (std::nothrow) Handle();
    if (!h) {
        g_err = "out of memory";
        return 0;
    }
    const char *err = vx_extractor_init(&h->ex, &cfg, rate);
    if (err) {
        g_err = err;
        delete h;
        return 0;
    }
    h->rate = rate;
    h->with_raw = with_raw;
    h->ex.cycles = now_ns;
    h->ex.on_frame = on_frame;
    h->ex.frame_user = h;
    return reinterpret_cast<jlong>(h);
}

JNIEXPORT jstring JNICALL Java_ai_vox_companion_audio_VxNative_lastError(JNIEnv *env, jclass) {
    return env->NewStringUTF(g_err ? g_err : "");
}

JNIEXPORT void JNICALL Java_ai_vox_companion_audio_VxNative_destroy(JNIEnv *, jclass, jlong p) {
    std::lock_guard<std::mutex> g(g_lock);
    delete H(p);
}

// A new stream: extractor state, sound numbering and the queue cleared (an open sound is dropped, as on the Pico).
JNIEXPORT void JNICALL Java_ai_vox_companion_audio_VxNative_reset(JNIEnv *, jclass, jlong p) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    vx_extractor_reset(&h->ex);
    h->sound_no = 0;
    h->n_out = 0;
    h->tick_n = 0;
    h->samples = 0;
}

JNIEXPORT jobjectArray JNICALL Java_ai_vox_companion_audio_VxNative_pushShorts(JNIEnv *env, jclass, jlong p,
                                                                               jshortArray a, jint off, jint n) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    return timed_push(env, h, [&] {
        int16_t tmp[kConv];
        while (n > 0) {
            int k = n < kConv ? n : kConv;
            env->GetShortArrayRegion(a, off, k, tmp);
            feed_i16(h, tmp, k);
            off += k;
            n -= k;
        }
    });
}

JNIEXPORT jobjectArray JNICALL Java_ai_vox_companion_audio_VxNative_pushFloats(JNIEnv *env, jclass, jlong p,
                                                                               jfloatArray a, jint off, jint n) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    return timed_push(env, h, [&] {
        float tmp[kConv];
        while (n > 0) {
            int k = n < kConv ? n : kConv;
            env->GetFloatArrayRegion(a, off, k, tmp);
            feed_f32(h, tmp, k);
            off += k;
            n -= k;
        }
    });
}

// The audio thread's path: AudioRecord.read(ByteBuffer) into a direct buffer, no copy on the Java side.
// isFloat: ENCODING_PCM_FLOAT samples, else ENCODING_PCM_16BIT.
JNIEXPORT jobjectArray JNICALL Java_ai_vox_companion_audio_VxNative_pushDirect(JNIEnv *env, jclass, jlong p,
                                                                               jobject buf, jint n, jboolean isFloat) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    void *base = env->GetDirectBufferAddress(buf);
    jlong cap = env->GetDirectBufferCapacity(buf);
    if (!base || n <= 0 || (jlong)n * (isFloat ? 4 : 2) > cap) return nullptr;
    return timed_push(env, h, [&] {
        if (isFloat) feed_f32(h, (const float *)base, n);
        else feed_i16(h, (const int16_t *)base, n);
    });
}

// End of stream (a feed): closes an open sound as if its hangover ran out.
JNIEXPORT jobjectArray JNICALL Java_ai_vox_companion_audio_VxNative_flush(JNIEnv *env, jclass, jlong p) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    vx_extractor_flush(&h->ex, on_event, h);
    return take_messages(env, h);
}

// Stats as JSON; reading resets the level window. Times in microseconds.
JNIEXPORT jstring JNICALL Java_ai_vox_companion_audio_VxNative_stats(JNIEnv *env, jclass, jlong p) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    char b[1600];
    // [8 band levels, dBFS] (mean square over the frames since the last read; -200 = silence), or null before a frame
    char bands[160] = "null";
    if (h->band_frames) {
        int o = snprintf(bands, sizeof(bands), "[");
        for (int i = 0; i < kBands; i++) {
            double ms = h->band_sum[i] / h->band_frames;
            o += snprintf(bands + o, sizeof(bands) - o, "%s%.1f", i ? "," : "", ms > 1e-20 ? 10 * log10(ms) : -200.0);
        }
        snprintf(bands + o, sizeof(bands) - o, "]");
    }
    double rms = h->lvl_n ? sqrt(h->lvl_sumsq / (double)h->lvl_n) : 0;
    double rms_db = rms > 0 ? 20 * log10(rms) : -200;
    double pk_db = h->lvl_peak > 0 ? 20 * log10((double)h->lvl_peak) : -200;
    double hop_mean = h->hops ? h->hop_sum_ns / 1e3 / h->hops : 0;
    double seg_mean = h->seg_n ? h->seg_sum_ns / 1e3 / h->seg_n : 0;
    double push_mean = h->pushes ? h->push_sum_ns / 1e3 / h->pushes : 0;
    snprintf(b, sizeof(b),
             "{\"rate\":%d,\"samples\":%llu,\"hops\":%u,\"hop_us\":{\"p50\":%.1f,\"p90\":%.1f,\"p99\":%.1f,"
             "\"mean\":%.2f,\"max\":%.1f,\"over_4ms\":%u},\"sound_end_us\":{\"n\":%u,\"mean\":%.1f,\"max\":%.1f},"
             "\"push_us\":{\"n\":%u,\"mean\":%.2f,\"max\":%.1f},\"sounds\":%u,\"events\":%u,\"dropped\":%u,"
             "\"ticks\":{\"on\":%s,\"n\":%u,\"dropped\":%u},\"queue_drops\":%d,\"floor_db\":%.2f,\"gate_open\":%s,\"level\":{\"rms_dbfs\":%.1f,\"peak_dbfs\":%.1f,"
             "\"ms\":%.0f,\"band_hz\":%d,\"bands_dbfs\":%s}}",
             h->rate, (unsigned long long)h->samples, h->hops, pct_us(h, 0.5), pct_us(h, 0.9), pct_us(h, 0.99),
             hop_mean, h->hop_max_ns / 1e3, h->hist_over, h->seg_n, seg_mean, h->seg_max_ns / 1e3, h->pushes,
             push_mean, h->push_max_ns / 1e3, h->sound_no, h->ex.stats.events, h->ex.stats.dropped,
             h->ex.tick ? "true" : "false", h->tick_count, h->tick_dropped, h->dropped_out,
             h->ex.seg.floor_db, h->ex.seg.open ? "true" : "false", rms_db, pk_db,
             h->lvl_n * 1000.0 / (h->rate ? h->rate : 16000), h->ex.fe.sr / 2 / kBands, bands);
    h->lvl_sumsq = 0;
    memset(h->band_sum, 0, sizeof(h->band_sum));
    h->band_frames = 0;
    h->lvl_n = 0;
    h->lvl_peak = 0;
    return env->NewStringUTF(b);
}

// Joystick ticks (vx_tick.h) on the same 16 kHz samples: on = a fresh tick analyzer (its floor learns again), off =
// none (the extractor path is then exactly as before). Returns false if the tick config did not init.
JNIEXPORT jboolean JNICALL Java_ai_vox_companion_audio_VxNative_enableTicks(JNIEnv *, jclass, jlong p, jboolean on) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    h->tick_n = 0;
    if (!on) {
        h->ex.tick = nullptr;
        h->ex.on_tick = nullptr;
        return JNI_TRUE;
    }
    double clarity = h->tick_inited ? h->tick.cfg.clarity_on : -1;
    double f0max = h->tick_inited ? h->tick.cfg.f0_max_hz : -1;
    if (vx_tick_init(&h->tick, nullptr)) return JNI_FALSE;
    if (clarity >= 0) h->tick.cfg.clarity_on = clarity;
    if (f0max > 0) h->tick.cfg.f0_max_hz = f0max;
    h->tick_inited = true;
    h->ex.tick = &h->tick;
    h->ex.on_tick = on_tick;
    h->ex.tick_user = h;
    return JNI_TRUE;
}

// The start threshold of a voiced tick (the person's own clarity_on from the setup; default 0.8). Kept across enableTicks.
JNIEXPORT void JNICALL Java_ai_vox_companion_audio_VxNative_setTickClarityOn(JNIEnv *, jclass, jlong p, jdouble v) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    if (!h->tick_inited) {
        if (vx_tick_init(&h->tick, nullptr)) return;
        h->tick_inited = true;
    }
    h->tick.cfg.clarity_on = v;
}

// The ticks' pitch ceiling (vx_tick_config_default: 1100 Hz; 2600 while a calibration's whistle range is in use, so a
// whistle is not read an octave or a twelfth low). Kept across enableTicks.
JNIEXPORT void JNICALL Java_ai_vox_companion_audio_VxNative_setTickF0MaxHz(JNIEnv *, jclass, jlong p, jdouble v) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    if (!h->tick_inited) {
        if (vx_tick_init(&h->tick, nullptr)) return;
        h->tick_inited = true;
    }
    if (v > 0) h->tick.cfg.f0_max_hz = v;
}

// The ticks since the last call, oldest first, kTickCols doubles each, into out (as many whole rows as fit; the rest
// stay queued). Returns the number of rows written.
JNIEXPORT jint JNICALL Java_ai_vox_companion_audio_VxNative_takeTicks(JNIEnv *env, jclass, jlong p, jdoubleArray out) {
    std::lock_guard<std::mutex> g(g_lock);
    Handle *h = H(p);
    int cap = env->GetArrayLength(out) / kTickCols;
    int n = h->tick_n < cap ? h->tick_n : cap;
    if (n <= 0) return 0;
    env->SetDoubleArrayRegion(out, 0, n * kTickCols, &h->tick_rows[0][0]);
    if (n < h->tick_n) memmove(h->tick_rows[0], h->tick_rows[n], sizeof(h->tick_rows[0]) * (size_t)(h->tick_n - n));
    h->tick_n -= n;
    return n;
}

JNIEXPORT void JNICALL Java_ai_vox_companion_audio_VxNative_statsReset(JNIEnv *, jclass, jlong p) {
    std::lock_guard<std::mutex> g(g_lock);
    stats_clear(H(p));
}

// The extractor's identity, for the status line and logs: fp version and the vocabulary digest input size.
JNIEXPORT jstring JNICALL Java_ai_vox_companion_audio_VxNative_version(JNIEnv *env, jclass) {
    return env->NewStringUTF("vox_extract C++ port, " VX_FP_VERSION
#if defined(__aarch64__)
                             ", arm64"
#elif defined(__x86_64__)
                             ", x86_64"
#endif
#ifdef VX_REAL_DOUBLE
                             ", double"
#else
                             ", float32"
#endif
    );
}

}   // extern "C"
