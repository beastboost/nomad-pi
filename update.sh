#!/bin/bash
set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
STATUS_FILE="/tmp/nomad-pi-update.json"
STATUS_DIR="/tmp"

update_status() {
    local tmp_file
    tmp_file=$(mktemp "$STATUS_DIR/nomad-pi-update.tmp.XXXXXX" 2>/dev/null) || tmp_file="$STATUS_DIR/nomad-pi-update.tmp.$$"
    # Use jq to build valid JSON if available, otherwise fallback to simple printf escaping
    if command -v jq >/dev/null 2>&1; then
        jq -n \
           --arg progress "$1" \
           --arg message "$2" \
           --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
           '{progress: ($progress|tonumber), message: $message, timestamp: $ts}' > "$tmp_file"
    else
        # Fallback to printf with basic escaping
        local escaped_msg=$(echo "$2" | sed 's/"/\\"/g')
        printf '{"progress": %d, "message": "%s", "timestamp": "%s"}' \
               "$1" "$escaped_msg" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" > "$tmp_file"
    fi
    chmod 644 "$tmp_file" 2>/dev/null || true
    # Try to move, if fails (e.g. permission denied), try sudo, otherwise fail silently so script doesn't crash
    mv -f "$tmp_file" "$STATUS_FILE" 2>/dev/null || sudo mv -f "$tmp_file" "$STATUS_FILE" 2>/dev/null || true
}

update_status 5 "Checking System Health..."
echo "Checking system memory and power resources..."

# Check for under-voltage/throttling (Pi specific)
if command -v vcgencmd >/dev/null 2>&1; then
    THROTTLED=$(vcgencmd get_throttled | cut -d= -f2)
    if [ "$THROTTLED" != "0x0" ]; then
        echo "WARNING: Your Pi is reporting throttling/under-voltage ($THROTTLED)!"
    fi
fi

# Ensure enough swap for pip installs
TOTAL_SWAP=$(free -m | awk '/Swap/ {print $2}')
if [ "$TOTAL_SWAP" -lt 1000 ]; then
    echo "Increasing swap to 1GB for stability..."
    if [ -f /etc/dphys-swapfile ]; then
        sudo -n sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile
        sudo -n dphys-swapfile setup
        sudo -n dphys-swapfile swapon
    fi
fi

# Stop the service ONLY when we are about to finish, to keep the UI responsive for as long as possible
# echo "Stopping nomad-pi service to free up memory..."
# sudo systemctl stop nomad-pi 2>/dev/null || true

update_status 10 "Configuring Git..."
echo "Optimizing Git configuration..."

# System update to pick up GnuTLS/security fixes (optional but recommended for handshake issues)
# sudo apt update && sudo apt full-upgrade -y

update_status 15 "Ensuring repository permissions..."
# Fix repository ownership if it was accidentally changed to root
# This is a common issue when running parts of the setup with sudo
echo "Ensuring correct repository permissions..."
REAL_USER=${SUDO_USER:-$USER}

sudo -n chown -R "$REAL_USER:$REAL_USER" . 2>/dev/null || true
# Mark directory as safe for git (common issue on newer git versions)
git config --global --add safe.directory "$SCRIPT_DIR" 2>/dev/null || true

# Check if we can actually run git commands here
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: Not a git repository or insufficient permissions to read .git"
    update_status 15 "ERROR: Git permission issue. Try: sudo chown -R $USER:$USER ."
    exit 1
fi

update_status 20 "Optimizing Git configuration..."
git config --global --unset http.sslBackend 2>/dev/null || true
git config --global http.sslVerify true
# Force HTTP/1.1 as GnuTLS on some Pi versions fails to negotiate HTTP/2 correctly with GitHub
git config --global http.version HTTP/1.1
# Increase postBuffer to 50MB (from default 1MB) for stable large transfers without excessive memory usage
git config --global http.postBuffer 52428800
# Memory optimizations for Git on Pi Zero
git config --global pack.windowMemory "10m"
git config --global pack.packSizeLimit "20m"
git config --global core.packedGitLimit "20m"
git config --global core.packedGitWindowSize "10m"

