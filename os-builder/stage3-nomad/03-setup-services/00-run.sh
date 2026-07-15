#!/bin/bash -e

# Copy the service files and first-boot script
install -m 644 files/nomad-pi.service "${ROOTFS_DIR}/etc/systemd/system/"
install -m 644 files/nomad-pi-firstboot.service "${ROOTFS_DIR}/etc/systemd/system/"
install -m 755 files/nomad-pi-firstboot.sh "${ROOTFS_DIR}/usr/local/sbin/"

on_chroot << EOF
systemctl enable nomad-pi.service
systemctl enable nomad-pi-firstboot.service
systemctl enable NetworkManager.service

# Mask the system dnsmasq service so it never binds port 53 on all interfaces.
# NetworkManager manages its own private dnsmasq instance for the hotspot
# separately, so the hotspot still works correctly. Without this, dnsmasq
# starts on boot and intercepts DNS on the home LAN, breaking Pi-hole.
systemctl disable dnsmasq 2>/dev/null || true
systemctl mask dnsmasq 2>/dev/null || true

# Restrict NM's hotspot dnsmasq to the hotspot interface only
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
echo 'bind-interfaces' > /etc/NetworkManager/dnsmasq-shared.d/nomadpi-pihole-compat.conf
EOF
