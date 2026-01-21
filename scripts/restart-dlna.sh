#!/bin/bash
# Restart MiniDLNA and force rescan
# Usage: ./scripts/restart-dlna.sh

set -e

echo "Stopping MiniDLNA..."
sudo systemctl stop minidlna

echo "Clearing database cache..."
sudo rm -f /var/cache/minidlna/files.db

echo "Starting MiniDLNA..."
sudo systemctl start minidlna

echo "Forcing rescan..."
sudo minidlnad -R

echo "Checking status..."
sleep 2
sudo systemctl status minidlna --no-pager | head -20

echo ""
echo "MiniDLNA restarted successfully!"
echo "Check your TV/DLNA client for 'Nomad Pi' server"
echo "It may take a few minutes to scan all media files."
