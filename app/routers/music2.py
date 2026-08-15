"""Structured, cached Music 2.0 catalog for Nomad Pi.

The legacy library index is intentionally left untouched. Rich audio metadata
is populated in the background and cached by file size/mtime, so opening Music
does not synchronously ffprobe an entire collection on a Zero-class SBC.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from typing import Dict, Iterable, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app import database
from app.routers import media


router = APIRouter(prefix="/api/music", tags=["music"])
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".alac", ".aiff", ".aif"}
ART_CACHE = Path("data/cache/music-art")
ART_CACHE.mkdir(parents=True, exist_ok=True)
CATALOG_TTL_SECONDS = 12 * 60 * 60

_state_lock = threading.Lock()
_state = {
    "running": False,
    "discovered": 0,
    "processed": 0,
    "updated": 0,
    "errors": 0,
    "message": "idle",
    "started_at": None,
    "completed_at": None,
}
_schema_lock = threading.Lock()
_schema_ready = False


def _connect() -> sqlite3.Connection:
    path = database.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS music_catalog (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL DEFAULT '',
                    album_artist TEXT NOT NULL DEFAULT '',
                    album TEXT NOT NULL DEFAULT '',
                    disc_number INTEGER,
                    track_number INTEGER,
                    year INTEGER,
                    genre TEXT NOT NULL DEFAULT '',
                    duration REAL NOT NULL DEFAULT 0,
                    codec TEXT NOT NULL DEFAULT '',
                    bitrate INTEGER,
                    sample_rate INTEGER,
                    bit_depth INTEGER,
                    channels INTEGER,
                    replaygain_track_gain REAL,
                    replaygain_album_gain REAL,
                    has_artwork INTEGER NOT NULL DEFAULT 0,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    mtime_ns INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_music_catalog_artist
                    ON music_catalog(artist COLLATE NOCASE, album COLLATE NOCASE, disc_number, track_number);
                CREATE INDEX IF NOT EXISTS idx_music_catalog_album
                    ON music_catalog(album_artist COLLATE NOCASE, album COLLATE NOCASE, disc_number, track_number);
                CREATE INDEX IF NOT EXISTS idx_music_catalog_title
                    ON music_catalog(title COLLATE NOCASE);
                """
            )
            conn.commit()
            _schema_ready = True
        finally:
            conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_int(value) -> Optional[int]:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _gain(value) -> Optional[float]:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    try:
        return float(match.group(0)) if match else None
    except (TypeError, ValueError):
        return None


def _positive_int(value) -> Optional[int]:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _web_path(fs_path: str) -> str:
    absolute = os.path.abspath(fs_path)
    base = os.path.abspath(media.BASE_DIR)
    try:
        common = os.path.commonpath([absolute, base])
    except ValueError:
        common = ""
    if common == base:
        rel = os.path.relpath(absolute, base).replace(os.sep, "/")
        return f"/data/{rel}"
    if absolute.startswith("/media/") or absolute.startswith("/mnt/"):
        return absolute
    return absolute


def _discover_files() -> list[tuple[str, str]]:
    found: Dict[str, str] = {}
    for root in media.get_scan_paths("music"):
        if not root or not os.path.isdir(root):
            continue
        try:
            for dirpath, _dirnames, filenames in os.walk(root, followlinks=True):
                for name in filenames:
                    if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
                        continue
                    fs_path = os.path.join(dirpath, name)
                    try:
                        key = os.path.realpath(fs_path)
                    except OSError:
                        key = os.path.abspath(fs_path)
                    found.setdefault(key, _web_path(fs_path))
        except OSError:
            continue
    return [(real_path, web_path) for real_path, web_path in found.items()]


def _fallback_tags(fs_path: str) -> tuple[str, str, str]:
    p = Path(fs_path)
    title = p.stem
    album = p.parent.name if p.parent.name.lower() not in {"music", "audio", "songs"} else ""
    artist = ""
    if album and p.parent.parent.name.lower() not in {"music", "audio", "songs", "data"}:
        artist = p.parent.parent.name
    return title, artist, album


