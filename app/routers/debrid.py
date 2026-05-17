
Provides endpoints for:
- Saving / validating API keys for each provider
- Torrent search via Torrentio + Cinemeta title lookup
- Instant availability checking (cached torrents)
- Adding magnets, polling torrent status, unrestricting links
- Streaming and downloading to the Pi
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app import database
from app.routers.auth import get_current_user_id
from app.services import debrid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/debrid", tags=["debrid"])

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class KeyBody(BaseModel):
    key: str

class MagnetBody(BaseModel):
    info_hash: str
    title: str = ""
    year: str = ""
    media_type: str = "movie"
    season: int = 0
    episode: int = 0

class DownloadBody(BaseModel):
    url: str
    filename: str
    category: str = "auto"
    is_show: bool = False

class SelectFilesBody(BaseModel):
    file_ids: str = "all"


# ---------------------------------------------------------------------------
# Provider / key management
# ---------------------------------------------------------------------------

def _provider(request: Request) -> str:
    """Read the active debrid provider from the DB (rd / ad / tb)."""
    return database.get_setting("debrid_provider") or "rd"


def _key_for(provider: str) -> Optional[str]:
    mapping = {"rd": "rd_api_key", "ad": "ad_api_key", "tb": "tb_api_key"}
    setting = mapping.get(provider)
    return database.get_setting(setting) if setting else None


@router.get("/provider")
def get_provider(user_id: int = Depends(get_current_user_id)):
    return {"provider": database.get_setting("debrid_provider") or "rd"}


@router.post("/provider")
def set_provider(body: dict, user_id: int = Depends(get_current_user_id)):
    p = body.get("provider", "rd")
    if p not in ("rd", "ad", "tb"):
        raise HTTPException(400, "Invalid provider")
    database.set_setting("debrid_provider", p)
    return {"ok": True, "provider": p}


# --- Real-Debrid key ---
@router.post("/rd/key")
def set_rd_key(body: KeyBody, user_id: int = Depends(get_current_user_id)):
    try:
        user = debrid.get_rd_user(body.key)
        database.set_setting("rd_api_key", body.key)
        return {"ok": True, "user": user}
    except Exception as e:
        raise HTTPException(400, f"Invalid Real-Debrid key: {e}")


def _mask_key(key: str) -> str:
    """Mask an API key, avoiding overlap-exposure for short keys."""
    if len(key) >= 12:
        return key[:4] + "****" + key[-4:]
    return "****"


@router.get("/rd/key")
def get_rd_key(user_id: int = Depends(get_current_user_id)):
    key = database.get_setting("rd_api_key")
    if key:
        return {"has_key": True, "masked": _mask_key(key)}
    return {"has_key": False}


@router.delete("/rd/key")
def delete_rd_key(user_id: int = Depends(get_current_user_id)):
    database.set_setting("rd_api_key", "")
    return {"ok": True}


# --- AllDebrid key ---
@router.post("/ad/key")
def set_ad_key(body: KeyBody, user_id: int = Depends(get_current_user_id)):
    try:
        user = debrid.ad_get_user(body.key)
        database.set_setting("ad_api_key", body.key)
        return {"ok": True, "user": user}
    except Exception as e:
        raise HTTPException(400, f"Invalid AllDebrid key: {e}")


@router.get("/ad/key")
def get_ad_key(user_id: int = Depends(get_current_user_id)):
    key = database.get_setting("ad_api_key")
    if key:
        return {"has_key": True, "masked": _mask_key(key)}
    return {"has_key": False}


@router.delete("/ad/key")
def delete_ad_key(user_id: int = Depends(get_current_user_id)):
    database.set_setting("ad_api_key", "")
    return {"ok": True}


# --- TorBox key ---
@router.post("/tb/key")
def set_tb_key(body: KeyBody, user_id: int = Depends(get_current_user_id)):
    try:
        user = debrid.tb_get_user(body.key)
        database.set_setting("tb_api_key", body.key)
        return {"ok": True, "user": user}
    except Exception as e:
        raise HTTPException(400, f"Invalid TorBox key: {e}")


