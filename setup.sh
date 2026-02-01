#!/bin/bash

# Nomad Pi Setup Script for Raspberry Pi Zero 2W
# Run this script on your Raspberry Pi to install and configure Nomad Pi.

set -e

# Correctly identify the real user even if run with sudo
REAL_USER=${SUDO_USER:-$USER}
REAL_HOME=$(eval echo "~$REAL_USER" 2>/dev/null || echo "$HOME")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$SCRIPT_DIR" == /boot* ]]; then
    mkdir -p "$REAL_HOME/nomad-pi"
    if command -v rsync >/dev/null 2>&1; then
        sudo rsync -a --delete "$SCRIPT_DIR/app/" "$REAL_HOME/nomad-pi/app/" || true
    else
        sudo rm -rf "$REAL_HOME/nomad-pi/app" || true
        sudo cp -r "$SCRIPT_DIR/app" "$REAL_HOME/nomad-pi/" || true
    fi
    sudo cp -f "$SCRIPT_DIR/setup.sh" "$SCRIPT_DIR/update.sh" "$SCRIPT_DIR/requirements.txt" "$REAL_HOME/nomad-pi/" || true
    sudo chown -R "$REAL_USER:$REAL_USER" "$REAL_HOME/nomad-pi"
    sudo chmod +x "$REAL_HOME/nomad-pi/setup.sh" "$REAL_HOME/nomad-pi/update.sh"
    exec bash "$REAL_HOME/nomad-pi/setup.sh"
fi

# Also move out of /root if we're there, as it causes permission issues for the user
if [[ "$SCRIPT_DIR" == /root* ]]; then
    echo "Detected installation in /root. Moving to $REAL_HOME/nomad-pi for better permissions..."
    TARGET_DIR="$REAL_HOME/nomad-pi"
    sudo mkdir -p "$TARGET_DIR"
    sudo cp -r "$SCRIPT_DIR/." "$TARGET_DIR/"
    sudo chown -R "$REAL_USER:$REAL_USER" "$TARGET_DIR"
    sudo chmod +x "$TARGET_DIR/setup.sh" "$TARGET_DIR/update.sh"
    echo "Moved to $TARGET_DIR. Restarting setup from new location..."
    cd "$TARGET_DIR"
    exec bash "./setup.sh"
fi

cd "$SCRIPT_DIR"
CURRENT_DIR=$(pwd)

# Ensure all scripts are executable and have correct line endings
chmod +x *.sh 2>/dev/null || true
find . -name "*.sh" -exec chmod +x {} +
find app -name "*.py" -exec sed -i 's/\r$//' {} +
find . -maxdepth 1 -name "*.txt" -exec sed -i 's/\r$//' {} +
sed -i 's/\r$//' requirements.txt || true

# 0. System Tuning (Inotify limits for MiniDLNA and Ingest Service)
echo "Tuning system for media streaming..."
if ! grep -q "fs.inotify.max_user_watches" /etc/sysctl.conf; then
    echo "Increasing inotify watch limit..."
    echo "fs.inotify.max_user_watches=100000" | sudo tee -a /etc/sysctl.conf
    sudo sysctl -p
fi

# Ensure home directory is traversable by services (minidlna, etc)
sudo chmod o+x "$REAL_HOME" 2>/dev/null || true

echo "=========================================="
echo "      Nomad Pi Installation Script        "
echo "=========================================="

# 0. Check for Updates and Fix Git Remote
if [ -d ".git" ]; then
    echo "[0/10] Optimizing Git configuration..."
    
    GIT_PREFIX=()
    if [ "$(id -u)" = "0" ] && [ -n "$REAL_USER" ] && id "$REAL_USER" >/dev/null 2>&1; then
        GIT_PREFIX=(sudo -u "$REAL_USER")
    fi

    if [ "$(id -u)" = "0" ] && [ -n "$REAL_USER" ] && id "$REAL_USER" >/dev/null 2>&1; then
        if [ -d "$SCRIPT_DIR/.git" ]; then
            sudo chown -R "$REAL_USER:$REAL_USER" "$SCRIPT_DIR/.git" 2>/dev/null || true
        fi
    fi

    "${GIT_PREFIX[@]}" git config --global --add safe.directory "$SCRIPT_DIR" 2>/dev/null || true

    # Refined Git config for stability on Pi OS (GnuTLS handshake workarounds)
    "${GIT_PREFIX[@]}" git config --global --unset http.sslBackend 2>/dev/null || true
    "${GIT_PREFIX[@]}" git config --global http.sslVerify true
    "${GIT_PREFIX[@]}" git config --global http.version HTTP/1.1
    "${GIT_PREFIX[@]}" git config --global http.postBuffer 52428800
    # Memory optimizations for Git on Pi Zero
    "${GIT_PREFIX[@]}" git config --global pack.windowMemory "10m"
    "${GIT_PREFIX[@]}" git config --global pack.packSizeLimit "20m"
    "${GIT_PREFIX[@]}" git config --global core.packedGitLimit "20m"
    "${GIT_PREFIX[@]}" git config --global core.packedGitWindowSize "10m"
    
    "${GIT_PREFIX[@]}" git remote set-url origin https://github.com/beastboost/nomad-pi.git
    "${GIT_PREFIX[@]}" git config credential.helper 'cache --timeout=2592000'
    
    echo "Pulling latest changes from GitHub..."
    AUTOSTASH_NAME=""
    if ! "${GIT_PREFIX[@]}" git diff --quiet 2>/dev/null || ! "${GIT_PREFIX[@]}" git diff --cached --quiet 2>/dev/null; then
        AUTOSTASH_NAME="setup-autostash-$(date +%Y%m%d-%H%M%S 2>/dev/null || date +%s)"
        "${GIT_PREFIX[@]}" git stash push -u -m "$AUTOSTASH_NAME" >/dev/null 2>&1 || AUTOSTASH_NAME=""
    fi

    if ! "${GIT_PREFIX[@]}" git pull --rebase; then
        echo "Warning: Could not pull latest changes. Continuing with current version."
    fi

    if [ -n "$AUTOSTASH_NAME" ]; then
        if ! "${GIT_PREFIX[@]}" git stash pop >/dev/null 2>&1; then
            echo "Warning: Local changes were stashed as '$AUTOSTASH_NAME' but could not be reapplied automatically."
            echo "Run: git stash list && git stash pop"
        fi
    fi
