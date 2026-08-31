#!/bin/bash
# Shared Nomad network identity, mDNS and captive-hotspot configuration.
# shellcheck shell=bash

NOMAD_HOTSPOT_NAME="${NOMAD_HOTSPOT_NAME:-NomadPi}"
NOMAD_HOTSPOT_IP="${NOMAD_HOTSPOT_IP:-10.42.0.1}"
NOMAD_HOTSPOT_CIDR="${NOMAD_HOTSPOT_CIDR:-10.42.0.1/24}"
NOMAD_HOTSPOT_PASSWORD="${NOMAD_HOTSPOT_PASSWORD:-nomadpassword}"
NOMAD_PRODUCT_HOSTNAME="${NOMAD_PRODUCT_HOSTNAME:-nomadpi}"

_nomad_net_sudo() {
    if declare -F nomad_sudo >/dev/null 2>&1; then
        nomad_sudo "$@"
    elif [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

nomad_configure_hostname_mdns() {
    local hostname="${1:-$NOMAD_PRODUCT_HOSTNAME}"
    hostname="$(printf '%s' "$hostname" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')"
    [ -n "$hostname" ] || hostname="nomadpi"

    # A short-lived development regression changed the default to `nomad`.
    # Repair that automatically, but still honour a deliberate custom hostname
    # supplied through NOMAD_HOSTNAME_OVERRIDE.
    if [ -z "${NOMAD_HOSTNAME_OVERRIDE:-}" ] && [ "$hostname" = "nomad" ]; then
        hostname="nomadpi"
    fi

    local current
    current="$(hostname 2>/dev/null || true)"
    if command -v hostnamectl >/dev/null 2>&1 && [ "$current" != "$hostname" ]; then
        echo "Setting Nomad hostname to '$hostname' for $hostname.local..."
        _nomad_net_sudo hostnamectl set-hostname "$hostname" || true
    fi

    _nomad_net_sudo python3 - "$hostname" <<'PY'
from pathlib import Path
import sys

hostname = sys.argv[1]
path = Path('/etc/hosts')
try:
    text = path.read_text(encoding='utf-8', errors='ignore')
except OSError:
    text = '127.0.0.1\tlocalhost\n'
lines = []
replaced = False
for line in text.splitlines():
    if line.startswith('127.0.1.1'):
        lines.append(f'127.0.1.1\t{hostname}')
        replaced = True
    else:
        lines.append(line)
if not replaced:
    lines.append(f'127.0.1.1\t{hostname}')
path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
PY

    if command -v avahi-daemon >/dev/null 2>&1 || [ -d /etc/avahi ]; then
        _nomad_net_sudo mkdir -p /etc/avahi/services
        local service_tmp
        service_tmp="$(mktemp)"
        cat > "$service_tmp" <<EOF
<?xml version="1.0" standalone='no'?><!--*-nxml-*-->
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">Nomad on %h</name>
  <service>
    <type>_http._tcp</type>
    <port>8000</port>
    <txt-record>path=/</txt-record>
  </service>
  <service>
    <type>_smb._tcp</type>
    <port>445</port>
  </service>
</service-group>
EOF
        _nomad_net_sudo install -m 644 "$service_tmp" /etc/avahi/services/nomad.service
        rm -f "$service_tmp"
        _nomad_net_sudo systemctl enable avahi-daemon >/dev/null 2>&1 || true
        _nomad_net_sudo systemctl restart avahi-daemon >/dev/null 2>&1 || true
    fi

    printf '%s' "$hostname"
}

nomad_install_captive_portal() {
    local root="$1"
    [ -f "$root/scripts/port80-redirect.sh" ] || return 0

    _nomad_net_sudo install -m 755 "$root/scripts/port80-redirect.sh" /usr/local/sbin/nomad-port80-redirect.sh

    local service_src="$root/os-builder/stage3-nomad/03-setup-services/files/nomad-pi-port80-redirect.service"
    if [ -f "$service_src" ]; then
        _nomad_net_sudo install -m 644 "$service_src" /etc/systemd/system/nomad-pi-port80-redirect.service
    fi

    # Remove the abandoned two-process prototype if an update happened to land
    # during development. Captive portal requests now stay inside app.main.
    _nomad_net_sudo systemctl disable --now nomad-pi-captive-portal.service >/dev/null 2>&1 || true
    _nomad_net_sudo rm -f /etc/systemd/system/nomad-pi-captive-portal.service /usr/local/sbin/nomad-captive-portal.py 2>/dev/null || true

    _nomad_net_sudo systemctl daemon-reload >/dev/null 2>&1 || true
    _nomad_net_sudo systemctl enable --now nomad-pi-port80-redirect.service >/dev/null 2>&1 || \
        echo "WARNING: port-80 redirect could not be enabled; use http://nomadpi.local:8000 until networking is repaired."
}

nomad_configure_hotspot_profile() {
    local root="$1"
    local wifi_dev="${2:-}"

    command -v nmcli >/dev/null 2>&1 || return 0
    if [ -z "$wifi_dev" ]; then
        wifi_dev="$(nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi" {print $1; exit}' || true)"
    fi
    [ -n "$wifi_dev" ] || return 0

    if ! nmcli connection show "$NOMAD_HOTSPOT_NAME" >/dev/null 2>&1; then
        echo "Creating fallback hotspot '$NOMAD_HOTSPOT_NAME'..."
        _nomad_net_sudo nmcli con add type wifi ifname "$wifi_dev" con-name "$NOMAD_HOTSPOT_NAME" autoconnect yes ssid "$NOMAD_HOTSPOT_NAME" >/dev/null 2>&1 || return 0
    fi

    _nomad_net_sudo nmcli con modify "$NOMAD_HOTSPOT_NAME" \
        connection.interface-name "$wifi_dev" \
        connection.autoconnect yes \
        connection.autoconnect-priority 0 \
        connection.autoconnect-retries 1 \
        connection.mdns yes \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        ipv4.method shared \
        ipv4.addresses "$NOMAD_HOTSPOT_CIDR" \
        ipv6.method disabled >/dev/null 2>&1 || true
    _nomad_net_sudo nmcli con modify "$NOMAD_HOTSPOT_NAME" \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$NOMAD_HOTSPOT_PASSWORD" >/dev/null 2>&1 || true

    # NetworkManager's shared dnsmasq sees only the hotspot. Rewrite known
    # captive-check names to Nomad, but leave normal internet DNS untouched.
    _nomad_net_sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
    local dns_tmp
    dns_tmp="$(mktemp)"
    cat > "$dns_tmp" <<EOF
# Nomad captive portal — loaded only by NetworkManager's shared dnsmasq.
bind-interfaces
address=/captive.apple.com/$NOMAD_HOTSPOT_IP
address=/connectivitycheck.gstatic.com/$NOMAD_HOTSPOT_IP
address=/connectivitycheck.android.com/$NOMAD_HOTSPOT_IP
address=/clients3.google.com/$NOMAD_HOTSPOT_IP
address=/www.msftconnecttest.com/$NOMAD_HOTSPOT_IP
address=/www.msftncsi.com/$NOMAD_HOTSPOT_IP
address=/detectportal.firefox.com/$NOMAD_HOTSPOT_IP
address=/nomadpi.local/$NOMAD_HOTSPOT_IP
# RFC 8910 clients can open the setup page without probe interception.
dhcp-option=114,http://$NOMAD_HOTSPOT_IP/setup.html
EOF
    _nomad_net_sudo install -m 644 "$dns_tmp" /etc/NetworkManager/dnsmasq-shared.d/nomad-captive.conf
    rm -f "$dns_tmp"

    nomad_install_captive_portal "$root"
}

nomad_hotspot_is_active() {
    command -v nmcli >/dev/null 2>&1 || return 1
    nmcli -t -f NAME connection show --active 2>/dev/null | grep -Fxq "$NOMAD_HOTSPOT_NAME"
}
