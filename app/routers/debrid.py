"""
Provides endpoints for:
- Saving / validating API keys for each provider
- Torrent search via Torrentio + Cinemeta title lookup
- Instant availability checking (cached torrents)
- Adding magnets, polling torrent status, unrestricting links
- Streaming and downloading to the Pi
"""

import logging
import json
import time
import urllib.request
from urllib.parse import unquote, urlparse
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
import requests

from app import database
from app.routers.auth import get_current_user_id
from app.services import debrid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/debrid", tags=["debrid"])
SUPPORTED_PROVIDERS = {"rd", "ad", "tb"}


def _is_video_filename(name: str) -> bool:
    raw = (name or "").strip()
    if not raw:
        return False
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    if "://" in raw:
        try:
            raw = unquote(urlparse(raw).path)
        except Exception:
            pass
    base = raw.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    ext = base.rsplit(".", 1)[-1] if "." in base else ""
    return ext in {
        "mp4",
        "mkv",
        "avi",
        "mov",
        "webm",
        "m4v",
        "ts",
        "m2ts",
        "mts",
        "wmv",
        "flv",
        "mpg",
        "mpeg",
        "mpe",
        "3gp",
        "vob",
    }


# #region debug-point A:debug-helper
def _debug_report(hypothesis_id: str, location: str, msg: str, data: Optional[dict] = None, trace_id: str = "") -> None:
    _p = ".dbg/web-ui-not-loading.env"
    _u = "http://127.0.0.1:7777/event"
    _s = "web-ui-not-loading"
    try:
        with open(_p, encoding="utf-8") as f:
            c = f.read()
        for line in c.splitlines():
            if line.startswith("DEBUG_SERVER_URL="):
                _u = line.split("=", 1)[1] or _u
            elif line.startswith("DEBUG_SESSION_ID="):
                _s = line.split("=", 1)[1] or _s
    except Exception:
        pass
    try:
        payload = {
            "sessionId": _s,
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "msg": f"[DEBUG] {msg}",
            "data": data or {},
            "traceId": trace_id,
            "ts": int(time.time() * 1000),
        }
        urllib.request.urlopen(
            urllib.request.Request(
                _u,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            ),
            timeout=2,
        ).read()
    except Exception:
        pass
# #endregion

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

def _provider(request: Optional[Request] = None) -> str:
    """Read the active debrid provider from the DB and fall back to supported values."""
    provider = database.get_setting("debrid_provider") or "rd"
    return provider if provider in SUPPORTED_PROVIDERS else "rd"


def _key_for(provider: str) -> Optional[str]:
    mapping = {"rd": "rd_api_key", "ad": "ad_api_key", "tb": "tb_api_key"}
    setting = mapping.get(provider)
    return database.get_setting(setting) if setting else None


def _http_error_status(exc: Exception) -> Optional[int]:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


@router.get("/provider")
def get_provider(user_id: int = Depends(get_current_user_id)):
    return {"provider": _provider(None)}


@router.post("/provider")
def set_provider(body: dict, user_id: int = Depends(get_current_user_id)):
    p = body.get("provider", "rd")
    if p not in SUPPORTED_PROVIDERS:
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
                    filter_type: Optional[str] = Query(None), # e.g. "mp4", "mkv"
                    filter_quality: Optional[str] = Query(None), # e.g. "1080p", "2160p"
                    user_id: int = Depends(get_current_user_id)):
    results = debrid.search_torrentio("", media_type=media_type, imdb_id=imdb_id,
                                      season=season, episode=episode)
    
    filtered_results = []
    for r in results:
        name = r.get("name", "").lower()
        meta = r.get("meta", "").lower()
        codec = (r.get("codec") or "").lower()
        
        if filter_type and filter_type.lower() != "all":
            ft = filter_type.lower()

            # Container matching
            if ft == "mp4" and "mp4" not in name and "mp4" not in meta:
                continue
            if ft == "mkv" and "mkv" not in name and "mkv" not in meta:
                continue

            # Codec matching (comprehensive)
            if ft == "h264":
                # Look for H264 in the name, meta, or the newly extracted codec field
                if codec != "h264" and not any(t in name or t in meta for t in ["h264", "x264", "avc", "h.264"]):
                    continue

            if ft == "hevc":
                if codec != "hevc" and not any(t in name or t in meta for t in ["hevc", "h265", "x265", "h.265"]):
                    continue

            if ft == "av1":
                if codec != "av1" and "av1" not in name and "av1" not in meta:
                    continue
                
        if filter_quality and filter_quality.lower() != "all":
            if filter_quality.lower() == "2160p" and "2160p" not in meta and "4k" not in meta:
                continue
            if filter_quality.lower() == "1080p" and "1080p" not in meta:
                continue
            if filter_quality.lower() == "720p" and "720p" not in meta:
                continue
                
        filtered_results.append(r)
        
    return {"results": filtered_results}


