// Included first by every extractor .cpp (never by users of the library): build settings for the port.
// No fused multiply-add: the host exactness runs (tools/check_extract.sh, -ffp-contract=off) compute every a*b+c
// with two roundings; GCC for the M33 would otherwise fuse them (-ffp-contract=fast is its GNU default), and the
// device would round differently from the checked build.
// clang (the Android NDK build, android/app/src/main/cpp/CMakeLists.txt) ignores this GCC pragma and fuses by default
// (-ffp-contract=on): a clang build MUST pass -ffp-contract=off itself, or it drifts from the vectors.
#pragma once
#if defined(__GNUC__) && !defined(__clang__) && !defined(VX_ALLOW_FMA)
#pragma GCC optimize("fp-contract=off")
#endif
// arduino-pico builds sketches and libraries with -Os; the extractor is worth -O2 (about 7% fewer instructions per
// hop in extract/host/m33, for some KB of flash)
#if defined(__arm__) && defined(__GNUC__) && !defined(__clang__) && !defined(VX_KEEP_OPT)
#pragma GCC optimize("O2")
#endif
// VX_HOT: the per-hop functions run from RAM on the Pico (arduino-pico copies .time_critical* to RAM), so they do
// not compete with core 0 (BTstack, USB) for the 16 KB XIP flash cache. About 6 KB of RAM.
#if defined(ARDUINO_ARCH_RP2040) && !defined(VX_NO_RAMFUNC)
#define VX_HOT __attribute__((section(".time_critical.vox_extract")))
#else
#define VX_HOT
#endif