def _probe(fs_path: str) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is not installed")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_entries",
            "format=duration,bit_rate:format_tags=title,artist,album_artist,album,date,year,genre,track,disc,replaygain_track_gain,replaygain_album_gain",
            "-show_entries",
            "stream=codec_type,codec_name,sample_rate,bits_per_raw_sample,bits_per_sample,channels:stream_disposition=attached_pic",
            fs_path,
        ],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "ffprobe failed").strip()[:600])
    data = json.loads(result.stdout or "{}")
    fmt = data.get("format") or {}
    raw_tags = fmt.get("tags") or {}
    tags = {str(k).lower(): v for k, v in raw_tags.items()}
    audio = next((s for s in data.get("streams") or [] if s.get("codec_type") == "audio"), {})
    attached = any(
        s.get("codec_type") == "video" and bool((s.get("disposition") or {}).get("attached_pic"))
        for s in data.get("streams") or []
    )
    fallback_title, fallback_artist, fallback_album = _fallback_tags(fs_path)
    year = _first_int(tags.get("date") or tags.get("year"))
    bit_depth = _positive_int(audio.get("bits_per_raw_sample")) or _positive_int(audio.get("bits_per_sample"))
    return {
        "title": str(tags.get("title") or fallback_title).strip(),
        "artist": str(tags.get("artist") or fallback_artist).strip(),
        "album_artist": str(tags.get("album_artist") or tags.get("artist") or fallback_artist).strip(),
        "album": str(tags.get("album") or fallback_album).strip(),
        "disc_number": _first_int(tags.get("disc")),
        "track_number": _first_int(tags.get("track")),
        "year": year,
        "genre": str(tags.get("genre") or "").strip(),
        "duration": float(fmt.get("duration") or 0),
        "codec": str(audio.get("codec_name") or "").lower(),
        "bitrate": _positive_int(fmt.get("bit_rate")),
        "sample_rate": _positive_int(audio.get("sample_rate")),
        "bit_depth": bit_depth,
        "channels": _positive_int(audio.get("channels")),
        "replaygain_track_gain": _gain(tags.get("replaygain_track_gain")),
        "replaygain_album_gain": _gain(tags.get("replaygain_album_gain")),
        "has_artwork": bool(attached),
    }


def _cached_fresh(conn: sqlite3.Connection, web_path: str, size: int, mtime_ns: int) -> bool:
    row = conn.execute(
        "SELECT file_size, mtime_ns FROM music_catalog WHERE path=?",
        (web_path,),
    ).fetchone()
    return bool(row and int(row["file_size"] or 0) == size and int(row["mtime_ns"] or 0) == mtime_ns)


def _upsert(conn: sqlite3.Connection, web_path: str, fs_path: str, meta: dict, size: int, mtime_ns: int) -> None:
    conn.execute(
        """
        INSERT INTO music_catalog (
            path,name,title,artist,album_artist,album,disc_number,track_number,year,genre,
            duration,codec,bitrate,sample_rate,bit_depth,channels,
            replaygain_track_gain,replaygain_album_gain,has_artwork,file_size,mtime_ns,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET
            name=excluded.name,title=excluded.title,artist=excluded.artist,
            album_artist=excluded.album_artist,album=excluded.album,
            disc_number=excluded.disc_number,track_number=excluded.track_number,
            year=excluded.year,genre=excluded.genre,duration=excluded.duration,
            codec=excluded.codec,bitrate=excluded.bitrate,sample_rate=excluded.sample_rate,
            bit_depth=excluded.bit_depth,channels=excluded.channels,
            replaygain_track_gain=excluded.replaygain_track_gain,
            replaygain_album_gain=excluded.replaygain_album_gain,
            has_artwork=excluded.has_artwork,file_size=excluded.file_size,
            mtime_ns=excluded.mtime_ns,updated_at=excluded.updated_at
        """,
        (
            web_path, os.path.basename(fs_path), meta["title"], meta["artist"],
            meta["album_artist"], meta["album"], meta["disc_number"], meta["track_number"],
            meta["year"], meta["genre"], meta["duration"], meta["codec"], meta["bitrate"],
            meta["sample_rate"], meta["bit_depth"], meta["channels"],
            meta["replaygain_track_gain"], meta["replaygain_album_gain"],
            1 if meta["has_artwork"] else 0, size, mtime_ns, _now(),
        ),
    )


