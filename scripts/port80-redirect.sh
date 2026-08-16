#!/bin/bash
# Redirect HTTP requests addressed to this Nomad appliance from port 80 to the
# existing uvicorn listener on 8000. This keeps captive-portal support and
# http://nomadpi.local convenience inside ONE application process.
set -u

ACTION="${1:-start}"
TARGET_PORT="${NOMAD_WEB_PORT:-8000}"
NFT_TABLE="nomad_port80"

log() { logger -t nomad-port80 "$*" 2>/dev/null || true; }

nft_start() {
    nft list table inet "$NFT_TABLE" >/dev/null 2>&1 && return 0
    nft -f - <<EOF
add table inet $NFT_TABLE
add chain inet $NFT_TABLE prerouting { type nat hook prerouting priority dstnat; policy accept; }
add rule inet $NFT_TABLE prerouting fib daddr type local tcp dport 80 redirect to :$TARGET_PORT
EOF
}

nft_stop() {
    nft delete table inet "$NFT_TABLE" >/dev/null 2>&1 || true
}

iptables_start_one() {
    local bin="$1"
    command -v "$bin" >/dev/null 2>&1 || return 0
    "$bin" -t nat -C PREROUTING -p tcp -m addrtype --dst-type LOCAL --dport 80 \
        -j REDIRECT --to-ports "$TARGET_PORT" >/dev/null 2>&1 && return 0
    "$bin" -t nat -A PREROUTING -p tcp -m addrtype --dst-type LOCAL --dport 80 \
        -j REDIRECT --to-ports "$TARGET_PORT"
}

iptables_stop_one() {
    local bin="$1"
    command -v "$bin" >/dev/null 2>&1 || return 0
    while "$bin" -t nat -C PREROUTING -p tcp -m addrtype --dst-type LOCAL --dport 80 \
        -j REDIRECT --to-ports "$TARGET_PORT" >/dev/null 2>&1; do
        "$bin" -t nat -D PREROUTING -p tcp -m addrtype --dst-type LOCAL --dport 80 \
            -j REDIRECT --to-ports "$TARGET_PORT" >/dev/null 2>&1 || break
    done
}

case "$ACTION" in
    start)
        if command -v nft >/dev/null 2>&1; then
            if nft_start; then
                log "redirecting local TCP/80 to :$TARGET_PORT with nftables"
                exit 0
            fi
            log "nftables redirect failed; trying iptables compatibility path"
        fi
        if command -v iptables >/dev/null 2>&1; then
            iptables_start_one iptables
            iptables_start_one ip6tables
            log "redirecting local TCP/80 to :$TARGET_PORT with iptables"
            exit 0
        fi
        echo "nomad-port80: neither nft nor iptables is available" >&2
        exit 1
        ;;
    stop)
        command -v nft >/dev/null 2>&1 && nft_stop
        iptables_stop_one iptables
        iptables_stop_one ip6tables
        ;;
    *)
        echo "usage: $0 {start|stop}" >&2
        exit 2
        ;;
esac
