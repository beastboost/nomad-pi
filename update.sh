#!/bin/bash
# Nomad Pi Update Script

echo "Pulling latest code from GitHub..."
git pull

echo "Updating Python dependencies..."
source venv/bin/activate
pip install -r requirements.txt

echo "Restarting Nomad Pi service..."
sudo systemctl restart nomadpi

echo "Update complete! Remember to Ctrl+F5 your browser."
