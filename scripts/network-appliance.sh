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

    local current
    current="$(hostname 2>/dev/null || true)"
    if command -v hostnamectl >/dev/null 2>&1 && [ "$current" != "$hostname" ]; then
        echo "Setting Nomad hostname to '$hostname' for $hostname.local..."
        _nomad_net_sudo hostnamectl set-hostname "$hostname" || true
    fi

    # Keep /etc/hosts coherent with the hostname. Some Debian images omit the
    # 127.0.1.1 line entirely, so replace it when present and append otherwise.
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
    [ -f "$root/scripts/captive-portal.py" ] || return 0

    _nomad_net_sudo install -m 755 "$root/scripts/captive-portal.py" /usr/local/sbin/nomad-captive-portal.py

    local service_src="$root/os-builder/stage3-nomad/03-setup-services/files/nomad-pi-captive-portal.service"
    if [ -f "$service_src" ]; then
        _nomad_net_sudo install -m 644 "$service_src" /etc/systemd/system/nomad-pi-captive-portal.service
    else
        local tmp
        tmp="$(mktemp)"
        cat > "$tmp" <<'EOF'
[Unit]
Description=Nomad captive portal and port-80 redirect
After=network.target
Wants=network.target

[Service]
Type=simple
User=nobody
Group=nogroup
ExecStart=/usr/bin/python3 /usr/local/sbin/nomad-captive-portal.py
Restart=always
RestartSec=8
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_INET AF_INET6
MemoryMax=64M
CPUQuota=15%

[Install]
WantedBy=multi-user.target
EOF
        _nomad_net_sudo install -m 644 "$tmp" /etc/systemd/system/nomad-pi-captive-portal.service
        rm -f "$tmp"
    fi

    _nomad_net_sudo systemctl daemon-reload >/dev/null 2>&1 || true
    _nomad_net_sudo systemctl enable --now nomad-pi-captive-portal.service >/dev/null 2>&1 || \
        echo "WARNING: captive portal port-80 responder could not be started (port 80 may already be in use)."
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

    # Fix the gateway instead of accepting NetworkManager's variable 10.42.x.1
    # choice. Captive-portal discovery can then safely advertise one URL.
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

    # NetworkManager's `shared` mode owns this dnsmasq instance. Override only
    # well-known captive-check names, never all DNS, so an Ethernet/uplink can
    # still provide normal internet through the hotspot.
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
# RFC 8910 captive-portal URL. Older clients still use the DNS probe overrides.
dhcp-option=114,http://$NOMAD_HOTSPOT_IP/portal
EOF
    _nomad_net_sudo install -m 644 "$dns_tmp" /etc/NetworkManager/dnsmasq-shared.d/nomad-captive.conf
    rm -f "$dns_tmp"

    nomad_install_captive_portal "$root"
}

nomad_hotspot_is_active() {
    command -v nmcli >/dev/null 2>&1 || return 1
    nmcli -t -f NAME connection show --active 2>/dev/null | grep -Fxq "$NOMAD_HOTSPOT_NAME"
}