fi

# 0.1 Proactive Swap Check (Crucial for Pi Zero 512MB RAM)
echo "Checking system memory and power resources..."

# Stop the service if it's running to free up RAM
echo "Stopping nomad-pi service to free up memory..."
sudo systemctl stop nomad-pi 2>/dev/null || true

# Check for under-voltage/throttling (Pi specific)
if command -v vcgencmd >/dev/null 2>&1; then
    THROTTLED=$(vcgencmd get_throttled | cut -d= -f2)
    if [ "$THROTTLED" != "0x0" ]; then
        echo "WARNING: Your Pi is reporting throttling/under-voltage ($THROTTLED)!"
        echo "This is a major cause of crashes during setup. Please check your power supply."
    fi
fi

TOTAL_SWAP=$(free -m | awk '/Swap/ {print $2}')
if [ "$TOTAL_SWAP" -lt 1000 ]; then
    echo "Total swap ($TOTAL_SWAP MB) is less than 1GB. Increasing swap to prevent OOM crashes..."
    if [ -f /etc/dphys-swapfile ]; then
        sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile
        sudo dphys-swapfile setup
        sudo dphys-swapfile swapon
        echo "Swap increased to 1GB."
    else
        echo "Creating temporary 1GB swap file..."
        sudo dd if=/dev/zero of=/var/swap.tmp bs=1M count=1024
        sudo mkswap /var/swap.tmp
        sudo swapon /var/swap.tmp
        echo "Temporary swap enabled."
    fi
fi

# 1. System Updates
echo "[1/10] Checking system packages..."
PACKAGES="python3 python3-pip python3-venv network-manager dos2unix python3-dev ntfs-3g exfat-fuse avahi-daemon samba samba-common-bin minidlna p7zip-full unar libarchive-tools curl ffmpeg"
MISSING_PACKAGES=""

for pkg in $PACKAGES; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
    fi
done

if [ -n "$MISSING_PACKAGES" ]; then
    echo "Installing missing packages: $MISSING_PACKAGES"
    # Only update if we actually need to install something
    if ! sudo apt-get install -y $MISSING_PACKAGES; then
        echo "Install failed, updating package list and trying again..."
        sudo apt-get update
        sudo apt-get install -y $MISSING_PACKAGES
    fi
else
    echo "All system packages are already installed."
fi

# 2. Set Hostname (for http://nomadpi.local:8000)
echo "[2/10] Configuring Hostname and mDNS..."
CURRENT_HOSTNAME=$(cat /etc/hostname | tr -d " \t\n\r")
NEW_HOSTNAME="nomadpi"
if [ "$CURRENT_HOSTNAME" != "$NEW_HOSTNAME" ]; then
    echo "Setting hostname to $NEW_HOSTNAME..."
    sudo hostnamectl set-hostname $NEW_HOSTNAME
    sudo sed -i "s/127.0.1.1.*$CURRENT_HOSTNAME/127.0.1.1\t$NEW_HOSTNAME/g" /etc/hosts || echo "Could not update /etc/hosts, but hostnamectl ran."
fi

# Ensure Avahi is running and configured for nomadpi.local
sudo systemctl enable avahi-daemon
sudo systemctl restart avahi-daemon
echo "Hostname set to 'nomadpi'. You can access the server at http://nomadpi.local:8000"

# 3. Python Environment
echo "[3/10] Setting up Python environment..."

VENV_PREFIX=()
if [ "$(id -u)" = "0" ] && [ -n "$REAL_USER" ] && id "$REAL_USER" >/dev/null 2>&1; then
    VENV_PREFIX=(sudo -u "$REAL_USER")
fi

