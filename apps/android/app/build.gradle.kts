import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val environment = Properties().apply {
    rootProject.file(".env").takeIf { it.exists() }?.reader()?.use { load(it) }
}
fun setting(name: String): String = (providers.environmentVariable(name).orNull
    ?: environment.getProperty(name, "")).trim().removeSurrounding("\"").removeSurrounding("'")
fun literal(value: String) = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
val googleKey = setting("STALKER_GOOGLE_MAPS_ANDROID_API_KEY")
val googleEnabled = googleKey.isNotBlank()

android {
    namespace = "eco.roberts.familystalker"
    compileSdk = 36
    defaultConfig {
        applicationId = "eco.roberts.familystalker"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        manifestPlaceholders["googleMapsKey"] = googleKey
        buildConfigField("String", "DEFAULT_SERVER_URL", literal(setting("STALKER_SERVER_URL")))
        buildConfigField("String", "MAP_PROVIDER", literal(if (googleEnabled) "google" else "openstreetmap"))
    }
    sourceSets["main"].java.srcDir(if (googleEnabled) "src/google/kotlin" else "src/osm/kotlin")
    buildFeatures { compose = true; buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.11.01"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    if (googleEnabled) implementation("com.google.android.gms:play-services-maps:19.2.0")
    else implementation("org.maplibre.gl:android-sdk:11.13.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
    testImplementation("org.json:json:20240303")
}
