// Host stand-in for the few Arduino / arduino-pico pieces ext.cpp uses, so tools/check_extract.sh can run the
// sketch's core-0/core-1 glue with two host threads (extract/host/ext_sim.cpp). Not a general Arduino emulation.
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sched.h>
#include <time.h>

#ifndef F_CPU
#define F_CPU 150000000L
#endif

static inline uint64_t host_ns() {
    timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000000000ull + t.tv_nsec;
}
static inline uint32_t millis() { return (uint32_t)(host_ns() / 1000000); }
static inline uint32_t time_us_32() { return (uint32_t)(host_ns() / 1000); }
static inline void __wfe() { sched_yield(); }
static inline void __sev() {}
struct HostRp2040 {
    uint32_t getCycleCount() { return (uint32_t)(host_ns() * 3 / 20); }   // ns -> "150 MHz cycles"
};
extern HostRp2040 rp2040;
