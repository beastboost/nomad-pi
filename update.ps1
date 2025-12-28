# Nomad Pi Update Script for Windows

Write-Output "--- Nomad Pi Update ---"

# 1. Pull latest changes
Write-Output "[1/3] Pulling latest changes from Git..."
git pull

# 2. Setup/Update Virtual Environment
Write-Output "[2/3] Checking Python environment..."
if (-not (Test-Path "venv")) {
    Write-Output "Creating virtual environment..."
    python -m venv venv
}

Write-Output "Installing/Updating dependencies..."
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

# 3. Environment Check
Write-Output "[3/3] Checking configuration..."
if (-not $env:ADMIN_PASSWORD -and -not $env:ADMIN_PASSWORD_HASH -and -not $env:ALLOW_INSECURE_DEFAULT) {
    Write-Output "Warning: No authentication environment variables set."
    Write-Output "By default, the server will use 'nomad' as the password."
}

Write-Output "`nUpdate complete!"
Write-Output "To start the server, run:"
Write-Output ".\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
