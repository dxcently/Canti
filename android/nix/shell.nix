# Dev shell: SDK + emulator + JDK 17 + Gradle + Python (suite) + Flutter (the ../ui module, and its Linux desktop build).
# All mutable state lives under the android/ directory (.state/), never in ~/.gradle, ~/.android, ~/.flutter,
# ~/.pub-cache, ~/.config or /tmp.
{ pkgs, sdk }:
let
  jdk = pkgs.jdk17;
  gradle = pkgs.gradle.override { java = jdk; };
in
pkgs.mkShell {
  name = "vox-android";
  # pkgs.flutter is nixpkgs' wrapped Flutter SDK: it carries its own clang, cmake, ninja, pkg-config and the GTK 3
  # libraries for `flutter build linux`, and the engine artifacts for Android and Linux.
  # cmake + ninja: the NDK build of the phone-mic extractor (app/src/main/cpp; AGP finds them on PATH, at the
  # version in VOX_CMAKE_VERSION).
  packages = [ sdk.androidsdk jdk gradle pkgs.python3 pkgs.jq pkgs.curl pkgs.unzip pkgs.flutter pkgs.cmake pkgs.ninja ];

  JAVA_HOME = jdk.home;
  ANDROID_HOME = sdk.sdkRoot;
  ANDROID_SDK_ROOT = sdk.sdkRoot;
  VOX_ANDROID_API = sdk.versions.platform;
  VOX_ANDROID_BUILD_TOOLS = sdk.versions.buildTools;
  VOX_ANDROID_IMAGE = "system-images;android-${sdk.versions.platform};${sdk.versions.image};${sdk.versions.abi}";
  VOX_ANDROID_PLAY_IMAGE = "system-images;android-${sdk.versions.platform};${sdk.versions.playImage};${sdk.versions.abi}";
  VOX_ANDROID_NDK = sdk.versions.ndk;
  VOX_CMAKE_VERSION = pkgs.cmake.version;
  LANG = "C.UTF-8";

  shellHook = ''
    # VOX_ANDROID = the android/ project root (the directory holding settings.gradle.kts).
    if [ -z "''${VOX_ANDROID:-}" ]; then
      d="$PWD"; while [ "$d" != / ] && [ ! -f "$d/settings.gradle.kts" ]; do d="$(dirname "$d")"; done
      export VOX_ANDROID="$d"
    fi
    export VOX_STATE="$VOX_ANDROID/.state"
    mkdir -p "$VOX_STATE"/{gradle,android-user,avd,tmp}
    export GRADLE_USER_HOME="$VOX_STATE/gradle"
    export ANDROID_USER_HOME="$VOX_STATE/android-user"
    export ANDROID_EMULATOR_HOME="$VOX_STATE/android-user"
    export ANDROID_AVD_HOME="$VOX_STATE/avd"
    export TMPDIR="$VOX_STATE/tmp"
    # AGP's aapt2 from Maven is a generic-Linux binary that cannot run on NixOS; use the SDK's patched one.
    export GRADLE_OPTS="-Dorg.gradle.project.android.aapt2FromMavenOverride=$ANDROID_HOME/build-tools/${sdk.versions.buildTools}/aapt2"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
    # adb keeps its key in $HOME/.android and ignores ANDROID_USER_HOME: give it a HOME inside .state whose
    # .android is the emulator's user dir, so the keys match and nothing is written to the real home.
    mkdir -p "$VOX_STATE/home" "$VOX_STATE/bin"
    ln -sfn "$ANDROID_USER_HOME" "$VOX_STATE/home/.android"
    printf '#!/bin/sh\nHOME="%s" exec "%s" "$@"\n' "$VOX_STATE/home" "$ANDROID_HOME/platform-tools/adb" > "$VOX_STATE/bin/adb"
    chmod +x "$VOX_STATE/bin/adb"
    export PATH="$VOX_STATE/bin:$PATH"
    printf 'sdk.dir=%s\n' "$ANDROID_HOME" > "$VOX_ANDROID/local.properties"
    # AGP writes analytics.settings to <user.home>/.android whatever ANDROID_USER_HOME says; Java takes user.home from
    # passwd (not $HOME) and Gradle drops -Duser.home from org.gradle.jvmargs. So wrap gradle: JAVA_TOOL_OPTIONS is
    # inherited by the forked build daemon and the test workers. (-XX:-UsePerfData: no /tmp/hsperfdata files.)
    # Flutter and Dart keep their config, analytics consent and caches under $HOME and the XDG dirs, and the pub cache
    # under $PUB_CACHE: point all of them into .state. Gradle gets the same environment, because the Flutter Gradle
    # plugin runs `flutter assemble` for the ../ui module during the app build.
    mkdir -p "$VOX_STATE/home/.config" "$VOX_STATE/home/.cache" "$VOX_STATE/home/.local/share" "$VOX_STATE/pub-cache"
    homeenv="HOME=$VOX_STATE/home XDG_CONFIG_HOME=$VOX_STATE/home/.config XDG_CACHE_HOME=$VOX_STATE/home/.cache XDG_DATA_HOME=$VOX_STATE/home/.local/share PUB_CACHE=$VOX_STATE/pub-cache"
    # The Flutter Gradle plugin is an included build inside the read-only Flutter SDK. nixpkgs relocates its build to
    # $XDG_CACHE_HOME/flutter/nix-flutter-tools-gradle/<engine rev>, but only works when Gradle also gets the project
    # cache dir and Kotlin's persistent dir there (what nixpkgs' `flutter build` passes; without them Gradle exits 1
    # with no message). The flutter.* properties tell the plugin the NDK is installed, so it does not try to install
    # one into the read-only SDK.
    fcache="$VOX_STATE/home/.cache/flutter/nix-flutter-tools-gradle/$(head -c 10 ${pkgs.flutter}/bin/internal/engine.version)"
    gargs="--project-cache-dir=$fcache/cache -Pkotlin.project.persistent.dir=$fcache/kotlin -Pflutter.androidSdkRoot=$ANDROID_HOME -Pflutter.installedNdkVersions=${sdk.versions.ndk}"
    printf '#!/bin/sh\nexport %s\nJAVA_TOOL_OPTIONS="-Duser.home=%s -XX:-UsePerfData" exec "%s" %s "$@"\n' \
      "$homeenv" "$VOX_STATE/home" "${gradle}/bin/gradle" "$gargs" > "$VOX_STATE/bin/gradle"
    chmod +x "$VOX_STATE/bin/gradle"
    for t in flutter dart; do
      printf '#!/bin/sh\nexport %s\nexec "%s" "$@"\n' "$homeenv" "${pkgs.flutter}/bin/$t" > "$VOX_STATE/bin/$t"
      chmod +x "$VOX_STATE/bin/$t"
    done
    # No analytics, once per .state (the consent is stored in the redirected home).
    if [ ! -f "$VOX_STATE/home/.vox-flutter-analytics-off" ]; then
      "$VOX_STATE/bin/flutter" --disable-analytics >/dev/null 2>&1 || true
      "$VOX_STATE/bin/flutter" config --no-analytics --no-cli-animations >/dev/null 2>&1 || true
      "$VOX_STATE/bin/dart" --disable-analytics >/dev/null 2>&1 || true
      touch "$VOX_STATE/home/.vox-flutter-analytics-off"
    fi
  '';
}
