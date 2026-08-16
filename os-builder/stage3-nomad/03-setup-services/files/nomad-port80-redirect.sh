#!/bin/bash
set -u
ACTION="${1:-start}"
TARGET_PORT="${NOMAD_WEB_PORT:-8000}"
NFT_TABLE="nomad_port80"

nft_start() {
    nft list table inet "$NFT_TABLE" >/dev/null 2>&1 && return 0
    nft -f - <<EOF
add table inet $NFT_TABLE
add chain inet $NFT_TABLE prerouting { type nat hook prerouting priority dstnat; policy accept; }
add rule inet $NFT_TABLE prerouting fib daddr type local tcp dport 80 redirect to :$TARGET_PORT
EOF
}

nft_stop() { nft delete table inet "$NFT_TABLE" >/dev/null 2>&1 || true; }

ipt_start() {
    local bin="$1"
    command -v "$bin" >/dev/null 2>&1 || return 0
    "$bin" -t nat -C PREROUTING -p tcp -m addrtype --dst-type LOCAL --dport 80 -j REDIRECT --to-ports "$TARGET_PORT" >/dev/null 2>&1 && return 0
    "$bin" -t nat -A PREROUTING -p tcp -m addrtype --dst-type LOCAL --dport 80 -j REDIRECT --to-ports "$TARGET_PORT"
}

ipt_stop() {
    local bin="$1"
    command -v "$bin" >/dev/null 2>&1 || return 0
    while "$bin" -t nat -C PREROUTING -p tcp -m addrtype --dst-type LOCAL --dport 80 -j REDIRECT --to-ports "$TARGET_PORT" >/dev/null 2>&1; do
        "$bin" -t nat -D PREROUTING -p tcp -m addrtype --dst-type LOCAL --dport 80 -j REDIRECT --to-ports "$TARGET_PORT" >/dev/null 2>&1 || break
    done
}

case "$ACTION" in
    start)
        if command -v nft >/dev/null 2>&1 && nft_start; then exit 0; fi
        command -v iptables >/dev/null 2>&1 || exit 1
        ipt_start iptables
        ipt_start ip6tables
        ;;
    stop)
        command -v nft >/dev/null 2>&1 && nft_stop
        ipt_stop iptables
        ipt_stop ip6tables
        ;;
    *) exit 2 ;;
esac
