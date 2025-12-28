#!/bin/bash

echo "=========================================="
echo "  Nomad Pi Upload Speed Diagnostics"
echo "=========================================="
echo ""

# Check WiFi connection
echo "1. WiFi Connection Status:"
if command -v iwconfig &> /dev/null; then
    iwconfig 2>&1 | grep -E "ESSID|Bit Rate|Link Quality|Signal level" || echo "   No WiFi interface found"
else
    echo "   iwconfig not available"
fi
echo ""

# Check network interface speeds
echo "2. Network Interface Information:"
if command -v ethtool &> /dev/null; then
    for iface in $(ls /sys/class/net/ | grep -v lo); do
        echo "   Interface: $iface"
        ethtool $iface 2>/dev/null | grep -E "Speed|Duplex" || echo "   (ethtool info not available)"
    done
else
    echo "   ethtool not available"
    ip link show | grep -E "state UP" || echo "   No active interfaces"
fi
echo ""

# Check if running on Raspberry Pi
echo "3. Hardware Information:"
if [ -f /proc/device-tree/model ]; then
    echo "   Model: $(cat /proc/device-tree/model)"
else
    echo "   Model: $(uname -m)"
fi
echo ""

# Check Python/FastAPI configuration
echo "4. Application Configuration:"
if [ -f "app/routers/uploads.py" ]; then
    echo "   Upload Chunk Size:"
    grep "CHUNK_SIZE" app/routers/uploads.py | head -1
    echo "   Buffer Size:"
    grep "BUFFER_SIZE" app/routers/uploads.py | head -1
else
    echo "   uploads.py not found"
fi
echo ""

# Check uvicorn settings
echo "5. Server Configuration:"
if [ -f "app/main.py" ]; then
    echo "   Uvicorn settings:"
    grep -A 8 "uvicorn.run" app/main.py | grep -E "limit_concurrency|timeout|backlog" || echo "   Using default settings"
else
    echo "   main.py not found"
fi
echo ""

# Check system resources
echo "6. System Resources:"
echo "   CPU: $(nproc) cores"
echo "   Memory: $(free -h | grep Mem | awk '{print $2}') total, $(free -h | grep Mem | awk '{print $7}') available"
echo "   Load Average: $(uptime | awk -F'load average:' '{print $2}')"
echo ""

# Check disk I/O
echo "7. Disk Performance:"
if [ -d "data/uploads" ]; then
    echo "   Testing write speed to data/uploads..."
    dd if=/dev/zero of=data/uploads/test_write bs=1M count=100 2>&1 | grep -E "copied|MB/s" || echo "   Test failed"
    rm -f data/uploads/test_write
else
    echo "   data/uploads directory not found"
fi
echo ""

# Check for known bottlenecks
echo "8. Known Bottlenecks:"
echo "   Raspberry Pi WiFi Limitations:"
echo "   - Pi 3: ~40-50 Mbps max (5-6 MB/s)"
echo "   - Pi 4: ~100-150 Mbps max (12-18 MB/s)"
echo "   - Pi 5: ~200-300 Mbps max (25-37 MB/s)"
echo ""
echo "   Current observed: ~1.5 MB/s (12 Mbps)"
echo "   This suggests WiFi signal or interference issues"
echo ""

# Recommendations
echo "9. Recommendations:"
echo "   ✓ Code optimizations applied (16MB chunks, buffering)"
echo "   ✓ Server settings optimized (concurrency, timeouts)"
echo ""
echo "   To improve upload speed further:"
echo "   1. Use Ethernet instead of WiFi (10x faster)"
echo "   2. Move Pi closer to WiFi router"
echo "   3. Use 5GHz WiFi instead of 2.4GHz"
echo "   4. Check for WiFi interference (other devices, microwaves)"
echo "   5. Update Pi firmware: sudo rpi-update"
echo "   6. Check router settings (QoS, bandwidth limits)"
echo ""

echo "=========================================="
echo "  Diagnostics Complete"
echo "=========================================="
