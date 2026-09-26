plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ai.vox.companion"
    compileSdk = 35
    // The NDK in nix/sdk.nix (versions.ndk). AGP only uses it to strip the Flutter engine's .so files; without it
    // they are packaged with full debug info (about 400 MB per ABI).
    ndkVersion = System.getenv("VOX_ANDROID_NDK") ?: "28.2.13676358"
    defaultConfig {
        applicationId = "ai.vox.companion"
        minSdk = 30
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }
    buildTypes {
        // Debug builds are debuggable: the adb-only debug feature source (see PROTOCOL.md) is enabled there only.
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        buildConfig = true
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    // The Flutter UI (../ui), from source. It brings the Flutter embedding and, with it, a few AndroidX libraries;
    // VOX's own code still uses framework APIs + Kotlin stdlib only.
    implementation(project(":flutter"))
    testImplementation("junit:junit:4.13.2")
    // org.json is part of android.jar but stubbed in JVM unit tests; this supplies a real implementation there.
    testImplementation("org.json:json:20250517")
}
