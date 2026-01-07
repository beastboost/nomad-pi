# Nomad Pi ✨

A high-performance, sleek, and portable media server optimized for **Raspberry Pi (Zero 2W, 3, 4, 5)** and **Radxa** boards. Turn your SBC into a powerful, offline-first media hub with a modern glassmorphism UI.

## 🚀 Key Features

- **Modern Glassmorphism UI**: A stunning, responsive interface with dark mode and real-time glass effects.
- **SBC Optimized**: Low-resource footprint, specifically tuned for Raspberry Pi and Radxa hardware.
- **Offline-First**: Operates as a standalone Wi-Fi Hotspot. No internet? No problem.
- **Auto-Organization**: Intelligent media ingestion that automatically sorts your Movies and TV Shows.
- **Advanced Metadata**: Automatic local caching of posters and metadata for 100% offline access.
- **One-Click Updates**: Keep your server current with the integrated "Update from GitHub" feature.
- **Universal Storage**: Seamlessly mount and manage external USB drives and network shares.
- **Multi-Media Support**:
  - 🎬 **Movies & Shows**: Resume playback, subtitle support, and episode tracking.
  - 🎵 **Music**: Full library indexing and web-based player.
  - 📚 **Books**: Integrated reader for PDF, EPUB, and Comic formats (CBR/CBZ).
  - 🖼️ **Gallery**: High-speed image and video browsing.

## 🛠️ Hardware Support

Nomad Pi is designed to run on a variety of Single Board Computers:
- **Raspberry Pi**: Zero 2W, 3B/3B+, 4B, 5.
- **Radxa**: Rock 4, Rock 5 series.
- **Other SBCs**: Any Debian-based Linux distribution (Ubuntu, Armbian, etc.).

## 📥 Installation

### 1. Prepare Environment
```bash
mkdir -p ~/nomad-pi && cd ~/nomad-pi
```

### 2. Clone & Setup
```bash
git clone https://github.com/beastboost/nomad-pi.git .
chmod +x setup.sh
sudo ./setup.sh
```

The installer will automatically:
- Install system dependencies (`minidlna`, `samba`, `ffmpeg`, etc.).
- Configure a Python virtual environment.
- Set up the `nomad-pi` system service.
- Configure the Wi-Fi Hotspot (`NomadPi`).

## 🔄 Updating
Simply go to the **Admin** panel in the web UI and click **Update from GitHub**. The server will automatically fetch the latest changes, install any new dependencies, and restart the service.

## 🧠 Smart Media Management
- **Duplicate Detection**: Automatically identify identical files (by name/size) or duplicate content (via IMDb IDs) across your library.
- **Unified Playback**: Consistent metadata handling (subtitles, trailers) across all entry points.
- **Library Organization**: Tools to automatically group shows and movies into standard folder structures.

## 📂 File Transfer
- **Web Upload**: Drag & drop files directly into the Admin panel.
- **Samba (SMB)**: Access your media via network shares at `\\nomadpi.local\nomadpi`.
- **USB Import**: Plug in a drive and use the **Storage Management** tool to mount and index files.

## 🔐 Security & First Login

Nomad Pi is designed with security-first principles. On the first run:

1.  **Run the Setup**: `sudo ./setup.sh`
2.  **Check the Console**: The installer will create a default `admin` user and print a **randomly generated password** to your terminal. 
    *   *If you set `ADMIN_PASSWORD` in your environment, that will be used instead.*
3.  **Login**: Access the web UI and log in with username `admin` and the password from Step 2.
4.  **Forced Change**: For your protection, you will be **forced to change your password** immediately after the first successful login.

You can manage additional users and roles in the **Admin -> User Management** section.

## 🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

---
*Optimized for portability, built for performance.*
