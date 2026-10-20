plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release signing: Uses the existing keystore in ~/.gradle/gradle.properties or environment
fun prop(k: String) = project.findProperty(k)?.toString()
val canSign = prop("SHEMA_STORE_FILE")?.let { file(it).exists() } == true

android {
    namespace = "com.shema.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.shema.listener"
        minSdk = 29
        targetSdk = 36
        versionCode = 113
        versionName = "1.0.16"

        // NDK ABI filters: arm64-v8a covers virtually 100% of modern Android devices
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }

    signingConfigs {
        if (canSign) {
            create("release") {
                storeFile = file(prop("SHEMA_STORE_FILE")!!)
                storePassword = prop("SHEMA_STORE_PASSWORD")
                keyAlias = prop("SHEMA_KEY_ALIAS")
                keyPassword = prop("SHEMA_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (canSign) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        debug {
            applicationIdSuffix = ".debug"
            isDebuggable = true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    bundle {
        language { enableSplit = false }
        density { enableSplit = true }
        abi { enableSplit = true }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.20.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    implementation("com.android.billingclient:billing-ktx:8.0.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
}
