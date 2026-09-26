#include "mic.h"
#include "config.h"
#include "out.h"
#include <I2S.h>
#include <math.h>

void mic_changed(bool present);   // in vox_node.ino: refreshes INFO

static I2S s_i2s(INPUT);
static bool s_running = false;
static bool s_off = false;     // stopped for sleep (mic_end)
static MicMode s_mode = MicMode::Off;
static int s_gain_db = 12;

// presence
static bool s_present = false;
static uint32_t s_last_alive_ms = 0;
static const uint32_t ALIVE_HOLD_MS = 2000;

// 100 ms analysis window (1600 samples)
struct Win {
    uint32_t n;
    int64_t sum;
    double sumsq;
    int32_t peak, mn, mx;
    uint32_t nonzero_l, nonzero_r;
    int32_t first;
    bool constant;
};
static Win s_w;
static uint32_t s_overruns;

// stream
static int16_t s_frame[160];
static int s_frame_n;
static uint32_t s_stream_frames;

static void win_reset() {
    s_w = Win{};
    s_w.constant = true;
    s_w.mn = INT32_MAX;
    s_w.mx = INT32_MIN;
}

static double dbfs(double v) { return v <= 0 ? -144.0 : 20.0 * log10(v / 8388608.0); }

static void win_done(uint32_t now) {
    bool alive = !s_w.constant;   // any change at all in the left slot
    if (alive) s_last_alive_ms = now;
    bool present = s_last_alive_ms && now - s_last_alive_ms < ALIVE_HOLD_MS;
    if (present != s_present) {
        s_present = present;
        out_printf("mic: %s", present ? "signal detected (inmp441)" : "no signal (none)");
        mic_changed(present);
    }
    if (s_mode == MicMode::Level) {
        double mean = (double)s_w.sum / s_w.n;
        double var = s_w.sumsq / s_w.n - mean * mean;
        double rms = var > 0 ? sqrt(var) : 0;
        if (s_w.nonzero_l == 0 && s_w.nonzero_r == 0) {
            out_line("mic level: ALL ZEROS - no mic data. Check VDD=3V3, GND, SD->GP20, SCK->GP18, WS->GP19");
        } else if (s_w.nonzero_l == 0) {
            out_line("mic level: left slot is zero but the RIGHT slot has data - tie the mic's L/R pin to GND");
        } else if (s_w.constant) {
            out_printf("mic level: CONSTANT value %ld - stuck data line? Check SD->GP20 and the clock wires",
                       (long)s_w.first);
        } else {
            out_printf("mic level: rms %6.1f dBFS  peak %6.1f dBFS  dc %6.1f dBFS%s", dbfs(rms), dbfs(s_w.peak),
                       dbfs(fabs(mean)), s_w.peak >= 8388000 ? "  CLIPPING" : "");
        }
    }
    win_reset();
}

void mic_begin() {
    s_i2s.setBCLK(PIN_MIC_BCLK);    // WS = BCLK + 1 = GP19
    s_i2s.setDATA(PIN_MIC_DATA);
    s_i2s.setBitsPerSample(32);
    s_i2s.setFrequency(16000);
    s_i2s.setBuffers(16, 256);      // 16 x 128 stereo frames = 128 ms of slack
    s_off = false;
    s_running = s_i2s.begin();
    gpio_pull_down(PIN_MIC_DATA);   // an absent mic then reads as exact zeros, not noise
    win_reset();
    if (!s_running) {
        out_line("mic: I2S failed to start");
        return;
    }
    // presence check: drop the INMP441 start-up (~85 ms; also the floating data pin before the pull-down, seen as
    // a false "signal" after a wake), then look at ~200 ms
    static int32_t junk[128];
    uint32_t t0 = millis();
    while (millis() - t0 < 120) {
        while (s_i2s.available() >= (int)sizeof(junk)) s_i2s.read((uint8_t *)junk, sizeof(junk));
    }
    win_reset();
    s_last_alive_ms = 0;
    t0 = millis();
    while (millis() - t0 < 220) mic_poll(millis());
}

void mic_poll(uint32_t now) {
    if (!s_running) return;
    if (s_i2s.getOverUnderflow()) s_overruns++;
    static int32_t buf[128];  // 64 stereo frames
    for (int guard = 0; guard < 8; guard++) {
        int avail = s_i2s.available();          // bytes
        if (avail < (int)sizeof(buf)) break;
        size_t got = s_i2s.read((uint8_t *)buf, sizeof(buf));
        int frames = got / 8;
        for (int i = 0; i < frames; i++) {
            int32_t l = buf[2 * i], r = buf[2 * i + 1];
            int32_t s = l >> 8;                 // 24-bit sample, MSB-aligned in the 32-bit slot
            if (s_w.n == 0) s_w.first = s;
            else if (s != s_w.first) s_w.constant = false;
            s_w.n++;
            s_w.sum += s;
            s_w.sumsq += (double)s * s;
            int32_t a = s < 0 ? -s : s;
            if (a > s_w.peak) s_w.peak = a;
            if (l) s_w.nonzero_l++;
            if (r) s_w.nonzero_r++;
            if (s_w.n >= 1600) win_done(now);
            if (s_mode == MicMode::Stream) {
                int shift = 16 - s_gain_db / 6;  // 0 dB = the top 16 bits (l >> 16); each 6 dB is one bit less
                int32_t v = l >> shift;
                if (v > 32767) v = 32767;
                if (v < -32768) v = -32768;
                s_frame[s_frame_n++] = (int16_t)v;
                if (s_frame_n == 160) {
                    out_frame('A', (const uint8_t *)s_frame, sizeof(s_frame));
                    s_frame_n = 0;
                    s_stream_frames++;
                }
            }
        }
    }
}

void mic_set_mode(MicMode m) {
    if (m == MicMode::Stream && s_mode != MicMode::Stream) {
        s_frame_n = 0;
        s_stream_frames = 0;
        out_printf("mic stream: PCM16 LE mono 16 kHz, gain %d dB, 160-sample 'A' frames; `mic off` stops", s_gain_db);
        g_streaming = true;
    }
    if (m != MicMode::Stream && s_mode == MicMode::Stream) {
        g_streaming = false;
        out_printf("mic stream stopped after %lu frames", (unsigned long)s_stream_frames);
    }
    s_mode = m;
}

// Sleep: stop I2S, so the mic's clock stops (the INMP441 then drops into its own sleep mode).
void mic_end() {
    if (s_mode != MicMode::Off) mic_set_mode(MicMode::Off);
    if (s_running) s_i2s.end();
    s_running = false;
    s_off = true;
}

MicMode mic_mode() { return s_mode; }
bool mic_present() { return s_present; }
int mic_gain_db() { return s_gain_db; }

void mic_set_gain_db(int db) {
    db = constrain(db, 0, 24);
    s_gain_db = db / 6 * 6;
}

void mic_status() {
    out_printf("mic: %s, I2S %s, mode %s, stream gain %d dB, buffer overruns %lu",
               s_present ? "inmp441 (signal)" : "none (no signal)", s_running ? "running" : (s_off ? "off (asleep)" : "FAILED"),
               s_mode == MicMode::Off ? "off" : s_mode == MicMode::Level ? "level" : "stream", s_gain_db,
               (unsigned long)s_overruns);
}
