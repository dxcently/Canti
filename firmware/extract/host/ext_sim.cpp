// Runs the sketch's extractor glue (arduino/vox_node/ext.cpp) on the host: a second thread plays core 1
// (setup1 + loop1), the main thread plays core 0 and feeds a vector either the way the mic does (ext_mic_push in
// 64-sample chunks, paced at ~8x real time) or the way `ext feed` does (ext_feed_room / ext_feed_bytes in
// random-sized pieces). Prints the delivered sounds as JSON lines, like vx_cli, so tools/check_extract.py compares
// them with the reference: this checks the ring, the reset / flush handshakes and the event queue, not the DSP.
// Hold messages (vx_hold.h) come out as JSON lines with a "hold" key, in order with the sounds (stream times).
//
//   ext_sim --pcm vectors/x.pcm [--rate 16000|48000] --mode feed|mic
#include <stdarg.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <string>
#include <thread>
#include <vector>
#include "Arduino.h"
#include "ext.h"
#include "out.h"
#include "power.h"
#include "vox_state.h"

HostRp2040 rp2040;
volatile bool g_streaming = false;
VoxState g_state = {true, false, VoxMode::Gesture, false};

void setup1();
void loop1();

static std::string s_lines;
void out_line(const char *s) {
    s_lines += s;
    s_lines += "\n";
}
void out_printf(const char *fmt, ...) {
    char b[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(b, sizeof(b), fmt, ap);
    va_end(ap);
    out_line(b);
}
void info_changed() {}
bool power_asleep() { return false; }
static int s_sent;
static std::string s_sent_json;
uint32_t send_sound(const char *label, const char *line, uint32_t t0, uint32_t t1, const char *features, int32_t sound,
                    bool held) {
    char b[1400];
    snprintf(b, sizeof(b), "{\"t_start_ms\": %u, \"t_end_ms\": %u, \"label\": \"%s\", \"text\": \"%s\", \"sound\": %d, \"held\": %s, "
             "\"features\": %s}", t0, t1, label, line, (int)sound, held ? "true" : "false", features ? features : "null");
    s_sent_json += b;
    s_sent_json += "\n";
    return ++s_sent;
}
// hold messages (vox_state.cpp send_hold), in order with the sounds, device clock; main() re-bases both times
uint32_t send_hold(const char *kind, int32_t sound, uint32_t t_start_ms, uint32_t t_ms, double f0_hz, bool flat, int dir) {
    char b[240];
    snprintf(b, sizeof(b), "{\"hold\": \"%s\", \"sound\": %d, \"t_start_ms\": %u, \"t_ms\": %u, \"f0_hz\": %.1f, \"flat\": %s%s}\n",
             kind, (int)sound, t_start_ms, t_ms, f0_hz, flat ? "true" : "false",
             dir > 0 ? ", \"from\": \"glide\", \"dir\": \"up\"" : dir < 0 ? ", \"from\": \"glide\", \"dir\": \"down\"" : "");
    s_sent_json += b;
    return ++s_sent;
}

static std::atomic<bool> s_quit{false};

int main(int argc, char **argv) {
    const char *pcm = nullptr, *mode = "feed";
    int rate = 16000;
    for (int i = 1; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "--pcm")) pcm = argv[i + 1];
        else if (!strcmp(argv[i], "--rate")) rate = atoi(argv[i + 1]);
        else if (!strcmp(argv[i], "--mode")) mode = argv[i + 1];
    }
    FILE *f = pcm ? fopen(pcm, "rb") : nullptr;
    if (!f) {
        fprintf(stderr, "ext_sim --pcm file [--rate r] --mode feed|mic\n");
        return 2;
    }
    std::vector<uint8_t> b;
    uint8_t tmp[65536];
    size_t k;
    while ((k = fread(tmp, 1, sizeof(tmp), f)) > 0) b.insert(b.end(), tmp, tmp + k);
    fclose(f);
    std::thread core1([] {
        setup1();
        while (!s_quit) loop1();
    });
    ext_begin();
    srand(1);
    if (!strcmp(mode, "feed")) {
        ext_stream_start();   // awake with the mic running, then a feed takes over
        if (!ext_feed_begin((uint32_t)(b.size() / 2), rate)) return 2;
        size_t pos = 0;
        while (ext_feeding()) {
            size_t room = ext_feed_room();
            size_t n = std::min(room, std::min(b.size() - pos, (size_t)(1 + rand() % 700)));   // odd sizes too
            if (n) {
                ext_feed_bytes(&b[pos], n);
                pos += n;
            }
            ext_poll(millis());
        }
        for (int i = 0; i < 20000 && s_lines.find("ext feed: done") == std::string::npos; i++) {
            ext_poll(millis());
            sched_yield();
        }
        s_quit = true;
        core1.join();
        // the `ext event` / `ext features` lines -> one JSON object per event (as tools/ext_feed.py reads them)
        size_t p = 0;
        std::string ev;
        while (p < s_lines.size()) {
            size_t e = s_lines.find('\n', p);
            std::string l = s_lines.substr(p, e - p);
            p = e + 1;
            if (!l.compare(0, 10, "ext event ")) {
                if (!ev.empty()) printf("%s}\n", ev.c_str());
                ev = l.substr(10);
                ev.pop_back();   // reopen the object for the features
            } else if (!l.compare(0, 13, "ext features ") && !ev.empty()) {
                ev += ", \"features\": " + l.substr(13);
            } else if (!l.compare(0, 9, "ext hold ")) {   // stream times already; in order with the events
                if (!ev.empty()) printf("%s}\n", ev.c_str());
                ev.clear();
                printf("%s\n", l.substr(9).c_str());
            } else if (l.compare(0, 4, "ext:") && l.compare(0, 9, "ext feed:")) {
                fprintf(stderr, "%s\n", l.c_str());
            }
        }
        if (!ev.empty()) printf("%s}\n", ev.c_str());
        return s_lines.find("ext feed: done") == std::string::npos ? 1 : 0;
    }
    // mic mode: 16 kHz only (the mic path); paced 64-sample chunks with occasional bursts; then silence to flush
    if (rate != 16000) return 2;
    ext_stream_start();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));   // core 1 takes the reset (on the device: the
                                                                  // 120 ms mic start-up in mic_begin)
    uint32_t base = 0;
    std::vector<int16_t> x(b.size() / 2);
    memcpy(x.data(), b.data(), x.size() * 2);
    x.resize(x.size() + 16000, 0);   // 1 s of silence: every sound ends through the hangover, as on the device
    for (size_t i = 0; i < x.size(); i += 64) {
        int n = (int)std::min((size_t)64, x.size() - i);
        ext_mic_push(&x[i], n);
        if (i == 0) base = millis();
        std::this_thread::sleep_for(std::chrono::microseconds(500));   // 64 samples = 4 ms: ~8x real time
        ext_poll(millis());
    }
    for (int i = 0; i < 200; i++) {
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
        ext_poll(millis());
    }
    s_quit = true;
    core1.join();
    ext_poll(millis());
    // device times are base + stream time; print stream time for the comparison
    size_t p = 0;
    while (p < s_sent_json.size()) {
        size_t e = s_sent_json.find('\n', p);
        std::string l = s_sent_json.substr(p, e - p);
        p = e + 1;
        unsigned t0, t1;
        if (!l.compare(0, 9, "{\"hold\": ")) {   // re-base t_start_ms and t_ms; the rest (f0_hz, flat, from, dir) as sent
            char kind[8];
            int sound;
            sscanf(l.c_str(), "{\"hold\": \"%7[a-z]\", \"sound\": %d, \"t_start_ms\": %u, \"t_ms\": %u", kind, &sound, &t0, &t1);
            printf("{\"hold\": \"%s\", \"sound\": %d, \"t_start_ms\": %d, \"t_ms\": %d%s\n", kind, sound, (int)(t0 - base),
                   (int)(t1 - base), l.c_str() + l.find(", \"f0_hz\""));
            continue;
        }
        sscanf(l.c_str(), "{\"t_start_ms\": %u, \"t_end_ms\": %u", &t0, &t1);
        size_t rest = l.find(", \"label\"");
        printf("{\"t_start_ms\": %d, \"t_end_ms\": %d%s\n", (int)(t0 - base), (int)(t1 - base), l.c_str() + rest);
    }
    ext_stats(false);
    for (size_t q = 0, e; (e = s_lines.find('\n', q)) != std::string::npos; q = e + 1) {
        std::string l = s_lines.substr(q, e - q);
        if (!l.compare(0, 4, "ext:") && (l.find("overflow") != std::string::npos)) fprintf(stderr, "%s\n", l.c_str());
    }
    return 0;
}