# Hardcode the public URL to avoid password prompts
git remote set-url origin https://github.com/beastboost/nomad-pi.git
git config credential.helper 'cache --timeout=2592000'

update_status 10 "Pulling latest changes from Git..."
echo "Pulling latest changes from Git..."
echo "Git remote:"
git remote -v || true
# Force reset to origin/main to solve any local change conflicts automatically
update_status 30 "Fetching latest changes..."
git fetch origin
update_status 40 "Resetting to latest version..."
git reset --hard origin/main
echo "Updated to commit:"
git log -1 --oneline --no-decorate || true

# Fix permissions immediately after pull
chmod +x *.sh
find . -name "*.sh" -exec chmod +x {} +

update_status 50 "Installing system dependencies..."
echo "Installing/Updating system dependencies..."
# Ensure all required system packages are present
# We only run update if install fails to save time on Pi
# Note: unrar is in non-free repo for better CBR/RAR support (unar is fallback)
# Note: 7zip replaces p7zip-full on Ubuntu 24.04+
if [ "$(id -u)" = "0" ]; then
    echo "Updating dependencies as root..."
    apt-get update
    apt-get install -y python3 python3-pip python3-venv network-manager dos2unix python3-dev ntfs-3g exfat-fuse avahi-daemon samba samba-common-bin minidlna 7zip unar unrar libarchive-tools curl ffmpeg
else
    echo "Updating dependencies with sudo..."
    if ! sudo -n apt-get update; then
        echo "Failed to update package list with sudo -n. Trying interactive sudo..."
        sudo apt-get update
    fi
    
    if ! sudo -n apt-get install -y python3 python3-pip python3-venv network-manager dos2unix python3-dev ntfs-3g exfat-fuse avahi-daemon samba samba-common-bin minidlna 7zip unar unrar libarchive-tools curl ffmpeg; then
        echo "Failed to install packages with sudo -n. Trying interactive sudo..."
        sudo apt-get install -y python3 python3-pip python3-venv network-manager dos2unix python3-dev ntfs-3g exfat-fuse avahi-daemon samba samba-common-bin minidlna 7zip unar unrar libarchive-tools curl ffmpeg
    fi
fi

# Ensure Tailscale is installed (for updates via UI)
update_status 55 "Checking Tailscale..."
if command -v tailscale >/dev/null 2>&1; then
    echo "Tailscale is already installed."
else
    echo "Installing Tailscale..."
    if curl -fsSL https://tailscale.com/install.sh | sh; then
        echo "Tailscale installed successfully!"
    else
        echo "WARNING: Failed to install Tailscale. Check logs."
    fi
fi

# Ensure Tailscale service is running
if command -v tailscale >/dev/null 2>&1; then
    if ! systemctl is-active --quiet tailscaled 2>/dev/null; then
        echo "Starting Tailscale service..."
        sudo systemctl enable tailscaled 2>/dev/null || true
        sudo systemctl start tailscaled 2>/dev/null || true
    fi
fi

update_status 60 "Installing Python dependencies..."
echo "Installing Python dependencies..."

# Fix permissions on venv if it exists to avoid Errno 13
if [ -d "venv" ]; then
    echo "Fixing venv permissions..."
    sudo chown -R $USER:$USER venv || true
fi

if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv
fi

update_status 70 "Upgrading pip..."
./venv/bin/pip install --upgrade pip

# Check for requirements changes to skip redundant installs
update_status 75 "Checking dependencies..."
REQUIREMENTS_HASH=$(md5sum requirements.txt | awk '{ print $1 }')
PREV_HASH=$(cat .requirements_hash 2>/dev/null || echo "")