# ---------------------------------------------------------------------------
# Instant availability (cached check)
# ---------------------------------------------------------------------------

@router.post("/instant")
def check_instant(body: dict, user_id: int = Depends(get_current_user_id)):
    """Check instant availability for a list of hashes on the active provider."""
    hashes = body.get("hashes", [])
    provider = body.get("provider") or _provider(None)
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
    provider = _provider(None)
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
            files = []
            links = []
            if status_info.get("statusCode", 0) >= 4:
                ad_files = debrid.ad_get_magnet_files(key, magnet_id)
                ad_files = sorted(
                    ad_files,
                    key=lambda f: (
                        0 if _is_video_filename(str(f.get("filename") or f.get("link") or "")) else 1,
                        -int(f.get("size") or 0),
                        str(f.get("filename", "")).lower(),
                    ),
                )
                has_video = any(_is_video_filename(str(f.get("filename") or f.get("link") or "")) for f in ad_files)
                idx = 0
                for f in ad_files:
                    if has_video and not _is_video_filename(str(f.get("filename") or f.get("link") or "")):
                        continue
                    link = f.get("link")
                    if link:
                        links.append(link)
                        files.append({
                            "id": idx,
                            "path": f.get("filename", ""),
                            "bytes": f.get("size", 0),
                            "selected": 1
                        })
                        idx += 1
            return {
                "ok": True,
                "provider": "ad",
                "torrent_id": magnet_id,
                "status": "downloaded" if status_info.get("statusCode", 0) >= 4 and links else ("error" if status_info.get("statusCode", 0) >= 5 else "processing"),
                "links": links,
                "filename": status_info.get("filename") or status_info.get("name") or result.get("name", ""),
                "files": files,
                "message": (status_info.get("error", {}) or {}).get("message", "") if isinstance(status_info.get("error"), dict) else "",
            }
        elif provider == "tb":
            result = debrid.tb_add_magnet(key, body.info_hash)
            torrent_id = result.get("torrent_id") or result.get("torrentId") or result.get("id") or result.get("Id")
            info = {}
            for _ in range(15):
                info = debrid.tb_get_torrent_info(key, torrent_id)
                ds = str(info.get("download_state", ""))
                if ds in ("completed", "cached", "uploading", "paused"):
                    break
                if info.get("download_finished"):
                    break
                time.sleep(1)
            files = info.get("files", [])
            if isinstance(files, list):
                files = sorted(
                    files,
                    key=lambda f: (
                        0 if _is_video_filename(str(f.get("name") or f.get("path") or "")) else 1,
                        -int(f.get("size") or 0),
                        str(f.get("name", "")).lower(),
                    ),
                )
            links = []
            if info.get("download_finished") or info.get("download_state") in ("completed", "cached", "uploading") or info.get("download_present"):
                has_video = isinstance(files, list) and any(_is_video_filename(str(f.get("name") or f.get("path") or "")) for f in files)
                for f in files:
                    if has_video and not _is_video_filename(str(f.get("name") or f.get("path") or "")):
                        continue
                    try:
                        dl = debrid.tb_request_download(key, torrent_id, f.get("id", 0))
                        if dl:
                            links.append(dl)
                    except Exception as e:
                        logger.warning(f"TorBox requestdl failed for torrent {torrent_id} file {f.get('id')}: {e}")
                if not links:
                    try:
                        dl = debrid.tb_request_download(key, torrent_id, 0)
                        if dl:
                            links.append(dl)
                    except Exception as e:
                        logger.warning(f"TorBox requestdl failed for torrent {torrent_id}: {e}")
            return {
                "ok": True,
                "provider": "tb",
                "torrent_id": torrent_id,
                "status": "downloaded" if links else ("error" if (info.get("download_finished") or info.get("download_present")) else "processing"),
                "links": links,
                "filename": info.get("name", ""),
                "files": files,
                "message": "" if links else "TorBox reported this torrent ready, but no download link could be generated.",
            }
    except Exception as e:
        status_code = _http_error_status(e)
        if provider == "rd" and status_code == 451:
            raise HTTPException(451, "Real-Debrid blocked this release. Try a BluRay, HEVC, AV1, or another safer torrent.")
        raise HTTPException(500, f"Failed to add magnet: {e}")


