# NomadOS Builder

This directory contains the necessary configuration and scripts to build a custom Linux operating system image (NomadOS) for the Raspberry Pi using `pi-gen`.

## Architecture

NomadOS is built on top of Raspberry Pi OS Lite (Debian Bookworm) and strips out unnecessary components while baking in:

1. **Python 3 & FFmpeg**: Native dependencies required for the backend.
2. **Nomad Pi Backend**: The FastAPI backend is copied directly into `/opt/nomad-pi`.
3. **Systemd Service**: `nomad-pi.service` is configured to launch the server instantly on boot.
4. **NetworkManager & Hotspot**: A first-boot service (`nomad-pi-firstboot.service`) creates the `NomadPi` hotspot (password `nomadpassword`), matching a setup.sh install. If no known Wi-Fi network is found, the hotspot broadcasts automatically; the web UI is at `http://10.42.0.1:8000`.

> **Note:** The image path installs only the backend and hotspot. Extras that `setup.sh` configures (Samba shares, MiniDLNA, sudoers rules for the Admin panel's reboot/update buttons) are not baked in yet — run `setup.sh` on the booted image if you need those.

## How to Build (Windows)

1. Ensure **Docker Desktop** is installed and running on your Windows machine.
2. Ensure you have **Git** installed.
3. Open PowerShell as Administrator and run:
   ```powershell
   .\build.ps1
   ```

## What the build script does:
1. Clones the official `pi-gen` repository.
2. Copies our custom `config` and `stage3-nomad` into the pi-gen tree.
3. Copies the current `app/` directory and `requirements.txt` into the build context.
4. Runs `build-docker.sh` to compile the `.img` file.
5. Outputs the final flashable `NomadOS.img` into the `os-builder/deploy` folder.

You can then use [BalenaEtcher](https://etcher.balena.io/) or Raspberry Pi Imager to flash this image directly to your SD card.
