# nix: the pinned Android toolchain

A nix flake for everything needed to build the app and run the emulator: the Android SDK, JDK 17, Gradle, Python 3 and
Flutter (for the `../../ui` screens module, and its Linux desktop build).
Nothing is installed system-wide. Android SDK licences are accepted only through nixpkgs' `android_sdk.accept_license`.
All mutable state (Gradle home, AVD, adb keys, temp files) goes to `android/.state/`, never to `~/.android` or `~/.gradle`.

| File | What it does |
|---|---|
| `flake.nix` | Imports nixpkgs (with `allowUnfree` and the SDK licence) and exposes the dev shell for x86_64-linux. |
| `flake.lock` | Pins the nixpkgs revision. |
| `sdk.nix` | The Android SDK from `androidenv`, with every version in one place: platform 35 (the app, the emulator), platform 36 (Flutter 3.47 compiles its embedding against it), build-tools 35.0.0, NDK 28.2.13676358 (the Flutter Gradle plugin requires an NDK, and AGP uses it to strip `libflutter.so`), the emulator, and the `android-35;default;x86_64` system image (AOSP, no Google apps). `VOX_ANDROID_NDK` passes the NDK version to `app/build.gradle.kts`. |
| `shell.nix` | The dev shell: SDK, JDK 17, Gradle, Python 3, jq, curl, unzip, and nixpkgs' wrapped `flutter` (3.47.4, Dart 3.13.3; it brings its own clang, cmake, ninja, pkg-config and GTK 3 for `flutter build linux`). Its hook points every tool at `android/.state/`, writes `local.properties`, and adds wrappers for `adb`, `gradle`, `flutter` and `dart` so none of them writes to the real home directory. It also turns Flutter and Dart analytics off. The `gradle` wrapper passes three extra kinds of argument (next section). |

## Commands

Run these from `android/`. `../dev` uses a `path:` flake reference, so nix does not depend on git tracking of this folder.

```sh
./dev                                  # interactive shell with adb, emulator, gradle, python3
./dev gradle assembleDebug             # run one command in the shell
nix flake metadata path:$PWD/nix       # show the pinned nixpkgs revision
```

The first `./dev` builds the SDK from nixpkgs, which takes about 90 s; later runs use the nix store.

`./dev flutter doctor -v`: Flutter, the Linux toolchain and network resources pass. The Android toolchain
has no errors, but two warnings:
- **"Some Android licenses not accepted."** Only `android-sdk-license` is accepted, and it covers everything
  installed. The other six are for components this SDK does not contain: `android-googletv-license`,
  `android-googlexr-license`, `android-sdk-arm-dbt-license`, `android-sdk-preview-license`, `google-gdk-license` and
  `mips-android-sysimage-license`. Accepting them is the user's decision. If wanted, list them in `extraLicenses`
  in `sdk.nix`, which is androidenv's mechanism.
- **"Multiple adb binaries found."** This is expected: the second one is the `.state/bin/adb` wrapper that keeps adb's
  keys out of the home directory.

Chrome (web) is not installed and not needed.

### Why the gradle wrapper passes extra arguments

nixpkgs' Flutter keeps the Flutter Gradle plugin in the read-only store. Its `settings.gradle` therefore builds the
plugin in `$HOME/.cache/flutter/nix-flutter-tools-gradle/<rev>` (here under `.state/home`), and it expects the matching
`--project-cache-dir` and `-Pkotlin.project.persistent.dir`. Without them, the plugin build writes into the store and
**Gradle exits 1 with no output at all**. The wrapper also passes `-Pflutter.androidSdkRoot` and
`-Pflutter.installedNdkVersions`. Otherwise the plugin tries to install the NDK into the read-only SDK.

Flutter 3.47.4 warns during the build that support for Gradle 8.14.4 and AGP 8.13.2 "will soon be dropped" (it wants
Gradle 9.1 and AGP 9.0.1). The build works. Moving Gradle and AGP is a separate change.
