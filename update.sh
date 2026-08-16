#!/bin/bash
# Nomad Pi in-place updater for Debian-family Linux hosts.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
NOMAD_ROOT="$SCRIPT_DIR"
REAL_USER="${SUDO_USER:-${USER:-$(id -un)}}"
STATUS_FILE="/tmp/nomad-pi-update.json"
STATUS_DIR="/tmp"

update_status() {
    local progress="$1" message="$2" tmp_file
    tmp_file="$(mktemp "$STATUS_DIR/nomad-pi-update.tmp.XXXXXX" 2>/dev/null || echo "$STATUS_DIR/nomad-pi-update.tmp.$$")"
    if command -v jq >/dev/null 2>&1; then
        jq -n --arg progress "$progress" --arg message "$message" --arg ts "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
            '{progress: ($progress|tonumber), message: $message, timestamp: $ts}' > "$tmp_file"
    else
        PROGRESS="$progress" MESSAGE="$message" python3 - <<'PY' > "$tmp_file"
import json, os
from datetime import datetime, timezone
print(json.dumps({
    "progress": int(os.environ.get("PROGRESS", "0")),
    "message": os.environ.get("MESSAGE", ""),
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}))
PY
    fi
    chmod 644 "$tmp_file" 2>/dev/null || true
    mv -f "$tmp_file" "$STATUS_FILE" 2>/dev/null || sudo mv -f "$tmp_file" "$STATUS_FILE" 2>/dev/null || true
}

if [ ! -f scripts/install-common.sh ]; then
    update_status 1 "Update helper missing"
    echo "ERROR: scripts/install-common.sh is missing. Run setup.sh from a complete current checkout." >&2
    exit 1
fi
# shellcheck disable=SC1091
. scripts/install-common.sh
nomad_require_host

update_status 5 "Checking platform and system health..."
echo "============================================================" | tee -a update.log
echo "Nomad Pi update" | tee -a update.log
nomad_print_install_profile | tee -a update.log
echo "============================================================" | tee -a update.log
nomad_check_board_health
nomad_ensure_swap

update_status 12 "Preparing repository..."
# Repair ownership only for the application checkout. Do not recursively chown
# attached media under data/external during an update.
nomad_sudo chown "$REAL_USER:$REAL_USER" "$SCRIPT_DIR" 2>/dev/null || true
nomad_sudo chown -R "$REAL_USER:$REAL_USER" .git 2>/dev/null || true
nomad_configure_git "$REAL_USER" "$SCRIPT_DIR"

if ! nomad_as_user "$REAL_USER" git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    update_status 12 "ERROR: Nomad checkout is not a Git repository"
    exit 1
fi
nomad_as_user "$REAL_USER" git remote set-url origin https://github.com/beastboost/nomad-pi.git
nomad_as_user "$REAL_USER" git config credential.helper 'cache --timeout=2592000' 2>/dev/null || true

