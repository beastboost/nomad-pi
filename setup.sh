#!/bin/bash

# Nomad Pi Setup Script for Raspberry Pi Zero 2W
# Run this script on your Raspberry Pi to install and configure Nomad Pi.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$SCRIPT_DIR" == /boot* ]]; then
    mkdir -p "$HOME/nomad-pi"
    if command -v rsync >/dev/null 2>&1; then
        sudo rsync -a --delete "$SCRIPT_DIR/app/" "$HOME/nomad-pi/app/" || true
    else
        sudo rm -rf "$HOME/nomad-pi/app" || true
        sudo cp -r "$SCRIPT_DIR/app" "$HOME/nomad-pi/" || true
    fi
    sudo cp -f "$SCRIPT_DIR/setup.sh" "$SCRIPT_DIR/requirements.txt" "$HOME/nomad-pi/" || true
    sudo chown -R "$USER:$USER" "$HOME/nomad-pi"
    exec bash "$HOME/nomad-pi/setup.sh"
fi

# Also move out of /root if we're there, as it causes permission issues for the user
if [[ "$SCRIPT_DIR" == /root* ]]; then
    echo "Detected installation in /root. Moving to $HOME/nomad-pi for better permissions..."
    TARGET_DIR="$HOME/nomad-pi"
    sudo mkdir -p "$TARGET_DIR"
    sudo cp -r "$SCRIPT_DIR/." "$TARGET_DIR/"
    sudo chown -R "$USER:$USER" "$TARGET_DIR"
    echo "Moved to $TARGET_DIR. Restarting setup from new location..."
    cd "$TARGET_DIR"
    exec bash "./setup.sh"
fi

cd "$SCRIPT_DIR"

# Fix Windows line endings for other files just in case
find app -name "*.py" -exec sed -i 's/\r$//' {} +
find . -maxdepth 1 -name "*.txt" -exec sed -i 's/\r$//' {} +
sed -i 's/\r$//' requirements.txt || true

echo "=========================================="
echo "      Nomad Pi Installation Script        "
echo "=========================================="

# 0. Check for Updates
if [ -d ".git" ]; then
    echo "[0/9] Pulling latest changes from GitHub..."
    git pull || echo "Warning: Could not pull latest changes. Continuing with current version."
fi

# 1. System Updates
echo "[1/9] Updating system packages..."
sudo apt-get update
# Removed libatlas-base-dev as it causes issues on newer Debian versions and isn't strictly needed for our pure python usage
# Added ntfs-3g and exfat-fuse for better USB drive support
# Added avahi-daemon for mDNS (nomadpi.local) support
# Added samba and samba-common-bin for file sharing
# Added minidlna for Smart TV support
sudo apt-get install -y python3 python3-pip python3-venv network-manager dos2unix python3-dev ntfs-3g exfat-fuse avahi-daemon samba samba-common-bin minidlna p7zip-full unar libarchive-tools

# 2. Set Hostname (for http://nomadpi.local:8000)
echo "[2/9] Configuring Hostname..."
CURRENT_HOSTNAME=$(cat /etc/hostname | tr -d " \t\n\r")
NEW_HOSTNAME="nomadpi"
if [ "$CURRENT_HOSTNAME" != "$NEW_HOSTNAME" ]; then
    echo "Setting hostname to $NEW_HOSTNAME..."
    sudo hostnamectl set-hostname $NEW_HOSTNAME
    sudo sed -i "s/127.0.1.1.*$CURRENT_HOSTNAME/127.0.1.1\t$NEW_HOSTNAME/g" /etc/hosts || echo "Could not update /etc/hosts, but hostnamectl ran."
    echo "Hostname set to 'nomadpi'. You can access the server at http://nomadpi.local:8000"
fi

# 3. Python Environment
echo "[3/9] Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

echo "Installing Python dependencies..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. Create Directories
echo "[4/9] Ensuring data directories exist..."
mkdir -p data/movies data/shows data/music data/books data/files data/external data/gallery
# Fix permissions to ensure user can write
sudo chown -R $USER:$USER data
sudo chmod -R 775 data

# 5. Systemd Service Setup
echo "[5/9] Configuring systemd service..."