@router.get("/tb/key")
def get_tb_key(user_id: int = Depends(get_current_user_id)):
    key = database.get_setting("tb_api_key")
    if key:
        return {"has_key": True, "masked": _mask_key(key)}
    return {"has_key": False}


@router.delete("/tb/key")
def delete_tb_key(user_id: int = Depends(get_current_user_id)):
    database.set_setting("tb_api_key", "")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Title search (Cinemeta — no API key needed)
# ---------------------------------------------------------------------------

@router.get("/search/title")
def search_title(q: str = Query(..., min_length=1),
                 user_id: int = Depends(get_current_user_id)):
    """Search for movies/shows by title using Cinemeta."""
    import requests as req

    results = []
    for mtype in ("movie", "series"):
        try:
            url = f"https://v3-cinemeta.strem.io/catalog/{mtype}/top/search={q}.json"
            r = req.get(url, headers={"User-Agent": "NomadPi/1.0"}, timeout=10)
            if r.status_code == 200:
                for m in r.json().get("metas", []):
                    results.append({
                        "imdb_id": m.get("imdb_id") or m.get("id"),
                        "title": m.get("name", ""),
                        "year": m.get("releaseInfo", m.get("year", "")),
                        "type": mtype,
                        "poster": m.get("poster"),
                    })
        except Exception:
            pass
    return {"results": results}


# ---------------------------------------------------------------------------
# Torrent search
# ---------------------------------------------------------------------------

@router.get("/search/torrents")
def search_torrents(imdb_id: str = Query(...),
                    media_type: str = Query("movie"),
                    season: Optional[int] = Query(None),
                    episode: Optional[int] = Query(None),
                    user_id: int = Depends(get_current_user_id)):
    results = debrid.search_torrentio("", media_type=media_type, imdb_id=imdb_id,
                                      season=season, episode=episode)
    return {"results": results}


# ---------------------------------------------------------------------------
# Instant availability (cached check)
# ---------------------------------------------------------------------------

@router.post("/instant")
def check_instant(body: dict, user_id: int = Depends(get_current_user_id)):
    """Check instant availability for a list of hashes on the active provider."""
    hashes = body.get("hashes", [])
    provider = body.get("provider") or (database.get_setting("debrid_provider") or "rd")
    key = _key_for(provider)
    if not key:
        return {"cached": {}}
    try:
        if provider == "rd":
            cached = debrid.check_instant_availability(key, hashes)
        elif provider == "ad":
            cached = debrid.ad_check_instant(key, hashes)
        elif provider == "tb":
            cached = debrid.tb_check_instant(key, hashes)
        else:
            cached = {}
    except Exception as e:
        logger.warning(f"Instant check failed ({provider}): {e}")
        cached = {}
    return {"cached": cached}


# ---------------------------------------------------------------------------
# Add magnet / torrent operations (provider-agnostic)
# ---------------------------------------------------------------------------

