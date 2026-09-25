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
