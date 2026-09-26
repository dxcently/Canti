#include "out.h"
#include <stdarg.h>

volatile bool g_streaming = false;
static uint16_t s_frame_seq = 0;

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
    Serial.write(hdr, sizeof(hdr));
    Serial.write(payload, len);
    Serial.write(tail, 2);
}

void out_line(const char *s) {
    if (g_streaming) {
        out_frame('T', (const uint8_t *)s, (uint16_t)strlen(s));
    } else {
        Serial.print(s);
        Serial.print("\r\n");
    }
}

void out_printf(const char *fmt, ...) {
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    out_line(buf);
}
