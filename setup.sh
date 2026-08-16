#!/bin/bash
# Nomad Pi host installer for Debian-family Linux appliances and SBCs.
# Hardware-specific tuning is capability/board gated; Raspberry Pi is no longer
# assumed to be the host platform.

set -Eeuo pipefail

REAL_USER="${SUDO_USER:-${USER:-$(id -un)}}"
REAL_HOME="$(getent passwd "$REAL_USER" 2>/dev/null | cut -d: -f6)"
REAL_HOME="${REAL_HOME:-$HOME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Boot-media installs should become normal writable installs before doing any
# package/service work. Copy the repository rather than a Pi-specific subset so
# shared scripts and future platform adapters are not silently omitted.
if [[ "$SCRIPT_DIR" == /boot* ]]; then
    TARGET_DIR="$REAL_HOME/nomad-pi"
    echo "Boot-media install detected. Copying Nomad to $TARGET_DIR..."
    sudo mkdir -p "$TARGET_DIR"
    if command -v rsync >/dev/null 2>&1; then
        sudo rsync -a --exclude 'venv/' --exclude 'data/' "$SCRIPT_DIR/" "$TARGET_DIR/"
    else
        sudo cp -a "$SCRIPT_DIR/." "$TARGET_DIR/"
        sudo rm -rf "$TARGET_DIR/venv" 2>/dev/null || true
    fi
    sudo chown -R "$REAL_USER:$REAL_USER" "$TARGET_DIR"
    exec bash "$TARGET_DIR/setup.sh"
fi

if [[ "$SCRIPT_DIR" == /root* ]] && [ "$REAL_USER" != "root" ]; then
    TARGET_DIR="$REAL_HOME/nomad-pi"
    echo "Installation under /root detected. Moving Nomad to $TARGET_DIR..."
    sudo mkdir -p "$TARGET_DIR"
    sudo cp -a "$SCRIPT_DIR/." "$TARGET_DIR/"
    sudo chown -R "$REAL_USER:$REAL_USER" "$TARGET_DIR"
    exec bash "$TARGET_DIR/setup.sh"
fi

cd "$SCRIPT_DIR"
CURRENT_DIR="$SCRIPT_DIR"
NOMAD_ROOT="$CURRENT_DIR"

if [ ! -f "$CURRENT_DIR/scripts/install-common.sh" ]; then
    echo "ERROR: scripts/install-common.sh is missing. Pull the latest Nomad repository and retry." >&2
    exit 1
fi
# shellcheck disable=SC1091
. "$CURRENT_DIR/scripts/install-common.sh"
if [ -f "$CURRENT_DIR/scripts/network-appliance.sh" ]; then
    # shellcheck disable=SC1091
    . "$CURRENT_DIR/scripts/network-appliance.sh"
fi

nomad_require_host

echo "============================================================"
echo "                    Nomad Pi Setup"
echo "============================================================"
nomad_print_install_profile
echo "============================================================"

