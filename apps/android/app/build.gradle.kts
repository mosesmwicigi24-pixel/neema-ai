plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    // JVM screenshot tests of the UI (./gradlew :app:recordPaparazziDebug) — no device needed.
    alias(libs.plugins.paparazzi)
}

android {
    namespace = "ke.co.bethanyhouse.neema"
    compileSdk = 36

    defaultConfig {
        applicationId = "ke.co.bethanyhouse.neema"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
        // The same origin the web dashboard is served from; /api and /ws hang off it.
        buildConfigField("String", "NEEMA_BASE_URL", "\"https://neema.bethanyhouse.co.ke\"")
    }

    signingConfigs {
        // One development key for every build (committed; not a secret), so a
        // new APK always installs over the last. CI swaps in the production key
        // from repository secrets via NEEMA_KEYSTORE et al. — see android.yml.
        create("neema") {
            val prod = System.getenv("NEEMA_KEYSTORE")?.takeIf { it.isNotBlank() && file(it).exists() }
            if (prod != null) {
                storeFile = file(prod)
                storePassword = System.getenv("NEEMA_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("NEEMA_KEY_ALIAS")
                keyPassword = System.getenv("NEEMA_KEY_PASSWORD")
            } else {
                storeFile = rootProject.file("keystore/dev.jks")
                storePassword = "neema-dev"
                keyAlias = "neema-dev"
                keyPassword = "neema-dev"
            }
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("neema")
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("neema")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    // WebRTC ships native code for four CPU families; one APK per family keeps
    // each download ~4x smaller. A universal APK is built too, for sideloading.
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
            isUniversalApk = true
        }
    }
    testOptions {
        unitTests.all {
            // Screenshot and date tests are deterministic: a pinned "now" (it
            // still ticks) and a fixed zone, whatever day or machine runs them.
            it.systemProperty("neema.clock.pin", "2026-09-25T09:00:00Z")
            it.systemProperty("user.timezone", "Africa/Nairobi")
        }
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.security.crypto)
    implementation(libs.androidx.splashscreen)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.compose.material3.adaptive)
    implementation(libs.compose.material.icons)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)

    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.coil.compose)
    implementation(libs.coil.video)
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.ui)
    implementation(libs.webrtc)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
}

// ── Release gate: what R8 must not strip ─────────────────────────────────────
// kotlinx.serialization finds a model's serializer through its generated
// `$$serializer` class, and WebRTC's native code finds org.webrtc classes BY
// NAME over JNI. Minification that drops or renames either still builds and
// installs, then fails on the first API response / the first call. After R8
// runs, this reads its mapping and fails the release build if a kept
// @Serializable class lost its serializer or an org.webrtc JNI class was
// removed or renamed. (CI's assembleRelease runs it.)
val checkReleaseKeeps by tasks.registering {
    group = "verification"
    description = "Fails if R8 dropped a kotlinx.serialization serializer or renamed org.webrtc JNI classes."
    dependsOn("minifyReleaseWithR8")
    val mapping = layout.buildDirectory.file("outputs/mapping/release/mapping.txt")
    val sources = fileTree("src/main/java") { include("**/*.kt") }
    inputs.files(sources)
    inputs.file(mapping)
    doLast {
        val map = mapping.get().asFile.readLines()
        // "original.Name -> obfuscated:" — the classes R8 kept, by original name.
        val kept = map.filter { !it.startsWith(" ") && !it.startsWith("#") && it.endsWith(":") }
            .associate { line -> line.substringBefore(" -> ") to line.substringAfter(" -> ").removeSuffix(":") }
        // Classes with a generated serializer: @Serializable (no `with =`) on a
        // plain or data class — not an enum, sealed/abstract class or object.
        val decl = Regex("""@Serializable\s+(?:@[^\n]*\s+)*(?:(?:private|internal|public|data|open)\s+)*class\s+(\w+)""")
        val models = sources.files.flatMap { f -> decl.findAll(f.readText()).map { it.groupValues[1] }.toList() }.toSet()
        val problems = mutableListOf<String>()
        var checked = 0
        for (name in models) {
            val classes = kept.keys.filter { it.startsWith("ke.co.bethanyhouse.neema.") && (it.endsWith(".$name") || it.endsWith("$$name")) }
            for (c in classes) {
                checked++
                if ("$c\$\$serializer" !in kept) problems += "$c is kept but its \$\$serializer was removed"
            }
        }
        if (checked < 20) problems += "only $checked @Serializable models found in the mapping — did this check break?"
        val jni = listOf(
            "org.webrtc.PeerConnectionFactory", "org.webrtc.PeerConnection", "org.webrtc.NativeLibrary",
            "org.webrtc.JniCommon", "org.webrtc.WebRtcClassLoader", "org.webrtc.SessionDescription",
            "org.webrtc.IceCandidate", "org.webrtc.MediaStreamTrack", "org.webrtc.audio.WebRtcAudioRecord",
            "org.webrtc.audio.WebRtcAudioTrack",
        )
        for (c in jni) when (val to = kept[c]) {
            null -> problems += "$c was removed (native code looks it up by name)"
            c -> Unit
            else -> problems += "$c was renamed to $to (native code looks it up by name)"
        }
        if (problems.isNotEmpty()) throw GradleException("R8 stripped what the app needs at run time:\n  " + problems.joinToString("\n  "))
        logger.lifecycle("checkReleaseKeeps: $checked @Serializable models keep their serializers; ${jni.size} WebRTC JNI classes keep their names.")
    }
}
tasks.matching { it.name == "assembleRelease" }.configureEach { dependsOn(checkReleaseKeeps) }
