#!/bin/bash
echo "Fixing MiniDLNA..."
sudo systemctl stop minidlna
sudo rm -rf /var/cache/minidlna/*
sudo mkdir -p /var/cache/minidlna
sudo chown -R minidlna:minidlna /var/cache/minidlna
sudo chown -R minidlna:minidlna /var/log/minidlna
sudo chmod -R 755 /data
sudo chmod -R 755 /var/cache/minidlna
sudo systemctl start minidlna
sleep 2
if systemctl is-active --quiet minidlna; then
    echo "MiniDLNA is running!"
    echo "Give it a few minutes to scan media."
else
    echo "Failed to start. Check: sudo journalctl -u minidlna -n 50"
fi
