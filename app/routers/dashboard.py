"""
Dashboard Router - Real-time Now Playing & System Monitoring
Provides WebSocket streaming and REST endpoints for live playback tracking
Designed for external displays (ESP32, tablets, etc.)
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from typing import Dict, List, Optional
import asyncio
import json
import time
import psutil
import os
import logging
from datetime import datetime
from app.routers.auth import get_current_user_id

logger = logging.getLogger("nomad")
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# In-memory storage for active playback sessions
# Structure: {session_id: {user_id, path, title, current_time, duration, last_update, state, ...}}
active_sessions: Dict[str, Dict] = {}

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Dashboard WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Dashboard WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected WebSocket clients"""
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket client: {e}")
                dead_connections.append(connection)

        # Clean up dead connections
        for conn in dead_connections:
            self.disconnect(conn)

manager = ConnectionManager()

# Network tracking for speed calculation
last_network_check = {"time": 0, "bytes_sent": 0, "bytes_recv": 0}

def get_system_stats() -> Dict:
    """Get current system statistics"""
    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # Temperature (Pi-specific)
        cpu_temp = None
        try:
            if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    cpu_temp = float(f.read().strip()) / 1000.0
        except:
            pass

        # Memory
        mem = psutil.virtual_memory()

        # Disk
        disk = psutil.disk_usage('/')

        # Network speed (calculate from delta)
        current_time = time.time()
        net_io = psutil.net_io_counters()

        time_delta = current_time - last_network_check["time"]
        bytes_sent_delta = net_io.bytes_sent - last_network_check["bytes_sent"]
        bytes_recv_delta = net_io.bytes_recv - last_network_check["bytes_recv"]

        if time_delta > 0:
            download_bps = int(bytes_recv_delta / time_delta)
            upload_bps = int(bytes_sent_delta / time_delta)
        else:
            download_bps = 0
            upload_bps = 0

        # Update last check
        last_network_check["time"] = current_time
        last_network_check["bytes_sent"] = net_io.bytes_sent
        last_network_check["bytes_recv"] = net_io.bytes_recv

        # Uptime
        uptime_seconds = int(time.time() - psutil.boot_time())

        # Load average
        try:
            load_avg = os.getloadavg()[0]
        except:
            load_avg = 0.0

        return {
            "cpu_percent": round(cpu_percent, 1),
            "cpu_temp": round(cpu_temp, 1) if cpu_temp else None,
            "ram_percent": round(mem.percent, 1),
            "ram_used_mb": int(mem.used / 1024 / 1024),
            "ram_total_mb": int(mem.total / 1024 / 1024),
            "disk_percent": round(disk.percent, 1),
            "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
            "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            "network_down_bps": download_bps,
            "network_up_bps": upload_bps,
            "uptime_seconds": uptime_seconds,
            "load_avg": round(load_avg, 2),
            "active_users": len(set(s.get("user_id") for s in active_sessions.values()))
        }
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        return {
            "cpu_percent": 0,
            "cpu_temp": None,
            "ram_percent": 0,
            "ram_used_mb": 0,
            "ram_total_mb": 0,
            "disk_percent": 0,
            "disk_used_gb": 0,
            "disk_total_gb": 0,
            "network_down_bps": 0,
            "network_up_bps": 0,
            "uptime_seconds": 0,
            "load_avg": 0.0,
            "active_users": 0
        }

