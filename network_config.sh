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
    IP_ADDR=$(hostname -I | awk '{print $1}')
    echo "Current IP Address: ${IP_ADDR:-None}"
    echo "Hostname: nomadpi.local"
    echo "=========================================="
}

show_status

echo "Select an option:"
echo "1) Lock to Hotspot Mode Only (Best for portability)"
echo "2) Configure Home Wi-Fi (Connect to your router)"
echo "3) Reset All Networking (Clean start)"
echo "4) Exit"
echo ""
read -p "Choice [1-4]: " choice

case $choice in
    1)
        echo "Locking to Hotspot Mode..."
        # Set Hotspot to high priority
        sudo nmcli con modify "NomadPi" connection.autoconnect-priority 100
        # Disable autoconnect for other wireless connections
        while IFS=: read -r NAME TYPE; do
            if [ "$TYPE" = "802-11-wireless" ] && [ "$NAME" != "NomadPi" ]; then
                echo "Disabling autoconnect for $NAME..."
                sudo nmcli con modify "$NAME" connection.autoconnect no || true
            fi
        done < <(nmcli -t -f NAME,TYPE connection show)
        
        echo "Activating Hotspot..."
        sudo nmcli con up "NomadPi" || true
        echo "✓ Device locked to Hotspot mode."
        echo "Connect to: NomadPi (password: nomadpassword)"
        echo "Access at: http://10.42.0.1:8000"
        ;;
    2)
        echo "Configuring Home Wi-Fi..."
        read -p "Enter Wi-Fi SSID: " ssid
        read -sp "Enter Wi-Fi Password: " pass
        echo ""
        
        # Save to env file for persistence across setups
        if [ -f "$ENV_FILE" ]; then
            sudo sed -i '/^HOME_SSID=/d' "$ENV_FILE"
            sudo sed -i '/^HOME_PASS=/d' "$ENV_FILE"
        fi
        sudo bash -c "echo 'HOME_SSID=\"$ssid\"' >> $ENV_FILE"
        sudo bash -c "echo 'HOME_PASS=\"$pass\"' >> $ENV_FILE"
        
        echo "Connecting to $ssid..."
        if sudo nmcli dev wifi connect "$ssid" password "$pass"; then
            echo "✓ Connected successfully!"
            # Set Hotspot to lower priority so it only acts as fallback
            sudo nmcli con modify "NomadPi" connection.autoconnect-priority 0
            # Set this new connection to high priority
            sudo nmcli con modify "$ssid" connection.autoconnect yes connection.autoconnect-priority 10
            
            NEW_IP=$(hostname -I | awk '{print $1}')
            echo "Access Nomad Pi at: http://$NEW_IP:8000"
            echo "Or via hostname: http://nomadpi.local:8000"
        else
            echo "✗ Failed to connect. Reverting to Hotspot..."
            sudo nmcli con up "NomadPi" || true
        fi
        ;;
    3)
        echo "Resetting networking..."
        # This will remove all Wi-Fi connections except NomadPi if we're not careful
        # Better to just set priorities
        sudo nmcli con modify "NomadPi" connection.autoconnect yes connection.autoconnect-priority 0
        echo "Network priorities reset. Hotspot will act as fallback."
        ;;
    *)
        echo "Exiting."
        exit 0
        ;;
esac

echo ""
echo "Note: If you are on a home network, use http://nomadpi.local:8000"
echo "to avoid issues when the IP address changes."
