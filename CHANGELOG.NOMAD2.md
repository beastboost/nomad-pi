# Nomad 2 — development changelog

This file tracks the large in-flight Nomad 2 media-core branch separately from the historical release changelog until the branch is ready to squash/merge.

## Playback core
- capability-driven Direct Play, Remux, audio-transcode and video-transcode planning
- persistent playback sessions and short-lived, session-scoped stream tickets
- HTTP Range direct streaming and fMP4 HLS with absolute seek/restart
- hardware-accelerated SBC H.264/HEVC encoder selection with software fallback
- manual Original/1080p/720p/480p profiles and policy-driven multi-rendition Adaptive HLS
- text subtitles convert to WebVTT; image/PGS subtitles can be burned into video

## Devices
- multiple simultaneous account sessions
- persistent playback-device presence
- two-phase Play On handoff with position, quality, audio and subtitle state

## Music 2.0
- cached ffprobe music catalog with artist/album/disc/track/year/genre and technical metadata
- embedded artwork extraction/cache
- Songs, Albums and Artists views
- persistent queue, shuffle, repeat, Media Session controls and ReplayGain

## Stream + Keep
- Find results can stream a debrid source immediately while saving it locally
- the normal PlaybackPlanner selects direct proxy, remux or transcode for the remote source
- CDN URLs remain server-side behind signed Nomad URLs
- remote Range proxy and redirects use the SSRF guard
- remote HLS supports absolute seek while the existing downloader saves/indexes the local copy
- closing playback does not cancel the local keep download

## Foundation
- fixed JSON-body system-control admin routing
- preserved the existing large system/Nocturne implementations behind compatibility facades while new work is split into focused modules
- expanded regression coverage and synthetic FFmpeg single-HLS + ABR smoke tests
