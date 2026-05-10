"""Real-Debrid API client for Nomad Pi.

Handles torrent search via Torrentio, magnet submission to Real-Debrid,
unrestricting download links, and downloading files to the Pi.
"""

import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime
from typing import Optional

import requests

from app import database

logger = logging.getLogger(__name__)

RD_BASE = "https://api.real-debrid.com/rest/1.0"
TORRENTIO_BASE = "https://torrentio.strem.fun"

# Active downloads tracked in memory
_downloads: dict[str, dict] = {}
_downloads_lock = threading.Lock()


def _rd_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


# ---------------------------------------------------------------------------
# Real-Debrid account helpers
# ---------------------------------------------------------------------------

def get_rd_user(api_key: str) -> dict:
    """Validate API key and return user info."""
    r = requests.get(f"{RD_BASE}/user", headers=_rd_headers(api_key), timeout=10)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Torrent search via Torrentio (Stremio addon)
# ---------------------------------------------------------------------------

def search_torrentio(query: str, media_type: str = "movie", imdb_id: Optional[str] = None,
                     season: Optional[int] = None, episode: Optional[int] = None) -> list[dict]:
    """Search for torrents using Torrentio.

    If an IMDB ID is provided, fetch streams directly. Otherwise, we need
    to search TMDB/OMDb first to get the IMDB ID.
    """
    results = []

    if not imdb_id:
        return results

    try:
        if media_type == "series" and season is not None and episode is not None:
            url = f"{TORRENTIO_BASE}/stream/series/{imdb_id}:{season}:{episode}.json"
        else:
            url = f"{TORRENTIO_BASE}/stream/movie/{imdb_id}.json"

        r = requests.get(url, timeout=15)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()

        for stream in data.get("streams", []):
            title = stream.get("title", "")
            info_hash = stream.get("infoHash")
            file_idx = stream.get("fileIdx")

            if not info_hash:
                # Try to extract from behaviorHints or magnet-style URLs
                bh = stream.get("behaviorHints", {})
                info_hash = bh.get("infoHash")

            if not info_hash:
                continue

            # Parse quality/size from title lines
            lines = title.split("\n")
            name = lines[0] if lines else title
            details = lines[1] if len(lines) > 1 else ""

            # Extract size from details (e.g. "💾 1.45 GB")
            size_str = ""
            size_match = re.search(r"(\d+\.?\d*)\s*(GB|MB|TB)", details, re.IGNORECASE)
            if size_match:
                size_str = f"{size_match.group(1)} {size_match.group(2)}"

            # Extract quality
            quality = "Unknown"
            for q in ["2160p", "4K", "1080p", "720p", "480p", "HDCAM", "CAM"]:
                if q.lower() in title.lower():
                    quality = q
                    break

            # Extract source info
            source = ""
            for s in ["BluRay", "WEB-DL", "WEBRip", "HDRip", "BRRip", "DVDRip", "HDTV"]:
                if s.lower() in title.lower():
                    source = s
                    break

            results.append({
                "name": name,
                "info_hash": info_hash,
                "file_idx": file_idx,
                "quality": quality,
                "size": size_str,
                "source": source,
                "details": details,
                "seeders": stream.get("seeders"),
            })
    except requests.RequestException as e:
        logger.error(f"Torrentio search failed: {e}")

    return results


# ---------------------------------------------------------------------------
# Real-Debrid torrent / magnet operations
# ---------------------------------------------------------------------------

