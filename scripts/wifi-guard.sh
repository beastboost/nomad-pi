#!/bin/bash
# Nomad Pi — Wi-Fi guard
#
# A Nomad Pi is usually reachable ONLY over Wi-Fi: either its own hotspot or a
# network it joined. Turning the radio off therefore removes the only way back
# in, and `nmcli radio wifi off` persists across reboots (NetworkManager.state),
# as does the rfkill soft-block (systemd-rfkill restores it). Without this
# guard the box is unreachable until someone physically attaches Ethernet, a
# keyboard, or an SD reader.
#
# This runs on boot and every minute. If the radio is off, it decides whether
# that is deliberate and still safe:
#
#   * no deadline file      -> unexpected; restore the radio
#   * deadline in the past  -> the confirm window lapsed; restore the radio
#   * deadline in the future-> a client is expected to confirm; leave it
#   * "permanent"           -> honoured ONLY while another route exists
#                              (Ethernet carrier). If that route disappears,
#                              the radio comes back rather than stranding the
#                              box.
#
# The effect: a power cycle is always a valid recovery, and an accidental
# switch-off heals itself within a minute.

set -u

STATE_DIR="/etc/nomad-pi"
DEADLINE_FILE="$STATE_DIR/wifi-off-until"
LOG_TAG="nomad-pi-wifi-guard"

log() { logger -t "$LOG_TAG" "$1" 2>/dev/null || echo "$LOG_TAG: $1"; }

radio_is_off() {
    local state
    state="$(nmcli -t radio wifi 2>/dev/null)"
    [ "$state" = "disabled" ] && return 0
    rfkill list wifi 2>/dev/null | grep -qi "Soft blocked: yes" && return 0
    return 1
}

restore_radio() {
    log "restoring Wi-Fi: $1"
    rfkill unblock wifi 2>/dev/null || true
    nmcli radio wifi on 2>/dev/null || true
    rm -f "$DEADLINE_FILE" 2>/dev/null || true
}

# Is there a working route to this box other than Wi-Fi? Any non-wireless,
# non-loopback interface that is up with a carrier counts.
has_other_route() {
    local dev
    for dev in /sys/class/net/*; do
        local name; name="$(basename "$dev")"
        case "$name" in
            lo|wl*|wlan*|p2p*|docker*|veth*|br-*) continue ;;
        esac
        [ -r "$dev/carrier" ] || continue
        [ "$(cat "$dev/carrier" 2>/dev/null)" = "1" ] && return 0
    done
    return 1
}

radio_is_off || exit 0          # nothing to do

if [ ! -f "$DEADLINE_FILE" ]; then
    restore_radio "radio is off with no record of a deliberate switch-off"
    exit 0
fi

deadline="$(cat "$DEADLINE_FILE" 2>/dev/null || echo "")"

if [ "$deadline" = "permanent" ]; then
    if has_other_route; then
        exit 0                  # deliberate, and still reachable another way
    fi
    restore_radio "Wi-Fi was disabled permanently but no other route remains"
    exit 0
fi

case "$deadline" in
    ''|*[!0-9]*) restore_radio "unreadable deadline"; exit 0 ;;
esac

now="$(date +%s)"
if [ "$now" -ge "$deadline" ]; then
    restore_radio "confirmation window lapsed"
fi

exit 0
