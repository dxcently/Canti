# The Android SDK used for building and for the emulator. Everything version-sensitive is here.
{ pkgs }:
let
  versions = {
    platform = "35";        # compileSdk / targetSdk, and the emulator image's API level
    buildTools = "35.0.0";
    image = "default";      # AOSP image: no Google apps, no login prompts
    abi = "x86_64";         # KVM-accelerated on this x86_64 box
    flutterPlatform = "36"; # Flutter 3.47 compiles its embedding and module (../ui) against android-36
    # Flutter 3.47's NDK (FlutterExtension.ndkVersion). The Flutter Gradle plugin insists on it being installed (it
    # would otherwise try to download it into this read-only SDK); AGP uses it to strip the release .so files.
    ndk = "28.2.13676358";
  };
  composition = pkgs.androidenv.composeAndroidPackages {
    platformVersions = [ versions.platform versions.flutterPlatform ];
    buildToolsVersions = [ versions.buildTools ];
    includeEmulator = true;
    includeSystemImages = true;
    systemImageTypes = [ versions.image ];
    abiVersions = [ versions.abi ];
    includeNDK = true;
    ndkVersions = [ versions.ndk ];
    includeCmake = false;
    includeSources = false;
  };
in {
  inherit versions composition;
  androidsdk = composition.androidsdk;
  sdkRoot = "${composition.androidsdk}/libexec/android-sdk";
}