if [ "$REQUIREMENTS_HASH" != "$PREV_HASH" ] || [ ! -f "./venv/bin/uvicorn" ]; then
    echo "Requirements changed or environment incomplete. Installing dependencies..."
    
    # Split installation into chunks to avoid massive memory spikes (Pi Zero stability)
    echo "Installing base dependencies..."
    ./venv/bin/pip install --no-cache-dir --prefer-binary fastapi uvicorn psutil
    
    echo "Installing security and utility dependencies..."
    ./venv/bin/pip install --no-cache-dir --prefer-binary "passlib[bcrypt]" bcrypt==4.0.1 python-multipart aiofiles jinja2 python-jose[cryptography] httpx
    
    echo "Installing remaining requirements..."
    ./venv/bin/pip install --no-cache-dir --prefer-binary -r requirements.txt
    
    echo "$REQUIREMENTS_HASH" > .requirements_hash
else
    echo "Dependencies already up to date. Skipping pip install."
fi

# Final check for uvicorn
if [ ! -f "./venv/bin/uvicorn" ]; then
    echo "CRITICAL: uvicorn still missing. Trying emergency install..."
    ./venv/bin/pip install --no-cache-dir --prefer-binary uvicorn
fi

# Ensure Tailscale is installed (moved up)
# update_status 80 "Checking Tailscale..." (Logic moved up)

update_status 85 "Running database migrations..."
echo "Running database migrations..."
if [ -f "migrate_db.py" ]; then
    ./venv/bin/python migrate_db.py || {
        echo "WARNING: Database migration failed. Check logs." >> update.log
    }
else
    echo "No migration script found, skipping..." >> update.log
fi


# Ensure data directories exist
echo "Ensuring media directories exist..." >> update.log
mkdir -p data/movies data/shows data/music data/books data/files data/external data/gallery data/uploads data/cache

# Install MiniDLNA if not present
if ! command -v minidlnad >/dev/null 2>&1; then
    echo "Installing MiniDLNA..." >> update.log
    sudo apt-get update >> update.log 2>&1
    sudo apt-get install -y minidlna >> update.log 2>&1
fi

# Add minidlna user to group and fix permissions
if id "minidlna" &>/dev/null; then
    echo "Configuring minidlna permissions..." >> update.log

    # Add minidlna to user's group so it can access files
    sudo usermod -a -G "$REAL_USER" minidlna 2>/dev/null || true

    # Get the actual home directory path
    USER_HOME=$(eval echo ~$REAL_USER)

    # CRITICAL: Home directory must have group read+execute for minidlna user to traverse
    # Use 755 (rwxr-xr-x) to allow group and others to read and traverse
    sudo chmod 755 "$USER_HOME" 2>/dev/null || true

    # Make nomad-pi directory traversable and readable
    sudo chmod 755 "$SCRIPT_DIR" 2>/dev/null || true

    # Set ownership and permissions on data directory
    sudo chown -R $REAL_USER:$REAL_USER "$SCRIPT_DIR/data" 2>/dev/null || true
    sudo chmod -R 755 "$SCRIPT_DIR/data" 2>/dev/null || true
fi

# Fix MiniDLNA permissions and configuration
echo "Checking MiniDLNA configuration..." >> update.log

MINIDLNA_CONF="/etc/minidlna.conf"
MINIDLNA_TEMP="/tmp/minidlna.conf.tmp"
DLNA_CONFIG_CHANGED=0
CURRENT_HOSTNAME=$(hostname 2>/dev/null || echo "nomadpi")

sudo mkdir -p /var/cache/minidlna /var/log/minidlna 2>/dev/null || true
sudo -n chown -R minidlna:minidlna /var/cache/minidlna /var/log/minidlna 2>/dev/null || true

