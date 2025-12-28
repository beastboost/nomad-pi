#!/bin/bash
echo "Pulling latest changes from Git..."
git pull
echo "Installing dependencies..."
./venv/bin/pip install -r requirements.txt
echo "Update complete. Restarting application..."
sudo systemctl restart nomad-pi.service
