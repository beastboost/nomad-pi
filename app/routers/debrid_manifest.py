"""Selectable debrid manifests and correctly-structured series downloads.

Universal search should never blindly select an entire season pack before the
user has seen what is inside it. This router exposes a small provider-neutral
manifest/selection layer and a structured library download endpoint.
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers import debrid as debrid_router
from app.routers import media
from app.services import debrid


router = APIRouter(prefix="/universal", tags=["debrid-manifest"])

_VIDEO_EXT = {
    ".mp4", ".mkv", ".m4v", ".webm", ".avi", ".mov", ".ts", ".m2ts",
    ".mts", ".wmv", ".flv", ".mpg", ".mpeg", ".mpe", ".3gp", ".vob",
}
_SERIES_QUEUE: queue.Queue[tuple[str, str, str]] = queue.Queue()
_SERIES_WORKER_LOCK = threading.Lock()
_SERIES_WORKER: Optional[threading.Thread] = None


class ManifestRequest(BaseModel):
    info_hash: str = Field(min_length=8, max_length=128)
    title: str = Field(default="", max_length=300)
    year: str = Field(default="", max_length=20)
    media_type: str = Field(default="movie", pattern="^(movie|series|show)$")
    season: int = Field(default=1, ge=0, le=999)
    episode: int = Field(default=1, ge=0, le=9999)


class SelectionRequest(BaseModel):
    file_ids: list[int] = Field(min_length=1, max_length=200)


class LibraryDownloadRequest(BaseModel):
    url: str = Field(min_length=8, max_length=8000)
    filename: str = Field(default="media.mkv", max_length=600)
    title: str = Field(default="", max_length=300)
    year: str = Field(default="", max_length=20)
    media_type: str = Field(default="movie", pattern="^(movie|series|show)$")
    season: int = Field(default=0, ge=0, le=999)
    episode: int = Field(default=0, ge=0, le=9999)
    source_path: str = Field(default="", max_length=2000)


def _provider_key() -> tuple[str, str]:
    provider = debrid_router._provider(None)
    key = debrid_router._key_for(provider)
    if not key:
        raise HTTPException(400, f"No API key set for {provider}")
    return provider, key


def _episode_numbers(path: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    text = str(path or "")
    match = re.search(r"(?i)(?:^|[\s._/\\-])S(\d{1,3})E(\d{1,4})(?:E(\d{1,4}))?", text)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3)) if match.group(3) else None
    match = re.search(r"(?i)(?:^|[\s._/\\-])(\d{1,3})x(\d{1,4})(?:[-._ ]?(\d{1,4}))?", text)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3)) if match.group(3) else None
    return None, None, None


def _int(value, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _normal_file(item: dict, fallback_id: int) -> dict:
    path = str(item.get("path") or item.get("name") or item.get("filename") or "")
    file_id = _int(item.get("id"), fallback_id)
    size = _int(item.get("bytes") or item.get("size"), 0)
    season, episode, episode_end = _episode_numbers(path)
    ext = os.path.splitext(path.split("?", 1)[0])[1].lower()
    return {
        "id": file_id,
        "path": path,
        "bytes": size,
        "video": ext in _VIDEO_EXT,
        "season": season,
        "episode": episode,
        "episode_end": episode_end,
        "selected": bool(item.get("selected", False)),
    }


def _rd_manifest(key: str, info_hash: str) -> tuple[str, str, list[dict]]:
    result = debrid.add_magnet(key, info_hash)
    torrent_id = str(result.get("id") or "")
    if not torrent_id:
        raise RuntimeError("Real-Debrid did not return a torrent id")
    info = {}
    for _ in range(12):
        info = debrid.get_torrent_info(key, torrent_id)
        if str(info.get("status") or "") != "magnet_conversion":
            break
        time.sleep(0.5)
    files = [_normal_file(item, index) for index, item in enumerate(info.get("files") or [])]
    return torrent_id, str(info.get("status") or "ready"), files


def _ad_files(key: str, magnet_id: str) -> list[dict]:
    raw = debrid.ad_get_magnet_files(key, magnet_id)
    raw = sorted(raw, key=lambda item: str(item.get("filename") or "").lower())
    return [
        _normal_file({
            "id": index,
            "path": item.get("filename") or "",
            "bytes": item.get("size") or 0,
        }, index)
        for index, item in enumerate(raw)
    ]


def _ad_manifest(key: str, info_hash: str) -> tuple[str, str, list[dict]]:
    result = debrid.ad_add_magnet(key, info_hash)
    magnet_id = str(result.get("id") or "")
    if not magnet_id:
        raise RuntimeError("AllDebrid did not return a magnet id")
    status = {}
    for _ in range(12):
        status = debrid.ad_get_magnet_status(key, magnet_id)
        if _int(status.get("statusCode"), 0) >= 4:
            break
        time.sleep(0.5)
    files = _ad_files(key, magnet_id) if _int(status.get("statusCode"), 0) >= 4 else []
    state = "downloaded" if files else "processing"
    return magnet_id, state, files


def _tb_manifest(key: str, info_hash: str) -> tuple[str, str, list[dict]]:
    result = debrid.tb_add_magnet(key, info_hash)
    torrent_id = str(result.get("torrent_id") or result.get("torrentId") or result.get("id") or "")
    if not torrent_id:
        raise RuntimeError("TorBox did not return a torrent id")
    info = {}
    for _ in range(15):
        info = debrid.tb_get_torrent_info(key, torrent_id)
        state = str(info.get("download_state") or "").lower()
        if info.get("download_finished") or info.get("download_present") or state in {"completed", "cached", "uploading", "paused"}:
            break
        time.sleep(0.5)
    files = [_normal_file(item, index) for index, item in enumerate(info.get("files") or [])]
    return torrent_id, str(info.get("download_state") or "ready"), files


@router.post("/manifest")
def prepare_manifest(body: ManifestRequest, user_id: int = Depends(get_current_user_id)):
    """Open a release and return its files without selecting the whole pack."""
    provider, key = _provider_key()
    try:
        if provider == "rd":
            torrent_id, status, files = _rd_manifest(key, body.info_hash)
        elif provider == "ad":
            torrent_id, status, files = _ad_manifest(key, body.info_hash)
        elif provider == "tb":
            torrent_id, status, files = _tb_manifest(key, body.info_hash)
        else:
            raise RuntimeError(f"Unsupported provider: {provider}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Could not inspect release: {exc}") from exc

    video_files = [item for item in files if item["video"]]
    return {
        "provider": provider,
        "torrent_id": torrent_id,
        "status": status,
        "title": body.title,
        "year": body.year,
        "media_type": body.media_type,
        "requested_season": body.season,
        "requested_episode": body.episode,
        "files": files,
        "video_count": len(video_files),
        "video_bytes": sum(item["bytes"] for item in video_files),
    }


def _rd_resolve(key: str, torrent_id: str, ids: set[int]) -> list[dict]:
    debrid.select_files(key, torrent_id, ",".join(str(i) for i in sorted(ids)))
    info = {}
    for _ in range(20):
        info = debrid.get_torrent_info(key, torrent_id)
        if str(info.get("status") or "") == "downloaded" and info.get("links"):
            break
        time.sleep(0.5)
    selected = []
    for index, raw in enumerate(info.get("files") or []):
        item = _normal_file(raw, index)
        if item["id"] in ids or bool(raw.get("selected")):
            selected.append(item)
    links = list(info.get("links") or [])
    if not links:
        raise HTTPException(409, "The selected Real-Debrid files are not ready yet")
    return [{**item, "link": links[index]} for index, item in enumerate(selected[:len(links)])]


def _ad_resolve(key: str, torrent_id: str, ids: set[int]) -> list[dict]:
    raw = sorted(debrid.ad_get_magnet_files(key, torrent_id), key=lambda item: str(item.get("filename") or "").lower())
    resolved = []
    for index, source in enumerate(raw):
        if index not in ids:
            continue
        item = _normal_file({
            "id": index,
            "path": source.get("filename") or "",
            "bytes": source.get("size") or 0,
        }, index)
        link = source.get("link")
        if link:
            resolved.append({**item, "link": link})
    return resolved


def _tb_resolve(key: str, torrent_id: str, ids: set[int]) -> list[dict]:
    info = debrid.tb_get_torrent_info(key, torrent_id)
    resolved = []
    for index, raw in enumerate(info.get("files") or []):
        item = _normal_file(raw, index)
        if item["id"] not in ids:
            continue
        try:
            link = debrid.tb_request_download(key, torrent_id, item["id"])
        except Exception:
            link = None
        if link:
            resolved.append({**item, "link": link})
    return resolved


@router.post("/selection/{torrent_id}")
def resolve_selection(torrent_id: str, body: SelectionRequest,
                      user_id: int = Depends(get_current_user_id)):
    provider, key = _provider_key()
    ids = {int(value) for value in body.file_ids}
    try:
        if provider == "rd":
            resolved = _rd_resolve(key, torrent_id, ids)
        elif provider == "ad":
            resolved = _ad_resolve(key, torrent_id, ids)
        elif provider == "tb":
            resolved = _tb_resolve(key, torrent_id, ids)
        else:
            resolved = []
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Could not resolve selected files: {exc}") from exc
    if not resolved:
        raise HTTPException(409, "The provider returned no links for the selected files")
    return {"provider": provider, "torrent_id": torrent_id, "files": resolved}


def _show_destination(body: LibraryDownloadRequest) -> tuple[str, str, int, int]:
    source = body.source_path or body.filename
    parsed_season, parsed_episode, _ = _episode_numbers(source)
    season = int(body.season or parsed_season or 0)
    episode = int(body.episode or parsed_episode or 0)

    title = body.title.strip()
    if not title:
        base = os.path.splitext(os.path.basename(source))[0]
        title = re.split(r"(?i)[\s._-]+S\d{1,3}E\d{1,4}|[\s._-]+\d{1,3}x\d{1,4}", base, maxsplit=1)[0]
        title = re.sub(r"[._]+", " ", title).strip() or "Series"

    safe_title = debrid._sanitize_filename(title)
    year = re.sub(r"[^0-9]", "", str(body.year or ""))[:4]
    folder = f"{safe_title} ({year})" if year else safe_title
    ext = os.path.splitext(os.path.basename(body.filename or source))[1].lower()
    if ext not in _VIDEO_EXT:
        ext = os.path.splitext(os.path.basename(source))[1].lower()
    if ext not in _VIDEO_EXT:
        ext = ".mkv"

    if season and episode:
        filename = debrid._sanitize_filename(f"{safe_title} - S{season:02d}E{episode:02d}") + ext
    else:
        filename = debrid._sanitize_filename(os.path.basename(body.filename or source) or safe_title) or (safe_title + ext)
        if not os.path.splitext(filename)[1]:
            filename += ext

    root = media.pick_effective_storage_root_fs("shows")
    dest_dir = os.path.join(root, folder)
    if season:
        dest_dir = os.path.join(dest_dir, f"Season {season:02d}")
    os.makedirs(dest_dir, exist_ok=True)
    return media.pick_unique_dest(os.path.join(dest_dir, filename)), filename, season, episode


def _series_queue_loop() -> None:
    while True:
        download_id, url, dest_path = _SERIES_QUEUE.get()
        try:
            with debrid._downloads_lock:
                current = debrid._downloads.get(download_id)
                if not current or current.get("status") == "cancelled":
                    continue
                current["status"] = "downloading"
            debrid._download_worker(download_id, url, dest_path, "shows")
        finally:
            _SERIES_QUEUE.task_done()


def _ensure_series_worker() -> None:
    global _SERIES_WORKER
    if _SERIES_WORKER and _SERIES_WORKER.is_alive():
        return
    with _SERIES_WORKER_LOCK:
        if _SERIES_WORKER and _SERIES_WORKER.is_alive():
            return
        _SERIES_WORKER = threading.Thread(
            target=_series_queue_loop,
            name="nomad-series-downloads",
            daemon=True,
        )
        _SERIES_WORKER.start()


@router.post("/library-download")
def queue_library_download(body: LibraryDownloadRequest,
                           user_id: int = Depends(get_current_user_id)):
    if not debrid.is_safe_external_url(body.url):
        raise HTTPException(400, "Refusing to download from a non-public URL")

    is_show = body.media_type in {"series", "show"}
    if not is_show:
        try:
            download_id = debrid.download_to_pi("", body.url, body.filename, "movies", False)
            return {"ok": True, "download_id": download_id, "category": "movies"}
        except Exception as exc:
            raise HTTPException(500, f"Download failed: {exc}") from exc

    dest_path, filename, season, episode = _show_destination(body)
    download_id = f"series_{int(time.time())}_{abs(hash(dest_path)) & 0xFFFF:04x}"
    info = {
        "id": download_id,
        "filename": filename,
        "category": "shows",
        "dest_path": dest_path,
        "url": body.url,
        "status": "queued",
        "progress": 0,
        "speed": 0,
        "size_total": 0,
        "size_downloaded": 0,
        "started_at": datetime.now().isoformat(),
        "error": None,
        "series_title": body.title,
        "season": season,
        "episode": episode,
    }
    with debrid._downloads_lock:
        debrid._downloads[download_id] = info
    _ensure_series_worker()
    _SERIES_QUEUE.put((download_id, body.url, dest_path))
    return {
        "ok": True,
        "download_id": download_id,
        "category": "shows",
        "filename": filename,
        "season": season,
        "episode": episode,
        "destination": dest_path,
        "queue_depth": _SERIES_QUEUE.qsize(),
    }