chmod +x ./*.sh scripts/*.sh 2>/dev/null || true
find app -name '*.py' -exec sed -i 's/\r$//' {} + 2>/dev/null || true

# Shared file-watcher capacity for MiniDLNA/library ingest.
if [ -f /proc/sys/fs/inotify/max_user_watches ]; then
    if ! grep -q '^fs.inotify.max_user_watches=' /etc/sysctl.conf 2>/dev/null; then
        echo 'fs.inotify.max_user_watches=524288' | nomad_sudo tee -a /etc/sysctl.conf >/dev/null
    fi
    nomad_sudo sysctl -w fs.inotify.max_user_watches=524288 >/dev/null 2>&1 || true
fi

nomad_sudo chmod o+x "$REAL_HOME" 2>/dev/null || true

# Keep the service stopped during dependency work on low-memory boxes.
nomad_sudo systemctl stop nomad-pi 2>/dev/null || true
nomad_check_board_health
nomad_ensure_swap

# Git configuration is sized from detected memory rather than a Pi Zero label.
if [ -d .git ]; then
    if [ "$(id -u)" -eq 0 ] && [ "$REAL_USER" != "root" ]; then
        nomad_sudo chown -R "$REAL_USER:$REAL_USER" .git 2>/dev/null || true
    fi
    nomad_configure_git "$REAL_USER" "$CURRENT_DIR"
    nomad_as_user "$REAL_USER" git remote set-url origin https://github.com/beastboost/nomad-pi.git 2>/dev/null || true
    nomad_as_user "$REAL_USER" git config credential.helper 'cache --timeout=2592000' 2>/dev/null || true

    echo "Checking for repository updates..."
    AUTOSTASH_NAME=""
    if ! nomad_as_user "$REAL_USER" git diff --quiet 2>/dev/null || ! nomad_as_user "$REAL_USER" git diff --cached --quiet 2>/dev/null; then
        AUTOSTASH_NAME="setup-autostash-$(date +%Y%m%d-%H%M%S)"
        nomad_as_user "$REAL_USER" git stash push -u -m "$AUTOSTASH_NAME" >/dev/null 2>&1 || AUTOSTASH_NAME=""
    fi
    nomad_as_user "$REAL_USER" git pull --rebase || echo "WARNING: Git pull failed; continuing with the checked-out version."
    if [ -n "$AUTOSTASH_NAME" ]; then
        nomad_as_user "$REAL_USER" git stash pop >/dev/null 2>&1 || echo "WARNING: local changes remain stashed as $AUTOSTASH_NAME"
    fi
fi

# Refresh shared helpers after pull in case platform/install code changed.
# shellcheck disable=SC1091
. "$CURRENT_DIR/scripts/install-common.sh"
if [ -f "$CURRENT_DIR/scripts/network-appliance.sh" ]; then
    # shellcheck disable=SC1091
    . "$CURRENT_DIR/scripts/network-appliance.sh"
fi
nomad_detect_platform 2>/dev/null || true

# Debian/Radxa OS/Ubuntu package path. Optional archive/filesystem package names
# are handled as alternatives by the common installer.
echo "[1/10] System dependencies"
nomad_install_packages

# Nomad's product hostname is `nomad`, so the stable user-facing address is
# http://nomad.local on both Raspberry Pi and Radxa. Avahi also advertises the
# HTTP/SMB services explicitly; the port-80 helper redirects to the app on 8000.
echo "[2/10] Hostname and mDNS"
ENV_FILE="/etc/nomadpi.env"
STORED_HOSTNAME="$(nomad_get_env_key "$ENV_FILE" NOMAD_HOSTNAME)"
NEW_HOSTNAME="${NOMAD_HOSTNAME_OVERRIDE:-${STORED_HOSTNAME:-nomad}}"
if declare -F nomad_configure_hostname_mdns >/dev/null 2>&1; then
    nomad_configure_hostname_mdns "$NEW_HOSTNAME"
fi
NEW_HOSTNAME="$(hostname 2>/dev/null || printf '%s' "$NEW_HOSTNAME")"

# Python environment. Install as the actual service account even when setup was
# launched with sudo/root so future web updates do not inherit root-owned venvs.
echo "[3/10] Python environment"
if [ -d venv ]; then
    VENV_PYTHON_PATH="$(readlink -f venv/bin/python3 2>/dev/null || true)"
    if [ -n "$VENV_PYTHON_PATH" ] && [[ "$VENV_PYTHON_PATH" != "$CURRENT_DIR"* ]]; then
        echo "Moved/broken virtual environment detected; recreating it."
        rm -rf venv
    fi
fi
if [ ! -d venv ]; then
    nomad_as_user "$REAL_USER" python3 -m venv venv
fi
nomad_sudo chown -R "$REAL_USER:$REAL_USER" venv 2>/dev/null || true

mkdir -p data
REQ_HASH_FILE="data/.req_hash"
CURRENT_HASH="$(md5sum requirements.txt | awk '{print $1}')"
PREV_HASH="$(cat "$REQ_HASH_FILE" 2>/dev/null || true)"
if [ "$CURRENT_HASH" != "$PREV_HASH" ] || [ ! -x venv/bin/uvicorn ]; then
    echo "Installing Python dependencies (${NOMAD_MEMORY_CLASS:-unknown}-memory profile)..."
    nomad_as_user "$REAL_USER" ./venv/bin/python3 -m pip install --upgrade pip
    # Chunking remains useful on 1 GB-class machines such as the Cubie A7Z.
    nomad_as_user "$REAL_USER" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary fastapi uvicorn psutil
    nomad_as_user "$REAL_USER" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary 'passlib[bcrypt]' bcrypt==4.0.1 python-multipart aiofiles jinja2 'python-jose[cryptography]' httpx
    nomad_as_user "$REAL_USER" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary -r requirements.txt
    printf '%s\n' "$CURRENT_HASH" > "$REQ_HASH_FILE"
fi
if ! nomad_as_user "$REAL_USER" ./venv/bin/python3 -c 'import uvicorn, passlib, fastapi' >/dev/null 2>&1; then
    echo "ERROR: Python environment validation failed." >&2
    exit 1
fi

# Media roots. Do not recursively chown data/external: an attached multi-TB
# drive must not be walked just because setup was rerun.
echo "[4/10] Media directories and permissions"
mkdir -p data/movies data/shows data/music data/books data/files data/external data/gallery data/uploads data/cache data/.nomad_cache
nomad_sudo chown "$REAL_USER:$REAL_USER" data
for dir in data/movies data/shows data/music data/books data/files data/external data/gallery data/uploads data/cache data/.nomad_cache; do
    nomad_sudo chown "$REAL_USER:$REAL_USER" "$dir" 2>/dev/null || true
    nomad_sudo chmod 755 "$dir" 2>/dev/null || true
done
nomad_sudo chmod 755 "$CURRENT_DIR" "$REAL_HOME" 2>/dev/null || true
if id minidlna >/dev/null 2>&1; then
    nomad_sudo usermod -a -G "$REAL_USER" minidlna 2>/dev/null || true
fi

# Preserve the environment file. Older setup truncated it and accidentally
# discarded unrelated HOME_SSID/TAILSCALE/etc values on reruns.
echo "[5/10] Service configuration"
OMDB_KEY_VALUE="${OMDB_API_KEY:-$(nomad_get_env_key "$ENV_FILE" OMDB_API_KEY)}"
ADMIN_PASS_VALUE="${ADMIN_PASSWORD:-$(nomad_get_env_key "$ENV_FILE" ADMIN_PASSWORD)}"
if [ -z "$OMDB_KEY_VALUE" ] && [ -t 0 ]; then
    read -r -t 10 -p 'OMDb API key (optional, Enter to skip): ' OMDB_KEY_VALUE || OMDB_KEY_VALUE=""
fi
if [ -z "$ADMIN_PASS_VALUE" ]; then
    ADMIN_PASS_VALUE="nomad"
    echo "No existing admin password found; initial password is 'nomad'. Change it after login."
fi
nomad_sudo touch "$ENV_FILE"
nomad_sudo chmod 600 "$ENV_FILE"
[ -n "$OMDB_KEY_VALUE" ] && nomad_set_env_key "$ENV_FILE" OMDB_API_KEY "$OMDB_KEY_VALUE"
nomad_set_env_key "$ENV_FILE" ADMIN_PASSWORD "$ADMIN_PASS_VALUE"
nomad_set_env_key "$ENV_FILE" NOMAD_HOSTNAME "$NEW_HOSTNAME"

# Write detected platform into the service environment for diagnostics/logging.
nomad_set_env_key "$ENV_FILE" NOMAD_BOARD_FAMILY "${NOMAD_BOARD_FAMILY:-generic-linux}"
nomad_set_env_key "$ENV_FILE" NOMAD_MEMORY_CLASS "${NOMAD_MEMORY_CLASS:-unknown}"

STAMP="$(git -C "$CURRENT_DIR" rev-parse --short HEAD 2>/dev/null || date +%s)"
echo "Stamping browser assets with $STAMP..."
nomad_stamp_assets "$CURRENT_DIR" "$STAMP"
if [ -x scripts/vendor-assets.sh ]; then
    bash scripts/vendor-assets.sh || true
fi
nomad_install_wifi_guard "$CURRENT_DIR"

SERVICE_FILE="/etc/systemd/system/nomad-pi.service"
SERVICE_TMP="$(mktemp)"
cat > "$SERVICE_TMP" <<EOF
[Unit]
Description=Nomad Pi Media Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$CURRENT_DIR
EnvironmentFile=-$ENV_FILE
ExecStart=$CURRENT_DIR/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 300
Restart=always
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
nomad_sudo install -m 644 "$SERVICE_TMP" "$SERVICE_FILE"
rm -f "$SERVICE_TMP"
nomad_sudo systemctl daemon-reload
nomad_sudo systemctl enable nomad-pi.service

# Web-admin system controls currently require broad privileged operations. Keep
# the existing behaviour, but validate the generated sudoers file atomically.
echo "[6/10] Web-admin permissions"
SUDOERS_TMP="$(mktemp)"
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$REAL_USER" > "$SUDOERS_TMP"
if nomad_sudo visudo -cf "$SUDOERS_TMP" >/dev/null; then
    nomad_sudo install -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/nomad-pi
else
    echo "ERROR: generated sudoers policy failed validation." >&2
    rm -f "$SUDOERS_TMP"
    exit 1
fi
rm -f "$SUDOERS_TMP"

# NetworkManager setup is hardware-capability based: servers without Wi-Fi are
# simply left alone; SBCs with Wi-Fi receive the optional fallback hotspot.
echo "[7/10] Network"
HOME_SSID="$(nomad_get_env_key "$ENV_FILE" HOME_SSID)"
HOME_PASS="$(nomad_get_env_key "$ENV_FILE" HOME_PASS)"
if command -v nmcli >/dev/null 2>&1; then
    WIFI_DEV="$(nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi" {print $1; exit}')"
    if [ -n "$WIFI_DEV" ]; then
        nomad_sudo nmcli networking on >/dev/null 2>&1 || true
        nomad_sudo nmcli radio wifi on >/dev/null 2>&1 || true
        command -v rfkill >/dev/null 2>&1 && nomad_sudo rfkill unblock wifi >/dev/null 2>&1 || true
        command -v iw >/dev/null 2>&1 && nomad_sudo iw dev "$WIFI_DEV" set power_save off >/dev/null 2>&1 || true
        nomad_sudo mkdir -p /etc/NetworkManager/conf.d
        printf '[connection]\nwifi.powersave = 2\n' | nomad_sudo tee /etc/NetworkManager/conf.d/nomad-wifi-powersave.conf >/dev/null

        ACTIVE_WIFI="$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | awk -F: '$2=="802-11-wireless" {print $1; exit}')"
        if [ -z "$ACTIVE_WIFI" ] && [ -n "$HOME_SSID" ] && [ -n "$HOME_PASS" ]; then
            echo "Trying configured home Wi-Fi '$HOME_SSID'..."
            nomad_sudo timeout 30s nmcli dev wifi connect "$HOME_SSID" password "$HOME_PASS" >/dev/null 2>&1 || true
            ACTIVE_WIFI="$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | awk -F: '$2=="802-11-wireless" {print $1; exit}')"
        fi

        if declare -F nomad_configure_hotspot_profile >/dev/null 2>&1; then
            nomad_configure_hotspot_profile "$CURRENT_DIR" "$WIFI_DEV"
        fi
        if [ -z "$ACTIVE_WIFI" ]; then
            nomad_sudo timeout 20s nmcli con up "${NOMAD_HOTSPOT_NAME:-NomadPi}" >/dev/null 2>&1 || echo "WARNING: fallback hotspot could not be started."
        else
            echo "Leaving active Wi-Fi '$ACTIVE_WIFI' connected."
        fi
    else
        echo "No Wi-Fi interface detected; skipping hotspot setup."
    fi
fi

# Samba file sharing.
echo "[8/10] Samba"
SAMBA_CONF="/etc/samba/smb.conf"
[ -f "$SAMBA_CONF" ] && [ ! -f "$SAMBA_CONF.bak" ] && nomad_sudo cp "$SAMBA_CONF" "$SAMBA_CONF.bak" || true
SAMBA_TMP="$(mktemp)"
cat > "$SAMBA_TMP" <<EOF
[global]
   workgroup = WORKGROUP
   server string = $NEW_HOSTNAME
   security = user
   map to guest = Bad User
   dns proxy = no
   server min protocol = SMB2
   client min protocol = SMB2
   smb ports = 445
   netbios name = $(printf '%s' "$NEW_HOSTNAME" | tr '[:lower:]' '[:upper:]')

[data]
   path = $CURRENT_DIR/data
   browsable = yes
   writable = yes
   guest ok = no
   read only = no
   create mask = 0775
   directory mask = 0775
   valid users = $REAL_USER
   force user = $REAL_USER
   force group = $REAL_USER
EOF
nomad_sudo install -m 644 "$SAMBA_TMP" "$SAMBA_CONF"
rm -f "$SAMBA_TMP"
SAMBA_PASS="${SAMBA_PASSWORD:-$(nomad_get_env_key "$ENV_FILE" SAMBA_PASSWORD)}"
SAMBA_PASS="${SAMBA_PASS:-nomad}"
(printf '%s\n%s\n' "$SAMBA_PASS" "$SAMBA_PASS") | nomad_sudo smbpasswd -a -s "$REAL_USER" >/dev/null 2>&1 || true
nomad_sudo systemctl enable --now smbd 2>/dev/null || true
nomad_sudo systemctl enable --now nmbd 2>/dev/null || true

# DLNA scans the Nomad data root including mounted/symlinked external media.
echo "[9/10] MiniDLNA"
nomad_configure_minidlna "$CURRENT_DIR" "$NEW_HOSTNAME"

# Tailscale remains optional and does not make installation fail.
echo "[10/10] Remote access"
nomad_ensure_tailscale
TAILSCALE_AUTHKEY="$(nomad_get_env_key "$ENV_FILE" TAILSCALE_AUTHKEY)"
if [ -n "$TAILSCALE_AUTHKEY" ] && command -v tailscale >/dev/null 2>&1; then
    nomad_sudo tailscale status >/dev/null 2>&1 || nomad_sudo tailscale up --authkey "$TAILSCALE_AUTHKEY" --hostname "$NEW_HOSTNAME" >/dev/null 2>&1 || true
fi

# Raspberry-Pi-only tuning is now explicitly opt-in and cannot run on an A733,
# Rockchip, x86 server or other Linux host.
if [ "${NOMAD_IS_RPI:-0}" = "1" ] && [ "${NOMAD_PI_OVERCLOCK:-0}" = "1" ]; then
    CFG=""
    [ -f /boot/firmware/config.txt ] && CFG=/boot/firmware/config.txt
    [ -z "$CFG" ] && [ -f /boot/config.txt ] && CFG=/boot/config.txt
    if [ -n "$CFG" ] && printf '%s' "${NOMAD_BOARD_MODEL:-}" | grep -qi 'Raspberry Pi Zero 2'; then
        echo "Applying opt-in Raspberry Pi Zero 2 tuning to $CFG..."
        set_boot_cfg() {
            local key="$1" value="$2"
            if nomad_sudo grep -Eq "^[#[:space:]]*${key}=" "$CFG"; then
                nomad_sudo sed -i -E "s|^[#[:space:]]*${key}=.*|${key}=${value}|" "$CFG"
            else
                printf '%s=%s\n' "$key" "$value" | nomad_sudo tee -a "$CFG" >/dev/null
            fi
        }
        set_boot_cfg arm_freq "${NOMAD_PI_ARM_FREQ:-1200}"
        set_boot_cfg over_voltage "${NOMAD_PI_OVER_VOLTAGE:-2}"
    fi
fi

# Start only after installation/tuning has completed, minimising pressure on
# 1 GB-class appliances during pip/package work.
nomad_sudo systemctl daemon-reload
nomad_sudo systemctl restart nomad-pi.service

for _ in $(seq 1 10); do
    systemctl is-active --quiet nomad-pi.service && break
    sleep 2
done
if ! systemctl is-active --quiet nomad-pi.service; then
    echo "ERROR: nomad-pi.service failed to start." >&2
    nomad_sudo journalctl -u nomad-pi -n 40 --no-pager || true
    exit 1
fi

IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "============================================================"
echo "Nomad Pi setup complete"
echo "Board:   $NOMAD_BOARD_DISPLAY"
echo "Profile: ${NOMAD_MEMORY_CLASS:-unknown} memory (${NOMAD_RAM_MB:-?} MB RAM)"
echo "Web:     http://$NEW_HOSTNAME.local"
echo "Direct:  http://${IP_ADDR:-$NEW_HOSTNAME}:8000"
echo "mDNS:    $NEW_HOSTNAME.local"
echo "SMB:     \\\\$NEW_HOSTNAME.local\\data"
echo "Hotspot: ${NOMAD_HOTSPOT_NAME:-NomadPi} / ${NOMAD_HOTSPOT_PASSWORD:-nomadpassword} · portal http://${NOMAD_HOTSPOT_IP:-10.42.0.1}/"
echo "Admin:   initial password is the value in /etc/nomadpi.env"
echo "============================================================"