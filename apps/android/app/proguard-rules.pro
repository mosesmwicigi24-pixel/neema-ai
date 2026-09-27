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
# OkHttp
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
# Crash reports: keep file names + line numbers so a trace can be retraced with
# the release's mapping.txt (published next to the APKs).
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
