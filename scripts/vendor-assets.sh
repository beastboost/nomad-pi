#!/bin/bash
# Vendor the front-end's third-party assets into app/static/vendor/.
#
# Nomad Pi is used offline — on a hotspot in a van, on a plane, anywhere with
# no uplink. Loading the icon font and Inter from a CDN at runtime means the
# first visit on an offline box renders without icons. This script pulls them
# down once, at setup/update time (when the Pi does have internet), so the
# running app is fully self-hosted.
#
# Safe to re-run. Never fails the caller: if the network is unavailable the
# app falls back to the CDN links at runtime.

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$SCRIPT_DIR/app/static/vendor"
PH_VER="2.1.1"
PH_BASE="https://unpkg.com/@phosphor-icons/web@${PH_VER}/src"

mkdir -p "$VENDOR/phosphor" "$VENDOR/inter" || exit 0

fetch() {
    # fetch <url> <dest>  — returns non-zero on failure without killing the run
    curl -fsSL --max-time 45 --retry 2 --retry-delay 2 -o "$2" "$1" 2>/dev/null
}

ok=1

echo "Vendoring Phosphor icons…"
for variant in regular fill; do
    css="$VENDOR/phosphor/$variant.css"
    if fetch "$PH_BASE/$variant/style.css" "$css"; then
        # Pull every font file the stylesheet references and rewrite the urls
        # to sit next to it.
        grep -oE "url\(['\"]?[^)'\"]+\.(woff2|woff|ttf)" "$css" 2>/dev/null \
            | sed -E "s/url\(['\"]?//" | sort -u | while read -r rel; do
            file="$(basename "$rel")"
            case "$rel" in
                http*) url="$rel" ;;
                /*)    url="https://unpkg.com$rel" ;;
                *)     url="$PH_BASE/$variant/${rel#./}" ;;
            esac
            fetch "$url" "$VENDOR/phosphor/$file" || true
        done
        sed -i -E "s|url\((['\"]?)[^)'\"]*/([^)/'\"]+\.(woff2|woff|ttf))|url(\1\2|g" "$css"
    else
        echo "  ! could not fetch Phosphor $variant — the app will use the CDN"
        ok=0
    fi
done

echo "Vendoring Inter…"
INTER_CSS="$VENDOR/inter/inter.css"
# Ask for the woff2 form by sending a modern User-Agent
if curl -fsSL --max-time 45 \
     -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36" \
     -o "$INTER_CSS" \
     "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" 2>/dev/null; then
    grep -oE "https://fonts.gstatic.com[^)]+\.woff2" "$INTER_CSS" | sort -u | while read -r url; do
        fetch "$url" "$VENDOR/inter/$(basename "$url")" || true
    done
    sed -i -E "s|https://fonts.gstatic.com[^)]*/([^)/]+\.woff2)|\1|g" "$INTER_CSS"
else
    echo "  ! could not fetch Inter — the app will use the CDN"
    ok=0
fi

if [ "$ok" = "1" ]; then
    echo "Vendored assets ready in app/static/vendor/ — the UI no longer needs a CDN."
else
    echo "Some assets could not be vendored; the UI falls back to CDN links."
fi
exit 0
