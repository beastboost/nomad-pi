#!/bin/bash

# Nomad Pi Network Configuration Tool
# This tool helps you lock the device to Hotspot mode or configure Home Wi-Fi properly.

set -e

ENV_FILE="/etc/nomadpi.env"

echo "=========================================="
echo "    Nomad Pi Network Configuration        "
echo "=========================================="
echo ""

show_status() {
    echo "Current Network Status:"
    nmcli -t -f NAME,TYPE,DEVICE,STATE connection show --active | grep "802-11-wireless" || echo "No active Wi-Fi connections."
    echo ""
    echo "Saved Wi-Fi Networks:"
    nmcli -t -f NAME,TYPE connection show | grep "802-11-wireless" | cut -d: -f1 || echo "None"
    echo ""
    IP_ADDR=$(hostname -I | awk '{print $1}')
    echo "Current IP Address: ${IP_ADDR:-None}"
    echo "Hostname: nomadpi.local"
    echo "=========================================="
}

show_status

echo "Select an option:"
echo "1) Lock to Hotspot Mode Only (Best for portability)"
echo "2) Configure Home Wi-Fi (Connect to your router)"
echo "3) Lock to Current Wi-Fi (Disable others)"
echo "4) Delete a Saved Network"
echo "5) Reset All Networking (Clean start)"
echo "6) Exit"
echo ""
read -p "Choice [1-6]: " choice

case $choice in
    1)
        echo "Locking to Hotspot Mode..."
        sudo nmcli con modify "NomadPi" connection.autoconnect yes connection.autoconnect-priority 100
        while IFS=: read -r NAME TYPE; do
            if [ "$TYPE" = "802-11-wireless" ] && [ "$NAME" != "NomadPi" ]; then
                echo "Disabling autoconnect for $NAME..."
                sudo nmcli con modify "$NAME" connection.autoconnect no || true
            fi
        done < <(nmcli -t -f NAME,TYPE connection show)
        
        echo "Activating Hotspot..."
        sudo nmcli con up "NomadPi" || true
        echo "✓ Device locked to Hotspot mode."
        ;;
    2)
        echo "Configuring Home Wi-Fi..."
        read -p "Enter Wi-Fi SSID: " ssid
        read -sp "Enter Wi-Fi Password: " pass
        echo ""
        
        if [ -f "$ENV_FILE" ]; then
            sudo sed -i '/^HOME_SSID=/d' "$ENV_FILE"
            sudo sed -i '/^HOME_PASS=/d' "$ENV_FILE"
        fi
        sudo bash -c "echo 'HOME_SSID=\"$ssid\"' >> $ENV_FILE"
        sudo bash -c "echo 'HOME_PASS=\"$pass\"' >> $ENV_FILE"
        
        echo "Connecting to $ssid..."
        if sudo nmcli dev wifi connect "$ssid" password "$pass"; then
            echo "✓ Connected successfully!"
            sudo nmcli con modify "NomadPi" connection.autoconnect yes connection.autoconnect-priority 0
            sudo nmcli con modify "$ssid" connection.autoconnect yes connection.autoconnect-priority 10
        else
            echo "✗ Failed to connect. Reverting to Hotspot..."
            sudo nmcli con up "NomadPi" || true
        fi
        ;;
    3)
        echo "Locking to current Wi-Fi..."
        CURRENT_WIFI=$(nmcli -t -f NAME,TYPE,STATE connection show --active | grep "802-11-wireless" | grep ":activated" | cut -d: -f1 | head -n 1)
        if [ -z "$CURRENT_WIFI" ]; then
            echo "✗ You are not currently connected to any Wi-Fi. Connect first (Option 2)."
        else
            echo "Locking to '$CURRENT_WIFI' and disabling others..."
            while IFS=: read -r NAME TYPE; do
                if [ "$TYPE" = "802-11-wireless" ] && [ "$NAME" != "$CURRENT_WIFI" ] && [ "$NAME" != "NomadPi" ]; then
                    echo "Disabling autoconnect for $NAME..."
                    sudo nmcli con modify "$NAME" connection.autoconnect no || true
                fi
            done < <(nmcli -t -f NAME,TYPE connection show)
            
            sudo nmcli con modify "$CURRENT_WIFI" connection.autoconnect yes connection.autoconnect-priority 100
            echo "✓ Locked to '$CURRENT_WIFI'. The Pi will no longer hop to other networks."
        fi
        ;;
    4)
        echo "Select a network to delete:"
        nmcli -t -f NAME,TYPE connection show | grep "802-11-wireless" | cut -d: -f1
        read -p "Enter SSID to delete: " del_ssid
        if [ -n "$del_ssid" ]; then
            sudo nmcli connection delete "$del_ssid" && echo "✓ Deleted $del_ssid" || echo "✗ Failed to delete."
        fi
        ;;
    5)
        echo "Resetting networking..."
        sudo nmcli con modify "NomadPi" connection.autoconnect yes connection.autoconnect-priority 0
        while IFS=: read -r NAME TYPE; do
            if [ "$TYPE" = "802-11-wireless" ] && [ "$NAME" != "NomadPi" ]; then
                sudo nmcli con modify "$NAME" connection.autoconnect yes connection.autoconnect-priority 5 || true
            fi
        done < <(nmcli -t -f NAME,TYPE connection show)
        echo "Network priorities reset."
        ;;
    *)
        echo "Exiting."
        exit 0
        ;;
esac

echo ""
echo "Note: Use http://nomadpi.local:8000 to access your server consistently."
