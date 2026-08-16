# Nomad Pi ✨

A portable, offline-first media server for **Debian-family Linux SBCs and small servers**, with first-class support for Raspberry Pi and Radxa/Allwinner hardware. Turn a low-power device into a self-contained movies, shows, music, books and file hub with a mobile-friendly PWA.

> **Note:** This project is a fork of [Jcorp Nomad](https://github.com/Jstudner/jcorp-nomad) by Jstudner, with substantial playback, mobile UX, PWA, storage and appliance-management work.

## 🚀 Key Features

- **Responsive PWA UI**: Mobile-first interface designed to work locally and offline.
- **Platform-aware runtime**: Detects board family, architecture, RAM class, FFmpeg capabilities and available hardware video paths.
- **Offline-First**: Can operate as a standalone Wi-Fi hotspot when no home network is available.
- **Auto-Organization**: Intelligent media ingestion for Movies and TV Shows.
- **Advanced Metadata**: Local poster and metadata caching for offline use.
- **One-Click Updates**: Integrated update flow pulls `main`, refreshes dependencies and restarts the service.
- **Universal Storage**: Mount/manage external drives, scan external libraries and configure storage failover.
- **Playback engine**: Direct Play, remux HLS, audio/video transcode, adaptive HLS, track selection and browser compatibility planning.
- **Multi-Media Support**:
  - 🎬 **Movies & Shows**: Resume playback, subtitle/audio selection, episode tracking and media management.
  - 🎵 **Music**: Indexed library and web player.
  - 📚 **Books**: PDF, EPUB and comic readers.
  - 🖼️ **Gallery**: Image/video browsing.
- **🩺 Diagnostics**: Playback diagnostics report actual board identity, RAM, encoder candidates and runtime-validated hardware encoder paths.

## 🛠️ Hardware Support

Nomad's **runtime** is Linux-platform aware. The appliance installer currently targets Debian-family distributions using `apt` and `systemd`.

- **Radxa / Allwinner**: Cubie A7Z/A7-class A733 (`sun60iw2`) and other Debian-based Radxa systems.
- **Radxa / Rockchip**: Rock 4/5-class systems and other Rockchip boards where the OS exposes the relevant media stack.
- **Raspberry Pi**: Zero 2W, 3, 4 and 5. Raspberry-Pi firmware tuning is gated to actual Raspberry Pi hardware and overclocking is opt-in.
- **Other ARM SBCs**: Debian/Ubuntu/Armbian-style systemd hosts are supported by the generic ARM path.
- **x86-64**: Debian-family systemd hosts use the generic x86/server path.

The installer detects the device before tuning it. A typical Cubie A7Z reports something similar to:

```text
Detected platform:
  Board:        Allwinner A733 (sun60iw2)
  Family:       allwinner-a733
  Architecture: aarch64
  RAM:          ~959 MB (low)
```

Memory-constrained systems receive conservative Git/pip/swap policy based on **detected RAM**, not a hard-coded Raspberry Pi model.

## 📥 Installation

### 1. Install Git (fresh OS only)

```bash
sudo apt update
sudo apt install -y git
```

### 2. Clone & Setup

```bash
cd ~
git clone https://github.com/beastboost/nomad-pi.git
cd nomad-pi
chmod +x setup.sh
sudo ./setup.sh
```

The installer will:

- identify the board/SoC family, distro, architecture, CPU count, RAM and swap;
- select a RAM-appropriate installation profile;
- install Debian-family dependencies (`ffmpeg`, `minidlna`, `samba`, NetworkManager, etc.);
- create/repair the Python virtual environment as the real service user;
- configure the `nomad-pi` systemd service;
- preserve existing `/etc/nomadpi.env` settings on reruns;
- configure Samba and MiniDLNA;
- create a `NomadPi` fallback hotspot only when a Wi-Fi interface exists;
- install Tailscale when available;
- stamp the PWA/app modules with the deployed Git commit so clients fetch the matching frontend code.

### Memory / swap policy

Setup no longer blindly forces Pi-Zero tuning onto every host. Current defaults are:

- under 768 MB RAM: **tiny**, target 1 GB swap;
- 768–1535 MB RAM: **low**, target 1 GB swap;
- 1.5–4 GB RAM: **standard**, target 512 MB swap;
- 4 GB+ RAM: **high**, no extra Nomad swap requirement.

Existing swap counts toward the target. If a low-memory host needs extra swap and `dphys-swapfile` is unavailable, Nomad creates a persistent `/var/swap.nomad` file rather than a temporary swap file that disappears on reboot.

## 🔄 Updating

Use **Update from GitHub** in the web UI, or run:

```bash
cd ~/nomad-pi
./update.sh
```

The updater uses the same platform detector and memory policy as setup, refreshes the checkout to `origin/main`, updates dependencies/migrations, refreshes browser assets and restarts Nomad.

## 🧠 Smart Media Management

- **Duplicate Detection**: Identify identical/alternate media versions.
- **Unified Playback**: Consistent metadata, track and playback planning across entry points.
- **Library Organization**: Tools for grouping movies and shows into standard layouts.
- **Rename/Delete**: Manage movies, whole shows and individual episodes from the UI.

## 📡 Wi-Fi & Network Access

When a Wi-Fi adapter exists, Nomad can create a fallback hotspot:

- **Hotspot Name**: `NomadPi`
- **Password**: `nomadpassword`
- **Access URL**: `http://10.42.0.1:8000` when connected to the hotspot
- **mDNS**: `http://nomadpi.local:8000` on the LAN

Setup leaves an already-active Wi-Fi connection alone. If `HOME_SSID` and `HOME_PASS` are present in `/etc/nomadpi.env`, they can be used when no Wi-Fi connection is active. Hosts without a Wi-Fi interface simply skip hotspot setup.

## 📂 File Transfer

- **Web Upload**: Upload files from the browser.
- **Samba (SMB)**: `\\nomadpi.local\data`
  - **Username**: the Linux account that owns/runs the Nomad installation
  - **Default Samba password**: `nomad` unless `SAMBA_PASSWORD` is configured
- **USB / external media**: Mount and index external drives from Storage Management.
- **Storage failover**: Configure a secondary mounted volume and a free-space safety threshold for new persistent media writes.

## 🔐 Security & First Login

`setup.sh` preserves an existing `ADMIN_PASSWORD` from `/etc/nomadpi.env`. If no password exists and none is supplied through the environment, the compatibility default is currently:

```text
admin / nomad
```

Change the password after first login. Setup reruns no longer truncate unrelated values such as Wi-Fi/Tailscale settings from `/etc/nomadpi.env`.

The appliance web UI performs privileged host operations such as updates, mounts, networking and service control. The current appliance install therefore configures passwordless sudo for the Nomad service account. Use the server/container runtime instead if you do not want host-management privileges exposed to the application.

## 🎞️ Playback Hardware Detection

Nomad does not treat `ffmpeg -encoders` as proof that an SBC VPU works. Playback diagnostics now distinguish:

1. an encoder wrapper advertised by FFmpeg;
2. the selected hardware candidate;
3. a **runtime-validated** encoder that successfully processes a real test frame;
4. software fallback (`libx264`/`libx265`) when the hardware path is unavailable.

For Allwinner A733 systems, `sun60iw2` is recognised as the A733 platform identifier. Nomad can report V4L2 M2M and OpenMAX separately instead of misidentifying the board as generic Linux.

## 🤝 Contributing

Contributions are welcome. Please test changes on real target hardware where possible, particularly playback, storage and network-management changes.

---
*Portable by design; hardware-specific only where the hardware actually requires it.*
