"""
Dashboard Router - Real-time Now Playing & System Monitoring
Provides WebSocket streaming and REST endpoints for live playback tracking
Designed for external displays (ESP32, tablets, etc.)
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from typing import Dict, List, Optional
import asyncio
import json
import time
import psutil
import os
import subprocess
import logging
import hashlib
from datetime import datetime
from app.routers.auth import get_current_user_id
from app.routers.media import cache_remote_poster, POSTER_CACHE_DIR, BASE_DIR

logger = logging.getLogger("nomad")
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# In-memory storage for active playback sessions
# Structure: {session_id: {user_id, path, title, current_time, duration, last_update, state, ...}}
active_sessions: Dict[str, Dict] = {}
control_connections: Dict[str, WebSocket] = {}
_poster_cache_attempts: Dict[str, float] = {}
_public_poster_paths: Dict[str, Dict] = {}
_PUBLIC_POSTER_TTL_S = 3600.0
_PUBLIC_POSTER_MAX = 4096
_POSTER_THUMB_W = 120
_POSTER_THUMB_H = 180
_POSTER_MAX_SERVE_BYTES = 650_000

def _sniff_image_kind(fs_path: str) -> Optional[str]:
    try:
        with open(fs_path, "rb") as f:
            b = f.read(16)
        if len(b) >= 8 and b[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        if len(b) >= 2 and b[0] == 0xFF and b[1] == 0xD8:
            return "jpg"
        if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            return "webp"
        return None
    except Exception:
        return None

def _sniff_image_dims(fs_path: str) -> Optional[tuple[int, int]]:
    kind = _sniff_image_kind(fs_path)
    if kind == "png":
        try:
            with open(fs_path, "rb") as f:
                sig = f.read(8)
                if sig != b"\x89PNG\r\n\x1a\n":
                    return None
                ln = f.read(4)
                if len(ln) != 4:
                    return None
                _ = f.read(4)
                ihdr = f.read(13)
                if len(ihdr) != 13:
                    return None
                w = int.from_bytes(ihdr[0:4], "big")
                h = int.from_bytes(ihdr[4:8], "big")
                if w > 0 and h > 0:
                    return (w, h)
        except Exception:
            return None
        return None

    if kind == "jpg":
        try:
            with open(fs_path, "rb") as f:
                if f.read(2) != b"\xFF\xD8":
                    return None
                while True:
                    b = f.read(1)
                    if not b:
                        return None
                    while b != b"\xFF":
                        b = f.read(1)
                        if not b:
                            return None
                    while True:
                        m = f.read(1)
                        if not m:
                            return None
                        if m != b"\xFF":
                            break
                    marker = m[0]
                    if marker in (0xD8, 0xD9):
                        continue
                    if marker == 0xDA:
                        return None
                    seglen_b = f.read(2)
                    if len(seglen_b) != 2:
                        return None
                    seglen = int.from_bytes(seglen_b, "big")
                    if seglen < 2:
                        return None
                    if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        data = f.read(seglen - 2)
                        if len(data) < 7:
                            return None
                        h = int.from_bytes(data[1:3], "big")
                        w = int.from_bytes(data[3:5], "big")
                        if w > 0 and h > 0:
                            return (w, h)
                        return None
                    f.seek(seglen - 2, 1)
        except Exception:
            return None

    return None

def _session_to_payload(session_id: str, session: Dict, now: float) -> Dict:
    state = session.get("state", "unknown")
    try:
        cur = float(session.get("current_time", 0) or 0)
    except Exception:
        cur = 0.0
    try:
        dur = float(session.get("duration", 0) or 0)
    except Exception:
        dur = 0.0
    try:
        last = float(session.get("last_update", 0) or 0)
    except Exception:
        last = 0.0

    if state == "playing" and last > 0 and now > last:
        cur += (now - last)

    if dur > 0:
        if cur < 0:
            cur = 0.0
        if cur > dur:
            cur = dur
        progress_percent = round((cur / dur) * 100.0, 1)
    else:
        progress_percent = session.get("progress_percent", 0) or 0

    return {
        "session_id": session_id,
        "user_id": session.get("user_id"),
        "username": session.get("username", "Unknown"),
        "avatar_url": session.get("avatar_url"),
        "media_type": session.get("media_type", "unknown"),
        "title": session.get("title", "Unknown"),
        "poster_url": session.get("poster_url"),
        "poster_thumb": session.get("poster_thumb"),
        "progress_percent": progress_percent,
        "current_time": cur,
        "duration": dur,
        "state": state,
        "bitrate": session.get("bitrate", 0),
        "last_update": session.get("last_update", 0),
    }

def _transcode_poster_thumb_jpg(input_fs: str, output_fs: str) -> bool:
    if not isinstance(input_fs, str) or not input_fs:
        return False
    if not isinstance(output_fs, str) or not output_fs:
        return False
    if not os.path.isfile(input_fs):
        return False

    tmp_fs = output_fs + ".tmp"
    try:
        if os.path.exists(tmp_fs):
            try:
                os.remove(tmp_fs)
            except Exception:
                pass

        vf = f"scale={_POSTER_THUMB_W}:{_POSTER_THUMB_H}:force_original_aspect_ratio=increase,crop={_POSTER_THUMB_W}:{_POSTER_THUMB_H}"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            input_fs,
            "-vf",
            vf,
            "-frames:v",
            "1",
            "-q:v",
            "4",
            tmp_fs,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if result.returncode != 0:
            try:
                if os.path.exists(tmp_fs):
                    os.remove(tmp_fs)
            except Exception:
                pass
            return False

        if not (os.path.isfile(tmp_fs) and os.path.getsize(tmp_fs) > 0):
            try:
                if os.path.exists(tmp_fs):
                    os.remove(tmp_fs)
            except Exception:
                pass
            return False

        os.replace(tmp_fs, output_fs)
        return True
    except Exception:
        try:
            if os.path.exists(tmp_fs):
                os.remove(tmp_fs)
        except Exception:
            pass
        return False

def _ensure_cached_poster_jpg(poster_id: str, fs_path: str) -> Optional[str]:
    if not _is_hex_sha256(poster_id):
        return None
    if not isinstance(fs_path, str) or not fs_path:
        return None
    if not os.path.isfile(fs_path):
        return None

    out_fs = os.path.join(POSTER_CACHE_DIR, f"{poster_id}.jpg")
    try:
        if os.path.isfile(out_fs) and os.path.getsize(out_fs) > 0:
            if _sniff_image_kind(out_fs) == "jpg" and os.path.getsize(out_fs) <= _POSTER_MAX_SERVE_BYTES:
                dims = _sniff_image_dims(out_fs)
                if dims == (_POSTER_THUMB_W, _POSTER_THUMB_H):
                    return out_fs
    except Exception:
        pass

    if _transcode_poster_thumb_jpg(fs_path, out_fs):
        return out_fs
    return None

def _is_hex_sha256(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 64:
        return False
    try:
        int(s, 16)
        return True
    except Exception:
        return False

def _prune_public_poster_paths(now: float):
    try:
        expired = [k for k, v in _public_poster_paths.items() if not isinstance(v, dict) or (now - float(v.get("ts", 0.0))) > _PUBLIC_POSTER_TTL_S]
        for k in expired:
            _public_poster_paths.pop(k, None)

        if len(_public_poster_paths) <= _PUBLIC_POSTER_MAX:
            return

        items = sorted(
            [(k, float(v.get("ts", 0.0))) for k, v in _public_poster_paths.items() if isinstance(v, dict)],
            key=lambda kv: kv[1],
        )
        for k, _ in items[: max(1, len(_public_poster_paths) - _PUBLIC_POSTER_MAX)]:
            _public_poster_paths.pop(k, None)
    except Exception:
        _public_poster_paths.clear()

def _register_public_poster_fs(fs_path: str) -> Optional[str]:
    try:
        if not isinstance(fs_path, str) or not fs_path:
            return None
        if not os.path.isfile(fs_path):
            return None
        ext = os.path.splitext(fs_path)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png"):
            return None
        try:
            if os.path.getsize(fs_path) <= 0 or os.path.getsize(fs_path) > 5_000_000:
                return None
        except Exception:
            return None
        key = hashlib.sha256(fs_path.encode("utf-8", errors="ignore")).hexdigest()
        now = time.time()
        _public_poster_paths[key] = {"fs": fs_path, "ts": now}
        _prune_public_poster_paths(now)
        return key
    except Exception:
        return None

def _public_poster_url_for_data_path(web_path: str) -> Optional[str]:
    if not isinstance(web_path, str) or not web_path.startswith("/data/"):
        return None
    try:
        rel_web = web_path[len("/data/"):]
        parts = [p for p in rel_web.split("/") if p]
        if len(parts) >= 3 and parts[0] == "cache" and parts[1] == "posters":
            fname = parts[-1]
            base, ext = os.path.splitext(fname)
            if ext.lower() == ".jpg" and _is_hex_sha256(base):
                return f"/api/dashboard/poster/{base}"
    except Exception:
        pass

    rel = web_path[len("/data/"):]
    rel = rel.lstrip("/").replace("/", os.sep)
    base_abs = os.path.abspath(BASE_DIR)
    fs_path = os.path.abspath(os.path.join(base_abs, rel))
    if not (fs_path == base_abs or fs_path.startswith(base_abs + os.sep)):
        return None
    poster_id = _register_public_poster_fs(fs_path)
    if not poster_id:
        return None
    return f"/api/dashboard/poster/{poster_id}"

@router.get("/poster/{poster_id}")
async def get_public_poster(poster_id: str):
    if not _is_hex_sha256(poster_id):
        raise HTTPException(status_code=404, detail="Not found")

    cached = os.path.join(POSTER_CACHE_DIR, f"{poster_id}.jpg")
    if os.path.isfile(cached) and os.path.getsize(cached) > 0:
        try:
            size = int(os.path.getsize(cached) or 0)
            kind = _sniff_image_kind(cached)
            dims = _sniff_image_dims(cached)

            should_transcode = (
                size <= 0
                or size > _POSTER_MAX_SERVE_BYTES
                or kind in ("png", "webp", None)
                or size > 200_000
                or dims != (_POSTER_THUMB_W, _POSTER_THUMB_H)
            )

            if should_transcode:
                if _transcode_poster_thumb_jpg(cached, cached):
                    return FileResponse(cached, media_type="image/jpeg")

            size = int(os.path.getsize(cached) or 0)
            kind = _sniff_image_kind(cached)
            if kind == "jpg" and size > 0 and size <= _POSTER_MAX_SERVE_BYTES:
                return FileResponse(cached, media_type="image/jpeg")
            if kind == "png" and size > 0 and size <= _POSTER_MAX_SERVE_BYTES:
                return FileResponse(cached, media_type="image/png")
        except Exception:
            pass

    now = time.time()
    entry = _public_poster_paths.get(poster_id)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="Not found")
    if (now - float(entry.get("ts", 0.0))) > _PUBLIC_POSTER_TTL_S:
        _public_poster_paths.pop(poster_id, None)
        raise HTTPException(status_code=404, detail="Not found")

    fs_path = entry.get("fs")
    if not isinstance(fs_path, str) or not os.path.isfile(fs_path):
        _public_poster_paths.pop(poster_id, None)
        raise HTTPException(status_code=404, detail="Not found")

    cached = _ensure_cached_poster_jpg(poster_id, fs_path)
    if cached:
        return FileResponse(cached, media_type="image/jpeg")

    ext = os.path.splitext(fs_path)[1].lower()
    media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    try:
        size = int(os.path.getsize(fs_path) or 0)
    except Exception:
        size = 0
    kind = _sniff_image_kind(fs_path)
    if size > 0 and size <= _POSTER_MAX_SERVE_BYTES and kind in ("jpg", "png"):
        return FileResponse(fs_path, media_type=media_type)
    raise HTTPException(status_code=404, detail="Not found")

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
        except (FileNotFoundError, PermissionError, OSError, ValueError):
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
        except (OSError, AttributeError):
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
            now = time.time()
            for session_id, session in active_sessions.items():
                if isinstance(session, dict):
                    sessions_list.append(_session_to_payload(session_id, session, now))

            # Get system stats
            system_stats = get_system_stats()

            # Broadcast update
            offset = datetime.now().astimezone().utcoffset()
            tz_offset_sec = int(offset.total_seconds()) if offset else 0
            message = {
                "sessions": sessions_list,
                "system": system_stats,
                "timestamp": int(time.time()),
                "tz_offset_sec": tz_offset_sec,
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
async def update_session(data: Dict, background_tasks: BackgroundTasks, user_id: int = Depends(get_current_user_id)):
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

        poster_url = data.get("poster_url")
        poster_thumb = data.get("poster_thumb")

        def _cached_poster_url(url: str) -> Optional[str]:
            if not isinstance(url, str):
                return None
            if not (url.startswith("http://") or url.startswith("https://")):
                return None
            key = hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()
            out_fs = os.path.join(POSTER_CACHE_DIR, f"{key}.jpg")
            if os.path.isfile(out_fs) and os.path.getsize(out_fs) > 0:
                return f"/api/dashboard/poster/{key}"
            return None

        def _queue_poster_cache(url: str):
            if not isinstance(url, str):
                return
            if not (url.startswith("http://") or url.startswith("https://")):
                return
            now = time.time()
            last = _poster_cache_attempts.get(url, 0.0)
            if (now - last) < 60.0:
                return
            _poster_cache_attempts[url] = now
            if len(_poster_cache_attempts) > 4096:
                try:
                    for k in sorted(_poster_cache_attempts.keys(), key=lambda kk: _poster_cache_attempts[kk])[:1024]:
                        _poster_cache_attempts.pop(k, None)
                except Exception:
                    _poster_cache_attempts.clear()
            background_tasks.add_task(cache_remote_poster, url)

        if isinstance(poster_url, str) and (poster_url.startswith("http://") or poster_url.startswith("https://")):
            key = hashlib.sha256(poster_url.encode("utf-8", errors="ignore")).hexdigest()
            out_fs = os.path.join(POSTER_CACHE_DIR, f"{key}.jpg")
            if not (os.path.isfile(out_fs) and os.path.getsize(out_fs) > 0):
                _queue_poster_cache(poster_url)
            poster_url = f"/api/dashboard/poster/{key}"
        elif isinstance(poster_url, str) and poster_url.startswith("/data/"):
            poster_url = _public_poster_url_for_data_path(poster_url) or poster_url

        if not poster_thumb:
            poster_thumb = poster_url

        if isinstance(poster_thumb, str) and (poster_thumb.startswith("http://") or poster_thumb.startswith("https://")):
            key = hashlib.sha256(poster_thumb.encode("utf-8", errors="ignore")).hexdigest()
            out_fs = os.path.join(POSTER_CACHE_DIR, f"{key}.jpg")
            if not (os.path.isfile(out_fs) and os.path.getsize(out_fs) > 0):
                _queue_poster_cache(poster_thumb)
            poster_thumb = f"/api/dashboard/poster/{key}"
        elif isinstance(poster_thumb, str) and poster_thumb.startswith("/data/"):
            poster_thumb = _public_poster_url_for_data_path(poster_thumb) or poster_thumb

        prev = active_sessions.get(session_id) if isinstance(active_sessions.get(session_id), dict) else {}
        prev_queue = prev.get("command_queue") if isinstance(prev.get("command_queue"), list) else []
        prev_seq = prev.get("command_seq") if isinstance(prev.get("command_seq"), int) else 0

        # Update or create session
        active_sessions[session_id] = {
            "user_id": user_id,
            "username": data.get("username", "Unknown"),
            "avatar_url": data.get("avatar_url"),
            "path": data.get("path"),
            "title": data.get("title", "Unknown"),
            "media_type": data.get("media_type", "unknown"),
            "poster_url": poster_url,
            "poster_thumb": poster_thumb,
            "current_time": float(data.get("current_time", 0)),
            "duration": float(data.get("duration", 0)),
            "progress_percent": round((float(data.get("current_time", 0)) / float(data.get("duration", 1))) * 100, 1),
            "state": data.get("state", "unknown"),
            "bitrate": data.get("bitrate", 0),
            "last_update": time.time(),
            "command_seq": prev_seq,
            "command_queue": prev_queue[-100:],
        }

        logger.debug(f"Session updated: {session_id} - {data.get('title')} - {data.get('state')}")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error updating session: {e}")
        return {"status": "error", "message": str(e)}

@router.websocket("/control/ws")
async def websocket_control_endpoint(websocket: WebSocket):
    session_id = websocket.query_params.get("session_id")
    if not session_id:
        try:
            await websocket.close(code=1008)
        finally:
            return
    await websocket.accept()
    control_connections[session_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if control_connections.get(session_id) is websocket:
            del control_connections[session_id]
    except Exception:
        if control_connections.get(session_id) is websocket:
            del control_connections[session_id]

@router.get("/session/{session_id}/commands")
async def get_session_commands(session_id: str, after_seq: int = 0, user_id: int = Depends(get_current_user_id)):
    session = active_sessions.get(session_id)
    if not isinstance(session, dict):
        return {"commands": [], "last_seq": after_seq}
    if session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not your session")
    queue = session.get("command_queue") if isinstance(session.get("command_queue"), list) else []
    cmds = [c for c in queue if isinstance(c, dict) and isinstance(c.get("seq"), int) and c["seq"] > after_seq]
    last_seq = max([after_seq] + [c.get("seq", after_seq) for c in cmds])
    session["command_queue"] = queue[-100:]
    session["command_seq"] = session.get("command_seq") if isinstance(session.get("command_seq"), int) else last_seq
    return {"commands": cmds, "last_seq": last_seq}

@router.post("/session/{session_id}/command")
async def command_session(session_id: str, data: Dict):
    action = (data or {}).get("action")
    if action not in ("pause", "resume", "stop"):
        raise HTTPException(status_code=400, detail="Invalid action")

    if session_id in active_sessions:
        if action == "pause":
            active_sessions[session_id]["state"] = "paused"
        elif action == "resume":
            active_sessions[session_id]["state"] = "playing"
        elif action == "stop":
            active_sessions[session_id]["state"] = "stopped"
            active_sessions[session_id]["last_update"] = time.time() - 9999

        session = active_sessions.get(session_id)
        if isinstance(session, dict):
            seq = session.get("command_seq") if isinstance(session.get("command_seq"), int) else 0
            seq += 1
            session["command_seq"] = seq
            queue = session.get("command_queue") if isinstance(session.get("command_queue"), list) else []
            queue.append({"seq": seq, "action": action, "session_id": session_id, "ts": time.time()})
            session["command_queue"] = queue[-100:]

    ws = control_connections.get(session_id)
    if ws:
        try:
            await ws.send_json({"action": action, "session_id": session_id})
        except Exception:
            if control_connections.get(session_id) is ws:
                del control_connections[session_id]

    return {"status": "ok"}

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
    now = time.time()
    for session_id, session in active_sessions.items():
        if isinstance(session, dict):
            sessions_list.append(_session_to_payload(session_id, session, now))

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

@router.get("/public")
async def get_public_dashboard_snapshot():
    clean_stale_sessions()

    sessions_list = []
    now = time.time()
    for session_id, session in active_sessions.items():
        if isinstance(session, dict):
            sessions_list.append(_session_to_payload(session_id, session, now))

    offset = datetime.now().astimezone().utcoffset()
    tz_offset_sec = int(offset.total_seconds()) if offset else 0

    return {
        "sessions": sessions_list,
        "system": get_system_stats(),
        "timestamp": int(time.time()),
        "tz_offset_sec": tz_offset_sec,
        "source": "http",
    }

# Watch History Endpoints
from app import database

@router.get("/watch-history")
def get_watch_history(user_id: int = Depends(get_current_user_id), limit: int = 20):
    """Get recently watched items for the current user."""
    if limit > 100:
        limit = 100  # Cap at 100 to prevent excessive queries
    return database.get_recently_watched(user_id, limit)

@router.get("/most-watched")
def get_most_watched_items(user_id: int = Depends(get_current_user_id), limit: int = 20):
    """Get most watched items for the current user."""
    if limit > 100:
        limit = 100  # Cap at 100 to prevent excessive queries
    return database.get_most_watched(user_id, limit)
