# Android client — first native milestone

A Kotlin/Jetpack Compose app using MVVM: Compose renders immutable state, AppViewModel coordinates actions, and repositories handle native account requests and phone location. Map rendering stays in provider-specific UI adapters. There is no WebView.

## What works in this milestone

- HTTPS server entry and native bearer-token sign-in against the existing server.
- Password show/hide, visible request errors, loading state, and sign-out.
- Setup checklist with account email-verification status and a link to the server website.
- Opt-in map loading and one-time, permission-gated phone location shown locally.
- OpenStreetMap through MapLibre by default; Google Maps Android SDK when a build key is configured.

This is a **local map preview**, not encrypted household sharing yet. Android device-key generation/storage, signed enrollment, roster verification, ciphertext upload/decryption, household markers, Room/offline queue, background tracking and FCM remain next milestones. No location is uploaded to the Family-Stalker server by this build. Loading or centering the map reveals the viewed region to its map provider. Current location is only retained in ViewModel memory and clears on sign-out/process exit.

## Build and install

Requires Android Studio with JDK 17, Android SDK platform 36 and Build Tools 35.0.0. Open **apps/android** as the Android Studio project. It includes the Gradle 8.13 wrapper with its distribution checksum.

Copy `.env.example` to `.env` inside **apps/android**. This is separate from Docker's deployment `.env`:

```dotenv
STALKER_SERVER_URL=https://your-server.example
STALKER_GOOGLE_MAPS_ANDROID_API_KEY=
```

The server address is optional; enter it on the sign-in screen instead. Only the chosen address is saved in app preferences. Passwords and the 12-hour account bearer remain in memory; a fresh process requires sign-in. Sign-out clears local state even when the server is unavailable; an unrevoked server session expires normally.

Build the default map app:

```bash
./gradlew :app:assembleDebug :app:testOsmDebugUnitTest :app:lintOsmDebug
```

On Windows use `gradlew.bat`. The APK is `app/build/outputs/apk/osm/debug/app-osm-debug.apk`. Install through Android Studio or `adb install -r app/build/outputs/apk/osm/debug/app-osm-debug.apk`. Minimum Android version: 8.0 (API 26). Debug installs require approval for the installing source. Release signing and Play Store distribution are separate work.

GitHub's **Android** workflow builds both provider selections and publishes an installable **family-stalker-android-debug** artifact for the OpenStreetMap build. The Google CI key is synthetic and cannot display real Google maps.

## Optional Google Maps

Set `STALKER_GOOGLE_MAPS_ANDROID_API_KEY` in this project's `.env` to a key with **Maps SDK for Android** enabled. Restrict it to package `eco.roberts.familystalker` and the SHA-1 of the certificate signing your APK. Get local debug certificate fingerprints with:

```bash
./gradlew :app:signingReport
```

A CI debug APK uses a different signing certificate from a local Android Studio debug APK. Register the matching certificate, or use a stable release signing identity later. This Android key is separate from the browser key and its website restrictions. It is embedded in the manifest, so Google restrictions matter; never commit a populated `.env`.

For a configured Google build, use `:app:testGoogleDebugUnitTest :app:lintGoogleDebug` for its checks. Its APK is `app/build/outputs/apk/google/debug/app-google-debug.apk`.

A blank/absent key compiles only the MapLibre adapter and dependency. A nonempty key compiles only the Google adapter and dependency. Environment variables override `.env` values (CI uses this). Provider/key changes require a clean rebuild (`./gradlew clean :app:assembleDebug`) and reinstalling the APK; editing Docker's `.env` does not change an installed Android map SDK. An invalid Google key may produce a blank map; the UI reports a load timeout. Remove the key and rebuild to return to OpenStreetMap.

OpenStreetMap attribution remains visible. Requests use an app-specific User-Agent and HTTP cache, and no bulk download/prefetch feature is provided. Public tiles are a best-effort service under the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

## Architecture and next implementation

Compose observes the ViewModel’s StateFlow and sends user actions to it. The ViewModel calls account/location repositories. MapSurface renders through the Google or MapLibre adapter selected at build time.

The first release intentionally avoids adding unused Room/Koin/WorkManager dependencies. Add platform-protected device secrets and protocol interoperability tests before enabling publication. Room should then hold encrypted records and an encrypted offline upload queue. Background location needs an explicit opt-in foreground service, ongoing notification and pause control; WorkManager handles upload retry rather than continuous GPS collection.

[Server protocol](../../docs/server-protocol.md) defines the separate account/device credentials, canonical signatures, signed roster chain, per-recipient sealed boxes, retention and revocation. Preserve that protocol; never introduce a plaintext upload fallback.

## Acceptance on an Android phone

1. Install the OpenStreetMap debug build. Enter your exact public HTTPS server origin.
2. Sign in with an existing invited account; verify a wrong password/rate limit has visible feedback.
3. Confirm the Setup/Map tabs show which is selected and Android Back returns to Setup.
4. Verify there are no map requests before **Load map**.
5. Select **Show my phone once**; test approximate location, precise location and denial.
6. Background/rotate/reopen the app; check map lifecycle, retained screen state and sign-in behavior.
7. Check server requests contain no GPS upload. Sign out and ensure the location disappears.
8. For a Google build, register the correct signing certificate and repeat rendering/location checks.

Unit tests cover HTTPS origin validation, native authentication headers/body, logout, HTTP errors and redirect refusal, plus ViewModel permission/sign-in/local-location state. Builds and these tests do not establish device GPS, rendering, battery or locked-phone behavior.
