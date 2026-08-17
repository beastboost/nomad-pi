# Nomad for Android

Nomad Android is a **native Kotlin + Jetpack Compose client** for a Nomad server. It is not a WebView, Trusted Web Activity, browser wrapper, or packaged PWA.

## Architecture

The Android device owns the UI and decoding. The Pi/Radxa remains the source of truth for libraries, profiles, debrid resolution, progress, private Photos and server state.

- Kotlin + Jetpack Compose
- AndroidX Media3 / ExoPlayer for direct progressive and HLS playback
- Runtime Android decoder detection is sent to Nomad's capability-driven playback planner
- DataStore keeps the server/session/profile locally
- Android DNS-SD (`NsdManager`) discovers Nomad's `_http._tcp` Avahi advertisement
- HTTP Range is used for direct media, music and private gallery media
- No extra transcoding is introduced by the Android app

## Implemented in 0.1

- LAN discovery plus manual `nomadpi.local`, `10.42.0.1`, IP and Tailscale addresses
- Native login using Nomad Bearer sessions
- Household profile switching including PIN-protected profiles
- Movies poster grid and native Media3 playback
- Shows / seasons / episodes and native playback
- Music direct playback through Nomad's dedicated byte-range music endpoint
- Universal search with cached/Pi-safe release ranking
- Universal Search actions: Play, Stream + Keep, Download
- Profile-private Photos grid
- Swipeable full-screen photo viewer
- Native playback for gallery videos
- Photo albums, album filtering, long-press multi-select, bulk move and bulk delete
- Server download queue, cancel, refresh and clear
- Native CBZ/CBR comic reader with saved page progress
- Native PDF renderer using Android `PdfRenderer`
- Server status screen

## Deliberate 0.1 boundaries

The first APK focuses on a reliable local client before adding phone-side complexity.

- EPUB/MOBI/AZW3 currently hand off to an Android handler rather than shipping a browser-shaped ebook engine inside the app.
- Phone-local/offline copies are not yet a separate Android download library; the Downloads screen manages Nomad's server-side queue.
- Music plays natively but a persistent Android `MediaSessionService`/notification is a follow-up, so background playback is not considered complete yet.
- Android photo upload/share-to-Nomad is a follow-up; Photos browsing and organization are native now.
- Chromecast is not included in 0.1.

## Cloud APK build

The repository contains `.github/workflows/android-native.yml`.

Every push that changes `android/**` triggers a debug APK build. A successful run uploads:

`Nomad-Android-debug`

containing:

`app-debug.apk`

No Android development environment is required on the user's computer to install that artifact.

### Build contract

- JDK 17
- Android SDK 36
- Android Gradle Plugin 8.13.2
- Gradle 8.13
- Kotlin 2.3.21
- Compose BOM 2026.06.00
- Media3 1.10.1
- Minimum Android API 23
- Target Android API 36

## Local build, if needed later

```bash
gradle -p android :app:assembleDebug
```

The output is:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

## Nomad server compatibility

The native client intentionally reuses stable Nomad endpoints rather than duplicating server logic. Important contracts include:

- `/api/auth/login`
- `/api/playback/profiles`
- `/api/playback/start`
- `/api/playback/music/stream`
- `/api/media/library/*`
- `/api/media/shows/library`
- `/api/playback/gallery*`
- `/api/playback/gallery/albums`
- `/api/debrid/universal/*`
- `/api/playback/stream-keep/*`
- `/api/debrid/downloads`
- `/api/playback/reader/*`

The client advertises Android decoder capabilities to `/api/playback/start`; the server still decides whether the cheapest valid path is Direct Play, remux, audio-only conversion, or unsupported under Lite policy.