SERVICE_FILE="/etc/systemd/system/nomad-pi.service"
CURRENT_DIR=$(pwd)
USER_NAME=$(whoami)
ENV_FILE="/etc/nomadpi.env"
OMDB_KEY_VALUE="${OMDB_API_KEY:-}"
if [ -f "$ENV_FILE" ]; then
    EXISTING_OMDB_LINE="$(grep -E "^OMDB_API_KEY=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
    if [ -n "$EXISTING_OMDB_LINE" ] && [ -z "$OMDB_KEY_VALUE" ]; then
        OMDB_KEY_VALUE="${EXISTING_OMDB_LINE#OMDB_API_KEY=}"
    fi
fi

if [ -z "$OMDB_KEY_VALUE" ]; then
    read -r -p "Enter OMDb API key (leave blank to skip): " OMDB_KEY_VALUE
fi

sudo bash -c "umask 077; : > \"$ENV_FILE\""
sudo chmod 600 "$ENV_FILE"
if [ -n "$OMDB_KEY_VALUE" ]; then
    sudo bash -c "umask 077; printf 'OMDB_API_KEY=%s\n' \"$OMDB_KEY_VALUE\" > \"$ENV_FILE\""
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
ExecStart=$CURRENT_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop uvloop --http httptools --workers 1
Restart=always

[Install]
WantedBy=multi-user.target
EOL

echo "Enabling and starting service..."
sudo systemctl daemon-reload

# Kill any existing process on port 8000 to avoid conflicts
echo "Stopping any existing processes on port 8000..."
sudo fuser -k 8000/tcp >/dev/null 2>&1 || true

sudo systemctl enable nomad-pi
sudo systemctl restart nomad-pi

# 6. Sudoers Configuration (for Mount/Shutdown/Reboot/Service)
echo "[6/9] Configuring permissions..."
SUDOERS_FILE="/etc/sudoers.d/nomad-pi"
sudo bash -c "cat > $SUDOERS_FILE" <<EOL
$USER_NAME ALL=(ALL) NOPASSWD: /usr/bin/mount, /usr/bin/umount, /usr/sbin/shutdown, /usr/sbin/reboot, /usr/bin/systemctl restart nomad-pi.service, /usr/bin/systemctl restart nomad-pi
EOL
sudo chmod 0440 $SUDOERS_FILE

# 7. Network Configuration (Home Wi-Fi + Hotspot Fallback)
echo "[7/9] Configuring Network..."

if command -v nmcli &> /dev/null; then
    echo "NetworkManager found."
    
    # 7a. Hardcoded Home Wi-Fi Setup (giganet6e)
    HOME_SSID="giganet6e"
    HOME_PASS="Elijah161030"

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
        }
        create_hotspot || echo "Warning: Could not create hotspot (hardware might be missing or busy)."
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
            while IFS=: read -r CON_NAME CON_TYPE; do
                if [ "$CON_TYPE" = "802-11-wireless" ] && [ "$CON_NAME" != "NomadPi" ]; then
                    if sudo nmcli con up "$CON_NAME" >/dev/null 2>&1; then
                        CONNECTED="true"
                        break
                    fi
                fi
            done < <(nmcli -t -f NAME,TYPE connection show)

            if [ "$CONNECTED" != "true" ] && [ -n "$HOME_SSID" ] && [ -n "$HOME_PASS" ]; then
                sudo nmcli dev wifi connect "$HOME_SSID" password "$HOME_PASS" >/dev/null 2>&1 || true
            fi

            sleep 3
            WIFI_STATE=$(nmcli -t -f GENERAL.STATE dev show "$WIFI_DEV" 2>/dev/null | cut -d: -f2 || true)
            IP_ADDR=$(nmcli -t -f IP4.ADDRESS dev show "$WIFI_DEV" 2>/dev/null | head -n 1 | cut -d: -f2 || true)
            if [ "$WIFI_STATE" = "100" ] && [ -n "$IP_ADDR" ]; then
                echo "Wi-Fi connected with IP: $IP_ADDR"
            else
                echo "Wi-Fi not connected, enabling Hotspot 'NomadPi'..."
                sudo nmcli con up "NomadPi" || echo "Warning: Could not enable hotspot."
            fi
        fi
    fi
    fi
else
    echo "NetworkManager not found. Skipping Network setup."
fi

# 8. Samba Configuration (File Sharing)
echo "[8/9] Configuring Samba..."

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
   server string = Nomad Pi
   security = user
   map to guest = Bad User
   dns proxy = no
   server min protocol = SMB2
   client min protocol = SMB2
   ntlm auth = yes
   smb ports = 445
   netbios name = NOMADPI
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
echo "[9/9] Configuring MiniDLNA..."
MINIDLNA_CONF="/etc/minidlna.conf"
sudo bash -c "cat > $MINIDLNA_CONF" <<EOL
media_dir=A,$CURRENT_DIR/data/music
media_dir=V,$CURRENT_DIR/data/movies
media_dir=V,$CURRENT_DIR/data/shows
media_dir=P,$CURRENT_DIR/data/gallery
db_dir=/var/cache/minidlna
log_dir=/var/log
friendly_name=Nomad Pi
inotify=yes
presentation_url=http://nomadpi.local:8000/
EOL

