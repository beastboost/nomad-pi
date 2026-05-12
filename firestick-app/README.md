# Nomad Pi Firestick App

A simple Android WebView app wrapper for Nomad Pi - optimized for Amazon Fire TV/Firestick.

## Features

- **Full-screen immersive** - No browser chrome, just your media
- **Fire TV optimized** - Works with Fire TV remote
- **Remote friendly** - D-pad navigation
- **Simple setup** - Enter your server URL once
- **Offline indicator** - Know when connection is lost

## Installation

1. **Build the APK:**
   - Open `firestick-app/` in Android Studio
   - Build → Build APK(s)
   - Or use command line: `./gradlew assembleDebug`

2. **Install on Firestick:**
   - Enable "Apps from Unknown Sources" in Firestick Settings
   - Use ADB to install: `adb install app-debug.apk`
   - Or download the APK to a USB drive and use "Downloader" app

## Build Requirements

- Android Studio Arctic Fox+
- Gradle 8.2+
- JDK 17+

## Quick Commands

```bash
# Build debug APK
cd firestick-app
./gradlew assembleDebug

# Build release APK (requires signing config)
./gradlew assembleRelease
```

## Server URL Setup

On first launch, enter your Nomad Pi URL:
- Local: `http://192.168.1.x:8080` (your local IP)
- Or use a domain if you have remote access

## Remote Controls

| Button | Action |
|--------|--------|
| Menu | Show options menu |
| Back | Go back in browser |
| D-pad | Navigate |
| OK/Select | Click links |
| Play/Pause | Media controls work in video player |

## Troubleshooting

- **Can't connect?** Make sure your Firestick and Nomad Pi are on the same network
- **Video not playing?** Try changing video quality in Nomad Pi settings
- **Touch issues?** This app uses remote controls, not touch

## Customization

Edit `MainActivity.kt` to customize:
- Default server URL (line ~26)
- Theme colors in `themes.xml`
- Cache behavior in `WebSettings`