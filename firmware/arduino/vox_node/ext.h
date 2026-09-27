// On-device feature extractor (firmware/extract, the C++ port of extractor/vox_extract) running on core 1.
//
//   core 0  mic_poll -> ext_mic_push(): the mic's samples, quantised to int16 exactly like `mic stream` (so a
//           tools/pico_stream.py WAV replays the device's input), into a lock-free single-producer ring
//   core 1  setup1/loop1: ring -> vx_extractor_push -> finished sounds into a small event queue
//   core 0  ext_poll(): event queue -> send_sound() with the fp1 `features` (PROTOCOL.md), or the serial log;
//           the hold messages (vx_hold.h: hold start / pitch / end) share the queue, in order, -> send_hold().
//           Sound ids go on across wakes (1, 2, ... per boot)
//
// Serial: `ext on|off`, `ext stats`, `ext features on|off`, `ext feed <n> [16000|48000]` (n int16 LE samples
// follow as raw bytes; the events come back as `ext event {json}` lines and the hold messages as `ext hold {json}`; tools/ext_feed.py drives it).
// Sleep stops it with the mic (mic_end), a wake restarts it from a clean state (mic_begin).
#pragma once
#include <Arduino.h>

void ext_begin();                               // core 0 setup(), before mic_begin()
void ext_poll(uint32_t now);                    // core 0 loop(): deliver finished sounds
void ext_mic_push(const int16_t *s, int n);     // core 0, from mic_poll
void ext_stream_start();                        // mic_begin: a new stream (state cleared, clock re-based)
void ext_stream_stop();                         // mic_end: sleep
void ext_set_enabled(bool on);
bool ext_enabled();
void ext_set_features(bool on);
bool ext_features();
const char *ext_fp_version();                   // "fp1" while features are sent, else NULL (INFO)
void ext_stats(bool reset);                     // prints the stats lines; reset clears the counters after
void ext_status();                              // one-line summary (for `status`)

// feed mode (serial test): while ext_feeding() the console reads at most ext_feed_room() bytes and hands them over
bool ext_feed_begin(uint32_t n_samples, int rate);
bool ext_feeding();
size_t ext_feed_room();                         // bytes ext_feed_bytes takes now (0: ring full or not ready yet)
void ext_feed_bytes(const uint8_t *p, size_t n); // n <= ext_feed_room()
