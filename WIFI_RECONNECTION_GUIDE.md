# WiFi Reconnection Guide

## Hotspot Information

**SSID:** `NomadPi`  
**Password:** `nomadpassword`  
**IP Address:** `http://10.42.0.1:8000`

---

## Issue: Pi Disconnected from WiFi During Upload

This can happen when:
1. WiFi signal drops
2. Router disconnects idle devices
3. Network interference
4. Pi switches to hotspot mode automatically

---

## Quick Reconnection Methods

### Method 1: Via Hotspot (Easiest)

1. **Connect to Hotspot:**
   - On your device, connect to WiFi: `NomadPi`
   - Password: `nomadpassword`

2. **Access Web UI:**
   - Open browser to: `http://10.42.0.1:8000`

3. **Reconnect to WiFi:**
   ```bash
   # Via API
   curl -X POST http://10.42.0.1:8000/api/system/wifi/reconnect
   
   # Or specific network
   curl -X POST "http://10.42.0.1:8000/api/system/wifi/reconnect?ssid=YourWiFiName"
   ```

4. **Or use the reconnection script:**
   ```bash
   ssh pi@10.42.0.1
   cd /path/to/nomad-pi
   ./reconnect_wifi.sh
   ```

---

### Method 2: Via SSH

**If you can reach the Pi:**

```bash
# SSH into Pi
ssh pi@nomadpi.local
# OR
ssh pi@10.42.0.1  # If on hotspot

# Check current status
nmcli connection show --active

# Disable hotspot
sudo nmcli connection down NomadPi

# Reconnect to your WiFi
sudo nmcli connection up id "YourWiFiName"

# Or let it auto-connect
# (It should try to connect to saved WiFi automatically)
```

---

### Method 3: Use Reconnection Script

```bash
# SSH into Pi
ssh pi@nomadpi.local

# Run the script
cd /path/to/nomad-pi
./reconnect_wifi.sh
```

The script will:
- Show current connection status
- Offer to disable hotspot
- Try to reconnect to saved WiFi
- Or let you manually select a network

---

### Method 4: Via New API Endpoints

**Get WiFi Status:**
```bash
curl http://10.42.0.1:8000/api/system/wifi/status
```

**List Saved WiFi Networks:**
```bash
curl http://10.42.0.1:8000/api/system/wifi/saved
```

**Reconnect to WiFi:**
```bash
# Auto-reconnect to saved WiFi
curl -X POST http://10.42.0.1:8000/api/system/wifi/reconnect

# Connect to specific network
curl -X POST "http://10.42.0.1:8000/api/system/wifi/reconnect?ssid=YourWiFiName"
```

**Disable Hotspot:**
```bash
curl -X POST "http://10.42.0.1:8000/api/system/wifi/toggle-hotspot?enable=false"
```

---

## Preventing Future Disconnections

### 1. Improve WiFi Signal

**Check Signal Strength:**
```bash
iwconfig wlan0 | grep -E "Signal level|Link Quality"
```

**Improvements:**
- Move Pi closer to router
- Use 5GHz WiFi instead of 2.4GHz
- Remove obstacles between Pi and router
- Update router firmware

### 2. Disable WiFi Power Management

```bash
# Check if power management is on
iwconfig wlan0 | grep "Power Management"

# Disable it
sudo iwconfig wlan0 power off

# Make permanent
echo "wireless-power off" | sudo tee -a /etc/network/interfaces
```

### 3. Increase Router Timeout

In your router settings:
- Increase DHCP lease time
- Disable "disconnect idle devices"
- Increase WiFi timeout settings

### 4. Use Static IP

```bash
# Edit connection
sudo nmcli connection modify "YourWiFiName" ipv4.method manual
sudo nmcli connection modify "YourWiFiName" ipv4.addresses 192.168.1.100/24
sudo nmcli connection modify "YourWiFiName" ipv4.gateway 192.168.1.1
sudo nmcli connection modify "YourWiFiName" ipv4.dns "8.8.8.8 8.8.4.4"

# Reconnect
sudo nmcli connection up "YourWiFiName"
```

### 5. Disable Auto-Hotspot

If you don't want the Pi to automatically switch to hotspot:

```bash
# Lower hotspot priority
sudo nmcli connection modify NomadPi connection.autoconnect-priority -999

# Or disable auto-connect entirely
sudo nmcli connection modify NomadPi connection.autoconnect no
```

---

## Troubleshooting

### Can't Connect to Hotspot

**Check if hotspot is running:**
```bash
nmcli connection show --active | grep NomadPi
```

**Manually enable hotspot:**
```bash
sudo nmcli connection up NomadPi
```

**Check WiFi device:**
```bash
nmcli device status
# wlan0 should show as "connected" or "disconnected"
```

### Can't Reconnect to WiFi

**List saved connections:**
```bash
nmcli connection show
```

**Check WiFi is available:**
```bash
nmcli device wifi list
```

**Rescan for networks:**
```bash
sudo nmcli device wifi rescan
sleep 5
nmcli device wifi list
```

**Connect to new network:**
```bash
sudo nmcli device wifi connect "SSID" password "PASSWORD"
```