# Check if venv exists but is broken (e.g. moved from /root)
if [ -d "venv" ]; then
    # Check if the python interpreter inside venv is accessible and in the right place
    VENV_PYTHON_PATH=$(readlink -f ./venv/bin/python3 2>/dev/null || true)
    if [[ -n "$VENV_PYTHON_PATH" && "$VENV_PYTHON_PATH" != "$SCRIPT_DIR"* ]]; then
        echo "Virtual environment appears to be moved or broken (Points to $VENV_PYTHON_PATH). Recreating..."
        rm -rf venv
    fi
fi

if [ ! -d "venv" ]; then
    "${VENV_PREFIX[@]}" python3 -m venv venv
fi

if [ "$(id -u)" = "0" ] && [ -n "$REAL_USER" ] && id "$REAL_USER" >/dev/null 2>&1; then
    sudo chown -R "$REAL_USER:$REAL_USER" "$CURRENT_DIR/venv" 2>/dev/null || true
fi

echo "Checking Python dependencies..."
# Use a hash to skip pip install if requirements haven't changed
REQ_HASH_FILE="data/.req_hash"
mkdir -p data
CURRENT_HASH=$(md5sum requirements.txt | cut -d' ' -f1)
PREV_HASH=""
if [ -f "$REQ_HASH_FILE" ]; then
    PREV_HASH=$(cat "$REQ_HASH_FILE")
fi

if [ "$CURRENT_HASH" != "$PREV_HASH" ] || [ ! -f "venv/bin/activate" ]; then
    echo "Installing/Updating Python dependencies (this may take a while on Pi Zero)..."
    "${VENV_PREFIX[@]}" ./venv/bin/python3 -m pip install --upgrade pip
    
    # Split installation into chunks to avoid massive memory spikes
    echo "Installing base dependencies..."
    "${VENV_PREFIX[@]}" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary fastapi uvicorn psutil
    
    echo "Installing security and utility dependencies..."
    "${VENV_PREFIX[@]}" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary "passlib[bcrypt]" bcrypt==4.0.1 python-multipart aiofiles jinja2 python-jose[cryptography] httpx
    
    echo "Installing remaining requirements..."
    if ! "${VENV_PREFIX[@]}" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary -r requirements.txt; then
        echo "Error: Dependency installation failed even with 1GB swap."
        echo "The Pi Zero 2W may need a reboot or more swap space."
        exit 1
    fi
    
    if ! "${VENV_PREFIX[@]}" ./venv/bin/python3 -c "import uvicorn, passlib" >/dev/null 2>&1; then
        echo "CRITICAL: core Python modules missing. Re-installing requirements..."
        "${VENV_PREFIX[@]}" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary -r requirements.txt
    fi
    
    echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
else
    echo "Dependencies are already up to date."
    if ! "${VENV_PREFIX[@]}" ./venv/bin/python3 -c "import uvicorn, passlib" >/dev/null 2>&1; then
        echo "Detected missing core Python modules in venv. Repairing..."
        "${VENV_PREFIX[@]}" ./venv/bin/python3 -m pip install --upgrade pip
        "${VENV_PREFIX[@]}" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary -r requirements.txt
    fi
fi

# 4. Create Directories
echo "[4/10] Ensuring data directories exist..."
mkdir -p data/movies data/shows data/music data/books data/files data/external data/gallery data/uploads data/cache

# Optimize chown/chmod - only run if needed, and skip data/ for the main pass
echo "Verifying file permissions..."
CURRENT_OWNER=$(stat -c '%U:%G' "$CURRENT_DIR" 2>/dev/null || echo "unknown")
if [ "$CURRENT_OWNER" != "$REAL_USER:$REAL_USER" ]; then
    echo "Updating ownership to $REAL_USER (skipping data/ for speed)..."
    # Find everything except the data directory to avoid I/O hang
    find "$CURRENT_DIR" -maxdepth 1 ! -name "data" ! -name "." -exec sudo chown -R "$REAL_USER:$REAL_USER" {} +
    sudo chown "$REAL_USER:$REAL_USER" "$CURRENT_DIR"
fi

# Ensure data directory permissions are correct
echo "Setting data directory permissions..."
sudo chown -R "$REAL_USER:$REAL_USER" "$CURRENT_DIR/data"
sudo chmod -R 755 "$CURRENT_DIR/data"

# Ensure MiniDLNA user can access the media directories
if id "minidlna" &>/dev/null; then
    echo "Adding minidlna user to $REAL_USER group..."
    sudo usermod -a -G "$REAL_USER" minidlna

    # Get the actual home directory path
    USER_HOME=$(eval echo ~$REAL_USER)

    # CRITICAL: Home directory must have group read+execute for minidlna user to traverse
    # Use 755 (rwxr-xr-x) to allow group and others to read and traverse
    sudo chmod 755 "$USER_HOME" 2>/dev/null || true

    # Make nomad-pi directory traversable and readable
    sudo chmod 755 "$CURRENT_DIR" 2>/dev/null || true

    # Ensure data subdirectories are readable and executable
    sudo chmod -R 755 "$CURRENT_DIR/data" 2>/dev/null || true
fi

