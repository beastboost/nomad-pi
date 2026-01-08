#!/bin/bash
# One-time script to apply mobile menu fixes from feature branch

echo "Applying mobile menu fixes..."

# Pull from the fix branch
git fetch origin
git checkout claude/fix-mobile-burger-menu-qEre1
git pull origin claude/fix-mobile-burger-menu-qEre1

# Restart the service
echo "Restarting Nomad Pi service..."
if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl restart nomad-pi
    echo "Service restarted!"
else
    echo "Please manually restart the Nomad Pi service"
fi

echo "Mobile menu fixes applied!"
echo "Please refresh your browser and clear cache (Ctrl+Shift+R)"
