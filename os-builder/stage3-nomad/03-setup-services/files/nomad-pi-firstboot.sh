#!/bin/bash
# First-boot configuration for the Nomad Pi OS image.
# Creates the NomadPi hotspot (mirrors the hotspot block in setup.sh) so a
# freshly flashed Pi is reachable without any network. Runs once, then stamps
# /etc/nomad-pi/.firstboot-done so it never runs again.

set -u

DONE_STAMP="/etc/nomad-pi/.firstboot-done"
mkdir -p /etc/nomad-pi

# Wait up to 30s for NetworkManager to be ready and a wifi device to appear
for _ in $(seq 1 30); do
    WIFI_DEV="$(nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')"
    [ -n "$WIFI_DEV" ] && break
    sleep 1
done

if [ -z "${WIFI_DEV:-}" ]; then
    echo "nomad-pi-firstboot: no wifi device found; skipping hotspot creation."
    # Still stamp: retrying forever on wifi-less hardware is pointless
    touch "$DONE_STAMP"
    exit 0
fi

if nmcli connection show "NomadPi" >/dev/null 2>&1; then
    echo "nomad-pi-firstboot: hotspot 'NomadPi' already exists."
else
    echo "nomad-pi-firstboot: creating hotspot 'NomadPi' on $WIFI_DEV..."
    nmcli con add type wifi ifname "$WIFI_DEV" con-name "NomadPi" autoconnect yes ssid "NomadPi" && \
    nmcli con modify "NomadPi" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared && \
    nmcli con modify "NomadPi" wifi-sec.key-mgmt wpa-psk && \
    nmcli con modify "NomadPi" wifi-sec.psk "nomadpassword" && \
    nmcli con modify "NomadPi" connection.autoconnect-priority 0 && \
    nmcli con modify "NomadPi" connection.autoconnect-retries 1 || \
    echo "nomad-pi-firstboot: WARNING - hotspot creation failed."
fi

touch "$DONE_STAMP"
exit 0