def _refresh_worker(force: bool = False) -> None:
    ensure_schema()
    with _state_lock:
        if _state["running"]:
            return
        _state.update({
            "running": True, "discovered": 0, "processed": 0, "updated": 0,
            "errors": 0, "message": "discovering music", "started_at": _now(),
        })
    try:
        files = _discover_files()
        with _state_lock:
            _state["discovered"] = len(files)
            _state["message"] = "reading audio metadata"
        live_paths = set()
        conn = _connect()
        try:
            for fs_path, web_path in files:
                live_paths.add(web_path)
                try:
                    st = os.stat(fs_path)
                    if not force and _cached_fresh(conn, web_path, st.st_size, st.st_mtime_ns):
                        pass
                    else:
                        meta = _probe(fs_path)
                        _upsert(conn, web_path, fs_path, meta, st.st_size, st.st_mtime_ns)
                        conn.commit()
                        with _state_lock:
                            _state["updated"] += 1
                except Exception:
                    with _state_lock:
                        _state["errors"] += 1
                finally:
                    with _state_lock:
                        _state["processed"] += 1
            # Remove metadata for files that disappeared from every current music root.
            if live_paths:
                existing = [r[0] for r in conn.execute("SELECT path FROM music_catalog").fetchall()]
                stale = [path for path in existing if path not in live_paths]
                conn.executemany("DELETE FROM music_catalog WHERE path=?", [(path,) for path in stale])
                conn.commit()
        finally:
            conn.close()
        with _state_lock:
            _state["message"] = "ready"
            _state["completed_at"] = _now()
    finally:
        with _state_lock:
            _state["running"] = False


def start_refresh(force: bool = False) -> bool:
    with _state_lock:
        if _state["running"]:
            return False
        completed = _state.get("completed_at")
        if not force and completed:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(completed)
                if age.total_seconds() < CATALOG_TTL_SECONDS:
                    return False
            except (TypeError, ValueError):
                pass
    threading.Thread(target=_refresh_worker, kwargs={"force": force}, daemon=True, name="nomad-music-index").start()
    return True


def _row_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["has_artwork"] = bool(item.get("has_artwork"))
    return item


@router.get("/status")
def music_status():
    ensure_schema()
    start_refresh(force=False)
    with _state_lock:
        state = dict(_state)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) tracks, COUNT(DISTINCT NULLIF(artist,'')) artists, COUNT(DISTINCT NULLIF(album,'')) albums FROM music_catalog"
        ).fetchone()
        counts = dict(row) if row else {"tracks": 0, "artists": 0, "albums": 0}
    finally:
        conn.close()
    return {"index": state, "counts": counts}


@router.post("/refresh")
def refresh_music_catalog(force: bool = Query(default=False)):
    started = start_refresh(force=force)
    return {"started": started, "index": dict(_state)}


