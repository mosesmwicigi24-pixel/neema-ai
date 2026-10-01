# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class kotlinx.serialization.json.** { kotlinx.serialization.KSerializer serializer(...); }
-keep,includedescriptorclasses class ke.co.bethanyhouse.neema.**$$serializer { *; }
-keepclassmembers class ke.co.bethanyhouse.neema.** { *** Companion; }
-keepclasseswithmembers class ke.co.bethanyhouse.neema.** { kotlinx.serialization.KSerializer serializer(...); }
# WebRTC (JNI)
-keep class org.webrtc.** { *; }
-dontwarn org.webrtc.**
# WebRTC's JNI_OnLoad finds org.jni_zero.JniInit BY NAME and stops the process
# (SIGTRAP, "Failed to find class") when it is missing. No Java code calls it,
# and the AAR ships no consumer rules, so R8 removed it: every release build
# crashed natively the first time a call touched WebRTC (owner, 1 Oct 2026).
-keep class org.jni_zero.** { *; }
-dontwarn org.jni_zero.**
# OkHttp
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
# Crash reports: keep file names + line numbers so a trace can be retraced with
# the release's mapping.txt (published next to the APKs).
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
