"""Chapter markers, intro/credits skip cues and trickplay scrub previews.

Two features that separate a media *server* from a file server live here, and
both are built to stay affordable on a 2 GiB single-board computer:

* **Cues** — embedded container chapters are read with a single ffprobe call
  and classified into an intro/credits pair using their titles. Where a rip has
  no chapters (most of them), a viewer can mark the intro once and apply it to
  the whole season, which is the cheap substitute for the audio fingerprinting
  Plex and Jellyfin run on a much larger machine.
* **Trickplay** — a scrub-preview sprite sheet. Frames are pulled with input
  seeking (``-ss`` before ``-i``) rather than by decoding the whole file, so a
  two-hour film costs a couple of hundred cheap seeks instead of a full decode.
  Generation is opt-in per title, runs one job at a time on a background
  worker, and is niced so it never competes with playback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from hashlib import md5
from queue import Queue
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import database
from app.routers.auth import get_current_user_id
from app.routers.media import BASE_DIR, safe_fs_path_from_web_path

logger = logging.getLogger(__name__)

router = APIRouter()

CUES_CACHE_DIR = os.path.join(BASE_DIR, ".nomad_cache", "cues")
TRICKPLAY_CACHE_DIR = os.path.join(BASE_DIR, ".nomad_cache", "trickplay")
os.makedirs(CUES_CACHE_DIR, exist_ok=True)
os.makedirs(TRICKPLAY_CACHE_DIR, exist_ok=True)

# Sprite geometry. 160px-wide tiles in a 10-column sheet keeps a full-length
# film under ~400 KB, which a phone can hold in memory without complaint.
TILE_WIDTH = 160
SPRITE_COLUMNS = 10
MAX_TILES = 200
MIN_INTERVAL_SECONDS = 5.0

INTRO_TITLE_RE = re.compile(r"\b(intro|opening|op|titles?|theme|recap|previously)\b", re.I)
CREDITS_TITLE_RE = re.compile(r"\b(credits?|ending|ed|outro|closing|next\s*episode)\b", re.I)


# ── marker storage ────────────────────────────────────────────────────────

_MARKER_DDL = """
CREATE TABLE IF NOT EXISTS media_markers (
    scope_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    start REAL NOT NULL,
    "end" REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scope_key, kind)
)
"""
_markers_ready = False
_markers_lock = threading.Lock()


def _ensure_markers_table() -> None:
    """Create the marker table on first use so no migration step is required."""
    global _markers_ready
    if _markers_ready:
        return
    with _markers_lock:
        if _markers_ready:
            return
        conn = database.get_db()
        try:
            conn.execute(_MARKER_DDL)
            conn.commit()
            _markers_ready = True
        finally:
            database.return_db(conn)


def season_scope_key(web_path: str) -> str:
    """Scope key for "apply to the rest of this season".

    Episodes normally sit in ``.../Show/Season 01/``, so the parent directory is
    the season. Where a show is flat the parent is the show, which is still the
    right blanket scope for a marker.
    """
    parent = os.path.dirname(web_path.rstrip("/"))
    return f"dir:{parent}" if parent else f"dir:{web_path}"


def _load_markers(web_path: str) -> Dict[str, Dict[str, Any]]:
    """Markers for one item: an episode-specific row wins over its season row."""
    _ensure_markers_table()
    conn = database.get_db()
    try:
        rows = conn.execute(
            'SELECT scope_key, kind, start, "end" FROM media_markers WHERE scope_key IN (?, ?)',
            (f"item:{web_path}", season_scope_key(web_path)),
        ).fetchall()
    finally:
        database.return_db(conn)

    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        scope = "episode" if row["scope_key"].startswith("item:") else "season"
        kind = row["kind"]
        # Season rows are read first only by accident of row order, so let an
        # episode row overwrite a season row but never the other way around.
        if kind in out and out[kind]["source"] == "episode":
            continue
        out[kind] = {"start": float(row["start"]), "end": (float(row["end"]) if row["end"] is not None else None), "source": scope}
    return out


def _save_marker(scope_key: str, kind: str, start: float, end: Optional[float]) -> None:
    _ensure_markers_table()
    conn = database.get_db()
    try:
        conn.execute(
            'INSERT INTO media_markers (scope_key, kind, start, "end", updated_at) '
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
            'ON CONFLICT(scope_key, kind) DO UPDATE SET start=excluded.start, "end"=excluded."end", updated_at=CURRENT_TIMESTAMP',
            (scope_key, kind, float(start), (float(end) if end is not None else None)),
        )
        conn.commit()
    finally:
        database.return_db(conn)


def _delete_marker(scope_key: str, kind: str) -> int:
    _ensure_markers_table()
    conn = database.get_db()
    try:
        cur = conn.execute("DELETE FROM media_markers WHERE scope_key = ? AND kind = ?", (scope_key, kind))
        conn.commit()
        return cur.rowcount or 0
    finally:
        database.return_db(conn)


# ── embedded chapters ─────────────────────────────────────────────────────

def _cache_key(fs_path: str) -> str:
    """Cache identity that changes when the file is replaced in place."""
    try:
        st = os.stat(fs_path)
        raw = f"{fs_path}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        raw = fs_path
    return md5(raw.encode()).hexdigest()[:16]


def _probe_chapters(fs_path: str) -> Dict[str, Any]:
    """Read container chapters and duration. Result is cached on disk."""
    key = _cache_key(fs_path)
    cache_file = os.path.join(CUES_CACHE_DIR, f"{key}.json")
    try:
        with open(cache_file, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        pass

    data: Dict[str, Any] = {"chapters": [], "duration": 0.0}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-of", "json", "-show_chapters",
             "-show_entries", "format=duration", fs_path],
            capture_output=True, text=True, timeout=30, check=False,
        )
        probed = json.loads(result.stdout or "{}")
        data["duration"] = float((probed.get("format") or {}).get("duration") or 0)
        for chapter in probed.get("chapters") or []:
            try:
                start = float(chapter.get("start_time") or 0)
                end = float(chapter.get("end_time") or 0)
            except (TypeError, ValueError):
                continue
            title = str((chapter.get("tags") or {}).get("title") or "").strip()
            data["chapters"].append({"start": start, "end": end, "title": title})
        data["chapters"].sort(key=lambda c: c["start"])
    except Exception as exc:  # ffprobe missing, unreadable file, malformed json
        logger.warning("chapter probe failed for %s: %s", fs_path, exc)

    try:
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass
    return data


def _cues_from_chapters(chapters: List[Dict[str, Any]], duration: float) -> Dict[str, Dict[str, Any]]:
    """Classify named chapters into an intro/credits pair.

    Deliberately conservative: an unnamed chapter list yields nothing, because a
    wrong "Skip Intro" button that jumps over the first scene is worse than no
    button at all.
    """
    found: Dict[str, Dict[str, Any]] = {}
    if not chapters or duration <= 0:
        return found

    for chapter in chapters:
        title = chapter.get("title") or ""
        if not title:
            continue
        start, end = float(chapter["start"]), float(chapter["end"])
        if "intro" not in found and INTRO_TITLE_RE.search(title) and start < duration * 0.35 and end > start:
            found["intro"] = {"start": start, "end": end, "source": "chapter", "title": title}
        elif "credits" not in found and CREDITS_TITLE_RE.search(title) and start > duration * 0.6:
            found["credits"] = {"start": start, "end": end or duration, "source": "chapter", "title": title}
    return found


# ── trickplay generation ──────────────────────────────────────────────────

class _TrickplayJob:
    def __init__(self, key: str, fs_path: str, duration: float):
        self.key = key
        self.fs_path = fs_path
        self.duration = duration
        self.state = "queued"
        self.progress = 0
        self.error: Optional[str] = None


_jobs: Dict[str, _TrickplayJob] = {}
_jobs_lock = threading.Lock()
_job_queue: "Queue[_TrickplayJob]" = Queue()
_worker: Optional[threading.Thread] = None


def _sprite_path(key: str) -> str:
    return os.path.join(TRICKPLAY_CACHE_DIR, f"{key}.jpg")


def _manifest_path(key: str) -> str:
    return os.path.join(TRICKPLAY_CACHE_DIR, f"{key}.json")


def _nice_prefix() -> List[str]:
    """Run generation at low priority so it never starves playback."""
    return ["nice", "-n", "15"] if shutil.which("nice") else []


def _generate_sprite(job: _TrickplayJob) -> None:
    duration = job.duration
    interval = max(MIN_INTERVAL_SECONDS, duration / MAX_TILES)
    count = max(1, min(MAX_TILES, int(duration // interval)))
    columns = min(SPRITE_COLUMNS, count)
    rows = max(1, (count + columns - 1) // columns)
    tile_height = 0

    work_dir = tempfile.mkdtemp(prefix="trickplay-", dir=TRICKPLAY_CACHE_DIR)
    try:
        for index in range(count):
            # Input seeking: ffmpeg jumps to the nearest keyframe and decodes a
            # single frame, instead of walking the file at 1/interval fps.
            timestamp = index * interval
            frame_out = os.path.join(work_dir, f"{index + 1:04d}.jpg")
            subprocess.run(
                _nice_prefix() + [
                    "ffmpeg", "-nostdin", "-v", "error", "-ss", f"{timestamp:.3f}", "-i", job.fs_path,
                    "-frames:v", "1", "-an", "-sn", "-vf", f"scale={TILE_WIDTH}:-2", "-q:v", "6",
                    "-y", frame_out,
                ],
                capture_output=True, timeout=60, check=False,
            )
            if not os.path.exists(frame_out):
                # A seek past the last keyframe yields nothing; reuse the
                # previous tile so the grid stays aligned with its timestamps.
                previous = os.path.join(work_dir, f"{index:04d}.jpg")
                if index and os.path.exists(previous):
                    shutil.copyfile(previous, frame_out)
                else:
                    raise RuntimeError("could not extract preview frames")
            job.progress = int((index + 1) * 100 / count)

        sprite = _sprite_path(job.key)
        subprocess.run(
            _nice_prefix() + [
                "ffmpeg", "-nostdin", "-v", "error", "-i", os.path.join(work_dir, "%04d.jpg"),
                "-vf", f"tile={columns}x{rows}", "-frames:v", "1", "-q:v", "6", "-y", sprite,
            ],
            capture_output=True, timeout=300, check=False,
        )
        if not os.path.exists(sprite):
            raise RuntimeError("could not assemble the preview sheet")

        # Read the real tile height back off the first frame rather than
        # assuming 16:9 — the scale filter preserved the source aspect.
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-of", "csv=p=0", "-select_streams", "v:0",
             "-show_entries", "stream=height", os.path.join(work_dir, "0001.jpg")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        try:
            tile_height = int((probe.stdout or "0").strip().splitlines()[0])
        except (ValueError, IndexError):
            tile_height = 0

        manifest = {
            "count": count, "interval": interval, "columns": columns, "rows": rows,
            "tile_width": TILE_WIDTH, "tile_height": tile_height or int(TILE_WIDTH * 9 / 16),
            "duration": duration,
        }
        with open(_manifest_path(job.key), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _worker_loop() -> None:
    while True:
        job = _job_queue.get()
        try:
            job.state = "running"
            _generate_sprite(job)
            job.state = "ready"
            job.progress = 100
        except Exception as exc:
            logger.warning("trickplay generation failed for %s: %s", job.fs_path, exc)
            job.state = "error"
            job.error = str(exc)
        finally:
            _job_queue.task_done()


def _ensure_worker() -> None:
    global _worker
    with _jobs_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="trickplay", daemon=True)
            _worker.start()


def _prune_trickplay(keep_key: str, max_entries: int = 30) -> None:
    """Keep the sprite cache bounded; oldest sheets go first."""
    try:
        sprites = [
            (os.path.getmtime(os.path.join(TRICKPLAY_CACHE_DIR, name)), name)
            for name in os.listdir(TRICKPLAY_CACHE_DIR)
            if name.endswith(".jpg")
        ]
    except OSError:
        return
    if len(sprites) <= max_entries:
        return
    for _, name in sorted(sprites)[: len(sprites) - max_entries]:
        if name == f"{keep_key}.jpg":
            continue
        for path in (os.path.join(TRICKPLAY_CACHE_DIR, name),
                     os.path.join(TRICKPLAY_CACHE_DIR, name[:-4] + ".json")):
            try:
                os.remove(path)
            except OSError:
                pass


# ── API ───────────────────────────────────────────────────────────────────

class MarkerRequest(BaseModel):
    path: str
    kind: str = Field(pattern="^(intro|credits)$")
    start: float = Field(ge=0)
    end: Optional[float] = Field(default=None, ge=0)
    scope: str = Field(default="episode", pattern="^(episode|season)$")


class MarkerClearRequest(BaseModel):
    path: str
    kind: str = Field(pattern="^(intro|credits)$")
    scope: str = Field(default="episode", pattern="^(episode|season)$")


@router.get("/cues")
def get_cues(path: str = Query(...), user_id: int = Depends(get_current_user_id)):
    """Chapters plus the intro/credits cues the player draws skip buttons from."""
    fs_path = safe_fs_path_from_web_path(path)
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Media not found")

    probed = _probe_chapters(fs_path)
    duration = float(probed.get("duration") or 0)
    cues = _cues_from_chapters(probed.get("chapters") or [], duration)
    # A hand-placed marker is the viewer's own correction, so it outranks
    # whatever the container claimed.
    cues.update(_load_markers(path))

    return {
        "path": path,
        "duration": duration,
        "chapters": probed.get("chapters") or [],
        "intro": cues.get("intro"),
        "credits": cues.get("credits"),
        "season_scope": season_scope_key(path),
    }


@router.post("/cues/mark")
def set_cue(req: MarkerRequest = Body(...), user_id: int = Depends(get_current_user_id)):
    """Place an intro/credits marker, optionally across the whole season."""
    safe_fs_path_from_web_path(req.path)
    if req.end is not None and req.end <= req.start:
        raise HTTPException(status_code=400, detail="Marker end must come after its start")
    scope_key = season_scope_key(req.path) if req.scope == "season" else f"item:{req.path}"
    _save_marker(scope_key, req.kind, req.start, req.end)
    return {"success": True, "scope": req.scope, "scope_key": scope_key}


@router.post("/cues/clear")
def clear_cue(req: MarkerClearRequest = Body(...), user_id: int = Depends(get_current_user_id)):
    safe_fs_path_from_web_path(req.path)
    scope_key = season_scope_key(req.path) if req.scope == "season" else f"item:{req.path}"
    removed = _delete_marker(scope_key, req.kind)
    return {"success": True, "removed": removed}


@router.get("/trickplay")
def trickplay_status(
    path: str = Query(...),
    generate: bool = Query(default=False),
    user_id: int = Depends(get_current_user_id),
):
    """Report — and on request start — the scrub-preview sheet for one title."""
    fs_path = safe_fs_path_from_web_path(path)
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Media not found")
    key = _cache_key(fs_path)

    manifest_file = _manifest_path(key)
    if os.path.exists(manifest_file) and os.path.exists(_sprite_path(key)):
        try:
            with open(manifest_file, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
            # Touch so the pruner treats a sheet in active use as recent.
            os.utime(_sprite_path(key), None)
            return {"state": "ready", "sheet": f"/api/playback/trickplay/sheet?key={key}", **manifest}
        except (OSError, ValueError):
            pass

    with _jobs_lock:
        job = _jobs.get(key)
    if job and job.state in {"queued", "running"}:
        return {"state": job.state, "progress": job.progress}
    if job and job.state == "error" and not generate:
        return {"state": "error", "error": job.error}

    if not generate:
        return {"state": "absent"}

    duration = float(_probe_chapters(fs_path).get("duration") or 0)
    if duration < 60:
        return {"state": "unsupported", "error": "Clip is too short for scrub previews"}

    job = _TrickplayJob(key, fs_path, duration)
    with _jobs_lock:
        _jobs[key] = job
    _prune_trickplay(key)
    _ensure_worker()
    _job_queue.put(job)
    return {"state": "queued", "progress": 0}


@router.get("/trickplay/sheet")
def trickplay_sheet(key: str = Query(...), user_id: int = Depends(get_current_user_id)):
    """Serve a generated sprite sheet by its cache key."""
    if not re.fullmatch(r"[0-9a-f]{16}", key or ""):
        raise HTTPException(status_code=400, detail="Invalid preview key")
    sprite = _sprite_path(key)
    if not os.path.exists(sprite):
        raise HTTPException(status_code=404, detail="Preview sheet not found")
    return FileResponse(sprite, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
