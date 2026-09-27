#!/usr/bin/env bash
# Build libvx_jni.so for THIS machine (x86_64 Linux, host g++ + the JDK's jni.h) from the same sources the app's NDK
# build uses: app/src/main/cpp/vx_jni.cpp + firmware/extract/src. The JVM unit test PhoneMicTest loads it
# (system property vox.vx_jni.path, set by app/build.gradle.kts) and checks every extractor/vectors case.
#   tools/build_host_jni.sh [out_dir]      default: app/build/host-jni
# Needs g++ and JAVA_HOME (both in the ./dev shell).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
src="$android/../firmware/extract/src"
out="${1:-$android/app/build/host-jni}"
: "${JAVA_HOME:?JAVA_HOME is not set (run inside ./dev)}"
mkdir -p "$out"
# The flags of the NDK build (app/src/main/cpp/CMakeLists.txt): -O2, no FMA contraction.
g++ -O2 -std=c++17 -ffp-contract=off -fPIC -shared -fno-exceptions -fno-rtti -fvisibility=hidden \
  -Wall -Wno-unused-parameter -I"$src" -I"$JAVA_HOME/include" -I"$JAVA_HOME/include/linux" \
  -o "$out/libvx_jni.so" "$android/app/src/main/cpp/vx_jni.cpp" "$src"/*.cpp -lm
echo "built $out/libvx_jni.so"
