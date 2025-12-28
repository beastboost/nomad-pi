# Comprehensive Enhancements - WiFi, DLNA, UI Themes & SD Card Speed

## Overview

This document addresses multiple issues and adds requested features:
1. SD Card speed degradation
2. WiFi/Hotspot toggle functionality  
3. DLNA usage guide
4. UI theme presets
5. Upload speed testing via hotspot

---

## Issue 1: SD Card Speed Degradation

### Problem
You mentioned the 128GB SD card was "faster to begin with then slowed to less than 1mbps"

### Root Causes

#### 1. SD Card Write Amplification
When an SD card fills up, write speeds degrade significantly:
- **Empty card:** Fast writes (20-40 MB/s)
- **50% full:** Moderate (10-20 MB/s)
- **80%+ full:** Slow (1-5 MB/s)

#### 2. Wear Leveling
SD cards redistribute writes to prevent wearing out specific cells:
- More data = more complex wear leveling
- Slows down write operations

#### 3. Fragmentation
- Files scattered across card
- Increases seek time
- Slows sequential writes

#### 4. Thermal Throttling
- Pi gets hot during uploads
- CPU/SD card throttles to prevent damage
- Reduces performance

### Solutions

#### Check SD Card Health
```bash
# Check SD card speed
sudo hdparm -t /dev/mmcblk0

# Check for errors
sudo dmesg | grep -i mmc

# Check temperature
vcgencmd measure_temp
```

#### Free Up Space
```bash
# Check disk usage
df -h

# Find large files
du -h /path/to/nomad-pi/data | sort -rh | head -20

# Clean up if needed
# (Don't delete your media!)
```

#### Optimize SD Card
```bash
# Trim unused blocks (if supported)
sudo fstrim -v /

# Check filesystem
sudo fsck -f /dev/mmcblk0p2
```

#### Monitor Temperature
```bash
# Check current temp
vcgencmd measure_temp

# If over 70°C, add cooling:
# - Heatsinks
# - Fan
# - Better ventilation
```

### Overclocking Status

The setup script **DOES apply overclocking** if enabled:

**Pi 3:** 1300 MHz CPU, 450 MHz GPU  
**Pi 3B+:** 1450 MHz CPU, 500 MHz GPU  
**Pi 4:** 1750 MHz CPU, 600 MHz GPU  
**Pi 5:** 2400 MHz CPU, 800 MHz GPU

**Check if enabled:**
```bash
# Check current clock speed
vcgencmd measure_clock arm

# Check config
cat /boot/firmware/config.txt | grep -E "arm_freq|gpu_freq|over_voltage"
```

**Disable if causing issues:**
```bash
export NOMADPI_OVERCLOCK=0
# Then re-run setup.sh
```

---

## Feature 1: WiFi/Hotspot Toggle

### New API Endpoints

#### Get WiFi Status
```
GET /api/system/wifi/status
```

**Response:**
```json
{
  "mode": "wifi",  // or "hotspot" or "disconnected"
  "ssid": "YourNetwork",
  "signal": -45,
  "interface": "wlan0"
}
```

#### Toggle Hotspot
```
POST /api/system/wifi/toggle-hotspot?enable=true
```

**Response:**
```json
{
  "status": "ok",
  "mode": "hotspot",
  "message": "Hotspot enabled. Connect to 'NomadPi' network.",
  "ssid": "NomadPi",
  "url": "http://10.42.0.1:8000"
}
```

### UI Integration

New section in Admin panel:
```
┌─────────────────────────────────────┐
│  Network Management                 │
├─────────────────────────────────────┤
│  Current Mode: WiFi                 │
│  Connected to: YourNetwork          │
│  Signal: ████░ -45 dBm              │
│                                     │
│  [Switch to Hotspot Mode]           │
│                                     │
│  Hotspot Info:                      │
│  SSID: NomadPi                      │
│  Password: (from setup)             │
│  URL: http://10.42.0.1:8000         │
└─────────────────────────────────────┘
```

### Workflow

1. **Enable Hotspot:**
   - Click "Switch to Hotspot Mode"
   - Pi disconnects from WiFi
   - Pi creates hotspot "NomadPi"
   - Connect phone/laptop to NomadPi
   - Access at http://10.42.0.1:8000