# Fix inotify max_user_watches limit for MiniDLNA file monitoring
# MiniDLNA needs to watch for file changes, increase the limit from default 8192 to 524288
if [ -f /proc/sys/fs/inotify/max_user_watches ]; then
    echo 524288 | sudo -n tee /proc/sys/fs/inotify/max_user_watches > /dev/null 2>&1 || true
    # Make it persistent across reboots
    if ! grep -q "fs.inotify.max_user_watches" /etc/sysctl.conf 2>/dev/null; then
        echo "fs.inotify.max_user_watches=524288" | sudo -n tee -a /etc/sysctl.conf > /dev/null 2>&1 || true
    fi
fi

# Build the complete config in a temp file
cat > "$MINIDLNA_TEMP" <<EOL
# Scan the entire data directory (includes external drives under data/external)
media_dir=$SCRIPT_DIR/data

# Database and logging
db_dir=/var/cache/minidlna
log_dir=/var/log/minidlna
log_level=general,artwork,database,inotify,scanner,metadata,http,ssdp,tivo=warn

# Network settings
friendly_name=$CURRENT_HOSTNAME
port=8200

# File monitoring - scan every 60 seconds for changes
inotify=yes
notify_interval=60

# Container settings - use "." for hierarchical folders
root_container=.

# Presentation
presentation_url=http://$CURRENT_HOSTNAME.local:8000/
album_art_names=Cover.jpg/cover.jpg/AlbumArtSmall.jpg/albumartsmall.jpg/AlbumArt.jpg/albumart.jpg/Album.jpg/album.jpg/Folder.jpg/folder.jpg/Thumb.jpg/thumb.jpg

# Optimization
max_connections=50
strict_dlna=no
enable_tivo=no
wide_links=yes

# Exclusions - skip junk folders from Windows/Mac/Linux systems
# This prevents log spam from scanning recycle bins, system folders, etc.
exclude=\$RECYCLE.BIN,\$Recycle.Bin,Recycled,System Volume Information,.Trashes,.Trash-*,.TemporaryItems,.Spotlight-V100,.fseventsd,lost+found,.AppleDouble,.DS_Store,Thumbs.db
EOL

# Only update if config changed (use diff like setup.sh does)
if [ ! -f "$MINIDLNA_CONF" ] || ! diff -q "$MINIDLNA_TEMP" "$MINIDLNA_CONF" >/dev/null 2>&1; then
    echo "Updating MiniDLNA configuration..." >> update.log
    sudo -n cp "$MINIDLNA_TEMP" "$MINIDLNA_CONF"
    DLNA_CONFIG_CHANGED=1
else
    echo "MiniDLNA configuration unchanged." >> update.log
fi
rm -f "$MINIDLNA_TEMP"

# Re-verify sudoers configuration (in case it was removed by system update)
REAL_USER=${SUDO_USER:-$USER}
SYSTEMCTL_PATH=$(command -v systemctl || echo "/usr/bin/systemctl")
MINIDLNAD_PATH=$(command -v minidlnad || echo "/usr/sbin/minidlnad")
SUDOERS_FILE="/etc/sudoers.d/nomad-pi"
CHOWN_PATH=$(command -v chown || echo "/usr/bin/chown")
CHMOD_PATH=$(command -v chmod || echo "/usr/bin/chmod")

if [ ! -f "$SUDOERS_FILE" ] || ! grep -q "$MINIDLNAD_PATH" "$SUDOERS_FILE" 2>/dev/null || ! grep -q "$CHOWN_PATH" "$SUDOERS_FILE" 2>/dev/null || ! grep -q "$CHMOD_PATH" "$SUDOERS_FILE" 2>/dev/null; then
    echo "Re-applying sudoers permissions..." >> update.log
    MOUNT_PATH=$(command -v mount || echo "/usr/bin/mount")
    UMOUNT_PATH=$(command -v umount || echo "/usr/bin/umount")
    SHUTDOWN_PATH=$(command -v shutdown || echo "/usr/sbin/shutdown")
    REBOOT_PATH=$(command -v reboot || echo "/usr/sbin/reboot")
    NMCLI_PATH=$(command -v nmcli || echo "/usr/bin/nmcli")
    TAILSCALE_PATH=$(command -v tailscale || echo "/usr/bin/tailscale")

    # Write to temp file first and validate before installing
    # GRANT FULL PASSWORDLESS SUDO ACCESS to ensure updates and system control work from Web UI
    SUDOERS_TMP=$(mktemp)
    cat > "$SUDOERS_TMP" <<EOL
