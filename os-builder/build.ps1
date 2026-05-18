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

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "Running build via Docker directly..."
    
    # Check if Docker daemon is actually running
    docker info > $null 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker is installed, but the Docker daemon is not running! Please open 'Docker Desktop' from your Windows Start Menu, wait for it to initialize, and try again."
        exit 1
    }

    Write-Host "Building Docker image first..."
    docker build -t pi-gen .
    
    Write-Host "Running container..."
    # Format the path for Docker on Windows
    $WIN_PWD = $($PWD.Path -replace '\\', '/')
    docker run --rm --privileged -v "${WIN_PWD}:/pi-gen" -e DEBIAN_FRONTEND=noninteractive pi-gen
} elseif (Get-Command wsl -ErrorAction SilentlyContinue) {
    # Check if WSL actually has a distro installed
    $wslList = wsl -l -q 2>$null
    if ($wslList) {
        Write-Host "Running build via WSL..."
        wsl -- ./build-docker.sh
    } else {
        Write-Error "WSL is installed but no distributions are found. Please install Ubuntu (wsl --install -d Ubuntu) or use Docker Desktop."
        exit 1
    }
} else {
    Write-Error "Neither WSL (with a distro) nor Docker was found. Cannot compile image on Windows."
    exit 1
}

Write-Host "=========================================="
Write-Host " Build Complete! Check os-builder/pi-gen/deploy for the .img file."
Write-Host "=========================================="