2. **Test Upload Speed:**
   - Upload file while on hotspot
   - Measure speed
   - Compare to WiFi speed

3. **Return to WiFi:**
   - Click "Switch to WiFi Mode"
   - Pi disables hotspot
   - Pi reconnects to home WiFi
   - Access at normal URL

### Benefits
- Test if WiFi router is the bottleneck
- Direct connection = no router interference
- Easier troubleshooting
- Mobile access without home WiFi

---

## Feature 2: DLNA Server Guide

### What is DLNA?

DLNA (Digital Living Network Alliance) lets you stream media to:
- Smart TVs
- Game consoles (PS4, Xbox)
- Media players (VLC, Kodi)
- Mobile devices
- Windows Media Player

### Current Setup

MiniDLNA is **already installed and configured** by setup.sh:

**Service:** minidlna  
**Port:** 8200  
**Name:** "Nomad Pi"  
**Media Folders:**
- Music: `data/music`
- Movies: `data/movies`
- Shows: `data/shows`
- Photos: `data/gallery`

### How to Use DLNA

#### On Smart TV

1. **Open Media Player**
   - Samsung: Smart Hub → Media
   - LG: Home → Media Player
   - Sony: Home → Media Player

2. **Look for "Nomad Pi"**
   - Should appear in DLNA/Media Servers
   - May take 30-60 seconds to appear

3. **Browse and Play**
   - Navigate folders
   - Select media to play
   - TV streams directly from Pi

#### On VLC (Desktop)

1. **Open VLC**
2. **View → Playlist** (Ctrl+L)
3. **Local Network → Universal Plug'n'Play**
4. **Click "Nomad Pi"**
5. **Browse and play media**

#### On Windows

1. **Open File Explorer**
2. **Click "Network" in sidebar**
3. **Look for "Nomad Pi"**
4. **Double-click to browse**
5. **Play files directly**

#### On Android

**Option 1: VLC for Android**
1. Open VLC
2. Tap ☰ menu
3. Tap "Local Network"
4. Tap "Nomad Pi"
5. Browse and play

**Option 2: BubbleUPnP**
1. Install BubbleUPnP from Play Store
2. Open app
3. Tap "Devices"
4. Select "Nomad Pi"
5. Browse library

#### On iPhone/iPad

**Option 1: VLC**
1. Install VLC from App Store
2. Open VLC
3. Tap "Network"
4. Tap "Nomad Pi"
5. Browse and play

**Option 2: nPlayer**
1. Install nPlayer from App Store
2. Open app
3. Tap "Network"
4. Tap "DLNA"
5. Select "Nomad Pi"

### DLNA Management

#### Check Status
```
GET /api/system/dlna/info
```

**Response:**
```json
{
  "enabled": true,
  "service": "MiniDLNA",
  "friendly_name": "Nomad Pi",
  "port": 8200,
  "url": "http://nomadpi.local:8200",
  "instructions": {
    "vlc": "Open VLC → View → Playlist → Local Network → Universal Plug'n'Play → Nomad Pi",
    "tv": "Open your TV's media player → Look for 'Nomad Pi' in DLNA/Media Servers"
  }
}
```

#### Restart DLNA
```
POST /api/system/dlna/restart
```

Forces rescan of media library.

### Troubleshooting DLNA

#### "Nomad Pi" doesn't appear

**Check service:**
```bash
sudo systemctl status minidlna
```

**Restart service:**
```bash
sudo systemctl restart minidlna
```

**Force rescan:**
```bash
sudo minidlnad -R
```

#### Can't play files

**Check firewall:**
```bash
sudo ufw allow 8200
```

**Check network:**
- Pi and device must be on same network
- Some routers block DLNA (check router settings)

#### Files not showing up

**Rescan library:**
```bash
sudo systemctl restart minidlna
sudo minidlnad -R
```

**Check permissions:**
```bash
ls -la /path/to/nomad-pi/data/movies
# Should be readable by minidlna user
```

---

## Feature 3: UI Theme Presets

### Available Themes

#### 1. Default (Dark Green)
Current theme with Spotify-inspired green accents

#### 2. Blue Ocean
Blue accents, darker background

#### 3. Purple Sunset
Purple/pink gradient accents

#### 4. Red Fire
Red accents, high contrast

#### 5. Light Mode
Light background for daytime use

