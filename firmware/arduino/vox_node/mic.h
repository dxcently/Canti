// INMP441 I2S microphone: 16 kHz, 32-bit slots (64 BCLK per frame), mono from the LEFT slot (L/R pin to GND).
// Capture runs all the time; there is no on-device extractor yet.
//   presence   "inmp441" once the left slot carries a changing signal, "none" if it is all zeros or constant
//              (GP20 has a pull-down, so an unplugged mic reads as exact zeros). Reported in INFO.
//   mic level  ~10x/s: RMS, peak and DC in dBFS (of the mic's 24-bit full scale), plus wiring diagnostics
//   mic stream raw PCM16 LE mono 16 kHz over USB serial in 'A' frames (out.h); tools/pico_stream.py -> WAV
#pragma once
#include <Arduino.h>

enum class MicMode : uint8_t { Off, Level, Stream };

void mic_begin();                 // starts I2S and runs a ~0.3 s presence check (also after mic_end)
void mic_end();                   // sleep: stops I2S (the mic clock stops)
void mic_poll(uint32_t now);
void mic_set_mode(MicMode m);
MicMode mic_mode();
bool mic_present();
void mic_set_gain_db(int db);     // stream gain: 0, 6, 12, 18 or 24 dB above the top 16 of the 24 bits
int mic_gain_db();
void mic_status();                // one-line summary
