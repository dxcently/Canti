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
        // [phone-mic] libvx_jni.so (the extractor for the phone/USB mic): 64-bit ARM phones and the x86_64 emulator.
        // (Not ndk.abiFilters: that would also drop the Flutter engine's other ABIs.)
        externalNativeBuild { cmake { abiFilters += listOf("arm64-v8a", "x86_64") } }
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
    // [phone-mic] The NDK build of firmware/extract/src + the JNI glue (src/main/cpp). cmake/ninja come from the dev shell.
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            System.getenv("VOX_CMAKE_VERSION")?.let { version = it }
        }
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

// [phone-mic] The JVM tests load a host (x86_64 Linux) build of the same JNI code (PhoneMicTest: parity with
// extractor/vectors); built with the dev shell's g++ by tools/build_host_jni.sh.
val hostJni = tasks.register<Exec>("hostJni") {
    val out = layout.buildDirectory.file("host-jni/libvx_jni.so")
    inputs.files(fileTree("src/main/cpp"), fileTree("../../firmware/extract/src"), file("../tools/build_host_jni.sh"))
    outputs.file(out)
    commandLine(file("../tools/build_host_jni.sh").absolutePath, layout.buildDirectory.dir("host-jni").get().asFile.absolutePath)
}
tasks.withType<Test>().configureEach {
    dependsOn(hostJni)
    systemProperty("vox.vx_jni.path", layout.buildDirectory.file("host-jni/libvx_jni.so").get().asFile.absolutePath)
    systemProperty("vox.vectors", file("../../extractor/vectors").absolutePath)
}