@router.get("/torrent/{torrent_id}")
def get_torrent_status(torrent_id: str,
                       user_id: int = Depends(get_current_user_id)):
    provider = _provider(None)
    key = _key_for(provider)
    # #region debug-point A:router-torrent-entry
    _debug_report("A", "app/routers/debrid.py:get_torrent_status", "router torrent status entry", {"provider": provider, "torrent_id": str(torrent_id), "has_key": bool(key)})
    # #endregion
    if not key:
        raise HTTPException(400, f"No API key set for {provider}")
    try:
        if provider == "rd":
            info = debrid.get_torrent_info(key, torrent_id)
            response = {
                "status": info.get("status"),
                "progress": info.get("progress", 0),
                "speed": info.get("speed"),
                "links": info.get("links", []),
                "filename": info.get("filename", ""),
                "files": info.get("files", []),
            }
            # #region debug-point A:router-torrent-rd-success
            _debug_report("A", "app/routers/debrid.py:get_torrent_status", "router torrent status rd success", {"provider": provider, "torrent_id": str(torrent_id), "status": str(response.get("status", "")), "links_count": len(response.get("links", []) or [])})
            # #endregion
            return response
        elif provider == "ad":
            info = debrid.ad_get_magnet_status(key, torrent_id)
            files = []
            links = []
            status_code = info.get("statusCode", 0)
            if status_code >= 4:
                ad_files = debrid.ad_get_magnet_files(key, torrent_id)
                ad_files = sorted(
                    ad_files,
                    key=lambda f: (
                        0 if _is_video_filename(str(f.get("filename") or f.get("link") or "")) else 1,
                        -int(f.get("size") or 0),
                        str(f.get("filename", "")).lower(),
                    ),
                )
                has_video = any(_is_video_filename(str(f.get("filename") or f.get("link") or "")) for f in ad_files)
                idx = 0
                for f in ad_files:
                    if has_video and not _is_video_filename(str(f.get("filename") or f.get("link") or "")):
                        continue
                    link = f.get("link")
                    if link:
                        links.append(link)
                        files.append({
                            "id": idx,
                            "path": f.get("filename", ""),
                            "bytes": f.get("size", 0),
                            "selected": 1
                        })
                        idx += 1
            size = info.get("size") or info.get("size_total") or 1
            downloaded = info.get("downloaded") or info.get("downloadedBytes") or info.get("downloaded_bytes") or 0
            progress = 100 if status_code >= 4 else (float(downloaded) / max(float(size), 1.0) * 100)
            response = {
                "status": "downloaded" if status_code >= 4 and links else ("error" if status_code >= 5 else "processing"),
                "progress": round(progress, 1),
                "speed": info.get("downloadSpeed", 0),
                "links": links,
                "filename": info.get("filename") or info.get("name") or "",
                "files": files,
                "message": "" if status_code < 5 else "AllDebrid reported an error processing this magnet.",
            }
            # #region debug-point A:router-torrent-ad-success
            _debug_report("A", "app/routers/debrid.py:get_torrent_status", "router torrent status ad success", {"provider": provider, "torrent_id": str(torrent_id), "status": str(response.get("status", "")), "links_count": len(response.get("links", []) or []), "file_count": len(files)})
            # #endregion
            return response
        elif provider == "tb":
            info = debrid.tb_get_torrent_info(key, torrent_id)
            files = info.get("files") or []
            if isinstance(files, list):
                files = sorted(
                    files,
                    key=lambda f: (
                        0 if _is_video_filename(str(f.get("name") or f.get("path") or "")) else 1,
                        -int(f.get("size") or 0),
                        str(f.get("name", "")).lower(),
                    ),
                )
            links = []
            ds = str(info.get("download_state", "")).lower()
            finished = bool(info.get("download_finished") or info.get("download_present")) or ds in ("cached",)
            if finished:
                has_video = isinstance(files, list) and any(_is_video_filename(str(f.get("name") or f.get("path") or "")) for f in files)
                for f in files:
                    if has_video and not _is_video_filename(str(f.get("name") or f.get("path") or "")):
                        continue
                    try:
                        dl = debrid.tb_request_download(key, torrent_id, f.get("id", 0))
                        if dl:
                            links.append(dl)
                    except Exception as e:
                        logger.warning(f"TorBox requestdl failed for torrent {torrent_id} file {f.get('id')}: {e}")
                if not links:
                    try:
                        dl = debrid.tb_request_download(key, torrent_id, 0)
                        if dl:
                            links.append(dl)
                    except Exception as e:
                        logger.warning(f"TorBox requestdl failed for torrent {torrent_id}: {e}")
            progress = info.get("progress", 0)
            if isinstance(progress, float) and progress <= 1:
                progress = progress * 100
            response = {
                "status": "downloaded" if finished and links else ("error" if finished else "processing"),
                "progress": round(progress, 1),
                "speed": info.get("download_speed", 0),
                "links": links,
                "filename": info.get("name", ""),
                "files": files,
                "message": "" if links else ("TorBox reported this torrent ready, but no download link could be generated." if finished else ""),
            }
            # #region debug-point A:router-torrent-tb-success
            _debug_report("A", "app/routers/debrid.py:get_torrent_status", "router torrent status tb success", {"provider": provider, "torrent_id": str(torrent_id), "status": str(response.get("status", "")), "links_count": len(response.get("links", []) or []), "file_count": len(files)})
            # #endregion
            return response
    except Exception as e:
        status_code = _http_error_status(e)
        if provider == "rd" and status_code == 404:
            response = {
                "status": "expired",
                "progress": 0,
                "speed": 0,
                "links": [],
                "filename": "",
                "files": [],
            }
            # #region debug-point A:router-torrent-rd-expired
            _debug_report("A", "app/routers/debrid.py:get_torrent_status", "router torrent status rd expired", {"provider": provider, "torrent_id": str(torrent_id)})
            # #endregion
            return response
        # #region debug-point A:router-torrent-error
        _debug_report("A", "app/routers/debrid.py:get_torrent_status", "router torrent status error", {"provider": provider, "torrent_id": str(torrent_id), "error": str(e), "error_type": type(e).__name__})
        # #endregion
        raise HTTPException(500, f"Failed to get torrent status: {e}")


