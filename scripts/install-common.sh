#!/bin/bash
# Common setup/update helpers for Nomad Pi.
# shellcheck shell=bash

NOMAD_ROOT="${NOMAD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [ -f "$NOMAD_ROOT/scripts/platform-detect.sh" ]; then
    # shellcheck disable=SC1091
    . "$NOMAD_ROOT/scripts/platform-detect.sh"
else
    NOMAD_OS="$(uname -s 2>/dev/null || echo unknown)"
    NOMAD_ARCH="$(uname -m 2>/dev/null || echo unknown)"
    NOMAD_BOARD_DISPLAY="$NOMAD_ARCH Linux device"
    NOMAD_BOARD_FAMILY="generic-linux"
    NOMAD_RAM_MB="$(awk '/MemTotal:/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)"
    NOMAD_SWAP_MB="$(free -m 2>/dev/null | awk '/Swap:/ {print $2}' || echo 0)"
    NOMAD_SWAP_TARGET_MB=0
    NOMAD_MEMORY_CLASS="unknown"
    NOMAD_IS_RPI=0
    NOMAD_IS_A733=0
fi

nomad_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

nomad_as_user() {
    local user="$1"
    shift
    if [ "$(id -u)" -eq 0 ] && [ -n "$user" ] && id "$user" >/dev/null 2>&1; then
        sudo -u "$user" "$@"
    else
        "$@"
    fi
}

nomad_require_host() {
    if [ "${NOMAD_OS:-}" != "Linux" ]; then
        echo "ERROR: Nomad host setup currently supports Linux hosts only (detected ${NOMAD_OS:-unknown})." >&2
        return 1
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        echo "ERROR: systemd/systemctl is required for appliance installation." >&2
        echo "For containers/server-only deployments use the documented server runtime instead." >&2
        return 1
    fi
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "ERROR: This installer currently supports Debian-family hosts (apt)." >&2
        echo "Detected: ${NOMAD_DISTRO_NAME:-Linux}. Runtime code remains portable; package installation needs a distro adapter." >&2
        return 1
    fi
}

nomad_print_install_profile() {
    if declare -F nomad_print_platform >/dev/null 2>&1; then
        nomad_print_platform
    else
        echo "Detected platform: $NOMAD_BOARD_DISPLAY · $NOMAD_ARCH · ${NOMAD_RAM_MB:-?} MB RAM"
    fi
    echo "  Install mode: Debian-family systemd host"
}

nomad_configure_git() {
    local user="$1"
    local repo="$2"
    nomad_as_user "$user" git config --global --add safe.directory "$repo" 2>/dev/null || true
    nomad_as_user "$user" git config --global --unset http.sslBackend 2>/dev/null || true
    nomad_as_user "$user" git config --global http.sslVerify true 2>/dev/null || true
    nomad_as_user "$user" git config --global http.version HTTP/1.1 2>/dev/null || true
    nomad_as_user "$user" git config --global http.postBuffer 52428800 2>/dev/null || true

    # Tight Git pack limits only help memory-constrained machines. Do not force
    # Pi-Zero-era limits onto machines with several GB of RAM.
    if [ "${NOMAD_RAM_MB:-0}" -gt 0 ] && [ "$NOMAD_RAM_MB" -lt 2048 ]; then
        nomad_as_user "$user" git config --global pack.windowMemory "10m" 2>/dev/null || true
        nomad_as_user "$user" git config --global pack.packSizeLimit "20m" 2>/dev/null || true
        nomad_as_user "$user" git config --global core.packedGitLimit "20m" 2>/dev/null || true
        nomad_as_user "$user" git config --global core.packedGitWindowSize "10m" 2>/dev/null || true
    fi
}

nomad_check_board_health() {
    if [ "${NOMAD_IS_RPI:-0}" = "1" ] && command -v vcgencmd >/dev/null 2>&1; then
        local throttled
        throttled="$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2 || true)"
        if [ -n "$throttled" ] && [ "$throttled" != "0x0" ]; then
            echo "WARNING: Raspberry Pi firmware reports throttling/under-voltage ($throttled)."
        fi
    fi
}

