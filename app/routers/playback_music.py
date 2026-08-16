"""Authenticated Music 2.0 routes mounted below /api/playback/music."""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.routers.auth import get_current_user_id
from app.routers import media, music2


router = APIRouter()

_AUDIO_EXT = {
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma",
}


def _music_fs_path(web_path: str) -> str:
    """Resolve a music path without treating legal filename characters as shell.

    Playback never interpolates this value into a shell command. Security comes
    from path normalisation and root confinement, not from rejecting characters
    such as '$' or '&' that legitimately occur in artist/track names.
    """
    if not isinstance(web_path, str) or not web_path or "\x00" in web_path:
        raise HTTPException(status_code=400, detail="Invalid music path")
    if len(web_path) > 4096:
        raise HTTPException(status_code=400, detail="Music path too long")

    if web_path.startswith("/data/"):
        rel = os.path.normpath(web_path[len("/data/"):]).lstrip("/")
        if rel in {"", ".", ".."} or rel.startswith("../"):
            raise HTTPException(status_code=400, detail="Invalid music path")
        base = Path(media.BASE_DIR).resolve()
        candidate = (base / rel).resolve()
        try:
            candidate.relative_to(base)
            return str(candidate)
        except ValueError:
            # data/external symlinks intentionally resolve outside data/. Only
            # standard removable-media roots are accepted after resolution.
            candidate_text = str(candidate)
            if candidate_text == "/media" or candidate_text.startswith("/media/"):
                return candidate_text
            if candidate_text == "/mnt" or candidate_text.startswith("/mnt/"):
                return candidate_text
            raise HTTPException(status_code=400, detail="Music path escaped the media roots")

    if web_path.startswith("/media/") or web_path.startswith("/mnt/"):
        candidate = Path(web_path).resolve()
        text = str(candidate)
        if text.startswith("/media/") or text.startswith("/mnt/"):
            return text

    raise HTTPException(status_code=400, detail="Invalid music path")


def _parse_range(value: Optional[str], size: int) -> Optional[Tuple[int, int]]:
    if not value:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match:
        raise ValueError("Invalid range")
    start_raw, end_raw = match.groups()
    if not start_raw and not end_raw:
        raise ValueError("Invalid range")
    if not start_raw:
        suffix = int(end_raw)
        if suffix <= 0:
            raise ValueError("Invalid range")
        return max(0, size - suffix), size - 1
    start = int(start_raw)
    end = int(end_raw) if end_raw else size - 1
    if start >= size or end < start:
        raise ValueError("Range not satisfiable")
    return start, min(end, size - 1)


def _chunks(path: str, start: int, length: int, chunk_size: int = 256 * 1024):
    remaining = length
    with open(path, "rb") as handle:
        handle.seek(start)
        while remaining > 0:
            block = handle.read(min(chunk_size, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


@router.get("/music/status")
def status(user_id: int = Depends(get_current_user_id)):
    return music2.music_status()


@router.post("/music/refresh")
def refresh(
    force: bool = Query(default=False),
    user_id: int = Depends(get_current_user_id),
):
    return music2.refresh_music_catalog(force=force)


@router.get("/music/catalog")
def catalog(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=250, ge=1, le=1000),
    q: str = Query(default="", max_length=200),
    artist: str = Query(default="", max_length=300),
    album: str = Query(default="", max_length=300),
    user_id: int = Depends(get_current_user_id),
):
    return music2.music_catalog(
        offset=offset,
        limit=limit,
        q=q,
        artist=artist,
        album=album,
    )


@router.get("/music/facets")
def facets(user_id: int = Depends(get_current_user_id)):
    return music2.music_facets()


@router.get("/music/artwork")
def artwork(
    path: str = Query(...),
    user_id: int = Depends(get_current_user_id),
):
    return music2.music_artwork(path=path)


@router.get("/music/stream")
def stream_music(
    request: Request,
    path: str = Query(...),
    user_id: int = Depends(get_current_user_id),
):
    """Zero-transcode music streaming with native byte-range seeking."""
    fs_path = _music_fs_path(path)
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Track not found")
    if Path(fs_path).suffix.lower() not in _AUDIO_EXT:
        raise HTTPException(status_code=400, detail="Not a supported music file")

    size = os.path.getsize(fs_path)
    try:
        byte_range = _parse_range(request.headers.get("range"), size)
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    media_type = mimetypes.guess_type(fs_path)[0] or {
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".opus": "audio/ogg",
    }.get(Path(fs_path).suffix.lower(), "application/octet-stream")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
    }
    if byte_range is None:
        return FileResponse(fs_path, media_type=media_type, headers=headers)

    start, end = byte_range
    length = end - start + 1
    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(length),
    })
    return StreamingResponse(
        _chunks(fs_path, start, length),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )
