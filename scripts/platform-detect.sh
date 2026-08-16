#!/bin/bash
# Shared platform detection for setup.sh and update.sh.
# This file only discovers capabilities; callers decide what to install/tune.

nomad_read_dt() {
    local path="$1"
    [ -r "$path" ] || return 0
    tr '\0' ' ' < "$path" 2>/dev/null | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//'
}

nomad_detect_platform() {
    NOMAD_OS="$(uname -s 2>/dev/null || echo unknown)"
    NOMAD_ARCH="$(uname -m 2>/dev/null || echo unknown)"
    NOMAD_KERNEL="$(uname -r 2>/dev/null || echo unknown)"
    NOMAD_HOSTNAME="$(hostname 2>/dev/null || echo nomadpi)"

    NOMAD_DISTRO_ID="linux"
    NOMAD_DISTRO_NAME="Linux"
    NOMAD_DISTRO_VERSION=""
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        NOMAD_DISTRO_ID="${ID:-linux}"
        NOMAD_DISTRO_NAME="${PRETTY_NAME:-${NAME:-Linux}}"
        NOMAD_DISTRO_VERSION="${VERSION_ID:-}"
    fi

    NOMAD_BOARD_MODEL="$(nomad_read_dt /proc/device-tree/model)"
    [ -n "$NOMAD_BOARD_MODEL" ] || NOMAD_BOARD_MODEL="$(nomad_read_dt /sys/firmware/devicetree/base/model)"
    NOMAD_BOARD_COMPATIBLE="$(nomad_read_dt /proc/device-tree/compatible)"
    [ -n "$NOMAD_BOARD_COMPATIBLE" ] || NOMAD_BOARD_COMPATIBLE="$(nomad_read_dt /sys/firmware/devicetree/base/compatible)"

    local cpu_hw=""
    if [ -r /proc/cpuinfo ]; then
        cpu_hw="$(awk -F: '/^(Hardware|Model name)[[:space:]]*:/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit}' /proc/cpuinfo 2>/dev/null)"
    fi

    local probe
    probe="$(printf '%s %s %s' "$NOMAD_BOARD_MODEL" "$NOMAD_BOARD_COMPATIBLE" "$cpu_hw" | tr '[:upper:]' '[:lower:]')"

    NOMAD_BOARD_FAMILY="generic-linux"
    NOMAD_SOC_FAMILY="unknown"
    NOMAD_BOARD_VENDOR="Generic"
    NOMAD_IS_RPI=0
    NOMAD_IS_A733=0

    if printf '%s' "$probe" | grep -Eq 'raspberry pi|brcm,bcm'; then
        NOMAD_BOARD_FAMILY="raspberry-pi"
        NOMAD_SOC_FAMILY="broadcom"
        NOMAD_BOARD_VENDOR="Raspberry Pi"
        NOMAD_IS_RPI=1
    elif printf '%s' "$probe" | grep -Eq 'sun60iw2|allwinner,a733|(^|[^a-z0-9])a733([^a-z0-9]|$)|cubie[- ]a7'; then
        NOMAD_BOARD_FAMILY="allwinner-a733"
        NOMAD_SOC_FAMILY="allwinner-a733"
        NOMAD_BOARD_VENDOR="Allwinner"
        printf '%s' "$probe" | grep -Eq 'radxa|cubie' && NOMAD_BOARD_VENDOR="Radxa"
        NOMAD_IS_A733=1
    elif printf '%s' "$probe" | grep -Eq 'rockchip|(^|[^a-z0-9])rk(32|33|35)[0-9]{2}([^a-z0-9]|$)'; then
        NOMAD_BOARD_FAMILY="rockchip"
        NOMAD_SOC_FAMILY="rockchip"
        NOMAD_BOARD_VENDOR="Rockchip"
    elif printf '%s' "$probe" | grep -Eq 'amlogic|(^|[^a-z0-9])s9[0-9]{2}([^a-z0-9]|$)'; then
        NOMAD_BOARD_FAMILY="amlogic"
        NOMAD_SOC_FAMILY="amlogic"
        NOMAD_BOARD_VENDOR="Amlogic"
    elif printf '%s' "$NOMAD_ARCH" | grep -Eq '^(aarch64|arm64|armv7l|armv8l)$'; then
        NOMAD_BOARD_FAMILY="generic-arm"
        NOMAD_SOC_FAMILY="arm"
        NOMAD_BOARD_VENDOR="Generic ARM"
    elif printf '%s' "$NOMAD_ARCH" | grep -Eq '^(x86_64|amd64|i.86)$'; then
        NOMAD_BOARD_FAMILY="generic-x86"
        NOMAD_SOC_FAMILY="x86"
        NOMAD_BOARD_VENDOR="Generic x86"
    fi

    NOMAD_RAM_MB="$(awk '/MemTotal:/ {printf "%d", $2 / 1024}' /proc/meminfo 2>/dev/null)"
    [ -n "$NOMAD_RAM_MB" ] || NOMAD_RAM_MB=0
    NOMAD_SWAP_MB="$(free -m 2>/dev/null | awk '/Swap:/ {print $2}')"
    [ -n "$NOMAD_SWAP_MB" ] || NOMAD_SWAP_MB=0
    NOMAD_CPU_COUNT="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"

    if [ "$NOMAD_RAM_MB" -lt 768 ]; then
        NOMAD_MEMORY_CLASS="tiny"
        NOMAD_SWAP_TARGET_MB=1024
    elif [ "$NOMAD_RAM_MB" -lt 1536 ]; then
        NOMAD_MEMORY_CLASS="low"
        NOMAD_SWAP_TARGET_MB=1024
    elif [ "$NOMAD_RAM_MB" -lt 4096 ]; then
        NOMAD_MEMORY_CLASS="standard"
        NOMAD_SWAP_TARGET_MB=512
    else
        NOMAD_MEMORY_CLASS="high"
        NOMAD_SWAP_TARGET_MB=0
    fi

    NOMAD_BOARD_DISPLAY="$NOMAD_BOARD_MODEL"
    if [ "$NOMAD_BOARD_FAMILY" = "allwinner-a733" ]; then
        case "$(printf '%s' "$NOMAD_BOARD_MODEL" | tr '[:upper:]' '[:lower:]')" in
            ""|sun60iw2|"allwinner sun60iw2") NOMAD_BOARD_DISPLAY="Allwinner A733 (sun60iw2)" ;;
            *) NOMAD_BOARD_DISPLAY="$NOMAD_BOARD_MODEL · Allwinner A733" ;;
        esac
    fi
    [ -n "$NOMAD_BOARD_DISPLAY" ] || NOMAD_BOARD_DISPLAY="$NOMAD_ARCH Linux device"

    export NOMAD_OS NOMAD_ARCH NOMAD_KERNEL NOMAD_HOSTNAME
    export NOMAD_DISTRO_ID NOMAD_DISTRO_NAME NOMAD_DISTRO_VERSION
    export NOMAD_BOARD_MODEL NOMAD_BOARD_COMPATIBLE NOMAD_BOARD_FAMILY NOMAD_SOC_FAMILY NOMAD_BOARD_VENDOR
    export NOMAD_IS_RPI NOMAD_IS_A733 NOMAD_RAM_MB NOMAD_SWAP_MB NOMAD_CPU_COUNT NOMAD_MEMORY_CLASS NOMAD_SWAP_TARGET_MB NOMAD_BOARD_DISPLAY
}

nomad_print_platform() {
    printf '%s\n' "Detected platform:"
    printf '  Board:        %s\n' "$NOMAD_BOARD_DISPLAY"
    printf '  Family:       %s\n' "$NOMAD_BOARD_FAMILY"
    printf '  OS:           %s\n' "$NOMAD_DISTRO_NAME"
    printf '  Architecture: %s\n' "$NOMAD_ARCH"
    printf '  Kernel:       %s\n' "$NOMAD_KERNEL"
    printf '  CPU threads:  %s\n' "$NOMAD_CPU_COUNT"
    printf '  RAM:          %s MB (%s)\n' "$NOMAD_RAM_MB" "$NOMAD_MEMORY_CLASS"
    printf '  Swap:         %s MB\n' "$NOMAD_SWAP_MB"
}

nomad_detect_platform
