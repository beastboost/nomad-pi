"""Real-Debrid integration router for Nomad Pi.

Provides endpoints for:
- Configuring RD API key
- Searching torrents via Torrentio
- Adding magnets to Real-Debrid
- Streaming directly from RD
- Downloading to Pi with auto-organization
- Download progress tracking
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import database
from app.routers.auth import get_current_user_id, get_current_admin
from app.services import debrid
from app.services import tmdb as tmdb_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debrid", tags=["debrid"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RDKeyRequest(BaseModel):
    api_key: str

class MagnetRequest(BaseModel):
    info_hash: str
    file_idx: Optional[int] = None

class DownloadRequest(BaseModel):
    download_url: str
    filename: str
    category: str = "auto"
    is_show: bool = False

class SelectFilesRequest(BaseModel):
    torrent_id: str
    file_ids: str = "all"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.post("/settings/key")
def set_rd_key(req: RDKeyRequest, admin: dict = Depends(get_current_admin)):
    """Save Real-Debrid API key (admin only)."""
    try:
        user_info = debrid.get_rd_user(req.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid API key: {e}")

    database.set_setting("rd_api_key", req.api_key)
    return {
        "status": "ok",
        "user": {
            "username": user_info.get("username"),
            "email": user_info.get("email"),
            "premium": user_info.get("premium", 0),
            "expiration": user_info.get("expiration"),
        }
    }


@router.get("/settings/key")
def get_rd_key_status(user_id: int = Depends(get_current_user_id)):
    """Check if RD API key is configured and valid."""
    api_key = database.get_setting("rd_api_key")
    if not api_key:
        return {"configured": False}

    try:
        user_info = debrid.get_rd_user(api_key)
        return {
            "configured": True,
            "user": {
                "username": user_info.get("username"),
                "premium": user_info.get("premium", 0),
                "expiration": user_info.get("expiration"),
            }
        }
    except Exception:
        return {"configured": True, "valid": False, "error": "API key is invalid or expired"}


@router.delete("/settings/key")
def remove_rd_key(admin: dict = Depends(get_current_admin)):
    """Remove stored RD API key."""
    database.set_setting("rd_api_key", "")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# AllDebrid Settings
# ---------------------------------------------------------------------------

@router.post("/settings/ad-key")
def set_ad_key(req: RDKeyRequest, admin: dict = Depends(get_current_admin)):
    """Save AllDebrid API key (admin only)."""
    try:
        user_info = debrid.ad_get_user(req.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid AllDebrid API key: {e}")

    database.set_setting("ad_api_key", req.api_key)
    return {
        "status": "ok",
        "user": {
            "username": user_info.get("username"),
            "premium": user_info.get("isPremium") or user_info.get("is_premium"),
        }
    }


@router.get("/settings/ad-key")
def get_ad_key_status(user_id: int = Depends(get_current_user_id)):
    """Check if AllDebrid API key is configured."""
    api_key = database.get_setting("ad_api_key")
    if not api_key:
        return {"configured": False}
    try:
        user_info = debrid.ad_get_user(api_key)
        return {
            "configured": True,
            "user": {
                "username": user_info.get("username"),
                "premium": user_info.get("isPremium") or user_info.get("is_premium"),
            }
        }
    except Exception:
        return {"configured": True, "valid": False, "error": "AllDebrid key invalid or expired"}


@router.delete("/settings/ad-key")
def remove_ad_key(admin: dict = Depends(get_current_admin)):
    """Remove stored AllDebrid API key."""
    database.set_setting("ad_api_key", "")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Provider detection helper
# ---------------------------------------------------------------------------

def _get_active_provider() -> tuple[str, str]:
    """Return (provider, api_key). Prefers RD, falls back to AD."""
    # First check explicit provider setting
    provider = database.get_setting("debrid_provider") or ""
    logger.info(f"Active debrid provider setting: {provider}")
    
    if provider == "ad":
        key = database.get_setting("ad_api_key")
        logger.info(f"AllDebrid explicit provider, key exists: {bool(key)}")
        if key:
            return "ad", key
        logger.warning("AllDebrid set as provider but no AD key found!")
    
    # Check RD key
    rd_key = database.get_setting("rd_api_key")
    if rd_key:
        logger.info("Using Real-Debrid as provider")
        return "rd", rd_key
    
    # Check AD key as fallback
    ad_key = database.get_setting("ad_api_key")
    if ad_key:
        logger.info("Using AllDebrid as fallback provider")
        return "ad", ad_key
    
    logger.warning("No debrid provider found!")
    return "rd", ""


@router.post("/settings/provider")
def set_provider(provider: str = Query(...), user_id: int = Depends(get_current_user_id)):
    """Switch active debrid provider (rd or ad)."""
    if provider not in ("rd", "ad"):
        raise HTTPException(status_code=400, detail="Invalid provider")
    database.set_setting("debrid_provider", provider)
    return {"status": "ok", "provider": provider}


@router.get("/settings/provider")
def get_provider(user_id: int = Depends(get_current_user_id)):
    """Get active debrid provider."""
    provider = database.get_setting("debrid_provider") or "rd"
    return {"provider": provider}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/search")
def search_torrents(
    query: str = "",
    imdb_id: str = "",
    media_type: str = Query("movie", regex="^(movie|series)$"),
    season: Optional[int] = None,
    episode: Optional[int] = None,
    user_id: int = Depends(get_current_user_id),
):
    """Search for torrents via Torrentio.

    Requires either an IMDB ID for direct lookup or a text query
    (which will be searched via TMDB/OMDb first for the IMDB ID).
    """
    actual_imdb_id = imdb_id

    if not actual_imdb_id and query:
        search_results = _search_titles(query, media_type)
        if search_results:
            return {"type": "search_results", "results": search_results}
        return {
            "type": "search_results",
            "results": [],
            "message": "No results found. Try a different search term or use an IMDB ID directly.",
        }

    if not actual_imdb_id:
        raise HTTPException(status_code=400, detail="Enter a search term or IMDB ID")

    results = debrid.search_torrentio(
        query=query,
        media_type=media_type,
        imdb_id=actual_imdb_id,
        season=season,
        episode=episode,
    )

    return {"type": "torrents", "results": results, "imdb_id": actual_imdb_id}


CINEMETA_BASE = "https://v3-cinemeta.strem.io"


def _search_titles(query: str, media_type: str) -> list[dict]:
    """Search for titles and return IMDB IDs.

    Uses Cinemeta (Stremio catalog, no API key needed) as primary,
    with TMDB and OMDb as fallbacks.
    """
    # Cinemeta — works without any API key, returns IMDB IDs directly
    try:
        import requests as _req
        url = f"{CINEMETA_BASE}/catalog/{media_type}/top/search={_req.utils.quote(query)}.json"
        r = _req.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            metas = data.get("metas", [])
            if metas:
                return [
                    {
                        "title": m.get("name"),
                        "year": (m.get("releaseInfo") or "")[:4],
                        "imdb_id": m.get("imdb_id") or m.get("id"),
                        "poster": m.get("poster"),
                        "type": m.get("type") or media_type,
                    }
                    for m in metas[:15]
                    if m.get("imdb_id") or (m.get("id", "").startswith("tt"))
                ]
    except Exception as e:
        logger.warning(f"Cinemeta search failed: {e}")

    # Fallback: TMDB (requires API key)
    try:
        if media_type == "series":
            tmdb_data = tmdb_service.search_shows(query)
        else:
            tmdb_data = tmdb_service.search_movies(query)

        if not tmdb_data.get("error") and tmdb_data.get("results"):
            results = []
            for item in tmdb_data["results"][:10]:
                tmdb_id = item.get("id")
                if not tmdb_id:
                    continue
                imdb_id = None
                try:
                    if media_type == "series":
                        details = tmdb_service.get_show_details(tmdb_id)
                    else:
                        details = tmdb_service.get_movie_details(tmdb_id)
                    if details:
                        imdb_id = details.get("imdb_id")
                except Exception:
                    pass
                if not imdb_id:
                    continue
                year = (item.get("release_date") or item.get("first_air_date") or "")[:4]
                results.append({
                    "title": item.get("title"),
                    "year": year,
                    "imdb_id": imdb_id,
                    "poster": item.get("poster"),
                    "type": media_type,
                })
            if results:
                return results
    except Exception as e:
        logger.warning(f"TMDB search failed: {e}")

    # Fallback: OMDb (requires API key)
    omdb_key = database.get_setting("omdb_api_key")
    if omdb_key:
        try:
            import httpx
            r = httpx.get(
                "https://www.omdbapi.com/",
                params={"apikey": omdb_key, "s": query, "type": media_type},
                timeout=10,
            )
            data = r.json()
            if data.get("Response") == "True" and data.get("Search"):
                return [
                    {
                        "title": item.get("Title"),
                        "year": item.get("Year"),
                        "imdb_id": item.get("imdbID"),
                        "poster": item.get("Poster") if item.get("Poster") != "N/A" else None,
                        "type": item.get("Type"),
                    }
                    for item in data["Search"][:10]
                ]
        except Exception as e:
            logger.warning(f"OMDb search failed: {e}")

    return []


# ---------------------------------------------------------------------------
# Debrid torrent operations (provider-aware)
# ---------------------------------------------------------------------------

def _require_debrid_key() -> tuple[str, str]:
    """Return (provider, api_key) or raise."""
    provider, api_key = _get_active_provider()
    if not api_key:
        raise HTTPException(status_code=400, detail="No debrid API key configured")
    return provider, api_key


def _require_rd_key() -> str:
    api_key = database.get_setting("rd_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Real-Debrid API key not configured")
    return api_key


class InstantCheckRequest(BaseModel):
    hashes: list[str]


@router.post("/instant")
def check_instant(req: InstantCheckRequest, user_id: int = Depends(get_current_user_id)):
    """Check which hashes are instantly available (cached) on the active debrid provider."""
    provider, api_key = _require_debrid_key()
    try:
        if provider == "ad":
            result = debrid.ad_check_instant(api_key, req.hashes)
        else:
            result = debrid.check_instant_availability(api_key, req.hashes)
        return {"cached": result}
    except Exception as e:
        logger.warning(f"Instant availability check failed: {e}")
        return {"cached": {}}


@router.post("/magnet")
def add_magnet(req: MagnetRequest, user_id: int = Depends(get_current_user_id)):
    """Add a magnet to the active debrid provider."""
    import time

    provider, api_key = _require_debrid_key()

    try:
        if provider == "ad":
            return _add_magnet_ad(api_key, req.info_hash)
        return _add_magnet_rd(api_key, req.info_hash)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add magnet failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _add_magnet_rd(api_key: str, info_hash: str) -> dict:
    import time

    result = debrid.add_magnet(api_key, info_hash)
    torrent_id = result.get("id")
    if not torrent_id:
        raise HTTPException(status_code=500, detail="Failed to get torrent ID")

    info = debrid.get_torrent_info(api_key, torrent_id)
    for _ in range(10):
        if info.get("status") != "magnet_conversion":
            break
        time.sleep(1)
        info = debrid.get_torrent_info(api_key, torrent_id)

    if info.get("status") == "waiting_files_selection":
        try:
            debrid.select_files(api_key, torrent_id, "all")
        except Exception as e:
            logger.warning(f"selectFiles failed: {e}")

        time.sleep(1)
        info = debrid.get_torrent_info(api_key, torrent_id)

        for _ in range(5):
            if info.get("status") == "downloaded":
                break
            time.sleep(1)
            info = debrid.get_torrent_info(api_key, torrent_id)

    return {
        "status": "ok",
        "torrent_id": torrent_id,
        "filename": info.get("filename"),
        "filesize": info.get("bytes"),
        "progress": info.get("progress"),
        "torrent_status": info.get("status"),
        "links": info.get("links", []),
        "files": [
            {"id": f.get("id"), "path": f.get("path"), "bytes": f.get("bytes"), "selected": f.get("selected")}
            for f in info.get("files", [])
        ],
    }


def _add_magnet_ad(api_key: str, info_hash: str) -> dict:
    import time
    import traceback

    try:
        result = debrid.ad_add_magnet(api_key, info_hash)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"AllDebrid add magnet failed: {error_msg}\n{traceback.format_exc()}")
        # Check for common errors
        if "discontinued" in error_msg.lower():
            raise HTTPException(status_code=410, detail="AllDebrid API endpoint discontinued. Please re-authenticate at alldebrid.com/tools")
        raise HTTPException(status_code=500, detail=f"AllDebrid error: {error_msg}")
    
    magnet_id = result.get("id")
    if not magnet_id:
        raise HTTPException(status_code=500, detail="Failed to add magnet to AllDebrid (no ID returned)")

    # Poll for ready status
    for _ in range(15):
        info = debrid.ad_get_magnet_status(api_key, str(magnet_id))
        status_code = info.get("statusCode", 0)
        # AD statusCode: 0=processing, 1=uploading, 2=uploading, 3=processing, 4=ready
        if status_code >= 4:
            break
        time.sleep(1)

    links = []
    ad_links = info.get("links", [])
    for lnk in ad_links:
        if isinstance(lnk, dict):
            links.append(lnk.get("link", ""))
        elif isinstance(lnk, str):
            links.append(lnk)

    ad_status_map = {0: "magnet_conversion", 1: "downloading", 2: "downloading",
                     3: "downloading", 4: "downloaded"}
    torrent_status = ad_status_map.get(status_code, "downloading")

    return {
        "status": "ok",
        "torrent_id": str(magnet_id),
        "filename": info.get("filename"),
        "filesize": info.get("size"),
        "progress": 100 if status_code >= 4 else (info.get("downloadSpeed", 0) or 0),
        "torrent_status": torrent_status,
        "links": links,
        "files": [],
    }


@router.post("/select-files")
def select_torrent_files(req: SelectFilesRequest, user_id: int = Depends(get_current_user_id)):
    """Select specific files from a torrent (RD only, AllDebrid auto-selects)."""
    provider, api_key = _require_debrid_key()
    if provider == "ad":
        return {"status": "ok"}
    try:
        debrid.select_files(api_key, req.torrent_id, req.file_ids)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/torrent/{torrent_id}")
def get_torrent_status(torrent_id: str, user_id: int = Depends(get_current_user_id)):
    """Get torrent status and download links."""
    provider, api_key = _require_debrid_key()
    try:
        if provider == "ad":
            info = debrid.ad_get_magnet_status(api_key, torrent_id)
            status_code = info.get("statusCode", 0)
            ad_status_map = {0: "magnet_conversion", 1: "downloading", 2: "downloading",
                             3: "downloading", 4: "downloaded"}
            links = []
            for lnk in info.get("links", []):
                if isinstance(lnk, dict):
                    links.append(lnk.get("link", ""))
                elif isinstance(lnk, str):
                    links.append(lnk)
            return {
                "torrent_id": torrent_id,
                "filename": info.get("filename"),
                "bytes": info.get("size"),
                "progress": 100 if status_code >= 4 else 0,
                "status": ad_status_map.get(status_code, "downloading"),
                "links": links,
                "speed": info.get("downloadSpeed"),
                "seeders": info.get("seeders"),
            }
        else:
            info = debrid.get_torrent_info(api_key, torrent_id)
            return {
                "torrent_id": torrent_id,
                "filename": info.get("filename"),
                "bytes": info.get("bytes"),
                "progress": info.get("progress"),
                "status": info.get("status"),
                "links": info.get("links", []),
                "speed": info.get("speed"),
                "seeders": info.get("seeders"),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unrestrict")
def unrestrict(
    link: str = Query(...),
    title: str = Query(""),
    year: str = Query(""),
    media_type: str = Query("movie"),
    season: Optional[int] = Query(None),
    episode: Optional[int] = Query(None),
    user_id: int = Depends(get_current_user_id),
):
    """Unrestrict a link via the active debrid provider."""
    provider, api_key = _require_debrid_key()
    try:
        if provider == "ad":
            result = debrid.ad_unrestrict_link(api_key, link)
            raw_filename = result.get("filename", "")
            download_url = result.get("link", "")
        else:
            result = debrid.unrestrict_link(api_key, link)
            raw_filename = result.get("filename", "")
            download_url = result.get("download", "")

        clean_filename = debrid.clean_media_filename(
            raw_filename,
            title=title,
            year=year,
            media_type=media_type,
            season=season or 0,
            episode=episode or 0,
        )
        return {
            "download": download_url,
            "filename": clean_filename,
            "raw_filename": raw_filename,
            "filesize": result.get("filesize") or result.get("size"),
            "host": result.get("host"),
            "streaming": result.get("streaming"),
            "id": result.get("id"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Stream from RD (proxy for video player)
# ---------------------------------------------------------------------------

@router.get("/stream-url")
def get_stream_url(link: str = Query(...), user_id: int = Depends(get_current_user_id)):
    """Get a direct streaming URL from the active debrid provider."""
    provider, api_key = _require_debrid_key()
    try:
        if provider == "ad":
            result = debrid.ad_unrestrict_link(api_key, link)
            return {
                "stream_url": result.get("link"),
                "filename": result.get("filename"),
                "filesize": result.get("size"),
            }
        else:
            result = debrid.unrestrict_link(api_key, link)
            return {
                "stream_url": result.get("download"),
                "filename": result.get("filename"),
                "filesize": result.get("filesize"),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Download to Pi
# ---------------------------------------------------------------------------

@router.post("/download")
def start_download(req: DownloadRequest, user_id: int = Depends(get_current_user_id)):
    """Download a file from Real-Debrid to the Pi's media library."""
    try:
        download_id = debrid.download_to_pi(
            api_key=_require_rd_key(),
            download_url=req.download_url,
            filename=req.filename,
            category=req.category,
            is_show=req.is_show,
        )
        return {"status": "ok", "download_id": download_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads")
def list_downloads(user_id: int = Depends(get_current_user_id)):
    """List all active/completed downloads to Pi."""
    return {"downloads": debrid.get_all_downloads()}


@router.get("/downloads/{download_id}")
def get_download(download_id: str, user_id: int = Depends(get_current_user_id)):
    """Get status of a specific download."""
    status = debrid.get_download_status(download_id)
    if not status:
        raise HTTPException(status_code=404, detail="Download not found")
    return status


@router.delete("/downloads/{download_id}")
def cancel_download(download_id: str, user_id: int = Depends(get_current_user_id)):
    """Cancel a download."""
    if debrid.cancel_download(download_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Download not found")


@router.post("/downloads/clear")
def clear_downloads(user_id: int = Depends(get_current_user_id)):
    """Clear completed/failed downloads from the list."""
    count = debrid.clear_completed()
    return {"status": "ok", "cleared": count}


# ---------------------------------------------------------------------------
# RD library (user's existing downloads/torrents on RD)
# ---------------------------------------------------------------------------

@router.get("/rd-downloads")
def list_rd_downloads(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
):
    """List user's download history on Real-Debrid."""
    api_key = _require_rd_key()
    try:
        downloads = debrid.get_rd_downloads(api_key, page, limit)
        return {"downloads": downloads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rd-torrents")
def list_rd_torrents(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
):
    """List user's torrents on Real-Debrid."""
    api_key = _require_rd_key()
    try:
        torrents = debrid.get_rd_torrents(api_key, page, limit)
        return {"torrents": torrents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rd-torrents/{torrent_id}")
def delete_rd_torrent(torrent_id: str, user_id: int = Depends(get_current_user_id)):
    """Delete a torrent from Real-Debrid."""
    api_key = _require_rd_key()
    try:
        debrid.delete_rd_torrent(api_key, torrent_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
