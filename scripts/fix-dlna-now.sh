#!/bin/bash
# Emergency DLNA fix script
# This will diagnose and fix DLNA configuration issues

echo "================================================"
echo "DLNA Emergency Diagnostic & Fix"
echo "================================================"
echo ""

# Find where nomad-pi is installed
NOMAD_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
echo "Nomad Pi directory: $NOMAD_DIR"
echo ""

# Check for media files
echo "Checking for media files..."
echo ""
echo "Movies in data/movies:"
find "$NOMAD_DIR/data/movies" -maxdepth 2 -type f \( -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" \) 2>/dev/null | head -5
MOVIE_COUNT=$(find "$NOMAD_DIR/data/movies" -type f \( -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" \) 2>/dev/null | wc -l)
echo "Total movies found: $MOVIE_COUNT"
echo ""

echo "Shows in data/shows:"
find "$NOMAD_DIR/data/shows" -maxdepth 3 -type f \( -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" \) 2>/dev/null | head -5
SHOW_COUNT=$(find "$NOMAD_DIR/data/shows" -type f \( -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" \) 2>/dev/null | wc -l)
echo "Total episodes found: $SHOW_COUNT"
echo ""

# Check current DLNA config
echo "Current MiniDLNA configuration:"
if [ -f /etc/minidlna.conf ]; then
    echo "Config file exists"
    grep "^media_dir=" /etc/minidlna.conf || echo "  No media_dir entries found!"
    grep "^root_container=" /etc/minidlna.conf || echo "  No root_container entry found!"
else
    echo "  ERROR: /etc/minidlna.conf does not exist!"
fi
echo ""

# Check DLNA service status
echo "MiniDLNA service status:"
systemctl is-active minidlna && echo "  Running" || echo "  NOT RUNNING"
echo ""

# Check permissions
echo "Checking permissions on data directory:"
ls -ld "$NOMAD_DIR/data" 2>/dev/null || echo "  data directory doesn't exist!"
ls -ld "$NOMAD_DIR/data/movies" 2>/dev/null || echo "  movies directory doesn't exist!"
ls -ld "$NOMAD_DIR/data/shows" 2>/dev/null || echo "  shows directory doesn't exist!"
echo ""

echo "================================================"
echo "FIXING CONFIGURATION"
echo "================================================"
echo ""

# Stop MiniDLNA
echo "Stopping MiniDLNA..."
sudo systemctl stop minidlna 2>/dev/null || true

# Create correct configuration
echo "Creating correct MiniDLNA configuration..."
sudo tee /etc/minidlna.conf > /dev/null <<EOL
# Media directories - using absolute paths
media_dir=V,$NOMAD_DIR/data/movies
media_dir=V,$NOMAD_DIR/data/shows
media_dir=A,$NOMAD_DIR/data/music
media_dir=P,$NOMAD_DIR/data/gallery
media_dir=P,$NOMAD_DIR/data/books

# Database location
db_dir=/var/cache/minidlna
log_dir=/var/log
log_level=general,artwork,database,inotify,scanner,metadata,http,ssdp,tivo=warn

# Network settings
friendly_name=nomadpi
network_interface=wlan0
port=8200

# File monitoring
inotify=yes
notify_interval=60

# CRITICAL: Use hierarchical folder structure
root_container=.

# Presentation
presentation_url=http://nomadpi.local:8000/
album_art_names=Cover.jpg/cover.jpg/AlbumArtSmall.jpg/albumartsmall.jpg/AlbumArt.jpg/albumart.jpg/Album.jpg/album.jpg/Folder.jpg/folder.jpg/Thumb.jpg/thumb.jpg

# Settings
max_connections=50
strict_dlna=no
enable_tivo=no
wide_links=no
EOL

echo "Configuration written to /etc/minidlna.conf"
echo ""

# Fix permissions
echo "Fixing permissions..."
sudo chown -R $(whoami):$(whoami) "$NOMAD_DIR/data" 2>/dev/null || true
sudo chmod -R 755 "$NOMAD_DIR/data" 2>/dev/null || true

# Add minidlna user to group
if id "minidlna" &>/dev/null; then
    echo "Adding minidlna user to group..."
    sudo usermod -a -G $(whoami) minidlna 2>/dev/null || true
    sudo chmod -R g+rX "$NOMAD_DIR/data" 2>/dev/null || true
fi

# Clear database and restart
echo "Clearing old database and rebuilding..."
sudo rm -rf /var/cache/minidlna/* 2>/dev/null || true
sudo mkdir -p /var/cache/minidlna /var/log
sudo chown -R minidlna:minidlna /var/cache/minidlna 2>/dev/null || true
sudo chown -R minidlna:minidlna /var/log/minidlna 2>/dev/null || true

# Start MiniDLNA
echo "Starting MiniDLNA..."
sudo systemctl enable minidlna
sudo systemctl start minidlna

# Force rescan
echo "Forcing media rescan..."
sleep 2
sudo minidlnad -R 2>/dev/null || true

echo ""
echo "================================================"
echo "Fix Complete!"
echo "================================================"
echo ""
echo "Summary:"
echo "  Movies found: $MOVIE_COUNT"
echo "  Episodes found: $SHOW_COUNT"
echo ""
echo "What to do next:"
echo "  1. Wait 2-3 minutes for MiniDLNA to scan all files"
echo "  2. Refresh your TV's DLNA browser"
echo "  3. You should see: Movies, TV Shows folders with your content"
echo ""
echo "If folders are still empty after 5 minutes:"
echo "  - Your media files might be in a different location"
echo "  - Run: ls -la $NOMAD_DIR/data/movies"
echo "  - Check where your 20 organized movies went"
echo ""
