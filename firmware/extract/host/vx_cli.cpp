// Host command line for the C++ extractor port: reads a vector or a WAV, prints one JSON event per line (the same
// fields as the Python Event.to_dict()), optionally the per-frame features as CSV (the vectors' frames.csv
// format). Built by firmware/tools/check_extract.sh; see firmware/README.md "Extractor".
//
//   vx_cli --pcm vectors/rise_20db.pcm --rate 16000 [--frames out.csv]
//   vx_cli --wav session.wav                 (PCM16 or float32 WAV at 16 or 48 kHz)
//   vx_cli --f32 x.f32 --rate 16000          (float32 LE samples, e.g. Python's to_16k output)
//   vx_cli --dump-config | --vocab-json | --decim in.f32 out.f32
//   --holds: also print the hold messages (vx_hold.h) as JSON lines with a "hold" key, in emission order with the
//            events (as Extractor.push_stream)
//   --ticks out.csv: also the joystick ticks (vx_tick.h, 16 kHz after decimation) as CSV; --tick-clarity V sets
//            their clarity_on; --tick-bench N times the tick analysis alone (N runs) and prints us/tick to stderr
//   options: --config cfg.json, --chunk N (input samples per push), --keep-dropped, --bench N (repeat N times and
//            print the time per hop to stderr), --stats
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <vector>
#include "vox_extract.h"

static std::vector<float> read_file_raw(const char *path, bool f32) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        exit(2);
    }
    std::vector<unsigned char> b;
    unsigned char tmp[65536];
    size_t k;
    while ((k = fread(tmp, 1, sizeof(tmp), f)) > 0) b.insert(b.end(), tmp, tmp + k);
    fclose(f);
    std::vector<float> x;
    if (f32) {
        x.resize(b.size() / 4);
        memcpy(x.data(), b.data(), x.size() * 4);
    } else {
        x.resize(b.size() / 2);
        for (size_t i = 0; i < x.size(); i++) {
            int16_t v = (int16_t)(b[2 * i] | (b[2 * i + 1] << 8));
            x[i] = (float)v / 32768.0f;
        }
    }
    return x;
}

static uint32_t rd32(const unsigned char *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint16_t rd16(const unsigned char *p) { return (uint16_t)(p[0] | (p[1] << 8)); }

// PCM16 or float32 WAV -> mono float32 (channels averaged in float32, like load_wav) and its rate
static std::vector<float> read_wav(const char *path, int *rate) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        exit(2);
    }
    std::vector<unsigned char> b;
    unsigned char tmp[65536];
    size_t k;
    while ((k = fread(tmp, 1, sizeof(tmp), f)) > 0) b.insert(b.end(), tmp, tmp + k);
    fclose(f);
    if (b.size() < 12 || memcmp(b.data(), "RIFF", 4) || memcmp(b.data() + 8, "WAVE", 4)) {
        fprintf(stderr, "%s: not a WAV file\n", path);
        exit(2);
    }
    int fmt = 0, ch = 0, bits = 0;
    size_t pos = 12;
    std::vector<float> x;
    while (pos + 8 <= b.size()) {
        uint32_t len = rd32(&b[pos + 4]);
        const unsigned char *d = &b[pos + 8];
        if (!memcmp(&b[pos], "fmt ", 4)) {
            fmt = rd16(d);
            ch = rd16(d + 2);
            *rate = (int)rd32(d + 4);
            bits = rd16(d + 14);
            if (fmt == 0xFFFE && len >= 26) fmt = rd16(d + 24);   // WAVE_FORMAT_EXTENSIBLE: sub-format
        } else if (!memcmp(&b[pos], "data", 4)) {
            size_t avail = b.size() - (pos + 8);
            if (len > avail) len = (uint32_t)avail;
            if (fmt == 1 && bits == 16) {
                size_t n = len / (2 * ch);
                x.resize(n);
                for (size_t i = 0; i < n; i++) {
                    float s = 0;
                    for (int c = 0; c < ch; c++) s += (float)(int16_t)rd16(d + 2 * (i * ch + c)) / 32768.0f;
                    x[i] = ch == 1 ? s : s / (float)ch;
                }
            } else if (fmt == 3 && bits == 32) {
                size_t n = len / (4 * ch);
                x.resize(n);
                for (size_t i = 0; i < n; i++) {
                    float s = 0;
                    for (int c = 0; c < ch; c++) {
                        float v;
                        memcpy(&v, d + 4 * (i * ch + c), 4);
                        s += v;
                    }
                    x[i] = ch == 1 ? s : s / (float)ch;
                }
            } else {
                fprintf(stderr, "%s: only PCM16 or float32 WAV (format %d, %d bits)\n", path, fmt, bits);
                exit(2);
            }
            return x;
        }
        pos += 8 + len + (len & 1);
    }
    fprintf(stderr, "%s: no data chunk\n", path);
    exit(2);
}