update_status 22 "Fetching latest Nomad version..."
nomad_as_user "$REAL_USER" git fetch origin
update_status 32 "Switching to latest main..."
nomad_as_user "$REAL_USER" git reset --hard origin/main
chmod +x ./*.sh scripts/*.sh 2>/dev/null || true

# Re-source after reset so this run immediately benefits from newer platform
# policy shipped in the commit it just installed.
# shellcheck disable=SC1091
. scripts/install-common.sh
nomad_detect_platform 2>/dev/null || true

echo "Updated to: $(git log -1 --oneline --no-decorate)" | tee -a update.log

update_status 40 "Refreshing browser assets..."
STAMP="$(git rev-parse --short HEAD 2>/dev/null || date +%s)"
nomad_stamp_assets "$SCRIPT_DIR" "$STAMP"
if [ -x scripts/vendor-assets.sh ]; then
    bash scripts/vendor-assets.sh || true
fi
nomad_install_wifi_guard "$SCRIPT_DIR"

update_status 50 "Checking system dependencies..."
nomad_install_packages

update_status 58 "Checking remote-access service..."
nomad_ensure_tailscale

update_status 64 "Updating Python environment..."
if [ -d venv ]; then
    nomad_sudo chown -R "$REAL_USER:$REAL_USER" venv 2>/dev/null || true
fi
if [ ! -d venv ]; then
    nomad_as_user "$REAL_USER" python3 -m venv venv
fi
nomad_as_user "$REAL_USER" ./venv/bin/python3 -m pip install --upgrade pip

REQUIREMENTS_HASH="$(md5sum requirements.txt | awk '{print $1}')"
PREV_HASH="$(cat .requirements_hash 2>/dev/null || true)"
if [ "$REQUIREMENTS_HASH" != "$PREV_HASH" ] || [ ! -x ./venv/bin/uvicorn ]; then
    echo "Requirements changed; installing with ${NOMAD_MEMORY_CLASS:-unknown}-memory profile." | tee -a update.log
    nomad_as_user "$REAL_USER" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary fastapi uvicorn psutil
    nomad_as_user "$REAL_USER" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary 'passlib[bcrypt]' bcrypt==4.0.1 python-multipart aiofiles jinja2 'python-jose[cryptography]' httpx
    nomad_as_user "$REAL_USER" ./venv/bin/python3 -m pip install --no-cache-dir --prefer-binary -r requirements.txt
    printf '%s\n' "$REQUIREMENTS_HASH" > .requirements_hash
fi
if ! nomad_as_user "$REAL_USER" ./venv/bin/python3 -c 'import uvicorn, fastapi, passlib' >/dev/null 2>&1; then
    update_status 68 "ERROR: Python environment validation failed"
    exit 1
fi

update_status 74 "Running database migrations..."
if [ -f migrate_db.py ]; then
    nomad_as_user "$REAL_USER" ./venv/bin/python migrate_db.py || echo "WARNING: database migration reported an error; inspect update.log." | tee -a update.log
fi

update_status 80 "Checking media directories..."
mkdir -p data/movies data/shows data/music data/books data/files data/external data/gallery data/uploads data/cache data/.nomad_cache
# Only repair the roots. Walking a mounted external library during every update
# can take minutes and generate huge unnecessary I/O.
for dir in data data/movies data/shows data/music data/books data/files data/external data/gallery data/uploads data/cache data/.nomad_cache; do
    nomad_sudo chown "$REAL_USER:$REAL_USER" "$dir" 2>/dev/null || true
    nomad_sudo chmod 755 "$dir" 2>/dev/null || true
done
if id minidlna >/dev/null 2>&1; then
    nomad_sudo usermod -a -G "$REAL_USER" minidlna 2>/dev/null || true
fi

update_status 85 "Refreshing media services..."
CURRENT_HOSTNAME="$(hostname 2>/dev/null || echo nomadpi)"
nomad_configure_minidlna "$SCRIPT_DIR" "$CURRENT_HOSTNAME"

# Preserve the existing web-admin privilege model, but repair the file if an OS
# update removed it. Validate before install so a malformed sudoers file cannot
# lock out the device.
SUDOERS_TMP="$(mktemp)"
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$REAL_USER" > "$SUDOERS_TMP"
if nomad_sudo visudo -cf "$SUDOERS_TMP" >/dev/null 2>&1; then
    nomad_sudo install -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/nomad-pi
fi
rm -f "$SUDOERS_TMP"

# Ensure the service definition follows the current checkout path/user. This is
# important when an install was migrated from /root or boot media.
update_status 90 "Refreshing Nomad service..."
SERVICE_TMP="$(mktemp)"
cat > "$SERVICE_TMP" <<EOF
[Unit]
Description=Nomad Pi Media Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=-/etc/nomadpi.env
ExecStart=$SCRIPT_DIR/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 300
Restart=always
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
nomad_sudo install -m 644 "$SERVICE_TMP" /etc/systemd/system/nomad-pi.service
rm -f "$SERVICE_TMP"
nomad_sudo systemctl daemon-reload
nomad_sudo systemctl enable nomad-pi.service

update_status 96 "Update complete; scheduling restart..."
echo "" >> update.log
echo "============================================================" >> update.log
echo "Update complete: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)" >> update.log
echo "Platform: ${NOMAD_BOARD_DISPLAY:-unknown}" >> update.log
echo "Memory profile: ${NOMAD_MEMORY_CLASS:-unknown} (${NOMAD_RAM_MB:-?} MB)" >> update.log
echo "============================================================" >> update.log

# Defer the restart so the HTTP request that launched update.sh can return its
# final status instead of killing itself mid-response.
RESTART_SCRIPT="/tmp/restart_nomad_pi.sh"
cat > "$RESTART_SCRIPT" <<'EOF'
#!/bin/bash
sleep 2
sudo -n systemctl restart nomad-pi.service
EOF
chmod +x "$RESTART_SCRIPT"
nohup "$RESTART_SCRIPT" >/dev/null 2>&1 &

update_status 100 "Update complete! Restarting Nomad..."
echo "Nomad Pi update complete."
