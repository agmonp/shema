# ProGuard & R8 rules for Shema Commercial Edition

# ONNX Runtime JNI preservation
-keep class ai.onnxruntime.** { *; }
-dontwarn ai.onnxruntime.**

# Google Play Billing
-keep class com.android.billingclient.api.** { *; }

# ZXing QR Scanner
-keep class com.google.zxing.** { *; }
-keep class com.journeyapps.barcodescanner.** { *; }

# Kotlin coroutines
-keepnames class kotlinx.coroutines.** { *; }

# Preserve native methods
-keepclasseswithmembernames class * {
    native <methods>;
}

# AndroidX
-keep class androidx.core.app.NotificationCompat** { *; }
