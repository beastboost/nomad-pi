#!/bin/bash
# Quick fix script for DLNA and movie organization issues

echo "======================================"
echo "Nomad Pi DLNA & Movie Organization Fix"
echo "======================================"

cd ~/nomad-pi || exit 1

# Pull latest code
echo ""
echo "[1/5] Pulling latest code from GitHub..."
git fetch origin
git checkout claude/fix-nowplaying-ui-DcsID
git pull origin claude/fix-nowplaying-ui-DcsID

# Create data directories
echo ""
echo "[2/5] Creating data directories..."
mkdir -p ~/nomad-pi/data/movies
mkdir -p ~/nomad-pi/data/shows
mkdir -p ~/nomad-pi/data/music
mkdir -p ~/nomad-pi/data/books
mkdir -p ~/nomad-pi/data/gallery
mkdir -p ~/nomad-pi/data/files
mkdir -p ~/nomad-pi/data/uploads
mkdir -p ~/nomad-pi/data/cache
mkdir -p ~/nomad-pi/data/external
chmod -R 755 ~/nomad-pi/data/

# Install MiniDLNA if needed
echo ""
echo "[3/5] Ensuring MiniDLNA is installed..."
if ! command -v minidlnad >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y minidlna
fi

# Configure MiniDLNA with hierarchical folders
echo ""
echo "[4/5] Configuring MiniDLNA..."
sudo tee /etc/minidlna.conf > /dev/null <<EOL
# Media directories
media_dir=V,/home/$(whoami)/nomad-pi/data/movies
media_dir=V,/home/$(whoami)/nomad-pi/data/shows
media_dir=A,/home/$(whoami)/nomad-pi/data/music
media_dir=P,/home/$(whoami)/nomad-pi/data/gallery
media_dir=P,/home/$(whoami)/nomad-pi/data/books

# Database and logging
db_dir=/var/cache/minidlna
log_dir=/var/log
log_level=general,artwork,database,inotify,scanner,metadata,http,ssdp,tivo=warn

# Network
friendly_name=nomadpi
network_interface=wlan0
port=8200

# File monitoring
inotify=yes
notify_interval=600

# IMPORTANT: Hierarchical folder structure
root_container=.

# Presentation
presentation_url=http://nomadpi.local:8000/
album_art_names=Cover.jpg/cover.jpg/AlbumArtSmall.jpg/albumartsmall.jpg/AlbumArt.jpg/albumart.jpg/Album.jpg/album.jpg/Folder.jpg/folder.jpg/Thumb.jpg/thumb.jpg

# Optimization
max_connections=50
strict_dlna=no
enable_tivo=no
wide_links=no
EOL

# Add minidlna user to group
if id "minidlna" &>/dev/null; then
    sudo usermod -a -G $(whoami) minidlna
    sudo chmod -R g+rX ~/nomad-pi/data
fi

# Set up cache directories
sudo mkdir -p /var/cache/minidlna /var/log
sudo chown -R minidlna:minidlna /var/cache/minidlna 2>/dev/null || true
sudo chown -R minidlna:minidlna /var/log/minidlna 2>/dev/null || true

# Restart MiniDLNA and rebuild database
echo ""
echo "[5/5] Restarting MiniDLNA and rebuilding database..."
sudo systemctl stop minidlna
sudo rm -f /var/cache/minidlna/files.db
sudo systemctl enable minidlna
sudo systemctl start minidlna
sleep 2
sudo minidlnad -R

# Restart nomad-pi service to apply code changes
echo ""
echo "Restarting nomad-pi service..."
sudo systemctl restart nomad-pi

echo ""
echo "======================================"
echo "Fix Complete!"
echo "======================================"
echo ""
echo "What was fixed:"
echo "  ✓ Updated code with error handling"
echo "  ✓ Created all data directories"
echo "  ✓ Configured MiniDLNA for hierarchical folders"
echo "  ✓ Rebuilt DLNA database"
echo "  ✓ Restarted services"
echo ""
echo "Next steps:"
echo "  1. Check your data directories:"
echo "     ls -la ~/nomad-pi/data/"
echo ""
echo "  2. If you have media files elsewhere, move them to:"
echo "     Movies: ~/nomad-pi/data/movies/"
echo "     Shows:  ~/nomad-pi/data/shows/"
echo ""
echo "  3. Refresh your DLNA browser - you should now see folders"
echo ""
echo "  4. Try 'Apply Movie Sort' in the web UI - should work now"
echo ""
echo "If folders are still empty in DLNA, you may need to add media files first!"
echo ""