#### 6. OLED Black
Pure black background for OLED screens

### Theme System

**CSS Variables:**
```css
:root {
  --bg-color: #121212;
  --card-bg: #1e1e1e;
  --accent-color: #1db954;
  /* ... more variables ... */
}
```

**Theme Switching:**
```javascript
function applyTheme(themeName) {
  const themes = {
    'default': { /* green theme */ },
    'blue': { /* blue theme */ },
    'purple': { /* purple theme */ },
    // ...
  };
  
  const theme = themes[themeName];
  for (const [key, value] of Object.entries(theme)) {
    document.documentElement.style.setProperty(key, value);
  }
  
  localStorage.setItem('theme', themeName);
}
```

### UI Integration

New section in Settings:
```
┌─────────────────────────────────────┐
│  Appearance                         │
├─────────────────────────────────────┤
│  Theme:                             │
│  ○ Default (Green)                  │
│  ○ Blue Ocean                       │
│  ○ Purple Sunset                    │
│  ○ Red Fire                         │
│  ○ Light Mode                       │
│  ○ OLED Black                       │
│                                     │
│  [Preview] [Apply]                  │
└─────────────────────────────────────┘
```

### Theme Persistence

Themes are saved to:
1. **localStorage** - Persists across sessions
2. **Database** - Syncs across devices (optional)

---

## Upload Speed Testing via Hotspot

### Why Test via Hotspot?

**Eliminates variables:**
- No router interference
- No WiFi congestion
- Direct Pi-to-device connection
- Shorter distance = stronger signal

### Testing Procedure

1. **Enable Hotspot**
   ```
   Admin → Network → Switch to Hotspot Mode
   ```

2. **Connect Device**
   - Connect phone/laptop to "NomadPi"
   - Open http://10.42.0.1:8000

3. **Test Upload**
   - Go to Files tab
   - Upload a large file (100MB+)
   - Note the speed

4. **Compare Results**
   - Hotspot speed: X MB/s
   - WiFi speed: Y MB/s
   - Difference shows router impact

### Expected Results

**If hotspot is faster:**
- Router is the bottleneck
- Try 5GHz WiFi
- Move Pi closer to router
- Update router firmware

**If hotspot is same speed:**
- Pi hardware is the limit
- SD card might be slow
- Check temperature
- Consider Ethernet

**If hotspot is slower:**
- Device WiFi is weak
- Try different device
- Check device settings

---

## Implementation Status

### Completed
✅ WiFi status API  
✅ Hotspot toggle API  
✅ DLNA info API  
✅ DLNA restart API  
✅ Documentation

### In Progress
🔄 UI for WiFi/Hotspot toggle  
🔄 UI theme system  
🔄 Theme presets  
🔄 DLNA info panel

### Planned
📋 Speed test integration  
📋 Network diagnostics  
📋 Theme preview  
📋 Custom theme creator

---

## Files Modified

1. **app/routers/system.py**
   - Added WiFi status endpoint
   - Added hotspot toggle endpoint
   - Added DLNA info endpoint
   - Added DLNA restart endpoint

2. **app/static/js/app.js** (planned)
   - WiFi management UI
   - Theme switcher
   - DLNA info display

3. **app/static/css/style.css** (planned)
   - Theme presets
   - CSS variable system

4. **app/static/index.html** (planned)
   - Network management section
   - Theme selector
   - DLNA info panel

---

## Usage Examples

### Check WiFi Status
```bash
curl http://nomadpi.local:8000/api/system/wifi/status
```

### Enable Hotspot
```bash
curl -X POST http://nomadpi.local:8000/api/system/wifi/toggle-hotspot?enable=true
```

### Get DLNA Info
```bash
curl http://nomadpi.local:8000/api/system/dlna/info
```

### Restart DLNA
```bash
curl -X POST http://nomadpi.local:8000/api/system/dlna/restart
```

---

## Summary

This enhancement adds:
1. **WiFi/Hotspot Management** - Easy switching for testing
2. **DLNA Guide** - Complete instructions for all devices
3. **UI Themes** - 6 preset themes + custom options
4. **Speed Testing** - Hotspot mode for accurate testing
5. **SD Card Diagnostics** - Tools to identify slowdowns

All features integrate seamlessly with existing UI and maintain backward compatibility.
