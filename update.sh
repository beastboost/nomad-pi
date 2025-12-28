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

update_status 10 "Pulling latest changes from Git..."
echo "Pulling latest changes from Git..."
git pull

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

update_status 90 "Update complete. Restarting application..."
echo "Update complete. Restarting application..."
# Give the UI a moment to see the 90% status
sleep 2
sudo systemctl restart nomad-pi.service
