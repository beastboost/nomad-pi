# Nomad Pi in Docker

Docker is supported as a **media/server runtime**, not as a replacement for the native appliance installer.

## Supported in the container

- Movies / TV / music / books / gallery APIs
- Direct Play and HTTP Range streaming
- FFmpeg remux, audio transcode and video transcode
- HLS and Adaptive HLS
- audio/subtitle selection and text/PGS handling
- persistent playback sessions and signed stream tickets
- Music 2.0 metadata/catalog/player
- playback-device presence/handoff
- Offline Sync prepared travel copies
- Library Health / intelligence scanner
- Reader progress, bookmarks and annotations
- debrid acquisition and Stream + Keep
- normal SQLite data, metadata and caches under `/app/data`

## Native-host-only appliance features

The container deliberately does **not** claim ownership of the Docker host's:

- NetworkManager / Wi-Fi radio / hotspot
- systemd units
- disk formatting or arbitrary host mounts
- host Samba/MiniDLNA installation
- host Tailscale service lifecycle
- reboot / shutdown / service-manager operations

Those remain features of the native Nomad Pi installation. API/UI code should treat them as unavailable in `NOMAD_RUNTIME_MODE=server` instead of assuming systemd exists inside the container.

## Start

```bash
docker compose up -d --build
```

The compose file persists `./data` at `/app/data` and mounts `/media` read-only by default. Managed downloads and prepared copies therefore live under `/app/data`; `/media` is intended as an existing host media library unless you deliberately change that mount.

## Hardware acceleration

Hardware acceleration defaults to off in Docker:

```text
NOMAD_HW_ACCEL=off
```

This prevents Nomad from selecting an encoder backed by a device that was never passed into the container. To experiment with hardware encoding, map the relevant host device(s) and set:

```text
NOMAD_HW_ACCEL=auto
```

Examples vary by host. Intel/AMD VAAPI commonly needs `/dev/dri`; Raspberry Pi/Rockchip builds may expose V4L2/RKMPP devices differently. Nomad's runtime health endpoint reports the encoders actually visible **inside** the container, which is the value that matters.

Do not use privileged mode merely to make the UI's native host-management controls work. If you need the full hotspot/storage/systemd appliance, use the native installer instead.
