#!/bin/bash
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

update_status 5 "Configuring Git..."
echo "Optimizing Git configuration..."

# System update to pick up GnuTLS/security fixes (optional but recommended for handshake issues)
# sudo apt update && sudo apt full-upgrade -y

# Refined Git config for stability on Pi OS (GnuTLS handshake workarounds)
# Explicitly unset the openssl backend in case it was set by a previous version of this script
git config --global --unset http.sslBackend 2>/dev/null || true
git config --global http.sslVerify true
# Force HTTP/1.1 as GnuTLS on some Pi versions fails to negotiate HTTP/2 correctly with GitHub
git config --global http.version HTTP/1.1
# Increase postBuffer to 50MB (from default 1MB) for stable large transfers without excessive memory usage
git config --global http.postBuffer 52428800

# Hardcode the public URL to avoid password prompts
git remote set-url origin https://github.com/beastboost/nomad-pi.git
git config credential.helper 'cache --timeout=2592000'

update_status 10 "Pulling latest changes from Git..."
echo "Pulling latest changes from Git..."
# Force reset to origin/main to solve any local change conflicts automatically
git fetch origin
git reset --hard origin/main

# Fix permissions immediately after pull
chmod +x *.sh
find . -name "*.sh" -exec chmod +x {} +

update_status 40 "Installing dependencies..."
echo "Installing dependencies..."
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

update_status 90 "Update complete. Preparing to restart..."
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
echo "Waiting 5 seconds for UI to update..."
sleep 5

# Try to restart the service, with fallback if service doesn't exist
# We use restart which works whether it was running or not
if command -v systemctl >/dev/null 2>&1; then
    echo "Attempting to restart nomad-pi service via systemctl..." >> update.log
    # Check if the service file exists at all
    if [ -f "/etc/systemd/system/nomad-pi.service" ]; then
        sudo systemctl daemon-reload
        sudo systemctl enable nomad-pi.service
        sudo systemctl restart nomad-pi.service
        echo "Service restart command issued." >> update.log
    else
        echo "Service file /etc/systemd/system/nomad-pi.service not found. Skipping service restart." >> update.log
    fi
else
    echo "systemctl not found. If running manually, please restart the application." >> update.log
fi