@router.get("/catalog")
def music_catalog(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=250, ge=1, le=1000),
    q: str = Query(default="", max_length=200),
    artist: str = Query(default="", max_length=300),
    album: str = Query(default="", max_length=300),
):
    ensure_schema()
    start_refresh(force=False)
    clauses = []
    params = []
    if q.strip():
        pattern = f"%{q.strip().lower()}%"
        clauses.append("(lower(title) LIKE ? OR lower(artist) LIKE ? OR lower(album) LIKE ?)")
        params += [pattern, pattern, pattern]
    if artist.strip():
        clauses.append("lower(artist)=?")
        params.append(artist.strip().lower())
    if album.strip():
        clauses.append("lower(album)=?")
        params.append(album.strip().lower())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""

    conn = _connect()
    try:
        total = int(conn.execute(f"SELECT COUNT(*) FROM music_catalog{where}", params).fetchone()[0])
        rows = conn.execute(
            f"""
            SELECT * FROM music_catalog{where}
            ORDER BY
                CASE WHEN lower(album_artist)='' THEN lower(artist) ELSE lower(album_artist) END,
                lower(album), COALESCE(disc_number,1), COALESCE(track_number,9999), lower(title)
            LIMIT ? OFFSET ?
            """,
            (*params, int(limit), int(offset)),
        ).fetchall()
        items = [_row_dict(row) for row in rows]
    finally:
        conn.close()
    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "total": total,
        "next_offset": offset + len(items),
        "has_more": offset + len(items) < total,
        "index": dict(_state),
    }


@router.get("/facets")
def music_facets():
    ensure_schema()
    conn = _connect()
    try:
        artists = [
            {"name": row["artist"], "tracks": row["tracks"], "albums": row["albums"]}
            for row in conn.execute(
                """
                SELECT artist, COUNT(*) tracks, COUNT(DISTINCT NULLIF(album,'')) albums
                FROM music_catalog WHERE artist<>'' GROUP BY artist COLLATE NOCASE ORDER BY artist COLLATE NOCASE
                """
            ).fetchall()
        ]
        albums = [
            {"artist": row["artist"], "album": row["album"], "year": row["year"], "tracks": row["tracks"], "art_path": row["art_path"]}
            for row in conn.execute(
                """
                SELECT
                    CASE WHEN album_artist<>'' THEN album_artist ELSE artist END artist,
                    album, MIN(year) year, COUNT(*) tracks,
                    MIN(CASE WHEN has_artwork=1 THEN path ELSE NULL END) art_path
                FROM music_catalog WHERE album<>''
                GROUP BY CASE WHEN album_artist<>'' THEN album_artist ELSE artist END COLLATE NOCASE, album COLLATE NOCASE
                ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE
                """
            ).fetchall()
        ]
        genres = [
            {"name": row["genre"], "tracks": row["tracks"]}
            for row in conn.execute(
                "SELECT genre, COUNT(*) tracks FROM music_catalog WHERE genre<>'' GROUP BY genre COLLATE NOCASE ORDER BY genre COLLATE NOCASE"
            ).fetchall()
        ]
    finally:
        conn.close()
    return {"artists": artists, "albums": albums, "genres": genres}


def _art_identity(fs_path: str) -> Path:
    st = os.stat(fs_path)
    identity = f"{os.path.realpath(fs_path)}|{st.st_size}|{st.st_mtime_ns}"
    return ART_CACHE / f"{hashlib.sha256(identity.encode()).hexdigest()[:28]}.jpg"


@router.get("/artwork")
def music_artwork(path: str = Query(...)):
    ensure_schema()
    try:
        fs_path = media.safe_fs_path_from_web_path(path)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid music path")
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Track not found")

    conn = _connect()
    try:
        row = conn.execute("SELECT has_artwork FROM music_catalog WHERE path=?", (path,)).fetchone()
    finally:
        conn.close()
    if row and not bool(row["has_artwork"]):
        raise HTTPException(status_code=404, detail="Track has no embedded artwork")

    target = _art_identity(fs_path)
    if not target.is_file() or target.stat().st_size <= 0:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise HTTPException(status_code=503, detail="ffmpeg is not installed")
        temp = target.with_suffix(".tmp.jpg")
        result = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", fs_path,
                "-map", "0:v:0", "-frames:v", "1", "-c:v", "mjpeg", "-q:v", "3", str(temp),
            ],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        if result.returncode != 0 or not temp.is_file() or temp.stat().st_size <= 0:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(status_code=404, detail="Embedded artwork could not be extracted")
        os.replace(temp, target)
    return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