$REAL_USER ALL=(ALL) NOPASSWD: ALL
EOL
    # Validate sudoers syntax before installing - a malformed file can lock out sudo access
    if sudo -n visudo -cf "$SUDOERS_TMP"; then
        sudo -n cp "$SUDOERS_TMP" "$SUDOERS_FILE"
        sudo -n chmod 0440 "$SUDOERS_FILE"
        echo "Sudoers permissions restored (Full Access)." >> update.log
    else
        echo "ERROR: Generated sudoers file failed syntax validation. Not installing." >> update.log
    fi
    rm -f "$SUDOERS_TMP"
fi

if command -v minidlnad >/dev/null 2>&1; then
    echo "Configuring MiniDLNA service..." >> update.log

    # Setup cache directories
    sudo mkdir -p /var/cache/minidlna /var/log 2>/dev/null || true
    sudo chown -R minidlna:minidlna /var/cache/minidlna 2>/dev/null || true
    sudo chown -R minidlna:minidlna /var/log/minidlna 2>/dev/null || true

    if [ "$DLNA_CONFIG_CHANGED" = "1" ]; then
        echo "Restarting MiniDLNA to apply changes..." >> update.log
        # Stop first to ensure clean DB if needed
        sudo -n systemctl stop minidlna 2>/dev/null || true
        sudo -n rm -f /var/cache/minidlna/files.db 2>/dev/null || true
        sudo -n systemctl enable minidlna
        sudo -n systemctl start minidlna
    else
        # Restart to ensure permissions apply (group changes)
        echo "Restarting MiniDLNA to apply permissions..." >> update.log
        sudo -n systemctl enable minidlna
        sudo -n systemctl restart minidlna
    fi
else
    echo "MiniDLNA not installed. Skipping configuration." >> update.log
fi

update_status 90 "Update complete. Finalizing..."
echo "Update complete. Preparing to restart..."

# Write completion marker to log BEFORE restarting
echo "" >> update.log
echo "==========================================" >> update.log
echo "          Update Complete!                " >> update.log
echo "==========================================" >> update.log
echo "Nomad Pi has been updated successfully." >> update.log
echo "Server will restart in 5 seconds..." >> update.log
echo "==========================================" >> update.log

update_status 100 "Update complete! Restarting in 5 seconds..."

# Give the UI time to read the completion status
echo "Waiting 2 seconds for UI to update..."
sleep 2

# Try to restart the service, with fallback if service doesn't exist
if command -v systemctl >/dev/null 2>&1; then
    echo "Restarting nomad-pi service..." >> update.log
    sudo -n systemctl daemon-reload
    sudo -n systemctl enable nomad-pi.service
    # Use systemd-run to defer restart (avoids self-restart issues)
    echo "Scheduling deferred service restart..." >> update.log

    # Create a one-shot script to restart the service after a delay
    RESTART_SCRIPT="/tmp/restart_nomad_pi.sh"
    cat > "$RESTART_SCRIPT" <<EOL
#!/bin/bash
sleep 2
sudo -n systemctl restart nomad-pi.service
EOL
    chmod +x "$RESTART_SCRIPT"
    nohup "$RESTART_SCRIPT" >/dev/null 2>&1 &
    
    echo "Update completed successfully!" >> update.log
    update_status 100 "Update complete!"
else
    echo "systemctl not found. If running manually, please restart the application." >> update.log
fi
