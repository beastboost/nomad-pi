# Nomad 2 — development changelog

This file tracks the large in-flight Nomad 2 media-platform branch separately from the historical release changelog until the branch is ready to squash/merge.

## Playback core
- capability-driven Direct Play, Remux, audio-transcode and video-transcode planning
- persistent playback sessions and short-lived, session-scoped stream tickets
- HTTP Range direct streaming and fMP4 HLS with absolute seek/restart
- hardware-accelerated SBC H.264/HEVC encoder selection with software fallback
- manual Original/1080p/720p/480p profiles and policy-driven multi-rendition Adaptive HLS
- text subtitles convert to WebVTT; image/PGS subtitles can be burned into video

## Devices and Watch Together
- multiple simultaneous account sessions
- persistent playback-device presence
- two-phase Play On handoff with position, quality, audio and subtitle state
- same-account Watch Together rooms use short six-character codes without exposing the library publicly
- host publishes authoritative playback state once per second
- followers compensate for timestamp/network delay, use ±3% rate correction for medium drift and hard-seek only for large drift
- Watch Together carries quality/adaptive, selected audio and subtitle state when a member joins

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
- remote HLS supports absolute seek while the local copy downloads/indexes in parallel
- local copies use stable `.part` files plus ETag/Last-Modified resume metadata
- interrupted downloads continue with HTTP `Range` + `If-Range` after transient failures or a Nomad process restart
- a valid `206` is required before appending; ignored/invalid ranges safely restart instead of corrupting the file
- Stream + Keep jobs automatically reattach/recover on process startup with a bounded retry count
- closing remote playback does not cancel the local keep download

## Offline Sync
- persistent per-user prepared travel-copy jobs
- restart-safe conversion queue with cancel/retry/delete
- compatible H.264/AAC media is copied/remuxed without unnecessary video encoding
- incompatible/high-resolution sources use the same hardware-first H.264 strategy with software fallback
- finished copies are exposed only through signed offline-download tickets
- Nocturne file actions and Downloads UI show preparation state and prepared copies

## Library intelligence
- cached technical probe data and same-size fingerprinting avoid expensive full-library work on every request
- exact duplicates are separated from alternate versions
- TV episode parsing identifies gaps/missing episodes
- broken/unreadable media and low-quality/legacy-codec upgrade candidates are surfaced in Library Health
- local recommendation/smart-collection work remains private to the Nomad instance

## Household profiles
- legacy single-profile records are mirrored into a backward-compatible household-profile store instead of rewriting the old table
- multiple profiles can exist under one account
- selected profile is persisted per login session using only a SHA-256 token fingerprint
- a fresh authenticated session is automatically bound to the account default, so omitting profile headers cannot bypass policy
- optional 4–8 digit profile PINs protect switching into locked profiles; PIN hashes use bcrypt and attempts are rate-limited
- profile create/edit/delete/PIN administration requires the account password
- restricted profiles default Library Health and server administration off and can independently block debrid, downloads, offline sync, deletion and libraries
- old authenticated media/debrid/system routes and the new playback core share the same bound-profile policy shell

## Reader state
- reading progress, bookmarks and annotations persist per user/path
- paged formats retain page/total-page positions
- EPUB stores real epub.js CFI, href, percentage and displayed-location metadata instead of unstable visual page numbers
- EPUB resume, bookmarks and note jumps use the stored CFI so changing screen/font layout does not invalidate the location

## Docker/server mode
- runtime capability reporting differentiates full appliance mode from container/server mode
- host-only controls such as Wi-Fi, hotspot, reboot/shutdown, mount/format and native service management are disabled in Nocturne when unavailable
- playback, Music 2, Offline Sync, reader state, library intelligence and Stream + Keep remain server-mode features

## Foundation and validation
- fixed JSON-body system-control admin routing
- preserved the existing large system/Nocturne implementations behind compatibility facades while new work is split into focused modules
- later feature routers and browser modules are explicitly mounted/loaded rather than merely existing in the repository
- regression coverage in the branch includes authentication, playback planning, HLS/ABR, hardware fallback, tracks/subtitles, device handoff, Music 2, Stream + Keep, byte-range resume, Offline Sync, Library Health, household profiles and Watch Together
- CI is configured to syntax-check all active Nomad 2 browser modules and run synthetic single-HLS + adaptive-HLS FFmpeg smoke tests
- execution of the full suite is still pending the merge/test phase: this runtime cannot clone GitHub because its container DNS cannot resolve `github.com`, and GitHub Actions has previously failed to allocate a runner for the repository account
