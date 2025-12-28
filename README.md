# Nomad Pi

A feature-rich, offline media server port of the [Jcorp Nomad](https://github.com/Jstudner/jcorp-nomad) project, optimized for the **Raspberry Pi Zero 2W**.

This project turns your Pi Zero 2W into a portable Wi-Fi Hotspot media center.

## Features

- **Offline Streaming**: Creates its own Wi-Fi Hotspot (`NomadPi`). No internet required.
- **Media Support**: Movies, TV Shows, Music, Books (PDF/EPUB), and **Gallery** (Images/Videos).
- **Resume Playback**: Automatically tracks progress for Movies and Shows.
- **Admin Panel**: 
  - **Upload** files directly from the browser.
  - **Mount** external USB drives/sticks on the fly.
  - **System Control** (Shutdown/Reboot) from the UI.
- **Modern UI**: Dark mode, responsive grid layout, mobile-friendly.

## One-Command Installation

1.  **Clone the repository** to your Raspberry Pi:
    ```bash
    git clone <your-repo-url> nomad-pi
    cd nomad-pi
    ```

2.  **Run the Installer**:
    ```bash
    chmod +x setup.sh
    ./setup.sh
    ```
    
    *This script will:*
    - Install all dependencies.
    - Setup the Python backend.
    - Configure the `nomad` system service to auto-start on boot.
    - **Create a Wi-Fi Hotspot** named `NomadPi` (password: `nomadpassword`).

3.  **Connect & Enjoy**:
    - Connect your phone/laptop to the `NomadPi` Wi-Fi network.
    - Open browser to: `http://10.42.0.1:8000` (or `http://<pi-ip>:8000`).

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

## Development

To run locally on your PC (Windows/Linux/Mac) for development:

```bash
python -m venv venv
# Activate venv (Windows: venv\Scripts\activate, Linux: source venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload
```
*Note: Hotspot and System Control features are disabled/simulated on Windows.*