# 5. Systemd Service Setup
echo "[5/10] Setting up Systemd service..."

SERVICE_FILE="/etc/systemd/system/nomad-pi.service"
# Use REAL_USER defined in step 4
USER_NAME=$REAL_USER
ENV_FILE="/etc/nomadpi.env"
OMDB_KEY_VALUE="${OMDB_API_KEY:-}"
ADMIN_PASS_VALUE="${ADMIN_PASSWORD:-}"

if [ -f "$ENV_FILE" ]; then
    EXISTING_OMDB_LINE="$(grep -E "^OMDB_API_KEY=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
    if [ -n "$EXISTING_OMDB_LINE" ] && [ -z "$OMDB_KEY_VALUE" ]; then
        OMDB_KEY_VALUE="${EXISTING_OMDB_LINE#OMDB_API_KEY=}"
    fi
    
    EXISTING_PASS_LINE="$(grep -E "^ADMIN_PASSWORD=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
    if [ -n "$EXISTING_PASS_LINE" ] && [ -z "$ADMIN_PASS_VALUE" ]; then
        ADMIN_PASS_VALUE="${EXISTING_PASS_LINE#ADMIN_PASSWORD=}"
    fi
fi

if [ -z "$OMDB_KEY_VALUE" ]; then
    # Use a timeout for the prompt to avoid hanging in headless setup
    echo "Enter OMDb API key (leave blank to skip, auto-skipping in 10s):"
    read -t 10 -r OMDB_KEY_VALUE </dev/tty || OMDB_KEY_VALUE=""
fi

# Set default password if none exists
if [ -z "$ADMIN_PASS_VALUE" ]; then
    ADMIN_PASS_VALUE="nomad"
    echo "No ADMIN_PASSWORD found. Setting default to: nomad"
fi

sudo bash -c "umask 077; : > \"$ENV_FILE\""
sudo chmod 600 "$ENV_FILE"
if [ -n "$OMDB_KEY_VALUE" ]; then
    sudo bash -c "umask 077; printf 'OMDB_API_KEY=%s\n' \"$OMDB_KEY_VALUE\" >> \"$ENV_FILE\""
fi
if [ -n "$ADMIN_PASS_VALUE" ]; then
    sudo bash -c "umask 077; printf 'ADMIN_PASSWORD=%s\n' \"$ADMIN_PASS_VALUE\" >> \"$ENV_FILE\""
fi

# Create service file
sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Nomad Pi Media Server
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$CURRENT_DIR
EnvironmentFile=-$ENV_FILE
ExecStart=$CURRENT_DIR/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOL

echo "Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl reset-failed nomad-pi 2>/dev/null || true

# Only restart if configuration changed or service is not running
if ! systemctl is-active --quiet nomad-pi; then
    echo "Starting nomad-pi service..."
    sudo systemctl enable nomad-pi
    sudo systemctl restart nomad-pi
else
    echo "nomad-pi service is already running. Reloading configuration..."
    sudo systemctl restart nomad-pi
fi

# Wait for service to start and show status with a better loop
echo "Waiting for service to initialize..."
for i in {1..10}; do
    if systemctl is-active --quiet nomad-pi; then
        echo "Nomad Pi service is running."
        break
    fi
    if [ $i -eq 10 ]; then
        echo "ERROR: Nomad Pi service failed to start within 50s."
        echo "Last 20 lines of service logs:"
        sudo journalctl -u nomad-pi -n 20 --no-pager
    fi
    sleep 5
done

# 6. Sudoers Configuration (for Mount/Shutdown/Reboot/Service)
echo "[6/10] Configuring permissions..."

# Detect paths for sudoers to be universal
MOUNT_PATH=$(command -v mount || echo "/usr/bin/mount")
UMOUNT_PATH=$(command -v umount || echo "/usr/bin/umount")
SHUTDOWN_PATH=$(command -v shutdown || echo "/usr/sbin/shutdown")
REBOOT_PATH=$(command -v reboot || echo "/usr/sbin/reboot")
SYSTEMCTL_PATH=$(command -v systemctl || echo "/usr/bin/systemctl")
NMCLI_PATH=$(command -v nmcli || echo "/usr/bin/nmcli")
MINIDLNAD_PATH=$(command -v minidlnad || echo "/usr/sbin/minidlnad")
TAILSCALE_PATH=$(command -v tailscale || echo "/usr/bin/tailscale")
CHOWN_PATH=$(command -v chown || echo "/usr/bin/chown")
CHMOD_PATH=$(command -v chmod || echo "/usr/bin/chmod")

