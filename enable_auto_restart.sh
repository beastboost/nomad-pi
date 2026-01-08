#!/bin/bash
# Add auto-restart to nomad-pi service

echo "Adding auto-restart to nomad-pi.service..."

SERVICE_FILE="/etc/systemd/system/nomad-pi.service"

# Check if Restart= already exists
if grep -q "^Restart=" "$SERVICE_FILE"; then
    echo "Auto-restart already configured"
    exit 0
fi

# Add Restart and RestartSec to [Service] section
sudo sed -i '/^\[Service\]/a Restart=always\nRestartSec=10' "$SERVICE_FILE"

echo "Auto-restart added!"
echo "Reloading systemd..."
sudo systemctl daemon-reload

echo ""
echo "Done! Service will now auto-restart within 10 seconds if it stops."
echo ""
echo "Starting service now..."
sudo systemctl start nomad-pi

sleep 2
if systemctl is-active --quiet nomad-pi; then
    echo "✓ Service is running!"
else
    echo "✗ Service failed to start. Check: sudo systemctl status nomad-pi"
fi
