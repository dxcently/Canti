// Canned test sounds (test_sounds.h, generated from the Python extractor) sent as real feature messages.
// A single sound is sent at once, as a sound that has just ended: t_end = now, t_start = now - its duration.
// A sequence sends each sound in its own message at the moment that sound ends on the device clock,
// t_start(next) = t_end(previous) + gap, exactly as the live device will.
#pragma once
#include <Arduino.h>

bool player_send(const char *name);                          // a single sound (or a sequence name)
bool player_seq(const char *const *names, int n, int gap_ms); // gap_ms < 0: default 250
bool player_busy();
void player_cancel();
void player_poll(uint32_t now);
void player_next_in_cycle();                                  // button trigger: rise, fall, ..., riserise, rise...
void player_list();