SUDOERS_FILE="/etc/sudoers.d/nomad-pi"
SUDOERS_TMP=$(mktemp)
cat > "$SUDOERS_TMP" <<EOL
$USER_NAME ALL=(ALL) NOPASSWD: $MOUNT_PATH, $UMOUNT_PATH, $SHUTDOWN_PATH, $REBOOT_PATH, $CHOWN_PATH, $CHMOD_PATH, $SYSTEMCTL_PATH restart nomad-pi.service, $SYSTEMCTL_PATH stop nomad-pi.service, $SYSTEMCTL_PATH start nomad-pi.service, $SYSTEMCTL_PATH status nomad-pi.service, $SYSTEMCTL_PATH restart nomad-pi, $NMCLI_PATH, $SYSTEMCTL_PATH restart minidlna, $SYSTEMCTL_PATH restart minidlna.service, $MINIDLNAD_PATH, $TAILSCALE_PATH status*, $TAILSCALE_PATH ip *, $TAILSCALE_PATH up *, $TAILSCALE_PATH down
EOL
if sudo visudo -cf "$SUDOERS_TMP"; then
    sudo cp "$SUDOERS_TMP" "$SUDOERS_FILE"
    sudo chmod 0440 "$SUDOERS_FILE"
else
    echo "ERROR: Generated sudoers file failed validation. Not installing."
fi
rm -f "$SUDOERS_TMP"

# 7. Network Configuration (Home Wi-Fi + Hotspot Fallback)
echo "[7/10] Configuring Network..."

if command -v nmcli &> /dev/null; then
    echo "NetworkManager found."
    
    # 7a. Home Wi-Fi Setup (Optional)
    # To set a home Wi-Fi, set HOME_SSID and HOME_PASS in /etc/nomadpi.env
    HOME_SSID=""
    HOME_PASS=""

    if [ -f "/etc/nomadpi.env" ]; then
        source "/etc/nomadpi.env" 2>/dev/null || true
    fi

    WIFI_DEV="$(nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')"
    if [ -z "$WIFI_DEV" ]; then
        echo "No Wi-Fi device found. Skipping Network setup."
    else

    # 7b. Hotspot Setup (Fallback)
    if nmcli connection show "NomadPi" &> /dev/null; then
        echo "Hotspot 'NomadPi' already exists."
    else
        echo "Creating Hotspot 'NomadPi'..."
        create_hotspot() {
            sudo nmcli con add type wifi ifname "$WIFI_DEV" con-name "NomadPi" autoconnect yes ssid "NomadPi"
            sudo nmcli con modify "NomadPi" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
            sudo nmcli con modify "NomadPi" wifi-sec.key-mgmt wpa-psk
            sudo nmcli con modify "NomadPi" wifi-sec.psk "nomadpassword"
            # Set lower priority for Hotspot so it only activates if Home Wi-Fi fails
            sudo nmcli con modify "NomadPi" connection.autoconnect-priority 0
            # Ensure the hotspot doesn't aggressively take over
            sudo nmcli con modify "NomadPi" connection.autoconnect-retries 1
        }
        create_hotspot || echo "Warning: Could not create hotspot (hardware might be missing or busy)."
    fi

    # Disable WiFi Power Management (Prevents disconnects mid-transfer)
    echo "Disabling WiFi Power Management..."
    sudo iw dev "$WIFI_DEV" set power_save off 2>/dev/null || true
    
    # Make power management change persistent
    if [ -d "/etc/NetworkManager/conf.d" ]; then
        sudo bash -c "cat > /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf" <<EOL
[connection]
wifi.powersave = 2
EOL
    fi

    sudo nmcli networking on >/dev/null 2>&1 || true
    sudo nmcli radio wifi on >/dev/null 2>&1 || true
    if command -v rfkill >/dev/null 2>&1; then
        sudo rfkill unblock wifi >/dev/null 2>&1 || true
    fi
    ACTIVE_WIFI_CON="$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | awk -F: '$2=="802-11-wireless"{print $1; exit}')"
    if [ -n "$ACTIVE_WIFI_CON" ] && [ "$ACTIVE_WIFI_CON" != "NomadPi" ]; then
        echo "Wi-Fi already active via '$ACTIVE_WIFI_CON' (leaving it alone)."
    else
        sudo nmcli con down "NomadPi" >/dev/null 2>&1 || true

        WIFI_STATE=$(nmcli -t -f GENERAL.STATE dev show "$WIFI_DEV" 2>/dev/null | cut -d: -f2 || true)
        IP_ADDR=$(nmcli -t -f IP4.ADDRESS dev show "$WIFI_DEV" 2>/dev/null | head -n 1 | cut -d: -f2 || true)

        if [ "$WIFI_STATE" = "100" ] && [ -n "$IP_ADDR" ]; then
            echo "Wi-Fi already connected with IP: $IP_ADDR"
        else
            CONNECTED="false"
            echo "Attempting to connect to known Wi-Fi networks..."
            # Limit the number of attempts and add a timeout
            COUNT=0
            while IFS=: read -r CON_NAME CON_TYPE; do
                if [ "$CON_TYPE" = "802-11-wireless" ] && [ "$CON_NAME" != "NomadPi" ]; then
                    echo "Trying connection: $CON_NAME"
                    if sudo timeout 20s nmcli con up "$CON_NAME" >/dev/null 2>&1; then
                        CONNECTED="true"
                        break
                    fi
                fi
                COUNT=$((COUNT+1))
                [ $COUNT -ge 5 ] && break # Don't try more than 5 networks
            done < <(nmcli -t -f NAME,TYPE connection show)

            if [ "$CONNECTED" != "true" ] && [ -n "$HOME_SSID" ] && [ -n "$HOME_PASS" ]; then
                echo "Trying home Wi-Fi: $HOME_SSID"
                sudo timeout 30s nmcli dev wifi connect "$HOME_SSID" password "$HOME_PASS" >/dev/null 2>&1 || true
            fi

            sleep 3
            WIFI_STATE=$(nmcli -t -f GENERAL.STATE dev show "$WIFI_DEV" 2>/dev/null | cut -d: -f2 || true)
            IP_ADDR=$(nmcli -t -f IP4.ADDRESS dev show "$WIFI_DEV" 2>/dev/null | head -n 1 | cut -d: -f2 || true)
            if [ "$WIFI_STATE" = "100" ] && [ -n "$IP_ADDR" ]; then
                echo "Wi-Fi connected with IP: $IP_ADDR"
            else
                echo "Wi-Fi not connected, enabling Hotspot 'NomadPi'..."
                sudo timeout 20s nmcli con up "NomadPi" || echo "Warning: Could not enable hotspot."
            fi
        fi
    fi
    fi
