# Nomad Pi Update Script for Windows

Write-Host "--- Nomad Pi Update ---" -ForegroundColor Cyan

# 1. Pull latest changes
Write-Host "[1/3] Pulling latest changes from Git..." -ForegroundColor Yellow
git pull

# 2. Setup/Update Virtual Environment
Write-Host "[2/3] Checking Python environment..." -ForegroundColor Yellow
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Gray
    python -m venv venv
}

Write-Host "Installing/Updating dependencies..." -ForegroundColor Gray
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

# 3. Environment Check
Write-Host "[3/3] Checking configuration..." -ForegroundColor Yellow
if (-not $env:ADMIN_PASSWORD -and -not $env:ADMIN_PASSWORD_HASH -and -not $env:ALLOW_INSECURE_DEFAULT) {
    Write-Host "Warning: No authentication environment variables set." -ForegroundColor Red
    Write-Host "By default, the server will use 'nomad' as the password." -ForegroundColor Gray
    Write-Host "You can set a custom password with: `$env:ADMIN_PASSWORD='yourpassword'`" -ForegroundColor Gray
}

Write-Host "`nUpdate complete!" -ForegroundColor Green
Write-Host "To start the server, run:" -ForegroundColor Gray
Write-Host ".\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" -ForegroundColor Cyan
