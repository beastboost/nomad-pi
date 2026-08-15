#!/bin/bash
# Vendor the front-end's third-party assets into app/static/vendor/.
#
# Nomad Pi is used offline — on a hotspot in a van, on a plane, anywhere with
# no uplink. Loading runtime assets from a CDN means the first visit on an
# offline box can lose icons, fonts, readers or adaptive playback. This script
# pulls them down once at setup/update time, so the running app is self-hosted.
#
# Safe to re-run. Never fails the caller: if the network is unavailable the
# app falls back to CDN links where a fallback exists.

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$SCRIPT_DIR/app/static/vendor"
PH_VER="2.1.1"
PH_BASE="https://unpkg.com/@phosphor-icons/web@${PH_VER}/src"
HLS_VER="1.6.16"

mkdir -p "$VENDOR/phosphor" "$VENDOR/inter" "$VENDOR/hls" || exit 0

fetch() {
    # fetch <url> <dest>  — returns non-zero on failure without killing the run
    curl -fsSL --max-time 45 --retry 2 --retry-delay 2 -o "$2" "$1" 2>/dev/null
}

ok=1

echo "Vendoring Phosphor icons…"
for variant in regular fill; do
    css="$VENDOR/phosphor/$variant.css"
    if fetch "$PH_BASE/$variant/style.css" "$css"; then
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

echo "Vendoring epub.js (EPUB reader)…"
mkdir -p "$VENDOR/epub" || true
JSZIP="$VENDOR/epub/.jszip.js"
EPUBJS="$VENDOR/epub/.epub.js"
if fetch "https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js" "$JSZIP" \
   && fetch "https://cdn.jsdelivr.net/npm/epubjs@0.3.93/dist/epub.min.js" "$EPUBJS"; then
    cat "$JSZIP" "$EPUBJS" > "$VENDOR/epub/epub.min.js"
    rm -f "$JSZIP" "$EPUBJS"
else
    echo "  ! could not fetch epub.js — EPUBs will offer a download instead"
    rm -f "$JSZIP" "$EPUBJS"
    ok=0
fi

echo "Vendoring Hls.js (adaptive browser playback)…"
if fetch "https://cdn.jsdelivr.net/npm/hls.js@${HLS_VER}/dist/hls.min.js" "$VENDOR/hls/hls.min.js"; then
    echo "  Hls.js ${HLS_VER} ready"
else
    echo "  ! could not fetch Hls.js — Safari/native HLS still works; other browsers need network fallback"
    rm -f "$VENDOR/hls/hls.min.js"
    ok=0
fi

if [ "$ok" = "1" ]; then
    echo "Vendored assets ready in app/static/vendor/ — the UI no longer needs a CDN."
else
    echo "Some assets could not be vendored; the UI falls back where possible."
fi
exit 0
