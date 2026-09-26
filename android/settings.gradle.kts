pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    // PREFER_SETTINGS, not FAIL_ON_PROJECT_REPOS: the Flutter Gradle plugin adds repositories to the :flutter project.
    // These settings repositories win.
    repositoriesMode.set(RepositoriesMode.PREFER_SETTINGS)
    repositories {
        google()
        mavenCentral()
        // The Flutter engine and embedding artifacts (io.flutter:*) for the ../ui module.
        maven("https://storage.googleapis.com/download.flutter.io")
    }
}
rootProject.name = "vox-android"
include(":app", ":fixture")

// The Flutter module ../ui, built from source (add-to-app): this adds the :flutter project. Its .android/ directory
// is generated (and git-ignored): `flutter pub get` in ../ui creates it; suite/run.sh build runs that first.
val flutterInclude = file("../ui/.android/include_flutter.groovy")
require(flutterInclude.exists()) { "$flutterInclude is missing: run `./dev bash -c 'cd ../ui && flutter pub get'` (suite/run.sh build does it)" }
apply(from = flutterInclude)
