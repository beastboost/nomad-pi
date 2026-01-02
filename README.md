# Nomad Pi

A feature-rich, offline media server port of the [Jcorp Nomad](https://github.com/Jstudner/jcorp-nomad) project, optimized for the **Raspberry Pi Zero 2W**.

This project turns your Pi Zero 2W into a portable Wi-Fi Hotspot media center.

## Features

- **Offline Streaming**: Creates its own Wi-Fi Hotspot (`NomadPi`). No internet required.
- **Modern Plex-like UI**: Dark mode, responsive grid layout, and metadata cards with hover effects and progress bars.
- **Offline Metadata & Posters**: Automatically fetches and caches movie/show posters locally for 100% offline access.
- **Advanced Metadata Parsing**: Intelligent parsing for scene-named files (e.g., `Show.S01E01.1080p...`) and hyphenated titles.
- **Auto-Organization**: One-click cleanup that moves files into standardized `Show/Season/Episode` or `Movie (Year)` folders.
- **System Logs Viewer**: Real-time system log monitoring directly from the Admin panel for easier debugging.
- **Media Support**: Movies, TV Shows, Music, Books (PDF/EPUB/CBR/CBZ), and **Gallery** (Images/Videos).
- **Resume Playback**: Automatically tracks progress for Movies and Shows across all devices.
- **Admin Panel**: 
  - **Upload** files directly from the browser.
  - **Mount** external USB drives/sticks on the fly.
  - **System Control** (Shutdown/Reboot) and Wi-Fi/Hotspot management.

## Installation & Setup (Raspberry Pi)

The easiest way to install Nomad Pi on your Raspberry Pi Zero 2W.

1.  **Prepare the directory**:
    ```bash
    mkdir -p ~/nomad-pi
    cd ~/nomad-pi
    ```

2.  **Clone the repository**:
    ```bash
    git clone https://github.com/beastboost/nomad-pi.git .
    ```
    *(Note: The dot `.` at the end clones it directly into the current folder)*

3.  **Run the Installer**:
    ```bash
    chmod +x setup.sh
    ./setup.sh
    ```
    
    *This script will automatically:*
    - Install all system dependencies.
    - Create a Python virtual environment.
    - Configure the `nomad-pi` system service to auto-start on boot.
    - Set up the Wi-Fi Hotspot (`NomadPi`, password: `nomadpassword`).
    - Configure the local hostname to `nomadpi.local`.

## Offline / SD Card Transfer
If your Pi has no internet, you can transfer files via the SD card's boot partition:
1.  **On your PC**: Copy the `nomad-pi` files or media to the SD card (the only partition Windows/Mac can see).
2.  **On the Pi**: Run this command to move them to the app folder:
    ```bash
    sudo rsync -av --exclude 'data' /boot/firmware/ ~/nomad-pi/ 2>/dev/null || sudo rsync -av --exclude 'data' /boot/ ~/nomad-pi/
    ```
3.  **Apply the update**:
    ```bash
    cd ~/nomad-pi && chmod +x update.sh && ./update.sh
    ```

## First-Time Run

Once the setup is complete and your Pi has rebooted:

1.  **Connect**: Join the `NomadPi` Wi-Fi network from your phone or laptop.
2.  **Access**: Open your browser and go to `http://nomadpi.local:8000` or `http://10.42.0.1:8000`.
3.  **Log In**: Use the default password: `nomad`.
4.  **Secure Your Pi**:
    - Go to the **Admin** panel (gear icon).
    - Scroll down to the **Security** section.
    - Change the default password to something secure.
5.  **Add Media**:
    - Use the **Upload** tab to add files.
    - Or plug in a USB drive and use **Admin -> Storage Management** to mount it.

## Development & Windows Usage

If you want to run Nomad Pi on Windows for development purposes:

1.  **Clone**: 
    ```powershell
    git clone https://github.com/beastboost/nomad-pi.git
    cd nomad-pi
    ```
2.  **Setup**: Create a `venv`, activate it, and `pip install -r requirements.txt`.
3.  **Run**: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
*Note: Hotspot and hardware-specific features are disabled on Windows.*

## Security & Authentication

Nomad Pi is designed to be secure even when used offline.

### Changing the Password
1. Log in to the Admin panel with the current password.
2. Go to **Settings** -> **Security Settings**.
3. Enter your current password and your new desired password.

### Environment Variables
You can configure authentication behavior using environment variables in your system service or shell:

- `ADMIN_PASSWORD`: Set a plain-text admin password (only used if no password is set in the database).
- `ADMIN_PASSWORD_HASH`: Set a pre-hashed (bcrypt) admin password (highest priority).
- `ALLOW_INSECURE_DEFAULT`: Set to `true` (default) to allow the "nomad" password if no other credentials are found. Set to `false` to prevent startup unless a password is explicitly provided via environment variables.

### Fail-Fast Protection
If you set `ALLOW_INSECURE_DEFAULT=false` and do not provide an environment variable password, the server will fail to start with a clear error message. This is recommended for production environments.

## Updating

To update your Nomad Pi to the latest version:

### On Raspberry Pi (Linux)
```bash
./update.sh
```

### On Windows (Development)
```powershell
./update.ps1
```

## Usage

### Expanding Storage
Plug in a USB thumb drive.
1. Go to **Admin** -> **Storage Management**.
2. Click **Scan Drives**.
3. Click **Mount**.
   - If your drive has folders named `Movies`, `Music`, etc., they will be automatically detected!

### Folder Structure
You can upload files via the web interface or copy them manually to `data/`:
- `/data/movies`
- `/data/shows`
- `/data/music`
- `/data/books`
- `/data/gallery`

*Note: Hotspot and System Control features are disabled/simulated on Windows.*
