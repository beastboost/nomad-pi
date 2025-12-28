# Nomad Pi Quick Reference Card

## 🔐 Hotspot Credentials

**SSID:** `NomadPi`  
**Password:** `nomadpassword`  
**URL:** `http://10.42.0.1:8000`

---

## 🔌 Quick Reconnect

### If Pi is on Hotspot:
```bash
# Connect to NomadPi WiFi (password: nomadpassword)
# Then run:
curl -X POST http://10.42.0.1:8000/api/system/wifi/reconnect
```

### Via SSH:
```bash
ssh pi@10.42.0.1
./reconnect_wifi.sh
```

---

## 📊 System Monitoring

### Check CPU Frequency:
```bash
curl http://nomadpi.local:8000/api/system/stats | jq '.cpu_freq'
```

### Check Throttling:
```bash
curl http://nomadpi.local:8000/api/system/stats | jq '.throttled'
```

### View System Info:
```bash
curl http://nomadpi.local:8000/api/system/info
```

---

## 📡 WiFi Management

### Check Status:
```bash
curl http://nomadpi.local:8000/api/system/wifi/status
```

### List Saved Networks:
```bash
curl http://nomadpi.local:8000/api/system/wifi/saved
```

### Enable Hotspot:
```bash
curl -X POST "http://nomadpi.local:8000/api/system/wifi/toggle-hotspot?enable=true"
```

### Disable Hotspot:
```bash
curl -X POST "http://nomadpi.local:8000/api/system/wifi/toggle-hotspot?enable=false"
```

---

## 📺 DLNA Streaming

### Find on Smart TV:
1. Open TV's media player
2. Look for "Nomad Pi" in DLNA/Media Servers
3. Browse and play

### VLC Desktop:
1. View → Playlist (Ctrl+L)
2. Local Network → Universal Plug'n'Play
3. Click "Nomad Pi"

### VLC Mobile:
1. Open VLC
2. Tap Network/Local Network
3. Tap "Nomad Pi"

---

## 🔄 Update System

### Via Web UI:
1. Admin → System
2. Click "Update from GitHub"
3. Wait for auto-refresh

### Via Command Line:
```bash
cd /path/to/nomad-pi
git pull origin main
sudo systemctl restart nomad-pi
```

---

## 🐛 Troubleshooting

### Upload Slow?
```bash
./diagnose_upload_speed.sh
```

### WiFi Disconnected?
```bash
./reconnect_wifi.sh
```

### Check Logs:
```bash
curl http://nomadpi.local:8000/api/system/logs?lines=50
```

### Check Temperature:
```bash
vcgencmd measure_temp
```

### Check Voltage:
```bash
vcgencmd measure_volts core
```

---

## 📁 Important Paths

- **Media:** `/path/to/nomad-pi/data/`
- **Movies:** `/path/to/nomad-pi/data/movies/`
- **Shows:** `/path/to/nomad-pi/data/shows/`
- **Music:** `/path/to/nomad-pi/data/music/`
- **Books:** `/path/to/nomad-pi/data/books/`
- **Uploads:** `/path/to/nomad-pi/data/uploads/`

---

## 🔧 Common Commands

### Restart Service:
```bash
sudo systemctl restart nomad-pi
```

### Check Service Status:
```bash
sudo systemctl status nomad-pi
```

### View Logs:
```bash
journalctl -u nomad-pi -f
```

### Check Network:
```bash
nmcli connection show --active
```

### Rescan WiFi:
```bash
sudo nmcli device wifi rescan
nmcli device wifi list
```

---

## 🚀 Performance Tips

### For Faster Uploads:
1. Use Ethernet cable (20-50x faster)
2. Move Pi closer to router
3. Use 5GHz WiFi
4. Disable WiFi power management:
   ```bash
   sudo iwconfig wlan0 power off
   ```

### For Better Stability:
1. Keep Pi cool (add heatsink/fan)
2. Use quality power supply
3. Update firmware:
   ```bash
   sudo rpi-update
   ```

---

## 📖 Documentation

- `WIFI_RECONNECTION_GUIDE.md` - WiFi troubleshooting
- `UPLOAD_SPEED_ANALYSIS.md` - Speed optimization
- `COMPREHENSIVE_ENHANCEMENTS.md` - All features
- `FULL_SYSTEM_FEATURES.md` - System monitoring
- `UPDATE_FUNCTION_FIX.md` - Update guide
- `FINAL_SUMMARY.md` - Complete overview

---

## 🆘 Emergency Access

### Can't Access Web UI:

1. **Try hotspot:**
   - Look for "NomadPi" WiFi
   - Password: `nomadpassword`
   - URL: `http://10.42.0.1:8000`

2. **Try mDNS:**
   - `http://nomadpi.local:8000`

3. **Check router:**
   - Find Pi's IP in router admin
   - Access via IP: `http://192.168.1.X:8000`

4. **Physical access:**
   - Connect monitor and keyboard
   - Login and check network

---

## 📞 Quick Support

### Check Everything:
```bash
# System status
curl http://nomadpi.local:8000/api/system/stats

# WiFi status
curl http://nomadpi.local:8000/api/system/wifi/status

# DLNA status
curl http://nomadpi.local:8000/api/system/dlna/info

# Network interfaces
curl http://nomadpi.local:8000/api/system/network/interfaces
```

### Full Diagnostic:
```bash
./diagnose_upload_speed.sh
```

---

**Remember:** Hotspot password is `nomadpassword` - write it down!
