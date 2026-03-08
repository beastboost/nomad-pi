# Nomad Pi Update Script for Windows
$statusFile = "update_status.json"

function Write-Status($progress, $message) {
    $status = @{
        progress = $progress
        message = $message
        timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    }
    $status | ConvertTo-Json | Out-File -FilePath $statusFile -Encoding utf8
    Write-Output "[$progress%] $message"
}

Write-Output "--- Nomad Pi Update Started at $(Get-Date) ---"
Write-Status 10 "Starting update..."

# 1. Pull latest changes
Write-Status 20 "Pulling latest changes from Git..."
git pull

# 2. Setup/Update Virtual Environment
Write-Status 40 "Checking Python environment..."
if (-not (Test-Path "venv")) {
    Write-Status 45 "Creating virtual environment..."
    python -m venv venv
}

Write-Status 60 "Installing/Updating dependencies..."
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

# 3. Environment Check
Write-Status 90 "Checking configuration..."
if (-not $env:ADMIN_PASSWORD -and -not $env:ADMIN_PASSWORD_HASH -and -not $env:ALLOW_INSECURE_DEFAULT) {
    Write-Output "Warning: No authentication environment variables set."
    Write-Output "By default, the server will use 'nomad' as the password."
}

Write-Status 100 "Update complete!"
Write-Output "`nUpdate complete!"
Write-Output "To start the server, run:"
Write-Output ".\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