static uint32_t ns_now() {
    timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint32_t)(t.tv_sec * 1000000000ull + t.tv_nsec);
}

static FILE *s_frames = NULL;
static void on_frame(const VxFrame *f, double floor_after, void *) {
    if (!s_frames) return;
    // the vectors' frames.csv columns, %.6g like export_vectors.py
    fprintf(s_frames, "%d,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g,%.6g\n", (int)f->index, (double)f->t_ms,
            (double)f->e_db, (double)f->zcr, (double)f->centroid, (double)f->flatness, (double)f->flux,
            (double)f->lf_ratio, (double)f->hf_ratio, (double)f->f0, (double)f->clarity, floor_after);
}

static bool s_print = true;
static char s_json[16384];
static void on_event(const VxEvent *ev, void *) {
    if (!s_print) return;
    VxJson j;
    vx_json_init(&j, s_json, sizeof(s_json));
    vx_json_event(&j, ev, true);
    puts(s_json);
}

static void on_hold(const VxHold *h, void *) {
    if (!s_print) return;
    VxJson j;
    vx_json_init(&j, s_json, sizeof(s_json));
    vx_json_hold(&j, h);
    puts(s_json);
}

static FILE *s_ticks = NULL;
static void on_tick(const VxTickOut *t, void *) {
    if (!s_ticks) return;
    fprintf(s_ticks, "%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,%d\n", t->t_ms, t->f0, t->f0_raw, t->clarity, t->db,
            t->floor_db, t->f1, t->f2, t->voiced ? 1 : 0, t->why);
}

static VxExtractor s_ex;
static VxTick s_tick;

