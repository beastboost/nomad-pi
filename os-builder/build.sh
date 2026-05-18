#!/bin/bash
set -e

echo "=========================================="
echo "    Starting NomadOS Build on Raspberry Pi"
echo "=========================================="

BUILD_DIR="$(pwd)/pi-gen"

# 1. Install dependencies required for pi-gen
echo "Installing build dependencies..."
sudo apt-get update
sudo apt-get install -y coreutils quilt parted qemu-user-static debootstrap zerofree zip \
dosfstools libarchive-tools libcap2-bin grep rsync xz-utils curl bc gpg pigz xxd file git \
kpartx fdisk bsdtar

# 2. Clone pi-gen if it doesn't exist
if [ ! -d "$BUILD_DIR" ]; then
    echo "Cloning pi-gen..."
    git clone https://github.com/RPi-Distro/pi-gen.git "$BUILD_DIR"
fi

# 3. Copy our configuration
echo "Applying NomadOS configuration..."
cp config "$BUILD_DIR/config"

# 4. Copy our custom stage
echo "Copying stage3-nomad..."
rm -rf "$BUILD_DIR/stage3-nomad"
cp -r stage3-nomad "$BUILD_DIR/"

# 5. Inject the app code into the stage files
echo "Injecting application source code..."
APP_DEST="$BUILD_DIR/stage3-nomad/02-install-app/files"
mkdir -p "$APP_DEST"
cp -r ../app "$APP_DEST/app"
cp ../requirements.txt "$APP_DEST/requirements.txt"

# 6. Run the build script
echo "Starting OS build (this will take a very long time)..."
cd "$BUILD_DIR"
sudo ./build.sh

echo "=========================================="
echo " Build Complete! Check os-builder/pi-gen/deploy for the .img file."
echo "=========================================="