else
    echo "NetworkManager not found. Skipping Network setup."
fi

# 8. Samba Configuration (File Sharing)
echo "[8/10] Configuring Samba..."

# Install Samba if not already installed (extra safety check)
if ! dpkg -s samba >/dev/null 2>&1; then
    echo "Installing Samba..."
    sudo apt-get install -y samba samba-common-bin
fi

# Backup existing config if not already backed up
if [ ! -f /etc/samba/smb.conf.bak ]; then
    sudo cp /etc/samba/smb.conf /etc/samba/smb.conf.bak
fi

# Create a simple share config
SAMBA_CONF="/etc/samba/smb.conf"
sudo bash -c "cat > $SAMBA_CONF" <<EOL
[global]
   workgroup = WORKGROUP
   server string = $NEW_HOSTNAME
   security = user
   map to guest = Bad User
   dns proxy = no
   server min protocol = SMB2
   client min protocol = SMB2
   ntlm auth = yes
   smb ports = 445
   netbios name = $(echo $NEW_HOSTNAME | tr '[:lower:]' '[:upper:]')
   wins support = yes

[data]
   path = $CURRENT_DIR/data
   browsable = yes
   writable = yes
   guest ok = no
   read only = no
   create mask = 0775
   directory mask = 0775
   valid users = $USER_NAME
   force user = $USER_NAME
   force group = $USER_NAME
EOL

# Set Samba password for the user (using HOME_PASS 'Elijah161030' as default for convenience, or 'nomad')
# Let's use 'nomad' to match the web login default, or we can prompt. 
# User asked for 'giganet6e' / 'Elijah161030' for wifi. 
# Let's set it to 'nomad' to keep it simple and consistent with default web login, 
# but print it out.
SAMBA_PASS="nomad"
(echo "$SAMBA_PASS"; echo "$SAMBA_PASS") | sudo smbpasswd -a -s $USER_NAME >/dev/null 2>&1 || true

# Ensure Samba service is unmasked, enabled, and restarted
sudo systemctl unmask smbd
sudo systemctl enable smbd
sudo systemctl restart smbd
sudo systemctl unmask nmbd
sudo systemctl enable nmbd
sudo systemctl restart nmbd

# 9. MiniDLNA Configuration (Smart TV Streaming)
echo "[9/10] Configuring MiniDLNA..."

# Ensure MiniDLNA is installed
if ! command -v minidlnad >/dev/null 2>&1; then
    echo "Installing MiniDLNA..."
    sudo apt-get update
    sudo apt-get install -y minidlna
fi

# Set up MiniDLNA cache and log directories with proper permissions
echo "Setting up MiniDLNA cache directories..."
sudo mkdir -p /var/cache/minidlna /var/log/minidlna
sudo chown -R minidlna:minidlna /var/cache/minidlna 2>/dev/null || true
sudo chown -R minidlna:minidlna /var/log/minidlna 2>/dev/null || true

# Fix inotify max_user_watches limit for MiniDLNA file monitoring
# MiniDLNA needs to watch for file changes, increase the limit from default 8192 to 524288
if [ -f /proc/sys/fs/inotify/max_user_watches ]; then
    echo 524288 | sudo tee /proc/sys/fs/inotify/max_user_watches > /dev/null 2>&1 || true
    # Make it persistent across reboots
    if ! grep -q "fs.inotify.max_user_watches" /etc/sysctl.conf 2>/dev/null; then
        echo "fs.inotify.max_user_watches=524288" | sudo tee -a /etc/sysctl.conf > /dev/null 2>&1 || true
    fi
fi

MINIDLNA_CONF="/etc/minidlna.conf"
MINIDLNA_TEMP="/tmp/minidlna.conf.tmp"
cat > "$MINIDLNA_TEMP" <<EOL
# Scan the entire data directory (includes external drives under data/external)
media_dir=$CURRENT_DIR/data

# Database and logging
db_dir=/var/cache/minidlna
log_dir=/var/log/minidlna
log_level=general,artwork,database,inotify,scanner,metadata,http,ssdp,tivo=warn

