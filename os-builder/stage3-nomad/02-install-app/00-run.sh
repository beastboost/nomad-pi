#!/bin/bash -e

# Create application directory
install -v -d -m 0755 "${ROOTFS_DIR}/opt/nomad-pi"

# Copy the app files into the rootfs
cp -a files/app "${ROOTFS_DIR}/opt/nomad-pi/"
cp files/requirements.txt "${ROOTFS_DIR}/opt/nomad-pi/"