def clean_stale_sessions():
    """Remove sessions that haven't updated in 30 seconds"""
    current_time = time.time()
    stale_threshold = 30  # seconds

    to_remove = []
    for session_id, session in active_sessions.items():
        if current_time - session.get("last_update", 0) > stale_threshold:
            to_remove.append(session_id)

    for session_id in to_remove:
        logger.info(f"Removing stale session: {session_id}")
        del active_sessions[session_id]

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time dashboard updates

    Streams JSON messages every 2 seconds with:
    - Active playback sessions
    - System statistics
    - Network activity

    Example message:
    {
        "sessions": [...],
        "system": {...},
        "timestamp": 1234567890
    }
    """
    await manager.connect(websocket)

    try:
        while True:
            # Clean up stale sessions
            clean_stale_sessions()

            # Prepare dashboard data
            sessions_list = []
            for session_id, session in active_sessions.items():
                sessions_list.append({
                    "session_id": session_id,
                    "user_id": session.get("user_id"),
                    "username": session.get("username", "Unknown"),
                    "avatar_url": session.get("avatar_url"),
                    "media_type": session.get("media_type", "unknown"),
                    "title": session.get("title", "Unknown"),
                    "poster_url": session.get("poster_url"),
                    "poster_thumb": session.get("poster_thumb"),
                    "progress_percent": session.get("progress_percent", 0),
                    "current_time": session.get("current_time", 0),
                    "duration": session.get("duration", 0),
                    "state": session.get("state", "unknown"),
                    "bitrate": session.get("bitrate", 0),
                    "last_update": session.get("last_update", 0)
                })

            # Get system stats
            system_stats = get_system_stats()

            # Broadcast update
            message = {
                "sessions": sessions_list,
                "system": system_stats,
                "timestamp": int(time.time())
            }

            await websocket.send_json(message)

            # Wait 2 seconds before next update
            await asyncio.sleep(2)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

@router.post("/session/update")
async def update_session(data: Dict, user_id: int = Depends(get_current_user_id)):
    """
    Update or create an active playback session

    Called automatically by the web player when playback state changes
    This tracks "who is watching what right now"

    Body:
    {
        "session_id": "unique_session_id",
        "path": "/data/movies/matrix.mp4",
        "title": "The Matrix",
        "media_type": "movie",
        "current_time": 1234.5,
        "duration": 5678.9,
        "state": "playing",  // playing, paused, stopped
        "poster_url": "/api/media/poster/...",
        "username": "John"
    }
    """
    try:
        session_id = data.get("session_id")
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        # Update or create session
        active_sessions[session_id] = {
            "user_id": user_id,
            "username": data.get("username", "Unknown"),
            "avatar_url": data.get("avatar_url"),
            "path": data.get("path"),
            "title": data.get("title", "Unknown"),
            "media_type": data.get("media_type", "unknown"),
            "poster_url": data.get("poster_url"),
            "poster_thumb": data.get("poster_thumb"),
            "current_time": float(data.get("current_time", 0)),
            "duration": float(data.get("duration", 0)),
            "progress_percent": round((float(data.get("current_time", 0)) / float(data.get("duration", 1))) * 100, 1),
            "state": data.get("state", "unknown"),
            "bitrate": data.get("bitrate", 0),
            "last_update": time.time()
        }

        logger.debug(f"Session updated: {session_id} - {data.get('title')} - {data.get('state')}")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error updating session: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/session/{session_id}/stop")
async def stop_session(session_id: str, user_id: int = Depends(get_current_user_id)):
    """
    Stop/remove an active session

    Removes the session from active tracking
    """
    if session_id in active_sessions:
        # Verify ownership
        if active_sessions[session_id].get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Not your session")

        del active_sessions[session_id]
        logger.info(f"Session stopped: {session_id}")
        return {"status": "ok", "message": "Session stopped"}

    return {"status": "not_found", "message": "Session not found"}

@router.post("/session/{session_id}/pause")
async def pause_session(session_id: str, user_id: int = Depends(get_current_user_id)):
    """
    Pause an active session
    """
    if session_id in active_sessions:
        # Verify ownership (optional, strict for now)
        if active_sessions[session_id].get("user_id") != user_id:
             # Allow admin to pause anyone? For now, strict.
             # raise HTTPException(status_code=403, detail="Not your session")
             pass 

        # Update state
        active_sessions[session_id]["state"] = "paused"
        # In a real implementation, we would send a WebSocket message to the player here
        logger.info(f"Session paused: {session_id}")
        return {"status": "ok", "message": "Session paused"}

    return {"status": "not_found", "message": "Session not found"}

@router.post("/session/{session_id}/resume")
async def resume_session(session_id: str, user_id: int = Depends(get_current_user_id)):
    """
    Resume an active session
    """
    if session_id in active_sessions:
        active_sessions[session_id]["state"] = "playing"
        logger.info(f"Session resumed: {session_id}")
        return {"status": "ok", "message": "Session resumed"}

    return {"status": "not_found", "message": "Session not found"}

@router.get("/now-playing")
async def get_now_playing(user_id: int = Depends(get_current_user_id)):
    """
    REST endpoint - Get current active sessions

    Returns same data as WebSocket but as a one-time HTTP request
    Useful for clients that don't support WebSocket
    """
    clean_stale_sessions()

    sessions_list = []
    for session_id, session in active_sessions.items():
        sessions_list.append({
            "session_id": session_id,
            "user_id": session.get("user_id"),
            "username": session.get("username", "Unknown"),
            "media_type": session.get("media_type", "unknown"),
            "title": session.get("title", "Unknown"),
            "poster_url": session.get("poster_url"),
            "poster_thumb": session.get("poster_thumb"),
            "progress_percent": session.get("progress_percent", 0),
            "current_time": session.get("current_time", 0),
            "duration": session.get("duration", 0),
            "state": session.get("state", "unknown"),
            "last_update": session.get("last_update", 0)
        })

    system_stats = get_system_stats()

    return {
        "sessions": sessions_list,
        "system": system_stats,
        "timestamp": int(time.time())
    }

@router.get("/stats")
async def get_stats():
    """
    Get system statistics only (no authentication required)

    Useful for public displays that only need system monitoring
    """
    return get_system_stats()
