#!/bin/bash
# Diagnostic script to verify Tailscale UI is present

echo "=================================="
echo "Tailscale UI Diagnostic Check"
echo "=================================="
echo ""

# Get the install directory
INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$INSTALL_DIR"

echo "Install directory: $INSTALL_DIR"
echo ""

# Check git branch and commit
echo "=== Git Status ==="
git branch --show-current
echo "Latest commit: $(git log -1 --oneline)"
echo ""

# Check if Tailscale section exists in HTML
echo "=== Checking admin.html ==="
if grep -q "Tailscale VPN" app/static/admin.html; then
    count=$(grep -c "Tailscale VPN" app/static/admin.html)
    echo "✓ Tailscale VPN section found ($count occurrences)"
else
    echo "✗ Tailscale VPN section NOT found in HTML!"
fi

# Check version number
version=$(grep "admin.js?v=" app/static/admin.html | grep -oP 'v=\K[0-9]+' | head -1)
echo "Cache-busting version: v=$version"
echo ""

# Check if Tailscale code exists in JS
echo "=== Checking admin.js ==="
if grep -q "tailscale:" app/static/js/admin.js; then
    echo "✓ Tailscale data object found"
else
    echo "✗ Tailscale data object NOT found in JS!"
fi

if grep -q "refreshTailscaleStatus" app/static/js/admin.js; then
    echo "✓ Tailscale methods found"
else
    echo "✗ Tailscale methods NOT found in JS!"
fi
echo ""

# Check if Tailscale endpoints exist in backend
echo "=== Checking system.py ==="
if grep -q "/tailscale/status" app/routers/system.py; then
    count=$(grep -c "@router.*tailscale" app/routers/system.py)
    echo "✓ Tailscale endpoints found ($count endpoints)"
else
    echo "✗ Tailscale endpoints NOT found in backend!"
fi
echo ""

# Check service worker version
echo "=== Checking service worker ==="
sw_version=$(grep "CACHE_NAME" app/static/sw.js | grep -oP "'.*?'" | head -1)
echo "Service worker cache: $sw_version"
echo ""

# Check if service is running
echo "=== Service Status ==="
if systemctl is-active --quiet nomad-pi 2>/dev/null; then
    echo "✓ nomad-pi service is running"
    echo "Service uptime: $(systemctl show nomad-pi --property=ActiveEnterTimestamp --value)"
else
    echo "✗ nomad-pi service is NOT running!"
fi
echo ""

# Check if files are being served
echo "=== File Verification ==="
echo "admin.html size: $(wc -c < app/static/admin.html) bytes"
echo "admin.html modified: $(stat -c %y app/static/admin.html 2>/dev/null || stat -f %Sm app/static/admin.html)"
echo "admin.js size: $(wc -c < app/static/js/admin.js) bytes"
echo "admin.js modified: $(stat -c %y app/static/js/admin.js 2>/dev/null || stat -f %Sm app/static/js/admin.js)"
echo ""

echo "=================================="
echo "Diagnostic complete!"
echo ""
echo "If all checks show ✓ but you still don't see the UI:"
echo "1. Restart service: sudo systemctl restart nomad-pi"
echo "2. Clear browser cache completely"
echo "3. Try accessing in incognito/private mode"
echo "4. Check browser console (F12) for JavaScript errors"
echo "=================================="