# Network settings
friendly_name=$NEW_HOSTNAME
port=8200

# File monitoring - scan every 60 seconds for changes
inotify=yes
notify_interval=60

# Container settings - use "." for hierarchical folders
root_container=.

# Presentation
presentation_url=http://$NEW_HOSTNAME.local:8000/
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

# Ensure the data directory is fully accessible to minidlna
echo "Finalizing permissions for MiniDLNA..."
sudo chown -R $REAL_USER:$REAL_USER "$CURRENT_DIR/data"
sudo chmod -R 755 "$CURRENT_DIR/data"

# Only update if config changed
if ! diff -q "$MINIDLNA_TEMP" "$MINIDLNA_CONF" >/dev/null 2>&1; then
    echo "Updating MiniDLNA configuration..."
    sudo cp "$MINIDLNA_TEMP" "$MINIDLNA_CONF"

    # Rebuild database and force rescan
    echo "Rebuilding MiniDLNA database..."
    sudo systemctl stop minidlna 2>/dev/null || true
    sudo rm -f /var/cache/minidlna/files.db
    sudo systemctl enable minidlna
    sudo systemctl start minidlna
    # MiniDLNA will automatically scan on startup when database is missing
else
    echo "MiniDLNA configuration unchanged. Skipping rebuild."
    # Ensure it's running though
    if ! systemctl is-active --quiet minidlna; then
        sudo systemctl enable minidlna
        sudo systemctl start minidlna
    fi
fi
rm -f "$MINIDLNA_TEMP"

# 10. Tailscale VPN Configuration (Remote Access)
echo "[10/10] Installing Tailscale VPN..."

# Check if Tailscale is already installed
if command -v tailscale >/dev/null 2>&1; then
    echo "Tailscale is already installed."
    TAILSCALE_VERSION=$(tailscale version | head -n 1)
    echo "Installed version: $TAILSCALE_VERSION"
else
    echo "Installing Tailscale..."
    # Download and install Tailscale using the official install script
    if curl -fsSL https://tailscale.com/install.sh | sh; then
        echo "Tailscale installed successfully!"
    else
        echo "WARNING: Failed to install Tailscale. You can install it manually later."
        echo "To install manually, run: curl -fsSL https://tailscale.com/install.sh | sh"
    fi
fi

# Check if tailscaled service is running
if systemctl is-active --quiet tailscaled 2>/dev/null; then
    echo "Tailscale service is running."
else
    if command -v tailscale >/dev/null 2>&1; then
        echo "Starting Tailscale service..."
        sudo systemctl enable tailscaled 2>/dev/null || true
        sudo systemctl start tailscaled 2>/dev/null || true
    fi
fi

# Optional non-interactive Tailscale login (set TAILSCALE_AUTHKEY in /etc/nomadpi.env)
if [ -f "/etc/nomadpi.env" ]; then
    source "/etc/nomadpi.env" 2>/dev/null || true
fi
if [ -n "${TAILSCALE_AUTHKEY:-}" ] && command -v tailscale >/dev/null 2>&1; then
    if ! sudo -n tailscale status >/dev/null 2>&1; then
        sudo -n tailscale up --authkey "$TAILSCALE_AUTHKEY" --hostname "$NEW_HOSTNAME" >/dev/null 2>&1 || true
    fi
fi

echo "Tailscale setup complete. You can configure it from the web admin panel under Settings."
echo "To connect manually: sudo tailscale up"
echo "To check status: sudo tailscale status"