nomad_ensure_swap() {
    local target="${NOMAD_SWAP_TARGET_MB:-0}"
    local current
    current="$(free -m 2>/dev/null | awk '/Swap:/ {print $2}')"
    current="${current:-0}"
    if [ "$target" -le 0 ]; then
        echo "Swap policy: no additional swap required for ${NOMAD_RAM_MB:-?} MB RAM."
        return 0
    fi
    if [ "$current" -ge "$target" ]; then
        echo "Swap policy: ${current} MB already available (target ${target} MB)."
        return 0
    fi

    echo "Swap policy: ${current} MB available; low-memory profile target is ${target} MB."
    if [ -f /etc/dphys-swapfile ] && command -v dphys-swapfile >/dev/null 2>&1; then
        nomad_sudo sed -i -E "s/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=${target}/" /etc/dphys-swapfile
        if ! grep -q '^CONF_SWAPSIZE=' /etc/dphys-swapfile 2>/dev/null; then
            echo "CONF_SWAPSIZE=${target}" | nomad_sudo tee -a /etc/dphys-swapfile >/dev/null
        fi
        nomad_sudo dphys-swapfile setup
        nomad_sudo dphys-swapfile swapon
        return 0
    fi

    local need=$((target - current))
    [ "$need" -lt 256 ] && need=256
    local swapfile="/var/swap.nomad"
    echo "Creating persistent ${need} MB Nomad swap file at $swapfile..."
    nomad_sudo swapoff "$swapfile" 2>/dev/null || true
    nomad_sudo rm -f "$swapfile"
    if command -v fallocate >/dev/null 2>&1; then
        nomad_sudo fallocate -l "${need}M" "$swapfile"
    else
        nomad_sudo dd if=/dev/zero of="$swapfile" bs=1M count="$need" status=progress
    fi
    nomad_sudo chmod 600 "$swapfile"
    nomad_sudo mkswap "$swapfile" >/dev/null
    nomad_sudo swapon "$swapfile"
    if ! grep -qsF "$swapfile none swap sw 0 0" /etc/fstab; then
        echo "$swapfile none swap sw 0 0" | nomad_sudo tee -a /etc/fstab >/dev/null
    fi
}

nomad_install_media_stack() {
    # A733 vendor images expose the supported VPU path through GStreamer OMX.
    # Do not replace Radxa's kernel/media libraries with an unrelated FFmpeg
    # build: install the userspace inspection/HLS pieces around the vendor
    # stack and validate the actual encoder instead.
    if [ "${NOMAD_IS_A733:-0}" != "1" ]; then
        return 0
    fi

    echo "Configuring Allwinner A733 hardware media stack..."
    local media_packages=(
        python3-gi gir1.2-gstreamer-1.0
        gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-base-apps
        gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
    )
    local missing=()
    local pkg
    for pkg in "${media_packages[@]}"; do
        dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        echo "Installing A733 media userspace packages: ${missing[*]}"
        if ! nomad_sudo apt-get install -y "${missing[@]}"; then
            echo "Refreshing apt metadata and retrying A733 media packages..."
            nomad_sudo apt-get update
            if ! nomad_sudo apt-get install -y "${missing[@]}"; then
                echo "WARNING: Some A733 GStreamer packages could not be installed."
            fi
        fi
    fi

    local ffmpeg_version=""
    if command -v ffmpeg >/dev/null 2>&1; then
        ffmpeg_version="$(ffmpeg -version 2>/dev/null | head -n 1 || true)"
        [ -n "$ffmpeg_version" ] && echo "FFmpeg: $ffmpeg_version"
    fi

    if ! command -v gst-inspect-1.0 >/dev/null 2>&1; then
        echo "WARNING: gst-inspect-1.0 is unavailable; A733 OMX hardware cannot be validated."
        return 0
    fi

    local required_element
    for required_element in uridecodebin hlssink2 avenc_aac h264parse; do
        if ! gst-inspect-1.0 "$required_element" >/dev/null 2>&1; then
            echo "WARNING: GStreamer element '$required_element' is missing; Nomad will retain FFmpeg fallback."
        fi
    done

    if gst-inspect-1.0 omxh264videoenc >/dev/null 2>&1; then
        echo "A733 OMX H.264 encoder found: omxh264videoenc"
        if timeout 12s gst-launch-1.0 -q -e \
            videotestsrc num-buffers=4 ! \
            video/x-raw,width=320,height=240,framerate=1/1 ! \
            omxh264videoenc ! h264parse ! fakesink >/dev/null 2>&1; then
            echo "A733 OMX H.264 encoder runtime test: PASS"
        else
            echo "WARNING: omxh264videoenc is installed but failed a runtime encode test."
            echo "         Nomad will not rely on it until playback diagnostics validates it."
        fi
    else
        echo "WARNING: Allwinner A733 detected but omxh264videoenc is not present."
        echo "         Radxa ships the A733 codec engine as part of its vendor OS media stack."
        echo "         Use 'sudo rsetup' -> System -> System Update, or a current official A733 image,"
        echo "         rather than replacing the vendor kernel/media libraries with a generic apt upgrade."
    fi
}

