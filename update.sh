#!/bin/bash
set -e
STATUS_FILE="/tmp/nomad-pi-update.json"

update_status() {
    # Construct JSON safely using a temporary file and atomic replace
    local tmp_file=$(mktemp)
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
    chmod 600 "$tmp_file"
    mv "$tmp_file" "$STATUS_FILE"
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
        sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile
        sudo dphys-swapfile setup
        sudo dphys-swapfile swapon
    fi
fi

# Stop the service ONLY when we are about to finish, to keep the UI responsive for as long as possible
# echo "Stopping nomad-pi service to free up memory..."
# sudo systemctl stop nomad-pi 2>/dev/null || true

update_status 10 "Configuring Git..."
echo "Optimizing Git configuration..."

# System update to pick up GnuTLS/security fixes (optional but recommended for handshake issues)
# sudo apt update && sudo apt full-upgrade -y

update_status 15 "Optimizing Git configuration..."
# Fix repository ownership if it was accidentally changed to root
echo "Ensuring correct repository permissions..."
sudo chown -R $USER:$USER . 2>/dev/null || true
# Mark directory as safe for git (common issue on newer git versions)
git config --global --add safe.directory $(pwd) 2>/dev/null || true

# Refined Git config for stability on Pi OS (GnuTLS handshake workarounds)
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
# Force reset to origin/main to solve any local change conflicts automatically
update_status 30 "Fetching latest changes..."
git fetch origin
update_status 40 "Resetting to latest version..."
git reset --hard origin/main

# Fix permissions immediately after pull
chmod +x *.sh
find . -name "*.sh" -exec chmod +x {} +

update_status 50 "Installing system dependencies..."
echo "Installing/Updating system dependencies..."
# Ensure all required system packages are present
# We only run update if install fails to save time on Pi
if ! sudo apt-get install -y python3 python3-pip python3-venv network-manager dos2unix python3-dev ntfs-3g exfat-fuse avahi-daemon samba samba-common-bin minidlna p7zip-full unar libarchive-tools; then
    echo "Some packages missing, updating list and trying again..." >> update.log
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip python3-venv network-manager dos2unix python3-dev ntfs-3g exfat-fuse avahi-daemon samba samba-common-bin minidlna p7zip-full unar libarchive-tools
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

update_status 85 "Running database migrations..."
echo "Running database migrations..."
if [ -f "migrate_db.py" ]; then
    ./venv/bin/python migrate_db.py || {
        echo "WARNING: Database migration failed. Check logs." >> update.log
    }
else
    echo "No migration script found, skipping..." >> update.log
fi


# Fix MiniDLNA permissions and sudoers after update
echo "Checking MiniDLNA configuration..." >> update.log

# Re-verify sudoers configuration (in case it was removed by system update)
REAL_USER=${SUDO_USER:-$USER}
SYSTEMCTL_PATH=$(command -v systemctl || echo "/usr/bin/systemctl")
MINIDLNAD_PATH=$(command -v minidlnad || echo "/usr/sbin/minidlnad")
SUDOERS_FILE="/etc/sudoers.d/nomad-pi"

if [ ! -f "$SUDOERS_FILE" ] || ! grep -q "$MINIDLNAD_PATH" "$SUDOERS_FILE" 2>/dev/null; then
    echo "Re-applying sudoers permissions for MiniDLNA..." >> update.log
    MOUNT_PATH=$(command -v mount || echo "/usr/bin/mount")
    UMOUNT_PATH=$(command -v umount || echo "/usr/bin/umount")
    SHUTDOWN_PATH=$(command -v shutdown || echo "/usr/sbin/shutdown")
    REBOOT_PATH=$(command -v reboot || echo "/usr/sbin/reboot")
    NMCLI_PATH=$(command -v nmcli || echo "/usr/bin/nmcli")

    # Write to temp file first and validate before installing
    SUDOERS_TMP=$(mktemp)
    cat > "$SUDOERS_TMP" <<EOL
$REAL_USER ALL=(ALL) NOPASSWD: $MOUNT_PATH, $UMOUNT_PATH, $SHUTDOWN_PATH, $REBOOT_PATH, $SYSTEMCTL_PATH restart nomad-pi.service, $SYSTEMCTL_PATH stop nomad-pi.service, $SYSTEMCTL_PATH start nomad-pi.service, $SYSTEMCTL_PATH status nomad-pi.service, $SYSTEMCTL_PATH restart nomad-pi, $NMCLI_PATH, $SYSTEMCTL_PATH restart minidlna, $SYSTEMCTL_PATH restart minidlna.service, $MINIDLNAD_PATH
EOL
    # Validate sudoers syntax before installing - a malformed file can lock out sudo access
    if sudo visudo -cf "$SUDOERS_TMP"; then
        sudo cp "$SUDOERS_TMP" "$SUDOERS_FILE"
        sudo chmod 0440 "$SUDOERS_FILE"
        echo "Sudoers permissions restored." >> update.log
    else
        echo "ERROR: Generated sudoers file failed syntax validation. Not installing." >> update.log
    fi
    rm -f "$SUDOERS_TMP"
fi

if command -v minidlnad >/dev/null 2>&1; then
    echo "Fixing MiniDLNA cache permissions..." >> update.log
    sudo chown -R minidlna:minidlna /var/cache/minidlna 2>/dev/null || true
    sudo chown -R minidlna:minidlna /var/log/minidlna 2>/dev/null || true

    # Restart MiniDLNA if it's running
    if systemctl is-active --quiet minidlna; then
        echo "Restarting MiniDLNA..." >> update.log
        sudo systemctl restart minidlna >> update.log 2>&1 || echo "MiniDLNA restart failed (non-critical)" >> update.log
    fi
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
    echo "Attempting to restart nomad-pi service via systemctl..." >> update.log
    if [ -f "/etc/systemd/system/nomad-pi.service" ]; then
        sudo systemctl daemon-reload
        sudo systemctl enable nomad-pi.service
        # Use systemd-run to defer restart (avoids self-restart issues)
        echo "Scheduling deferred service restart..." >> update.log

        # Create a one-shot script to restart the service after a delay
        echo "Creating restart script..." >> update.log
        cat > /tmp/nomad-restart.sh << 'RESTART_EOF'
#!/bin/bash
echo "$(date): Deferred restart starting..." >> /home/pi/nomad-pi/update.log
sleep 3
systemctl stop nomad-pi
echo "$(date): Service stopped" >> /home/pi/nomad-pi/update.log
sleep 7
systemctl start nomad-pi
echo "$(date): Service start command issued" >> /home/pi/nomad-pi/update.log
sleep 3
if systemctl is-active --quiet nomad-pi; then
    echo "$(date): Service restart successful!" >> /home/pi/nomad-pi/update.log
else
    echo "$(date): First start failed, retrying..." >> /home/pi/nomad-pi/update.log
    sleep 2
    systemctl start nomad-pi
    sleep 2
    if systemctl is-active --quiet nomad-pi; then
        echo "$(date): Service started on retry!" >> /home/pi/nomad-pi/update.log
    else
        echo "$(date): ERROR: Service failed to start!" >> /home/pi/nomad-pi/update.log
    fi
fi
rm -f /tmp/nomad-restart.sh
RESTART_EOF

        chmod +x /tmp/nomad-restart.sh
        echo "Launching deferred restart in background..." >> update.log

        # Use systemd-run if available, otherwise nohup
        if command -v systemd-run >/dev/null 2>&1; then
            sudo systemd-run --unit=nomad-pi-restart --description="Nomad Pi Deferred Restart" /tmp/nomad-restart.sh
            echo "Restart scheduled via systemd-run" >> update.log
        else
            sudo nohup /tmp/nomad-restart.sh >/dev/null 2>&1 &
            echo "Restart scheduled via nohup" >> update.log
        fi

        echo "Update complete. Service will restart in ~10 seconds." >> update.log
    else
        echo "Service file /etc/systemd/system/nomad-pi.service not found. Skipping service restart." >> update.log
    fi
else
    echo "systemctl not found. If running manually, please restart the application." >> update.log
fi
