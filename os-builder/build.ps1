# Check if Docker is installed
if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Warning "Docker is not installed or not in PATH. You will need Docker Desktop or WSL to actually run the build-docker.sh script."
    Write-Warning "Setting up the pi-gen environment anyway..."
}

Write-Host "=========================================="
Write-Host "    Starting NomadOS Build Pipeline       "
Write-Host "=========================================="

$BUILD_DIR = "$PSScriptRoot\pi-gen"

# 1. Clone pi-gen if it doesn't exist
if (!(Test-Path $BUILD_DIR)) {
    Write-Host "Cloning pi-gen..."
    git clone https://github.com/RPi-Distro/pi-gen.git $BUILD_DIR
}

# 2. Copy our configuration
Write-Host "Applying NomadOS configuration..."
Copy-Item "$PSScriptRoot\config" -Destination "$BUILD_DIR\config" -Force

# 3. Copy our custom stage
Write-Host "Copying stage3-nomad..."
if (Test-Path "$BUILD_DIR\stage3-nomad") { Remove-Item "$BUILD_DIR\stage3-nomad" -Recurse -Force }
Copy-Item -Path "$PSScriptRoot\stage3-nomad" -Destination "$BUILD_DIR\stage3-nomad" -Recurse -Force

# 4. Inject the app code into the stage files
Write-Host "Injecting application source code..."
$APP_DEST = "$BUILD_DIR\stage3-nomad\02-install-app\files"
if (!(Test-Path $APP_DEST)) { New-Item -ItemType Directory -Force -Path $APP_DEST | Out-Null }
Copy-Item -Path "$PSScriptRoot\..\app" -Destination "$APP_DEST\app" -Recurse -Force
Copy-Item -Path "$PSScriptRoot\..\requirements.txt" -Destination "$APP_DEST\requirements.txt" -Force

# 5. Run the Docker build script
Write-Host "Starting Docker build (this will take a while)..."
Set-Location $BUILD_DIR
# Windows requires running the bash script inside WSL or via a Linux container directly.
# The pi-gen repo provides a build-docker.sh script which mounts the directory into a debian container.
bash ./build-docker.sh

Write-Host "=========================================="
Write-Host " Build Complete! Check os-builder/pi-gen/deploy for the .img file."
Write-Host "=========================================="
