plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release signing: the keystore and its passwords live OUTSIDE the repository, in ~/.gradle/gradle.properties:
//   SHEMA_STORE_FILE=C:/Users/<you>/keys/shema-release.jks
//   SHEMA_STORE_PASSWORD=...   SHEMA_KEY_ALIAS=shema   SHEMA_KEY_PASSWORD=...
// Without them assembleRelease still builds, unsigned.
fun prop(k: String) = project.findProperty(k)?.toString()
val canSign = prop("SHEMA_STORE_FILE")?.let { file(it).exists() } == true

android {
    namespace = "app.shema.listener"
    compileSdk = 35
    defaultConfig {
        applicationId = "app.shema.listener"
        minSdk = 29
        targetSdk = 35
        versionCode = 100
        versionName = "1.0.0"
        ndk { abiFilters += "arm64-v8a" }          // almost every phone since 2017; onnxruntime for all ABIs makes the APK 80 MB
    }
    signingConfigs {
        if (canSign) create("release") {
            storeFile = file(prop("SHEMA_STORE_FILE")!!)
            storePassword = prop("SHEMA_STORE_PASSWORD")
            keyAlias = prop("SHEMA_KEY_ALIAS")
            keyPassword = prop("SHEMA_KEY_PASSWORD")
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            if (canSign) signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.20.0")   // Silero VAD on the phone
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")           // pairing QR, offline, no Google services
}