int main(int argc, char **argv) {
    const char *pcm = NULL, *wav = NULL, *f32 = NULL, *frames = NULL, *cfg_path = NULL;
    const char *ticks = NULL;
    double tick_clarity = -1;
    int tick_bench = 0;
    int rate = 16000, chunk = 0, bench = 0;
    bool keep_dropped = false, stats = false, holds = false;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        auto next = [&]() -> const char * {
            if (i + 1 >= argc) {
                fprintf(stderr, "%s needs a value\n", a);
                exit(2);
            }
            return argv[++i];
        };
        if (!strcmp(a, "--pcm")) pcm = next();
        else if (!strcmp(a, "--wav")) wav = next();
        else if (!strcmp(a, "--f32")) f32 = next();
        else if (!strcmp(a, "--rate")) rate = atoi(next());
        else if (!strcmp(a, "--frames")) frames = next();
        else if (!strcmp(a, "--config")) cfg_path = next();
        else if (!strcmp(a, "--chunk")) chunk = atoi(next());
        else if (!strcmp(a, "--bench")) bench = atoi(next());
        else if (!strcmp(a, "--keep-dropped")) keep_dropped = true;
        else if (!strcmp(a, "--stats")) stats = true;
        else if (!strcmp(a, "--holds")) holds = true;
        else if (!strcmp(a, "--ticks")) ticks = next();
        else if (!strcmp(a, "--tick-clarity")) tick_clarity = atof(next());
        else if (!strcmp(a, "--tick-bench")) tick_bench = atoi(next());
        else if (!strcmp(a, "--dump-config")) {
            VxConfig c;
            vx_config_default(&c);
            static char b[8192];
            vx_config_json(&c, b, sizeof(b));
            puts(b);
            return 0;
        } else if (!strcmp(a, "--vocab-json")) {
            static char b[4096];
            vx_vocab_json(b, sizeof(b));
            fputs(b, stdout);
            return 0;
        } else if (!strcmp(a, "--decim")) {
            const char *in = next(), *out = next();
            std::vector<float> x = read_file_raw(in, true);
            std::vector<vx_real> xr(x.begin(), x.end()), y(x.size() / 3 + 2);
            VxDecim3 d;
            vx_decim_reset(&d);
            int m = vx_decim_push(&d, xr.data(), (int)xr.size(), y.data());
            FILE *f = fopen(out, "wb");
            for (int k = 0; k < m; k++) {
                float v = (float)y[k];
                fwrite(&v, 4, 1, f);
            }
            fclose(f);
            return 0;
        } else {
            fprintf(stderr, "unknown option %s\n", a);
            return 2;
        }
    }
    std::vector<float> x;
    if (pcm) x = read_file_raw(pcm, false);
    else if (f32) x = read_file_raw(f32, true);
    else if (wav) x = read_wav(wav, &rate);
    else {
        fprintf(stderr, "give --pcm, --wav or --f32\n");
        return 2;
    }
    VxConfig cfg;
    vx_config_default(&cfg);
    if (cfg_path) {
        std::vector<float> dummy;
        FILE *f = fopen(cfg_path, "rb");
        if (!f) {
            fprintf(stderr, "cannot open %s\n", cfg_path);
            return 2;
        }
        static char b[16384];
        size_t n = fread(b, 1, sizeof(b) - 1, f);
        fclose(f);
        b[n] = 0;
        const char *err = vx_config_load_json(&cfg, b);
        if (err) {
            fprintf(stderr, "%s\n", err);
            return 2;
        }
    }
    const char *err = vx_extractor_init(&s_ex, &cfg, rate);
    if (err) {
        fprintf(stderr, "extractor: %s\n", err);
        return 2;
    }
    s_ex.keep_dropped = keep_dropped;
    if (holds) s_ex.on_hold = on_hold;
    s_ex.cycles = ns_now;
    if (!chunk) chunk = 1600 * (rate / 16000);
    std::vector<vx_real> xr(x.begin(), x.end());
    if (frames) {
        s_frames = fopen(frames, "w");
        fprintf(s_frames, "index,t_ms,e_db,zcr,centroid,flatness,flux,lf_ratio,hf_ratio,f0,clarity,floor_db_after\n");
        s_ex.on_frame = on_frame;
    }
    if (ticks || tick_bench) {
        vx_tick_init(&s_tick, NULL);
        if (tick_clarity >= 0) s_tick.cfg.clarity_on = tick_clarity;
    }
    if (ticks) {
        s_ticks = fopen(ticks, "w");
        fprintf(s_ticks, "t_ms,f0,f0_raw,clarity,db,floor_db,f1,f2,voiced,why\n");
        s_ex.tick = &s_tick;
        s_ex.on_tick = on_tick;
    }
    if (tick_bench > 0) {
        if (rate != 16000) {
            fprintf(stderr, "--tick-bench needs 16 kHz input\n");
            return 2;
        }
        uint64_t best = ~0ull;
        long nt = 0;
        VxTickOut o;
        for (int r = 0; r < tick_bench; r++) {
            vx_tick_reset(&s_tick);
            nt = 0;
            uint64_t t0 = ns_now();
            for (size_t i = 0; i < xr.size(); i++) nt += vx_tick_push(&s_tick, xr[i], &o);
            uint64_t dt = (uint32_t)(ns_now() - (uint32_t)t0);
            if (dt < best) best = dt;
        }
        fprintf(stderr, "ticks %ld; %.2f us/tick (best of %d)\n", nt, nt ? best / 1e3 / nt : 0.0, tick_bench);
        return 0;
    }
    int runs = bench > 0 ? bench : 1;
    uint64_t best_ns = ~0ull;
    VxStats st{};
    for (int r = 0; r < runs; r++) {
        s_print = r == 0;
        if (r) {
            vx_extractor_reset(&s_ex);
            s_ex.on_tick = NULL;
            if (s_frames) {
                fclose(s_frames);
                s_frames = NULL;
                s_ex.on_frame = NULL;
            }
        }
        uint64_t t0 = ns_now();
        for (size_t i = 0; i < xr.size(); i += chunk) {
            int k = (int)(xr.size() - i < (size_t)chunk ? xr.size() - i : chunk);
            vx_extractor_push(&s_ex, xr.data() + i, k, on_event, NULL);
        }
        vx_extractor_flush(&s_ex, on_event, NULL);
        uint64_t dt = (uint32_t)(ns_now() - (uint32_t)t0);
        if (dt < best_ns) best_ns = dt, st = s_ex.stats;
        fflush(stdout);
    }
    if (s_ticks) fclose(s_ticks);
    if (s_frames) fclose(s_frames);
    if (bench || stats) {
        fprintf(stderr, "hops %u, segments %u, events %u, dropped %u; total %.3f ms = %.2f us/hop; hop max %.2f us, "
                        "mean %.2f us; segment end max %.2f us\n",
                st.hops, st.segments, st.events, st.dropped, best_ns / 1e6, st.hops ? best_ns / 1e3 / st.hops : 0.0,
                st.hop_max / 1e3, st.hops ? st.hop_sum / 1e3 / st.hops : 0.0, st.seg_max / 1e3);
    }
    return 0;
}
