#!/bin/bash
# Fix and configure MiniDLNA for Nomad Pi

echo "=================================================="
echo "    MiniDLNA Configuration & Repair Script"
echo "=================================================="
echo ""

# Ensure MiniDLNA is installed
if ! command -v minidlnad >/dev/null 2>&1; then
    echo "Installing MiniDLNA..."
    sudo apt-get update
    sudo apt-get install -y minidlna
fi

# Stop the service
echo "Stopping MiniDLNA service..."
sudo systemctl stop minidlna

# Backup existing config
if [ -f /etc/minidlna.conf ]; then
    echo "Backing up existing config..."
    sudo cp /etc/minidlna.conf /etc/minidlna.conf.backup
fi

# Create fresh configuration
echo "Creating new configuration..."
sudo tee /etc/minidlna.conf > /dev/null << 'EOF'
# MiniDLNA Configuration for Nomad Pi
port=8200
network_interface=wlan0

# Media directories
media_dir=V,/data/movies
media_dir=V,/data/shows
media_dir=A,/data/music
media_dir=P,/data/gallery

# Also scan external drives
media_dir=V,/data/external

# Database and cache
db_dir=/var/cache/minidlna
log_dir=/var/log/minidlna

# Server settings
friendly_name=Nomad Pi Media Server
inotify=yes
notify_interval=300

# Enable wide links to follow symlinks
wide_links=yes

# Album art
album_art_names=Cover.jpg/cover.jpg/AlbumArtSmall.jpg/albumartsmall.jpg
album_art_names=AlbumArt.jpg/albumart.jpg/Album.jpg/album.jpg
album_art_names=Folder.jpg/folder.jpg/Thumb.jpg/thumb.jpg
album_art_names=poster.jpg/poster.png

# Media presentation
model_number=1
serial=12345678
EOF

echo "Configuration created!"

# Fix permissions
echo "Fixing permissions..."
sudo mkdir -p /data/movies /data/shows /data/music /data/gallery /data/external
sudo chown -R minidlna:minidlna /var/cache/minidlna
sudo chown -R minidlna:minidlna /var/log/minidlna

# Add minidlna user to necessary groups
sudo usermod -a -G $USER minidlna

# Give minidlna read access to data directories
sudo chmod -R 755 /data
sudo setfacl -R -m u:minidlna:rx /data 2>/dev/null || echo "ACL not available, using chmod instead"

# Clear the database to force rescan
echo "Clearing MiniDLNA database..."
sudo rm -rf /var/cache/minidlna/*

# Enable and start the service
echo "Enabling and starting MiniDLNA..."
sudo systemctl enable minidlna
sudo systemctl start minidlna

# Wait a moment for startup
sleep 3

# Force a rescan
echo "Forcing media rescan..."
sudo systemctl restart minidlna

# Check status
echo ""
echo "Checking service status..."
if systemctl is-active --quiet minidlna; then
    echo "✓ MiniDLNA is running!"
    echo ""
    echo "Server should be discoverable as: Nomad Pi Media Server"
    echo "Port: 8200"
    echo ""
    echo "Give it a few minutes to scan your media library."
    echo "Check progress: sudo tail -f /var/log/minidlna/minidlna.log"
else
    echo "✗ MiniDLNA failed to start!"
    echo "Check logs: sudo journalctl -u minidlna -n 50"
fi

echo ""
echo "=================================================="
echo "                  Complete!"
echo "=================================================="