if [ "${NOMADPI_OVERCLOCK:-1}" = "1" ] && [ "${NOMAD_PI_OVERCLOCK:-1}" = "1" ]; then
    CFG=""
    if [ -f "/boot/firmware/config.txt" ]; then
        CFG="/boot/firmware/config.txt"
    elif [ -f "/boot/config.txt" ]; then
        CFG="/boot/config.txt"
    fi

    if [ -n "$CFG" ]; then
        set_boot_cfg() {
            local k="$1"
            local v="$2"
            local f="$3"

            if sudo grep -Eq "^[#[:space:]]*${k}=" "$f"; then
                sudo sed -i -E "s|^[#[:space:]]*${k}=.*|${k}=${v}|g" "$f"
            else
                echo "${k}=${v}" | sudo tee -a "$f" >/dev/null
            fi
        }

        MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"

        ARM_FREQ=""
        GPU_FREQ=""
        CORE_FREQ=""
        OVER_VOLTAGE=""
        GPU_MEM=""
        SDRAM_FREQ=""
        OVER_VOLTAGE_SDRAM=""
        TEMP_LIMIT=""

        if echo "$MODEL" | grep -qi "Raspberry Pi Zero 2"; then
            OC_LEVEL="${NOMADPI_OC_LEVEL:-${NOMAD_PI_OC_LEVEL:-perf}}"
            if [ -n "${NOMADPI_ARM_FREQ:-}" ]; then
                ARM_FREQ="${NOMADPI_ARM_FREQ}"
            elif [ "$OC_LEVEL" = "safe" ]; then
                ARM_FREQ="1100"
            elif [ "$OC_LEVEL" = "perf" ]; then
                ARM_FREQ="1200"
            else
                ARM_FREQ="1200"
            fi

            GPU_MEM="${NOMADPI_GPU_MEM:-}"

            GPU_FREQ="${NOMADPI_GPU_FREQ:-500}"
            CORE_FREQ="${NOMADPI_CORE_FREQ:-500}"

            if [ -n "${NOMADPI_OVER_VOLTAGE:-}" ]; then
                OVER_VOLTAGE="${NOMADPI_OVER_VOLTAGE}"
            else
                OVER_VOLTAGE="2"
            fi

            if [ -n "${NOMADPI_SDRAM_FREQ:-}" ]; then
                SDRAM_FREQ="${NOMADPI_SDRAM_FREQ}"
            else
                SDRAM_FREQ="500"
            fi

            if [ -n "${NOMADPI_OVER_VOLTAGE_SDRAM:-}" ]; then
                OVER_VOLTAGE_SDRAM="${NOMADPI_OVER_VOLTAGE_SDRAM}"
            else
                OVER_VOLTAGE_SDRAM="2"
            fi

            TEMP_LIMIT="${NOMADPI_TEMP_LIMIT:-80}"
        elif echo "$MODEL" | grep -qi "Raspberry Pi 5"; then
            echo "Raspberry Pi 5 detected. Using default frequencies (high performance)."
            ARM_FREQ="" # Pi 5 is fast enough, don't force OC by default
        elif echo "$MODEL" | grep -qi "Raspberry Pi 4"; then
            ARM_FREQ="1750"
            GPU_FREQ="600"
            OVER_VOLTAGE="2"
        elif echo "$MODEL" | grep -qi "Raspberry Pi 3 Model B Plus"; then
            ARM_FREQ="1450"
            GPU_FREQ="500"
            OVER_VOLTAGE="2"
        elif echo "$MODEL" | grep -qi "Raspberry Pi 3"; then
            ARM_FREQ="1300"
            GPU_FREQ="450"
            OVER_VOLTAGE="2"
        else
            echo "Non-Raspberry Pi or unknown model detected ($MODEL)."
            echo "Skipping hardware-specific optimizations (Overclocking/config.txt)."
            ARM_FREQ=""
            OVER_VOLTAGE=""
        fi

        if [ -n "$ARM_FREQ" ]; then
            echo "Overclock enabled for: ${MODEL:-Unknown Pi model}"
            set_boot_cfg "arm_freq" "$ARM_FREQ" "$CFG"
            if [ -n "$GPU_FREQ" ]; then
                set_boot_cfg "gpu_freq" "$GPU_FREQ" "$CFG"
            fi
            if [ -n "$CORE_FREQ" ]; then
                set_boot_cfg "core_freq" "$CORE_FREQ" "$CFG"
            fi
            if [ -n "$OVER_VOLTAGE" ]; then
                set_boot_cfg "over_voltage" "$OVER_VOLTAGE" "$CFG"
            fi
            if [ -n "$GPU_MEM" ]; then
                set_boot_cfg "gpu_mem" "$GPU_MEM" "$CFG"
            fi
            if [ -n "$SDRAM_FREQ" ]; then
                set_boot_cfg "sdram_freq" "$SDRAM_FREQ" "$CFG"
            fi
            if [ -n "$OVER_VOLTAGE_SDRAM" ]; then
                set_boot_cfg "over_voltage_sdram" "$OVER_VOLTAGE_SDRAM" "$CFG"
            fi
            if [ -n "$TEMP_LIMIT" ]; then
                set_boot_cfg "temp_limit" "$TEMP_LIMIT" "$CFG"
            fi
            echo "Overclock settings written to $CFG. Reboot required."
        else
            echo "Overclock enabled, but Pi model not recognized. Skipping config changes."
        fi
    else
        echo "Overclock enabled, but config.txt not found. Skipping."
    fi
fi

echo "=========================================="
echo "      Installation Complete!              "
echo "=========================================="
echo "Access via Web: http://$NEW_HOSTNAME.local:8000 or http://$(hostname -I | awk '{print $1}'):8000"
echo "Access via SMB: \\\\$NEW_HOSTNAME.local\\data (User: $USER_NAME, Pass: $SAMBA_PASS)"
echo "Wifi: Tries '$HOME_SSID' first, then falls back to Hotspot 'NomadPi'."
echo "Please reboot to ensure all services start correctly: sudo reboot"

# Final Info
IP_ADDR=$(hostname -I | awk '{print $1}')
echo "=========================================="
echo "          Setup Complete!                 "
echo "=========================================="
echo "Nomad Pi is running."
echo "Access the interface at: http://$IP_ADDR:8000"
echo "Or connect to Wi-Fi 'NomadPi' (pass: nomadpassword) and go to http://10.42.0.1:8000"
echo ""
echo "Default Web Admin Password: nomad"
echo "Please change this in the Settings panel immediately."
echo "To check status: sudo systemctl status nomad-pi"
echo "=========================================="