@router.post("/magnet")
def add_magnet(body: MagnetBody, user_id: int = Depends(get_current_user_id)):
    provider = database.get_setting("debrid_provider") or "rd"
    key = _key_for(provider)
    if not key:
        raise HTTPException(400, f"No API key set for {provider}")
    try:
        if provider == "rd":
            result = debrid.add_magnet(key, body.info_hash)
            torrent_id = result.get("id")
            # Wait for magnet conversion
            for _ in range(10):
                info = debrid.get_torrent_info(key, torrent_id)
                st = info.get("status", "")
                if st != "magnet_conversion":
                    break
                time.sleep(1)
            # Select all files
            debrid.select_files(key, torrent_id, "all")
            # Wait for cached torrents to finish
            for _ in range(5):
                info = debrid.get_torrent_info(key, torrent_id)
                if info.get("status") == "downloaded":
                    break
                time.sleep(1)
            return {
                "ok": True,
                "provider": "rd",
                "torrent_id": torrent_id,
                "status": info.get("status"),
                "links": info.get("links", []),
                "filename": info.get("filename", ""),
                "files": info.get("files", []),
            }
        elif provider == "ad":
            result = debrid.ad_add_magnet(key, body.info_hash)
            magnet_id = str(result.get("id", ""))
            ready = result.get("ready", False)
            status_info = {}
            if ready:
                status_info = debrid.ad_get_magnet_status(key, magnet_id)
            else:
                for _ in range(10):
                    status_info = debrid.ad_get_magnet_status(key, magnet_id)
                    if status_info.get("statusCode", 0) >= 4:
                        break
                    time.sleep(1)
            # Get files
            files = []
            try:
                files = debrid.ad_get_magnet_files(key, magnet_id)
            except Exception:
                pass
            links = []
            if status_info.get("statusCode", 0) >= 4:
                for f in files:
                    if f.get("l"):
                        links.append(f["l"])
                    elif f.get("e"):
                        for sf in f["e"]:
                            if sf.get("l"):
                                links.append(sf["l"])
            return {
                "ok": True,
                "provider": "ad",
                "torrent_id": magnet_id,
                "status": "downloaded" if status_info.get("statusCode", 0) >= 4 else "processing",
                "links": links,
                "filename": status_info.get("filename", ""),
                "files": files,
            }
        elif provider == "tb":
            result = debrid.tb_add_magnet(key, body.info_hash)
            torrent_id = result.get("torrent_id") or result.get("id")
            # Poll for completion
            info = {}
            for _ in range(15):
                info = debrid.tb_get_torrent_info(key, torrent_id)
                ds = info.get("download_state", "")
                if ds in ("completed", "cached", "uploading", "paused"):
                    break
                if info.get("download_finished"):
                    break
                time.sleep(1)
            # Build file list with download links
            files = info.get("files", [])
            links = []
            if info.get("download_finished") or info.get("download_state") in ("completed", "cached"):
                for f in files:
                    try:
                        dl = debrid.tb_request_download(key, torrent_id, f.get("id", 0))
                        links.append(dl)
                    except Exception:
                        pass
            return {
                "ok": True,
                "provider": "tb",
                "torrent_id": torrent_id,
                "status": "downloaded" if links else "processing",
                "links": links,
                "filename": info.get("name", ""),
                "files": files,
            }
    except Exception as e:
        raise HTTPException(500, f"Failed to add magnet: {e}")


@router.get("/torrent/{torrent_id}")
def get_torrent_status(torrent_id: str,
                       user_id: int = Depends(get_current_user_id)):
    provider = database.get_setting("debrid_provider") or "rd"
    key = _key_for(provider)
    if not key:
        raise HTTPException(400, f"No API key set for {provider}")
    try:
        if provider == "rd":
            info = debrid.get_torrent_info(key, torrent_id)
            return {
                "status": info.get("status"),
                "progress": info.get("progress", 0),
                "speed": info.get("speed"),
                "links": info.get("links", []),
                "filename": info.get("filename", ""),
                "files": info.get("files", []),
            }
        elif provider == "ad":
            info = debrid.ad_get_magnet_status(key, torrent_id)
            files = []
            links = []
            try:
                files = debrid.ad_get_magnet_files(key, torrent_id)
            except Exception:
                pass
            if info.get("statusCode", 0) >= 4:
                for f in files:
                    if f.get("l"):
                        links.append(f["l"])
                    elif f.get("e"):
                        for sf in f["e"]:
                            if sf.get("l"):
                                links.append(sf["l"])
            progress = 100 if info.get("statusCode", 0) >= 4 else info.get("downloaded", 0) / max(info.get("size", 1), 1) * 100
            return {
                "status": "downloaded" if info.get("statusCode", 0) >= 4 else "processing",
                "progress": round(progress, 1),
                "speed": info.get("downloadSpeed", 0),
                "links": links,
                "filename": info.get("filename", ""),
                "files": files,
            }
        elif provider == "tb":
            info = debrid.tb_get_torrent_info(key, int(torrent_id))
            files = info.get("files", [])
            links = []
            finished = info.get("download_finished") or info.get("download_state") in ("completed", "cached")
            if finished:
                for f in files:
                    try:
                        dl = debrid.tb_request_download(key, int(torrent_id), f.get("id", 0))
                        links.append(dl)
                    except Exception:
                        pass
            progress = info.get("progress", 0)
            if isinstance(progress, float) and progress <= 1:
                progress = progress * 100
            return {
                "status": "downloaded" if finished else "processing",
                "progress": round(progress, 1),
                "speed": info.get("download_speed", 0),
                "links": links,
                "filename": info.get("name", ""),
                "files": files,
            }
    except Exception as e:
        raise HTTPException(500, f"Failed to get torrent status: {e}")


