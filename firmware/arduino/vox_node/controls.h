// The one button (PIN_BTN to GND, internal pull-up): debounce, press series and holds (PROTOCOL.md "The button").
//   series   presses shorter than BTN_HOLD_STOP_MS, each starting within BTN_SERIES_GAP_MS of the previous release.
//            A series ends BTN_SERIES_GAP_MS after its last release; then on_btn_series(n) runs (so a single click
//            acts only after the gap). A press that becomes a hold discards the series it was part of.
//   holds    on_btn_hold_stop() fires while still held at BTN_HOLD_STOP_MS, on_btn_hold_pair() at BTN_HOLD_PAIR_MS,
//            and on_btn_hold_released() on release.
// What each one does (awake / asleep) is in power.cpp.
// Held at power-on: that press is ignored and the test-sound trigger is turned on (2 presses = next canned sound).
// The serial console can press the button too (`btn click`, `btn clicks N`, `btn hold MS`): those presses are
// OR-ed with the real button and go through the same debounce and state machine.
#pragma once
#include <Arduino.h>

void controls_begin();        // also detects "button held at power-on"
void controls_poll(uint32_t now);
bool controls_down();         // debounced level (real or simulated)
bool controls_raw();          // the real button's level right now (true = pressed)
bool controls_idle();         // not pressed, no series pending, no simulated presses queued
const char *controls_state(); // one line for `buttons`

// Simulated presses (serial console). false if a previous simulation is still running.
bool controls_sim_clicks(int n);
bool controls_sim_hold(uint32_t ms);

// Events, implemented in power.cpp. Called from controls_poll().
void on_btn_series(int presses);
void on_btn_hold_stop();
void on_btn_hold_pair();
void on_btn_hold_released(uint32_t held_ms);
