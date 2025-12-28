# Nomad Pi Update Script for Windows

Write-Host "Checking for updates..." -ForegroundColor Cyan

# 1. Pull latest changes
Write-Host "Pulling latest changes from Git..." -ForegroundColor Yellow
git pull

# 2. Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt

Write-Host "Update complete!" -ForegroundColor Green
Write-Host "If the server was running, you may need to restart it for changes to take effect." -ForegroundColor Gray