@router.post("/unrestrict")
def unrestrict_link(body: dict, user_id: int = Depends(get_current_user_id)):
    """Unrestrict a download link (RD/AD). TorBox uses requestdl instead."""
    link = body.get("link", "")
    provider = database.get_setting("debrid_provider") or "rd"
    key = _key_for(provider)
    if not key:
        raise HTTPException(400, f"No API key for {provider}")
    try:
        if provider == "rd":
            result = debrid.unrestrict_link(key, link)
            return {
                "url": result.get("download"),
                "filename": result.get("filename", ""),
                "filesize": result.get("filesize", 0),
                "mimeType": result.get("mimeType", ""),
            }
        elif provider == "ad":
            result = debrid.ad_unrestrict_link(key, link)
            return {
                "url": result.get("link"),
                "filename": result.get("filename", ""),
                "filesize": result.get("filesize", 0),
                "mimeType": result.get("mimeType", ""),
            }
        elif provider == "tb":
            return {"url": link, "filename": "", "filesize": 0}
    except Exception as e:
        raise HTTPException(500, f"Unrestrict failed: {e}")


@router.post("/select-files/{torrent_id}")
def select_files(torrent_id: str, body: SelectFilesBody,
                 user_id: int = Depends(get_current_user_id)):
    provider = database.get_setting("debrid_provider") or "rd"
    key = _key_for(provider)
    if not key:
        raise HTTPException(400, f"No API key for {provider}")
    try:
        if provider == "rd":
            debrid.select_files(key, torrent_id, body.file_ids)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"Select files failed: {e}")


# ---------------------------------------------------------------------------
# Download to Pi
# ---------------------------------------------------------------------------

@router.post("/download")
def download_to_pi(body: DownloadBody, user_id: int = Depends(get_current_user_id)):
    try:
        download_id = debrid.download_to_pi(
            _key_for(database.get_setting("debrid_provider") or "rd") or "",
            body.url, body.filename, body.category, body.is_show,
        )
        return {"ok": True, "download_id": download_id}
    except Exception as e:
        raise HTTPException(500, f"Download failed: {e}")


@router.get("/downloads")
def get_downloads(user_id: int = Depends(get_current_user_id)):
    return {"downloads": debrid.get_all_downloads()}


@router.get("/download/{download_id}")
def get_download_status(download_id: str,
                        user_id: int = Depends(get_current_user_id)):
    status = debrid.get_download_status(download_id)
    if status is None:
        raise HTTPException(404, "Download not found")
    return status


@router.delete("/download/{download_id}")
def cancel_download(download_id: str,
                    user_id: int = Depends(get_current_user_id)):
    if debrid.cancel_download(download_id):
        return {"ok": True}
    raise HTTPException(404, "Download not found")


@router.post("/downloads/clear")
def clear_completed(user_id: int = Depends(get_current_user_id)):
    count = debrid.clear_completed()
    return {"ok": True, "cleared": count}


# ---------------------------------------------------------------------------
# File renaming helper
# ---------------------------------------------------------------------------

@router.post("/clean-filename")
def clean_filename(body: dict, user_id: int = Depends(get_current_user_id)):
    raw = body.get("filename", "")
    title = body.get("title", "")
    year = body.get("year", "")
    media_type = body.get("media_type", "movie")
    season = body.get("season", 0)
    episode = body.get("episode", 0)
    clean = debrid.clean_media_filename(raw, title, year, media_type, season, episode)
    return {"clean_filename": clean}
from fastapi import APIRouter
router = APIRouter(prefix="/api/debrid", tags=["debrid"])

print("[router] Debrid router reverted to placeholder")
