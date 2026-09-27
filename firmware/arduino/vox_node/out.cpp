#include "out.h"
#include <stdarg.h>

volatile bool g_streaming = false;
static uint16_t s_frame_seq = 0;
static uint32_t s_drop_bytes = 0, s_drop_lines = 0;
static bool s_line_lost;

// A write the terminal did not take in full: count what was lost (the rest of that line is gone).
static void put(const uint8_t *p, size_t n) {
    size_t w = Serial.write(p, n);
    if (w < n) {
        s_drop_bytes += n - w;
        s_line_lost = true;
    }
}

static uint16_t crc16_update(uint16_t crc, const uint8_t *p, size_t n) {
    while (n--) {
        crc ^= (uint16_t)(*p++) << 8;
        for (int i = 0; i < 8; i++) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
    return crc;
}

void out_frame(uint8_t type, const uint8_t *payload, uint16_t len) {
    uint8_t hdr[7] = {'V', 'X', type, (uint8_t)(s_frame_seq & 0xff), (uint8_t)(s_frame_seq >> 8),
                      (uint8_t)(len & 0xff), (uint8_t)(len >> 8)};
    s_frame_seq++;
    uint16_t crc = crc16_update(0xFFFF, hdr + 2, 5);
    crc = crc16_update(crc, payload, len);
    uint8_t tail[2] = {(uint8_t)(crc & 0xff), (uint8_t)(crc >> 8)};
    if (!Serial) return;
    s_line_lost = false;
    put(hdr, sizeof(hdr));
    put(payload, len);
    put(tail, 2);
    if (s_line_lost) s_drop_lines++;
}

void out_line(const char *s) {
    if (g_streaming) {
        out_frame('T', (const uint8_t *)s, (uint16_t)strlen(s));
    } else {
        if (!Serial) return;
        s_line_lost = false;
        put((const uint8_t *)s, strlen(s));
        put((const uint8_t *)"\r\n", 2);
        if (s_line_lost) s_drop_lines++;
    }
}

uint32_t out_dropped_bytes() { return s_drop_bytes; }
uint32_t out_dropped_lines() { return s_drop_lines; }

void out_printf(const char *fmt, ...) {
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    out_line(buf);
}
