plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Deterministic test target for the emulator suite. Framework views only.
android {
    namespace = "ai.vox.fixture"
    compileSdk = 35
    defaultConfig {
        applicationId = "ai.vox.fixture"
        minSdk = 30
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    lint { abortOnError = false; checkReleaseBuilds = false }
}

kotlin { jvmToolchain(17) }
