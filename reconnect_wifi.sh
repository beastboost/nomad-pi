#!/bin/bash

echo "=========================================="
echo "  Nomad Pi WiFi Reconnection Tool"
echo "=========================================="
echo ""

# Check current connection
echo "Current active connections:"
nmcli connection show --active
echo ""

# Check WiFi Power Management
WIFI_DEV="$(nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')"
if [ -n "$WIFI_DEV" ]; then
    echo "WiFi Power Management Status:"
    iw dev "$WIFI_DEV" get power_save 2>/dev/null || echo "  (Not supported/No iw tool)"
    echo ""
fi

# Check if hotspot is active
if nmcli connection show --active | grep -q "NomadPi"; then
    echo "✓ Hotspot 'NomadPi' is currently active"
    echo ""
    echo "Options:"
    echo "1. Disable hotspot and reconnect to saved WiFi"
    echo "2. Keep hotspot active"
    echo ""
    read -p "Enter choice (1 or 2): " choice
    
    if [ "$choice" = "1" ]; then
        echo ""
        echo "Disabling hotspot..."
        sudo nmcli connection down NomadPi
        
        echo "Waiting 3 seconds..."
        sleep 3
        
        # Try to connect to home WiFi
        if [ -f "/etc/nomadpi.env" ]; then
            source "/etc/nomadpi.env" 2>/dev/null || true
        fi
        
        if [ -n "$HOME_SSID" ]; then
            echo "Attempting to connect to '$HOME_SSID' from config..."
            sudo nmcli connection up id "$HOME_SSID" || sudo nmcli dev wifi connect "$HOME_SSID" password "$HOME_PASS"
        else
            echo "No HOME_SSID set. Listing available WiFi networks..."
            echo ""
            nmcli device wifi list
            echo ""
            read -p "Enter WiFi SSID to connect to: " SSID
            read -sp "Enter WiFi password: " PASSWORD
            echo ""
            
            echo "Connecting to '$SSID'..."
            sudo nmcli device wifi connect "$SSID" password "$PASSWORD"
        fi
        
        echo ""
        echo "Current connection status:"
        nmcli connection show --active
    fi
else
    echo "Hotspot is not active."
    echo ""
    echo "Checking WiFi connection..."
    
    if nmcli connection show --active | grep -q "802-11-wireless"; then
        echo "✓ Connected to WiFi"
        CURRENT_WIFI=$(nmcli -t -f NAME,TYPE connection show --active | grep "802-11-wireless" | cut -d: -f1)
        echo "  Network: $CURRENT_WIFI"
        
        # Get IP address
        IP=$(hostname -I | awk '{print $1}')
        echo "  IP Address: $IP"
        echo ""
        echo "Access Nomad Pi at: http://$IP:8000"
    else
        echo "✗ Not connected to WiFi"
        echo ""
        echo "Available WiFi networks:"
        nmcli device wifi list
        echo ""
        read -p "Enter WiFi SSID to connect to: " SSID
        read -sp "Enter WiFi password: " PASSWORD
        echo ""
        
        echo "Connecting to '$SSID'..."
        sudo nmcli device wifi connect "$SSID" password "$PASSWORD"
        
        if [ $? -eq 0 ]; then
            echo "✓ Successfully connected!"
            IP=$(hostname -I | awk '{print $1}')
            echo "Access Nomad Pi at: http://$IP:8000"
        else
            echo "✗ Connection failed"
            echo ""
            echo "Enabling hotspot as fallback..."
            sudo nmcli connection up NomadPi
            echo ""
            echo "Connect to WiFi 'NomadPi' (password: nomadpassword)"
            echo "Then access: http://10.42.0.1:8000"
        fi
    fi
fi

echo ""
echo "=========================================="
echo "  Done"
echo "=========================================="