### Pi Not Responding

**Physical access needed:**
1. Connect monitor and keyboard
2. Login (default: pi/raspberry or your password)
3. Run: `nmcli connection show --active`
4. Reconnect manually

**Or reboot:**
```bash
sudo reboot
```

After reboot, Pi should try to connect to saved WiFi automatically.

---

## Understanding the WiFi Priority System

The Pi tries connections in this order:

1. **Saved WiFi networks** (priority 0 or higher)
2. **Hotspot** (priority 0, but only if no WiFi available)

**How it works:**
- Pi boots → tries saved WiFi
- If WiFi fails → enables hotspot
- If WiFi comes back → stays on hotspot (manual switch needed)

**To change behavior:**
```bash
# Make WiFi higher priority
sudo nmcli connection modify "YourWiFiName" connection.autoconnect-priority 10

# Make hotspot lower priority
sudo nmcli connection modify NomadPi connection.autoconnect-priority -10
```

---

## Monitoring WiFi Connection

### Real-Time Monitoring

```bash
# Watch connection status
watch -n 2 'nmcli connection show --active'

# Watch signal strength
watch -n 2 'iwconfig wlan0 | grep -E "Signal level|Link Quality"'

# Watch for disconnections
journalctl -u NetworkManager -f
```

### Check Connection History

```bash
# Recent NetworkManager logs
journalctl -u NetworkManager -n 50

# WiFi disconnection events
journalctl | grep -i "wlan0.*disconnected"
```

---

## API Reference

### Get WiFi Status
```
GET /api/system/wifi/status

Response:
{
  "mode": "wifi|hotspot|disconnected",
  "ssid": "NetworkName",
  "signal": -45,
  "interface": "wlan0"
}
```

### Toggle Hotspot
```
POST /api/system/wifi/toggle-hotspot?enable=true

Response:
{
  "status": "ok",
  "mode": "hotspot",
  "ssid": "NomadPi",
  "password": "nomadpassword",
  "url": "http://10.42.0.1:8000"
}
```

### Reconnect to WiFi
```
POST /api/system/wifi/reconnect
POST /api/system/wifi/reconnect?ssid=NetworkName

Response:
{
  "status": "ok",
  "mode": "wifi",
  "ssid": "NetworkName",
  "message": "Connected to NetworkName"
}
```

### List Saved WiFi
```
GET /api/system/wifi/saved

Response:
{
  "connections": ["HomeWiFi", "WorkWiFi"],
  "count": 2
}
```

---

## Common Scenarios

### Scenario 1: Upload Interrupted

**What happened:**
- Upload in progress
- WiFi dropped
- Pi switched to hotspot
- Upload failed

**Solution:**
1. Connect to hotspot: `NomadPi` / `nomadpassword`
2. Access: `http://10.42.0.1:8000`
3. Run: `curl -X POST http://10.42.0.1:8000/api/system/wifi/reconnect`
4. Wait for reconnection
5. Resume upload

### Scenario 2: Can't Find Pi

**What happened:**
- Pi disconnected
- Don't know if it's on WiFi or hotspot

**Solution:**
1. Check for hotspot: Look for `NomadPi` in WiFi list
2. If found: Connect and access `http://10.42.0.1:8000`
3. If not found: Pi might be on WiFi, try `http://nomadpi.local:8000`
4. Still can't find: Check router for Pi's IP address

### Scenario 3: Frequent Disconnections

**What happened:**
- Pi keeps disconnecting from WiFi
- Switches to hotspot repeatedly

**Solution:**
1. Check signal strength: `iwconfig wlan0`
2. Move Pi closer to router
3. Disable power management: `sudo iwconfig wlan0 power off`
4. Use Ethernet instead (most reliable)

---

## Best Practices

### For Uploads

1. **Use Ethernet** if possible (most reliable)
2. **Check WiFi signal** before large uploads
3. **Disable power management** on WiFi
4. **Use hotspot mode** for direct connection testing

### For Reliability

1. **Set static IP** to prevent DHCP issues
2. **Increase router timeout** settings
3. **Monitor signal strength** regularly
4. **Keep Pi close to router** or use WiFi extender

### For Troubleshooting

1. **Always have hotspot as backup**
2. **Know the hotspot password**: `nomadpassword`
3. **Keep SSH access** available
4. **Monitor logs** for disconnection patterns

---

## Summary

**Hotspot Info:**
- SSID: `NomadPi`
- Password: `nomadpassword`
- URL: `http://10.42.0.1:8000`

**Quick Reconnect:**
```bash
# Via hotspot
curl -X POST http://10.42.0.1:8000/api/system/wifi/reconnect

# Via SSH
sudo nmcli connection down NomadPi
sudo nmcli connection up id "YourWiFiName"

# Via script
./reconnect_wifi.sh
```

**Prevention:**
- Improve WiFi signal
- Disable power management
- Use static IP
- Consider Ethernet

---

**Need Help?**
- Check logs: `journalctl -u NetworkManager -n 50`
- Check status: `nmcli connection show --active`
- Run diagnostic: `./diagnose_upload_speed.sh`