@router.post("/unrestrict")
def unrestrict_link(body: dict, user_id: int = Depends(get_current_user_id)):
    """Unrestrict a download link (RD/AD). TorBox uses requestdl instead."""
    link = body.get("link", "")
    provider = _provider(None)
    key = _key_for(provider)
    # #region debug-point A:router-unrestrict-entry
    _debug_report("A", "app/routers/debrid.py:unrestrict_link", "router unrestrict entry", {"provider": provider, "has_key": bool(key), "link_prefix": link[:120]})
    # #endregion
    if not key:
        raise HTTPException(400, f"No API key for {provider}")
    try:
        if provider == "rd":
            result = debrid.unrestrict_link(key, link)
            response = {
                "url": result.get("download"),
                "filename": result.get("filename", ""),
                "filesize": result.get("filesize", 0),
                "mimeType": result.get("mimeType", ""),
            }
            # #region debug-point A:router-unrestrict-rd-success
            _debug_report("A", "app/routers/debrid.py:unrestrict_link", "router unrestrict rd success", {"provider": provider, "has_url": bool(response.get("url")), "filename": response.get("filename", "")[:120]})
            # #endregion
            return response
        elif provider == "ad":
            try:
                result = debrid.ad_unrestrict_link(key, link)
                response = {
                    "url": result.get("link"),
                    "filename": result.get("filename", ""),
                    "filesize": result.get("filesize", 0),
                    "mimeType": result.get("mimeType", ""),
                }
                # #region debug-point A:router-unrestrict-ad-success
                _debug_report("A", "app/routers/debrid.py:unrestrict_link", "router unrestrict ad success", {"provider": provider, "has_url": bool(response.get("url")), "filename": response.get("filename", "")[:120]})
                # #endregion
                return response
            except Exception:
                import urllib.parse
                import os
                try:
                    fname = os.path.basename(urllib.parse.urlparse(link).path)
                    if not fname:
                        fname = "alldebrid_download"
                except Exception:
                    fname = "alldebrid_download"
                response = {"url": link, "filename": fname, "filesize": 0}
                _debug_report("A", "app/routers/debrid.py:unrestrict_link", "router unrestrict ad passthrough", {"provider": provider, "has_url": bool(response.get("url")), "filename": fname[:120]})
                return response
        elif provider == "tb":
            import os
            import re
            import urllib.parse

            def _cd_filename(cd: str) -> str:
                if not cd:
                    return ""
                m = re.search(r"filename\*=(?:UTF-8''|utf-8'')([^;]+)", cd)
                if m:
                    try:
                        return urllib.parse.unquote(m.group(1)).strip().strip('"')
                    except Exception:
                        return m.group(1).strip().strip('"')
                m = re.search(r'filename="([^"]+)"', cd)
                if m:
                    return m.group(1).strip()
                m = re.search(r"filename=([^;]+)", cd)
                if m:
                    return m.group(1).strip().strip('"')
                return ""

            def _ext_from_content_type(ct: str) -> str:
                ct = (ct or "").split(";", 1)[0].strip().lower()
                mapping = {
                    "video/mp4": ".mp4",
                    "video/quicktime": ".mov",
                    "video/x-matroska": ".mkv",
                    "video/webm": ".webm",
                    "video/x-msvideo": ".avi",
                    "video/mp2t": ".ts",
                    "application/x-matroska": ".mkv",
                }
                return mapping.get(ct, "")

            url = link
            fname = ""
            size = 0
            try:
                r = debrid.safe_head(url, timeout=10)
                cd = r.headers.get("Content-Disposition") or r.headers.get("content-disposition") or ""
                ct = r.headers.get("Content-Type") or r.headers.get("content-type") or ""
                size = int(r.headers.get("Content-Length") or r.headers.get("content-length") or 0)
                fname = _cd_filename(cd)
                if not fname:
                    path_base = os.path.basename(urllib.parse.urlparse(r.url or url).path)
                    fname = path_base
                if fname and not os.path.splitext(fname)[1]:
                    ext = _ext_from_content_type(ct)
                    if ext:
                        fname = fname + ext
            except Exception:
                fname = ""

            if not fname:
                try:
                    fname = os.path.basename(urllib.parse.urlparse(url).path)
                except Exception:
                    fname = ""
            if not fname:
                fname = "torbox_download"
            response = {"url": url, "filename": fname, "filesize": size}
            # #region debug-point A:router-unrestrict-tb-success
            _debug_report("A", "app/routers/debrid.py:unrestrict_link", "router unrestrict tb passthrough", {"provider": provider, "has_url": bool(response.get("url"))})
            # #endregion
            return response
    except Exception as e:
        status_code = _http_error_status(e)
        if provider == "rd" and status_code == 451:
            raise HTTPException(451, "Real-Debrid blocked this file. Try a BluRay, HEVC, AV1, or another safer torrent.")
        # #region debug-point A:router-unrestrict-error
        _debug_report("A", "app/routers/debrid.py:unrestrict_link", "router unrestrict error", {"provider": provider, "error": str(e), "error_type": type(e).__name__, "link_prefix": link[:120]})
        # #endregion
        raise HTTPException(500, f"Unrestrict failed: {e}")


@router.post("/select-files/{torrent_id}")
def select_files(torrent_id: str, body: SelectFilesBody,
                 user_id: int = Depends(get_current_user_id)):
    provider = _provider(None)
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
