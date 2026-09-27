// Console output. While `mic stream` is running, the USB serial port carries binary audio frames, so every text
// line is wrapped in a text frame instead (tools/pico_stream.py prints those).
#pragma once
#include <Arduino.h>

void out_printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void out_line(const char *s);

// Output a terminal did not take: with the port open but nobody reading, the USB write gives up after about 1 s and
// then drops at once (arduino-pico SerialUSB), so the device never stalls on it. Counted only while a terminal is
// open (DTR set); with no terminal nothing is written or counted.
uint32_t out_dropped_bytes();
uint32_t out_dropped_lines();

// Binary framing used by `mic stream`: "VX" type seq(u16 LE) len(u16 LE) payload crc16(u16 LE)
// crc16 = CRC-16/CCITT-FALSE over type..payload. Types: 'A' = PCM16LE mono 16 kHz, 'T' = a text line.
void out_frame(uint8_t type, const uint8_t *payload, uint16_t len);
extern volatile bool g_streaming;