sudo sysctl -w fs.inotify.max_user_watches=100000 >/dev/null
grep -q "^fs\.inotify\.max_user_watches=100000$" /etc/sysctl.conf || echo "fs.inotify.max_user_watches=100000" | sudo tee -a /etc/sysctl.conf >/dev/null

sudo systemctl enable minidlna
sudo systemctl restart minidlna

if [ "${NOMADPI_OVERCLOCK:-1}" = "1" ] && [ "${NOMAD_PI_OVERCLOCK:-1}" = "1" ]; then
    CFG=""
    if [ -f "/boot/firmware/config.txt" ]; then
        CFG="/boot/firmware/config.txt"
    elif [ -f "/boot/config.txt" ]; then
        CFG="/boot/config.txt"
    fi

    if [ -n "$CFG" ]; then
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
            elif [ "$OC_LEVEL" = "perf" ]; then
                OVER_VOLTAGE="4"
            else
                OVER_VOLTAGE="2"
            fi

            if [ -n "${NOMADPI_SDRAM_FREQ:-}" ]; then
                SDRAM_FREQ="${NOMADPI_SDRAM_FREQ}"
            elif [ "$OC_LEVEL" = "perf" ]; then
                SDRAM_FREQ="500"
            fi

            if [ -n "${NOMADPI_OVER_VOLTAGE_SDRAM:-}" ]; then
                OVER_VOLTAGE_SDRAM="${NOMADPI_OVER_VOLTAGE_SDRAM}"
            elif [ "$OC_LEVEL" = "perf" ]; then
                OVER_VOLTAGE_SDRAM="2"
            fi

            TEMP_LIMIT="${NOMADPI_TEMP_LIMIT:-80}"
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
            OVER_VOLTAGE=""
        fi

        if [ -n "$ARM_FREQ" ]; then
            echo "Overclock enabled for: ${MODEL:-Unknown Pi model}"
            grep -q "^arm_freq=" "$CFG" || echo "arm_freq=$ARM_FREQ" | sudo tee -a "$CFG" >/dev/null
            if [ -n "$GPU_FREQ" ]; then
                grep -q "^gpu_freq=" "$CFG" || echo "gpu_freq=$GPU_FREQ" | sudo tee -a "$CFG" >/dev/null
            fi
            if [ -n "$CORE_FREQ" ]; then
                grep -q "^core_freq=" "$CFG" || echo "core_freq=$CORE_FREQ" | sudo tee -a "$CFG" >/dev/null
            fi
            if [ -n "$OVER_VOLTAGE" ]; then
                grep -q "^over_voltage=" "$CFG" || echo "over_voltage=$OVER_VOLTAGE" | sudo tee -a "$CFG" >/dev/null
            fi
            if [ -n "$GPU_MEM" ]; then
                grep -q "^gpu_mem=" "$CFG" || echo "gpu_mem=$GPU_MEM" | sudo tee -a "$CFG" >/dev/null
            fi
            if [ -n "$SDRAM_FREQ" ]; then
                grep -q "^sdram_freq=" "$CFG" || echo "sdram_freq=$SDRAM_FREQ" | sudo tee -a "$CFG" >/dev/null
            fi
            if [ -n "$OVER_VOLTAGE_SDRAM" ]; then
                grep -q "^over_voltage_sdram=" "$CFG" || echo "over_voltage_sdram=$OVER_VOLTAGE_SDRAM" | sudo tee -a "$CFG" >/dev/null
            fi
            if [ -n "$TEMP_LIMIT" ]; then
                grep -q "^temp_limit=" "$CFG" || echo "temp_limit=$TEMP_LIMIT" | sudo tee -a "$CFG" >/dev/null
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
echo "Access via Web: http://nomadpi.local:8000 or http://$(hostname -I | awk '{print $1}'):8000"
echo "Access via SMB: \\\\nomadpi.local\\data (User: $USER_NAME, Pass: $SAMBA_PASS)"
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
echo "To check status: sudo systemctl status nomadpi"
echo "=========================================="
