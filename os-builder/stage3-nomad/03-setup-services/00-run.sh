#!/bin/bash -e

# Copy the service file
install -m 644 files/nomad-pi.service "${ROOTFS_DIR}/etc/systemd/system/"

on_chroot << EOF
systemctl enable nomad-pi.service
systemctl enable NetworkManager.service
EOF
