# Dashboard API Documentation

## Overview

The Dashboard API provides real-time monitoring of active playback sessions and system statistics. Designed for external displays (ESP32, tablets, smart mirrors, etc.) to show "Now Playing" information similar to Plex.

**Key Features:**
- ✅ Real-time WebSocket streaming (updates every 2 seconds)
- ✅ REST API fallback for HTTP-only clients
- ✅ Active session tracking (who's watching what, right now)
- ✅ System statistics (CPU, RAM, temperature, network speed)
- ✅ Playback control endpoints (stop sessions remotely)
- ✅ No polling required - push-based updates

---

## Quick Start

### Test the WebSocket

Open in your browser:
```
http://nomadpi.local:8000/dashboard_test.html
```

This test page will show:
- ✅ All active playback sessions in real-time
- ✅ System stats (CPU, RAM, temperature, network)
- ✅ WebSocket connection status
- ✅ Auto-reconnect on disconnect

Start playing media in the main app and watch it appear instantly on the dashboard!

---

## API Endpoints

### 1. WebSocket: Real-time Dashboard Stream

**Endpoint:** `ws://nomadpi.local:8000/api/dashboard/ws`

**Authentication:** None required (designed for local network displays)

**Update Frequency:** Every 2 seconds

**Message Format:**
```json
{
  "sessions": [
    {
      "session_id": "abc123-unique-id",
      "user_id": 1,
      "username": "John",
      "avatar_url": "/api/media/avatar/john",
      "media_type": "movie",
      "title": "The Matrix",
      "poster_url": "/api/media/poster/...",
      "poster_thumb": "/api/media/thumb/...",
      "progress_percent": 45.2,
      "current_time": 5025,
      "duration": 11062,
      "state": "playing",
      "bitrate": 2500000,
      "last_update": 1768670000
    }
  ],
  "system": {
    "cpu_percent": 23.4,
    "cpu_temp": 54.2,
    "ram_percent": 42.1,
    "ram_used_mb": 1536,
    "ram_total_mb": 3648,
    "disk_percent": 78.0,
    "disk_used_gb": 45.2,
    "disk_total_gb": 58.0,
    "network_down_bps": 2621440,
    "network_up_bps": 262144,
    "uptime_seconds": 442800,
    "load_avg": 0.45,
    "active_users": 2
  },
  "timestamp": 1768670000
}
```

**Session States:**
- `playing` - Currently playing
- `paused` - Paused
- `stopped` - Stopped (session will be removed soon)
- `buffering` - Buffering (future use)

**Example JavaScript Client:**
```javascript
const ws = new WebSocket('ws://nomadpi.local:8000/api/dashboard/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Active sessions:', data.sessions.length);
  console.log('CPU usage:', data.system.cpu_percent + '%');
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};
```

---

### 2. REST: Get Now Playing (HTTP Fallback)

**Endpoint:** `GET /api/dashboard/now-playing`

**Authentication:** Required (Bearer token or cookie)

**Response:** Same as WebSocket message (one-time snapshot)

**Use Case:** For clients that don't support WebSocket or need on-demand updates

**Example:**
```bash
curl -H "Authorization: Bearer <token>" \
  http://nomadpi.local:8000/api/dashboard/now-playing
```

---

### 3. REST: Get System Stats Only

**Endpoint:** `GET /api/dashboard/stats`

**Authentication:** None required

**Response:**
```json
{
  "cpu_percent": 23.4,
  "cpu_temp": 54.2,
  "ram_percent": 42.1,
  "ram_used_mb": 1536,
  "ram_total_mb": 3648,
  "disk_percent": 78.0,
  "network_down_bps": 2621440,
  "network_up_bps": 262144,
  "uptime_seconds": 442800,
  "load_avg": 0.45,
  "active_users": 2
}
```

**Use Case:** Public displays that only show system monitoring (no playback info)

---

### 4. Update Active Session

**Endpoint:** `POST /api/dashboard/session/update`

**Authentication:** Required

**Purpose:** Called automatically by the web player to track active sessions

**Body:**
```json
{
  "session_id": "unique-session-id",
  "path": "/data/movies/matrix.mp4",
  "title": "The Matrix",
  "media_type": "movie",
  "current_time": 1234.5,
  "duration": 5678.9,
  "state": "playing",
  "poster_url": "/api/media/poster/...",
  "username": "John"
}
```

**Note:** You don't need to call this manually - the web player does it automatically

---

### 5. Stop Session

**Endpoint:** `POST /api/dashboard/session/{session_id}/stop`

**Authentication:** Required (must be session owner)

**Purpose:** Stop/remove an active session

**Response:**
```json
{
  "status": "ok",
  "message": "Session stopped"
}
```

**Use Case:** Remote playback control from dashboard display

---

## Data Flow

### How Sessions Are Tracked:

1. **User starts playback** in web player
2. **Web player automatically calls** `/api/dashboard/session/update` every 5-10 seconds
3. **Backend stores** session in memory (`active_sessions` dict)
4. **WebSocket broadcasts** updates to all connected dashboard clients
5. **Sessions auto-expire** after 30 seconds of no updates (user paused/stopped)

### Session Lifecycle:

```
[User clicks play]
     ↓
[Web player calls /session/update with state="playing"]
     ↓
[Session added to active_sessions]
     ↓
[WebSocket broadcasts to all dashboard displays]
     ↓
[User pauses]
     ↓
[Web player calls /session/update with state="paused"]
     ↓
[WebSocket broadcasts new state]
     ↓
[User stops or closes browser]
     ↓
[No more updates received]
     ↓
[After 30 seconds, session auto-removed]
```

---

## ESP32 Implementation Guide

### Hardware Requirements:

- **ESP32 board** with WiFi (e.g., WT32-SC01 PLUS)
- **Display:** 480x320 TFT LCD
- **Libraries:**
  - `ArduinoWebsockets` or `ESPAsyncWebSocket`
  - `LVGL` (for UI)
  - `ArduinoJson` (for parsing)
  - `HTTPClient` (for REST fallback)

### Example ESP32 Code:

```cpp
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>

WebSocketsClient webSocket;

void setup() {
  Serial.begin(115200);

  // Connect to WiFi
  WiFi.begin("your-ssid", "your-password");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  // Connect to dashboard WebSocket
  webSocket.begin("nomadpi.local", 8000, "/api/dashboard/ws");
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
}

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_CONNECTED:
      Serial.println("WebSocket Connected");
      break;

    case WStype_TEXT: {
      // Parse JSON
      StaticJsonDocument<4096> doc;
      deserializeJson(doc, payload);

      // Extract data
      JsonArray sessions = doc["sessions"];
      JsonObject system = doc["system"];

      // Update display
      Serial.printf("Sessions: %d\n", sessions.size());
      Serial.printf("CPU: %.1f%%\n", system["cpu_percent"].as<float>());

      // Update LVGL widgets here
      updateDisplay(sessions, system);
      break;
    }

    case WStype_DISCONNECTED:
      Serial.println("WebSocket Disconnected");
      break;
  }
}

void loop() {
  webSocket.loop();
  // LVGL task handler
  lv_task_handler();
  delay(5);
}

void updateDisplay(JsonArray sessions, JsonObject system) {
  // Update your LVGL UI here
  // Example: lv_label_set_text(cpu_label, String(system["cpu_percent"]) + "%");
}
```

### Multi-Screen Swipe UI (LVGL):

```cpp
// Screen 1: Now Playing
lv_obj_t * screen_nowplaying = lv_obj_create(NULL);
lv_obj_t * poster_img = lv_img_create(screen_nowplaying);
lv_obj_t * progress_bar = lv_bar_create(screen_nowplaying);
lv_obj_t * title_label = lv_label_create(screen_nowplaying);

// Screen 2: System Stats
lv_obj_t * screen_stats = lv_obj_create(NULL);
lv_obj_t * cpu_label = lv_label_create(screen_stats);
lv_obj_t * temp_label = lv_label_create(screen_stats);

// Enable swipe gestures
lv_obj_set_gesture_parent(screen_nowplaying, true);
lv_obj_set_drag(screen_nowplaying, true);
lv_obj_set_drag_dir(screen_nowplaying, LV_DRAG_DIR_HOR);
```

---

## Network Speed Calculation

The dashboard calculates real-time network speed:

```python
# Taken from psutil network counters
bytes_sent_delta = current_bytes_sent - previous_bytes_sent
bytes_recv_delta = current_bytes_recv - previous_bytes_recv
time_delta = current_time - previous_time

download_speed_bps = bytes_recv_delta / time_delta
upload_speed_bps = bytes_sent_delta / time_delta
```

**Update interval:** Every WebSocket message (2 seconds)

**Smoothing:** No smoothing applied - shows instant speed

**Units:** Bits per second (bps)

---

## Thumbnail Support (Future)

Currently poster URLs are full-size. For ESP32 displays with limited memory:

**Option 1:** Use existing poster endpoint and resize on ESP32
```cpp
// Download poster, decode JPEG, resize to 150x225
```

**Option 2:** Request server-side thumbnail (to be implemented)
```
GET /api/media/thumb/{path}?width=150&height=225
```

---

## Performance Considerations

### Backend:

- **Memory:** ~1KB per active session
- **CPU overhead:** <1% for WebSocket broadcasting
- **Network:** ~2KB per WebSocket message every 2 seconds

### ESP32:

- **RAM usage:** ~50KB for LVGL + JSON parsing
- **WiFi bandwidth:** ~1KB/s average (minimal)
- **Update rate:** 2 seconds (can be adjusted)

---

## Troubleshooting

### WebSocket won't connect

1. **Check service is running:**
   ```bash
   sudo systemctl status nomad-pi
   ```

2. **Check port 8000 is accessible:**
   ```bash
   curl http://nomadpi.local:8000/api/dashboard/stats
   ```

3. **Check firewall:**
   ```bash
   sudo ufw allow 8000
   ```

### Sessions not appearing

1. **Start playing media** in the web player (not just browsing)
2. **Check browser console** for errors
3. **Verify updates are being sent:**
   - Open browser DevTools → Network → WS tab
   - Watch for `/api/dashboard/session/update` calls

### ESP32 WebSocket disconnects

1. **Increase reconnect interval** (default 5 seconds)
2. **Check WiFi signal strength**
3. **Add connection keep-alive:**
   ```cpp
   webSocket.enableHeartbeat(15000, 3000, 2);
   ```

---

## Integration with Existing Code

### ❌ **Won't Break:**
- Existing `/api/media/progress` endpoint (unchanged)
- Database schema (no modifications)
- User authentication (dashboard has own auth)
- Web player functionality (only adds new calls)

### ✅ **Adds:**
- New router: `app/routers/dashboard.py`
- New endpoints under `/api/dashboard/*`
- In-memory session tracking (separate from database)
- WebSocket support (new protocol, doesn't affect REST)

---

## Future Enhancements

### Planned:
- [ ] Playback control (pause/resume/stop from dashboard)
- [ ] Thumbnail generation endpoint for ESP32
- [ ] Historical playback stats (daily/weekly graphs)
- [ ] Multi-room audio sync status
- [ ] Bitrate/transcode status indicators

### Possible:
- [ ] Mobile app push notifications
- [ ] Discord/Telegram bot integration
- [ ] Smart home integration (HomeAssistant, etc.)

---

## Example Use Cases

### 1. **WT32-SC01 PLUS "Now Playing" Display**
- Mount near TV or in hallway
- Shows current playback with poster
- Swipe between screens (playback/system/network)
- Touch to pause/stop

### 2. **Raspberry Pi Zero 2W + 3.5" Screen**
- Standalone monitoring display
- WebSocket client in Python
- Pygame or Kivy UI
- USB-powered, wall-mounted

### 3. **Web Dashboard on Tablet**
- Old tablet repurposed as status monitor
- Browser kiosk mode with `dashboard_test.html`
- Auto-refresh on disconnect
- Full-screen PWA mode

### 4. **Home Assistant Integration**
- MQTT bridge from WebSocket
- Display in HA dashboard
- Automation triggers (notify when playback starts)

---

## API Summary Table

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/dashboard/ws` | WebSocket | No | Real-time streaming |
| `/api/dashboard/now-playing` | GET | Yes | HTTP fallback snapshot |
| `/api/dashboard/stats` | GET | No | System stats only |
| `/api/dashboard/session/update` | POST | Yes | Track active session |
| `/api/dashboard/session/{id}/stop` | POST | Yes | Stop session |

---

## Next Steps

1. ✅ **Test the WebSocket** - Open `dashboard_test.html` in browser
2. ✅ **Play some media** - Watch it appear on dashboard
3. ✅ **Check ESP32 compatibility** - Try example code above
4. 🚀 **Build your display!**

---

**Questions or issues?** Check the test page first, then review the troubleshooting section above.