nomad_ensure_ssh() {
    # A headless Nomad appliance must remain manageable even if the web UI is
    # unavailable. Debian-family images call the OpenSSH unit "ssh"; tolerate
    # distro aliases while keeping failure non-fatal to the media service.
    if ! command -v sshd >/dev/null 2>&1; then
        echo "WARNING: OpenSSH server binary is unavailable after package installation."
        return 0
    fi

    local unit=""
    if systemctl list-unit-files ssh.service >/dev/null 2>&1; then
        unit="ssh.service"
    elif systemctl list-unit-files sshd.service >/dev/null 2>&1; then
        unit="sshd.service"
    fi
    if [ -z "$unit" ]; then
        echo "WARNING: OpenSSH is installed but no ssh/sshd systemd unit was found."
        return 0
    fi

    if nomad_sudo systemctl enable --now "$unit" >/dev/null 2>&1; then
        local listen=""
        if command -v ss >/dev/null 2>&1; then
            listen="$(ss -ltn 2>/dev/null | awk '$4 ~ /(^|:)22$/ {print $4; exit}' || true)"
        fi
        if [ -n "$listen" ]; then
            echo "SSH remote access: enabled and listening on port 22 ($listen)."
        else
            echo "SSH remote access: $unit is active; port 22 listener not yet visible."
        fi
    else
        echo "WARNING: OpenSSH is installed but $unit could not be enabled/started."
        nomad_sudo systemctl status "$unit" --no-pager -l 2>/dev/null | tail -n 12 || true
    fi
}

nomad_install_packages() {
    local required=(
        git ca-certificates curl python3 python3-pip python3-venv python3-dev
        network-manager dos2unix ntfs-3g avahi-daemon samba samba-common-bin
        minidlna unar libarchive-tools ffmpeg openssh-server
    )
    local missing=()
    local pkg
    for pkg in "${required[@]}"; do
        dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done

    if [ "${#missing[@]}" -gt 0 ]; then
        echo "Installing required system packages: ${missing[*]}"
        if ! nomad_sudo apt-get install -y "${missing[@]}"; then
            echo "Refreshing apt metadata and retrying required packages..."
            nomad_sudo apt-get update
            nomad_sudo apt-get install -y "${missing[@]}"
        fi
    else
        echo "Required system packages are already installed."
    fi

    # Distro releases disagree on these package names. They are useful but not
    # worth aborting an otherwise healthy install.
    if ! command -v 7z >/dev/null 2>&1 && ! command -v 7zz >/dev/null 2>&1; then
        nomad_sudo apt-get install -y 7zip 2>/dev/null || nomad_sudo apt-get install -y p7zip-full 2>/dev/null || true
    fi
    if ! command -v mount.exfat >/dev/null 2>&1 && ! command -v mkfs.exfat >/dev/null 2>&1; then
        nomad_sudo apt-get install -y exfatprogs 2>/dev/null || nomad_sudo apt-get install -y exfat-fuse 2>/dev/null || true
    fi

    nomad_install_media_stack
    nomad_ensure_ssh
}

nomad_set_env_key() {
    local file="$1"
    local key="$2"
    local value="$3"
    local tmp
    tmp="$(mktemp)"
    if [ -f "$file" ]; then
        nomad_sudo cat "$file" > "$tmp" 2>/dev/null || true
    fi
    awk -v k="$key" 'index($0, k "=") != 1 {print}' "$tmp" > "${tmp}.new"
    printf '%s=%s\n' "$key" "$value" >> "${tmp}.new"
    nomad_sudo install -m 600 "${tmp}.new" "$file"
    rm -f "$tmp" "${tmp}.new"
}

nomad_get_env_key() {
    local file="$1"
    local key="$2"
    local value=""
    if [ -f "$file" ]; then
        value="$(nomad_sudo awk -v k="$key" '
            index($0, k "=") == 1 { value = substr($0, length(k) + 2) }
            END { if (value != "") print value }
        ' "$file" 2>/dev/null || true)"
    fi
    printf '%s' "$value"
    return 0
}

nomad_stamp_assets() {
    local root="$1"
    local stamp="$2"
    STAMP="$stamp" ROOT="$root" python3 - <<'PY'
import os
from pathlib import Path
import re

root = Path(os.environ["ROOT"])
stamp = re.sub(r"[^0-9A-Za-z._-]", "-", os.environ.get("STAMP", "dev"))
index = root / "app/static/index.html"
sw = root / "app/static/sw.js"

if index.exists():
    text = index.read_text(encoding="utf-8")
    text = re.sub(r"\?v=[0-9A-Za-z._-]+", f"?v={stamp}", text)
    index.write_text(text, encoding="utf-8")

if sw.exists():
    text = sw.read_text(encoding="utf-8")
    text = re.sub(r"const CACHE_NAME = '[^']*'", f"const CACHE_NAME = 'nomad-pi-{stamp}'", text, count=1)
    sw.write_text(text, encoding="utf-8")
PY
}

