plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "studio.camembertcheese.oracle.collector"
    compileSdk = 36

    defaultConfig {
        applicationId = "studio.camembertcheese.oracle.collector"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // 본인 기기 사이드로드 — 디버그 키로 서명(릴리스 키 추후)
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // 순수 플랫폼만 — 외부 의존성 없음(HttpURLConnection + org.json). 빌드 단순·안정.
}
