# libvx_jni.so: the C++ extractor port (firmware/extract/src, compiled from its own path, not copied) plus the JNI
# wrapper. Built by AGP (app/build.gradle.kts externalNativeBuild) for arm64-v8a and x86_64.
cmake_minimum_required(VERSION 3.18)
project(vx_jni CXX)

set(VX_SRC_DIR ${CMAKE_CURRENT_LIST_DIR}/../../../../../firmware/extract/src)
get_filename_component(VX_SRC_DIR ${VX_SRC_DIR} ABSOLUTE)
if(NOT EXISTS ${VX_SRC_DIR}/vox_extract.h)
  message(FATAL_ERROR "extractor sources not found at ${VX_SRC_DIR}")
endif()
file(GLOB VX_SOURCES CONFIGURE_DEPENDS ${VX_SRC_DIR}/*.cpp)

add_library(vx_jni SHARED vx_jni.cpp ${VX_SOURCES})
target_include_directories(vx_jni PRIVATE ${VX_SRC_DIR})
set_target_properties(vx_jni PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
target_compile_options(vx_jni PRIVATE
  # Optimised in every build type (AGP's debug variant would otherwise pass -O0): the extractor is the hot path.
  -O2
  # No fused multiply-add: clang's default (-ffp-contract=on) fuses a*b+c inside expressions, and then float32 results
  # differ from the host build that tools/check_extract.sh checks against Python (vx_impl.h does this for GCC only).
  -ffp-contract=off
  -fno-exceptions -fno-rtti -fvisibility=hidden -ffunction-sections -fdata-sections
  -Wall -Wno-unused-parameter)
# Only the JNI entry points are exported; drop unused sections.
target_link_options(vx_jni PRIVATE -Wl,--gc-sections -Wl,--exclude-libs,ALL)
target_link_libraries(vx_jni PRIVATE m)