def add_magnet(api_key: str, info_hash: str) -> dict:
    """Add a magnet link to Real-Debrid."""
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    r = requests.post(
        f"{RD_BASE}/torrents/addMagnet",
        headers=_rd_headers(api_key),
        data={"magnet": magnet},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def select_files(api_key: str, torrent_id: str, file_ids: str = "all") -> None:
    """Select files to download from a torrent."""
    r = requests.post(
        f"{RD_BASE}/torrents/selectFiles/{torrent_id}",
        headers=_rd_headers(api_key),
        data={"files": file_ids},
        timeout=15,
    )
    r.raise_for_status()


def get_torrent_info(api_key: str, torrent_id: str) -> dict:
    """Get torrent status and links."""
    r = requests.get(
        f"{RD_BASE}/torrents/info/{torrent_id}",
        headers=_rd_headers(api_key),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def unrestrict_link(api_key: str, link: str) -> dict:
    """Unrestrict a hoster link to get a direct download URL."""
    r = requests.post(
        f"{RD_BASE}/unrestrict/link",
        headers=_rd_headers(api_key),
        data={"link": link},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def get_rd_downloads(api_key: str, page: int = 1, limit: int = 50) -> list[dict]:
    """Get user's download history from Real-Debrid."""
    r = requests.get(
        f"{RD_BASE}/downloads",
        headers=_rd_headers(api_key),
        params={"page": page, "limit": limit},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def get_rd_torrents(api_key: str, page: int = 1, limit: int = 50) -> list[dict]:
    """Get user's torrent list from Real-Debrid."""
    r = requests.get(
        f"{RD_BASE}/torrents",
        headers=_rd_headers(api_key),
        params={"page": page, "limit": limit},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def delete_rd_torrent(api_key: str, torrent_id: str) -> None:
    """Delete a torrent from Real-Debrid."""
    r = requests.delete(
        f"{RD_BASE}/torrents/delete/{torrent_id}",
        headers=_rd_headers(api_key),
        timeout=15,
    )
    r.raise_for_status()


# ---------------------------------------------------------------------------
# Download management - download from RD to Pi
# ---------------------------------------------------------------------------

def _get_category_from_filename(filename: str) -> str:
    """Determine media category from file extension."""
    ext = os.path.splitext(filename)[1].lower()
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.wmv', '.flv'}
    music_exts = {'.mp3', '.flac', '.wav', '.m4a', '.ogg', '.aac'}
    book_exts = {'.pdf', '.epub', '.mobi', '.cbz', '.cbr'}

    if ext in video_exts:
        return "movies"
    elif ext in music_exts:
        return "music"
    elif ext in book_exts:
        return "books"
    return "files"


def _sanitize_filename(name: str) -> str:
    """Remove invalid filesystem characters."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')


def download_to_pi(api_key: str, download_url: str, filename: str,
                   category: str = "auto", is_show: bool = False) -> str:
    """Download a file from Real-Debrid to the Pi's media library.

    Returns the download_id for tracking progress.
    """
    from app.routers import media

    filename = _sanitize_filename(filename)

    if category == "auto":
        if is_show:
            category = "shows"
        else:
            category = _get_category_from_filename(filename)

    # Build destination path
    base_dir = media.BASE_DIR
    if category in ("movies", "shows"):
        # Create folder from filename (without extension)
        folder_name = os.path.splitext(filename)[0]
        dest_dir = os.path.join(base_dir, category, folder_name)
    else:
        dest_dir = os.path.join(base_dir, category)

    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)

    # Ensure unique destination
    dest_path = media.pick_unique_dest(dest_path)

    download_id = f"rd_{int(time.time())}_{hash(filename) & 0xFFFF:04x}"

    download_info = {
        "id": download_id,
        "filename": filename,
        "category": category,
        "dest_path": dest_path,
        "url": download_url,
        "status": "downloading",
        "progress": 0,
        "speed": 0,
        "size_total": 0,
        "size_downloaded": 0,
        "started_at": datetime.now().isoformat(),
        "error": None,
    }

    with _downloads_lock:
        _downloads[download_id] = download_info

    # Start download in background thread
    t = threading.Thread(target=_download_worker, args=(download_id, download_url, dest_path, category), daemon=True)
    t.start()

    return download_id


def _download_worker(download_id: str, url: str, dest_path: str, category: str):
    """Background worker that downloads a file and updates progress."""
    from app.routers import media

    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()

        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        last_update = time.time()
        last_bytes = 0

        with _downloads_lock:
            _downloads[download_id]["size_total"] = total

        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)

                now = time.time()
                elapsed = now - last_update
                if elapsed >= 1.0:
                    speed = (downloaded - last_bytes) / elapsed
                    progress = (downloaded / total * 100) if total > 0 else 0

                    with _downloads_lock:
                        if download_id in _downloads:
                            _downloads[download_id].update({
                                "progress": round(progress, 1),
                                "speed": round(speed),
                                "size_downloaded": downloaded,
                            })
                    last_update = now
                    last_bytes = downloaded

        with _downloads_lock:
            if download_id in _downloads:
                _downloads[download_id].update({
                    "status": "completed",
                    "progress": 100,
                    "size_downloaded": downloaded,
                    "speed": 0,
                })

        # Index the downloaded file
        try:
            web_path = f"/data/{os.path.relpath(dest_path, media.BASE_DIR).replace(os.sep, '/')}"
            st = os.stat(dest_path)
            folder = os.path.relpath(os.path.dirname(dest_path),
                                     os.path.join(media.BASE_DIR, category)).replace(os.sep, '/')
            item = {
                "path": web_path,
                "category": category,
                "name": os.path.basename(dest_path),
                "folder": folder,
                "source": "debrid",
                "poster": None,
                "mtime": float(st.st_mtime),
                "size": int(st.st_size),
            }
            media.database.upsert_library_index_item(item)
            logger.info(f"Debrid download indexed: {web_path}")
        except Exception as e:
            logger.error(f"Failed to index debrid download: {e}")

        logger.info(f"Download complete: {dest_path}")

    except Exception as e:
        logger.error(f"Download failed for {download_id}: {e}")
        with _downloads_lock:
            if download_id in _downloads:
                _downloads[download_id].update({
                    "status": "failed",
                    "error": str(e),
                })


def get_download_status(download_id: str) -> Optional[dict]:
    """Get status of a specific download."""
    with _downloads_lock:
        return _downloads.get(download_id, {}).copy() if download_id in _downloads else None


def get_all_downloads() -> list[dict]:
    """Get status of all downloads."""
    with _downloads_lock:
        return [d.copy() for d in _downloads.values()]


def cancel_download(download_id: str) -> bool:
    """Cancel/remove a download from tracking."""
    with _downloads_lock:
        if download_id in _downloads:
            _downloads[download_id]["status"] = "cancelled"
            return True
    return False


def clear_completed() -> int:
    """Remove completed/failed/cancelled downloads from tracking."""
    with _downloads_lock:
        to_remove = [k for k, v in _downloads.items()
                     if v["status"] in ("completed", "failed", "cancelled")]
        for k in to_remove:
            del _downloads[k]
        return len(to_remove)