nomad_install_wifi_guard() {
    local root="$1"
    [ -f "$root/scripts/wifi-guard.sh" ] || return 0
    nomad_sudo install -m 755 "$root/scripts/wifi-guard.sh" /usr/local/sbin/nomad-pi-wifi-guard.sh 2>/dev/null || return 0
    if [ -f "$root/os-builder/stage3-nomad/03-setup-services/files/nomad-pi-wifi-guard.service" ]; then
        nomad_sudo install -m 644 "$root/os-builder/stage3-nomad/03-setup-services/files/nomad-pi-wifi-guard.service" /etc/systemd/system/ 2>/dev/null || true
    fi
    if [ -f "$root/os-builder/stage3-nomad/03-setup-services/files/nomad-pi-wifi-guard.timer" ]; then
        nomad_sudo install -m 644 "$root/os-builder/stage3-nomad/03-setup-services/files/nomad-pi-wifi-guard.timer" /etc/systemd/system/ 2>/dev/null || true
    fi
    nomad_sudo mkdir -p /etc/nomad-pi 2>/dev/null || true
    nomad_sudo systemctl daemon-reload 2>/dev/null || true
    nomad_sudo systemctl enable --now nomad-pi-wifi-guard.timer 2>/dev/null || true
}

nomad_configure_minidlna() {
    local root="$1"
    local hostname="$2"
    command -v minidlnad >/dev/null 2>&1 || return 0

    nomad_sudo mkdir -p /var/cache/minidlna /var/log/minidlna
    nomad_sudo chown -R minidlna:minidlna /var/cache/minidlna /var/log/minidlna 2>/dev/null || true
    if [ -f /proc/sys/fs/inotify/max_user_watches ]; then
        echo 524288 | nomad_sudo tee /proc/sys/fs/inotify/max_user_watches >/dev/null 2>&1 || true
        if ! grep -q '^fs.inotify.max_user_watches=' /etc/sysctl.conf 2>/dev/null; then
            echo 'fs.inotify.max_user_watches=524288' | nomad_sudo tee -a /etc/sysctl.conf >/dev/null
        fi
    fi

    local tmp
    tmp="$(mktemp)"
    cat > "$tmp" <<EOF
media_dir=$root/data
db_dir=/var/cache/minidlna
log_dir=/var/log/minidlna
log_level=general,artwork,database,inotify,scanner,metadata,http,ssdp,tivo=warn
friendly_name=$hostname
port=8200
inotify=yes
notify_interval=60
root_container=.
presentation_url=http://$hostname.local:8000/
album_art_names=Cover.jpg/cover.jpg/AlbumArtSmall.jpg/albumartsmall.jpg/AlbumArt.jpg/albumart.jpg/Folder.jpg/folder.jpg/Thumb.jpg/thumb.jpg
max_connections=50
strict_dlna=no
enable_tivo=no
wide_links=yes
exclude=\$RECYCLE.BIN,\$Recycle.Bin,Recycled,System Volume Information,.Trashes,.Trash-*,.TemporaryItems,.Spotlight-V100,.fseventsd,lost+found,.AppleDouble,.DS_Store,Thumbs.db
EOF
    if [ ! -f /etc/minidlna.conf ] || ! diff -q "$tmp" /etc/minidlna.conf >/dev/null 2>&1; then
        nomad_sudo cp "$tmp" /etc/minidlna.conf
        nomad_sudo systemctl stop minidlna 2>/dev/null || true
        nomad_sudo rm -f /var/cache/minidlna/files.db 2>/dev/null || true
    fi
    rm -f "$tmp"
    nomad_sudo systemctl enable minidlna 2>/dev/null || true
    nomad_sudo systemctl restart minidlna 2>/dev/null || true
}

nomad_ensure_tailscale() {
    if command -v tailscale >/dev/null 2>&1; then
        nomad_sudo systemctl enable --now tailscaled 2>/dev/null || true
        return 0
    fi
    echo "Installing optional Tailscale remote-access client..."
    if curl -fsSL https://tailscale.com/install.sh | sh; then
        nomad_sudo systemctl enable --now tailscaled 2>/dev/null || true
    else
        echo "WARNING: Tailscale installation failed; Nomad itself remains usable."
    fi
}
