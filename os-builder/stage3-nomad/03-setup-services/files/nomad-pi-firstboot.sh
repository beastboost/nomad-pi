#!/bin/bash
# First-boot configuration for the Nomad Pi OS image.
# Creates the NomadPi hotspot with the same fixed gateway/captive behaviour as
# setup.sh so a freshly flashed device is reachable without another network.
# Runs once, then stamps /etc/nomad-pi/.firstboot-done.

set -u

DONE_STAMP="/etc/nomad-pi/.firstboot-done"
HOTSPOT_NAME="NomadPi"
HOTSPOT_IP="10.42.0.1"
mkdir -p /etc/nomad-pi

# Product identity remains `nomadpi`, so the stable Bonjour address is
# http://nomadpi.local on both Pi and Radxa appliances.
if command -v hostnamectl >/dev/null 2>&1; then
    hostnamectl set-hostname nomadpi 2>/dev/null || true
fi
if [ -f /etc/hosts ]; then
    python3 - <<'PY'
from pathlib import Path
p = Path('/etc/hosts')
text = p.read_text(encoding='utf-8', errors='ignore')
lines = []
found = False
for line in text.splitlines():
    if line.startswith('127.0.1.1'):
        line = '127.0.1.1\tnomadpi'
        found = True
    lines.append(line)
if not found:
    lines.append('127.0.1.1\tnomadpi')
p.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
PY
fi
systemctl restart avahi-daemon 2>/dev/null || true

# Wait up to 30s for NetworkManager to be ready and a wifi device to appear.
for _ in $(seq 1 30); do
    WIFI_DEV="$(nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')"
    [ -n "$WIFI_DEV" ] && break
    sleep 1
done

if [ -z "${WIFI_DEV:-}" ]; then
    echo "nomad-pi-firstboot: no wifi device found; skipping hotspot creation."
    touch "$DONE_STAMP"
    exit 0
fi

if nmcli connection show "$HOTSPOT_NAME" >/dev/null 2>&1; then
    echo "nomad-pi-firstboot: hotspot '$HOTSPOT_NAME' already exists; refreshing profile."
else
    echo "nomad-pi-firstboot: creating hotspot '$HOTSPOT_NAME' on $WIFI_DEV..."
    nmcli con add type wifi ifname "$WIFI_DEV" con-name "$HOTSPOT_NAME" autoconnect yes ssid "$HOTSPOT_NAME" || \
        echo "nomad-pi-firstboot: WARNING - hotspot profile creation failed."
fi

nmcli con modify "$HOTSPOT_NAME" \
    connection.interface-name "$WIFI_DEV" \
    connection.autoconnect yes \
    connection.autoconnect-priority 0 \
    connection.autoconnect-retries 1 \
    connection.mdns yes \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    ipv4.method shared \
    ipv4.addresses "$HOTSPOT_IP/24" \
    ipv6.method disabled 2>/dev/null || true
nmcli con modify "$HOTSPOT_NAME" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "nomadpassword" 2>/dev/null || true

mkdir -p /etc/NetworkManager/dnsmasq-shared.d
cat > /etc/NetworkManager/dnsmasq-shared.d/nomad-captive.conf <<EOF
bind-interfaces
address=/captive.apple.com/$HOTSPOT_IP
address=/connectivitycheck.gstatic.com/$HOTSPOT_IP
address=/connectivitycheck.android.com/$HOTSPOT_IP
address=/clients3.google.com/$HOTSPOT_IP
address=/www.msftconnecttest.com/$HOTSPOT_IP
address=/www.msftncsi.com/$HOTSPOT_IP
address=/detectportal.firefox.com/$HOTSPOT_IP
address=/nomadpi.local/$HOTSPOT_IP
dhcp-option=114,http://$HOTSPOT_IP/portal
EOF

if ! nmcli -t -f NAME connection show --active 2>/dev/null | grep -Fxq "$HOTSPOT_NAME"; then
    nmcli con up "$HOTSPOT_NAME" >/dev/null 2>&1 || echo "nomad-pi-firstboot: WARNING - hotspot activation failed."
fi

systemctl enable --now nomad-pi-captive-portal.service 2>/dev/null || true

touch "$DONE_STAMP"
exit 0
