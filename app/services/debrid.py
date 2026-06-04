"""Debrid API client for Nomad Pi.

Handles torrent search via Torrentio, magnet submission to Real-Debrid
or AllDebrid, unrestricting download links, and downloading files to the Pi.
"""

import json
import logging
import os
import ipaddress
import re
import shutil
import socket
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional, Union

import requests

from app import database

logger = logging.getLogger(__name__)

RD_BASE = "https://api.real-debrid.com/rest/1.0"
AD_BASE_V4 = "https://api.alldebrid.com/v4"
AD_BASE_V41 = "https://api.alldebrid.com/v4.1"
AD_BASE = AD_BASE_V4
TB_BASE = "https://api.torbox.app/v1/api"
TORRENTIO_BASE = "https://torrentio.strem.fun"

# Torrentio blocks the default python-requests User-Agent
_TORRENTIO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NomadPi/1.0)",
}

_RD_BLOCKED_SUBSTRINGS = (
    "web-dl",
    "webrip",
    "bdrip",
    "hdrip",
    "dvdrip",
)

_RD_BLOCKED_DOT_PATTERNS = (
    "bluray.x264",
    "hdtv.x264",
    "hdtv.xvid",
    "web.x264",
    "web.h264",
)

_RD_PREFERRED_TERMS = (
    "x265",
    "h265",
    "hevc",
    "av1",
    "avc",
    "blu-ray",
    "remux",
    "web.h265",
    "web.x265",
    "bluray.x265",
)

# Active downloads tracked in memory
_downloads: dict[str, dict] = {}
_downloads_lock = threading.Lock()

# Rate limiter for API calls
_api_call_times: dict[str, list] = {"rd": [], "ad": [], "tb": []}
_api_rate_lock = threading.Lock()
API_RATE_LIMIT = 100  # requests
API_RATE_WINDOW = 60   # seconds


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


class DebridAuthError(Exception):
    """Raised when API authentication fails."""
    pass


class DebridRateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass


def _check_rate_limit(provider: str) -> None:
    """Check and enforce rate limiting."""
    with _api_rate_lock:
        now = time.time()
        window_start = now - API_RATE_WINDOW
        
        # Remove old entries outside window
        _api_call_times[provider] = [t for t in _api_call_times[provider] if t > window_start]
        
        # Check if limit exceeded
        if len(_api_call_times[provider]) >= API_RATE_LIMIT:
            oldest = _api_call_times[provider][0]
            wait_time = (oldest + API_RATE_WINDOW) - now
            if wait_time > 0:
                logger.warning(f"{provider.upper()} rate limit approaching, waiting {wait_time:.1f}s")
                time.sleep(wait_time)
        
        # Record this call
        _api_call_times[provider].append(now)


def _rd_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _ad_headers(api_key: str) -> dict:
    """Return headers for AllDebrid API v4 with Bearer token auth."""
    return {"Authorization": f"Bearer {api_key}"}


def _tb_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _tb_extract_data(payload):
    if isinstance(payload, dict):
        success = payload.get("success")
        if success is None:
            success = payload.get("Success")
        if success is False:
            detail = payload.get("detail") or payload.get("error") or "TorBox error"
            raise Exception(str(detail))
        if "data" in payload:
            return payload.get("data")
        if "Data" in payload:
            return payload.get("Data")
    return payload


def _tb_request(method: str, path: str, api_key: str, **kwargs):
    _check_rate_limit("tb")
    r = requests.request(
        method,
        f"{TB_BASE}{path}",
        headers=_tb_headers(api_key),
        timeout=15,
        **kwargs,
    )
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        return r.text
    return _tb_extract_data(payload)


# ---------------------------------------------------------------------------
# Real-Debrid account helpers
# ---------------------------------------------------------------------------

def get_rd_user(api_key: str) -> dict:
    """Validate API key and return user info."""
    try:
        _check_rate_limit("rd")
        r = requests.get(f"{RD_BASE}/user", headers=_rd_headers(api_key), timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid or expired Real-Debrid API key")
        raise DebridAuthError(f"Real-Debrid auth failed: {str(e)}")
    except Exception as e:
        raise DebridAuthError(f"Real-Debrid connection failed: {str(e)}")


def tb_get_user(api_key: str) -> dict:
    """Validate TorBox API key and return account info."""
    try:
        data = _tb_request("GET", "/user/me", api_key)
        if isinstance(data, dict):
            return data
        raise DebridAuthError("Invalid TorBox API response")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            raise DebridAuthError("Invalid TorBox API key")
        raise DebridAuthError(f"TorBox connection failed: {str(e)}")
    except Exception as e:
        raise DebridAuthError(f"TorBox connection failed: {str(e)}")


def _quality_rank(quality: str) -> int:
    ranks = {
        "4k": 5,
        "2160p": 5,
        "1080p": 4,
        "720p": 3,
        "480p": 2,
        "hdcam": 1,
        "cam": 0,
        "unknown": 0,
    }
    return ranks.get((quality or "unknown").lower(), 0)


def _analyze_rd_release(title: str, details: str) -> dict:
    """Flag Torrentio releases that are likely to hit RD filename filters."""
    text = f"{title} {details}".lower()
    dot_text = re.sub(r"[\s_]+", ".", text)
    reasons = []

    for pattern in _RD_BLOCKED_SUBSTRINGS:
        if pattern in text:
            reasons.append(pattern.upper())

    for pattern in _RD_BLOCKED_DOT_PATTERNS:
        if pattern in dot_text:
            reasons.append(pattern.upper())

    preferred_terms = [term.upper() for term in _RD_PREFERRED_TERMS if term in dot_text or term in text]
    is_likely_blocked = bool(reasons)

    if is_likely_blocked:
        status = "likely_blocked"
        warning = f"Likely blocked by RD: {', '.join(reasons[:3])}"
        score = -100 - (len(reasons) * 10)
    elif preferred_terms:
        status = "safer"
        warning = f"Safer for RD: {', '.join(preferred_terms[:3])}"
        score = 25 + (len(preferred_terms) * 5)
    else:
        status = "neutral"
        warning = ""
        score = 0

    return {
        "status": status,
        "warning": warning,
        "reasons": reasons,
        "preferred_terms": preferred_terms,
        "score": score,
    }


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

        r = requests.get(url, headers=_TORRENTIO_HEADERS, timeout=15)
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

            # Extract codec
            codec = ""
            codec_map = {
                "HEVC": ["hevc", "h265", "h.265", "x265"],
                "H264": ["h264", "h.264", "x264", "avc"],
                "AV1": ["av1"],
                "XVID": ["xvid", "divx"]
            }
            title_lower = title.lower()
            for c_name, tags in codec_map.items():
                if any(t in title_lower for t in tags):
                    codec = c_name
                    break

            rd_analysis = _analyze_rd_release(name, details)

            results.append({
                "name": name,
                "info_hash": info_hash,
                "file_idx": file_idx,
                "quality": quality,
                "size": size_str,
                "source": source,
                "codec": codec,
                "details": details,
                "seeders": stream.get("seeders"),
                "rd_status": rd_analysis["status"],
                "rd_warning": rd_analysis["warning"],
                "rd_reasons": rd_analysis["reasons"],
                "rd_score": rd_analysis["score"],
            })
    except requests.RequestException as e:
        logger.error(f"Torrentio search failed: {e}")

    results.sort(
        key=lambda item: (
            item.get("rd_status") == "likely_blocked",
            -(item.get("rd_score", 0)),
            -int(item.get("seeders") or 0),
            -_quality_rank(item.get("quality", "Unknown")),
            item.get("name", "").lower(),
        )
    )

    return results


# ---------------------------------------------------------------------------
# TorBox helpers
# ---------------------------------------------------------------------------


def tb_check_instant(api_key: str, hashes: list[str]) -> dict[str, bool]:
    """Check which hashes are instantly available (cached) on TorBox."""
    if not hashes:
        return {}

    normalized = [h.lower() for h in hashes if h]
    result = {h: False for h in normalized}
    params = [("hash", h) for h in normalized]
    params.append(("format", "object"))

    try:
        data = _tb_request("GET", "/torrents/checkcached", api_key, params=params)
        if isinstance(data, dict):
            for key, value in data.items():
                hash_value = str(key).lower()
                if hash_value in result:
                    result[hash_value] = bool(value)
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, str):
                    hash_value = entry.lower()
                    if hash_value in result:
                        result[hash_value] = True
                elif isinstance(entry, dict):
                    hash_value = str(entry.get("hash", "")).lower()
                    if hash_value in result:
                        result[hash_value] = bool(
                            entry.get("cached")
                            or entry.get("available")
                            or entry.get("status") in ("cached", "found")
                        )
    except Exception as e:
        logger.warning(f"TorBox instant check failed: {e}")

    return result


def tb_add_magnet(api_key: str, info_hash: str) -> dict:
    """Create a TorBox torrent from an info hash."""
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    data = _tb_request("POST", "/torrents/createtorrent", api_key, data={"magnet": magnet})
    if isinstance(data, dict):
        torrent_id = data.get("torrent_id") or data.get("torrentId") or data.get("id") or data.get("Id")
        if torrent_id is not None and "torrent_id" not in data:
            data["torrent_id"] = torrent_id
        return data
    return {"id": data}


def _tb_normalize_file(file_item: dict) -> dict:
    out = dict(file_item)
    if "id" not in out and "Id" in out:
        out["id"] = out.get("Id")
    if "name" not in out and "Name" in out:
        out["name"] = out.get("Name")
    if "size" not in out and "Size" in out:
        out["size"] = out.get("Size")
    if "size" not in out and "bytes" in out:
        out["size"] = out.get("bytes")
    return out


def _tb_normalize_torrent(torrent: dict) -> dict:
    out = dict(torrent)
    mapping = {
        "downloadState": "download_state",
        "downloadFinished": "download_finished",
        "downloadPresent": "download_present",
        "downloadSpeed": "download_speed",
        "uploadSpeed": "upload_speed",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
        "expiresAt": "expires_at",
        "inactiveCheck": "inactive_check",
        "torrentFile": "torrent_file",
        "authId": "auth_id",
    }
    for src, dst in mapping.items():
        if dst not in out and src in out:
            out[dst] = out.get(src)

    if "id" not in out and "Id" in out:
        out["id"] = out.get("Id")

    files = out.get("files") or out.get("Files") or []
    if isinstance(files, list):
        out["files"] = [_tb_normalize_file(f) for f in files if isinstance(f, dict)]

    return out


def _tb_pick_torrent(payload, torrent_id: Union[int, str]) -> Optional[dict]:
    if isinstance(payload, dict):
        candidates = (
            payload.get("torrents")
            or payload.get("items")
            or payload.get("data")
            or payload.get("Data")
        )
        if isinstance(candidates, list):
            for item in candidates:
                if isinstance(item, dict) and str(item.get("id") or item.get("Id")) == str(torrent_id):
                    return item
            if len(candidates) == 1 and isinstance(candidates[0], dict):
                return candidates[0]

        if any(k in payload for k in ("downloadState", "download_state", "downloadFinished", "download_finished", "files", "Files")):
            return payload

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and str(item.get("id") or item.get("Id")) == str(torrent_id):
                return item
        if len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]

    return None



def tb_get_torrent_info(api_key: str, torrent_id: Union[int, str]) -> dict:
    """Fetch a TorBox torrent from the user's list."""
    try:
        # #region debug-point D:tb-torrent-info-entry
        _debug_report("D", "app/services/debrid.py:tb_get_torrent_info", "tb_get_torrent_info entry", {"torrent_id": str(torrent_id)})
        # #endregion
        data = _tb_request("GET", "/torrents/mylist", api_key, params={"id": torrent_id})
        picked = _tb_pick_torrent(data, torrent_id)
        if isinstance(picked, dict):
            normalized = _tb_normalize_torrent(picked)
            # #region debug-point D:tb-torrent-info-dict
            _debug_report("D", "app/services/debrid.py:tb_get_torrent_info", "tb_get_torrent_info dict payload", {"torrent_id": str(torrent_id), "keys": sorted(list(normalized.keys()))[:20], "download_state": str(normalized.get("download_state", "")), "download_finished": bool(normalized.get("download_finished"))})
            # #endregion
            return normalized
    except Exception as e:
        # #region debug-point D:tb-torrent-info-fallback
        _debug_report("D", "app/services/debrid.py:tb_get_torrent_info", "tb_get_torrent_info primary request failed", {"torrent_id": str(torrent_id), "error": str(e)})
        # #endregion
        data = _tb_request("GET", "/torrents/mylist", api_key)
        picked = _tb_pick_torrent(data, torrent_id)
        if isinstance(picked, dict):
            return _tb_normalize_torrent(picked)

    # #region debug-point D:tb-torrent-info-miss
    _debug_report("D", "app/services/debrid.py:tb_get_torrent_info", "tb_get_torrent_info not found", {"torrent_id": str(torrent_id)})
    # #endregion
    raise Exception(f"TorBox torrent {torrent_id} not found")


def tb_request_download(api_key: str, torrent_id: Union[int, str], file_id: Union[int, str] = 0) -> str:
    """Request a TorBox download link for a file in a torrent."""
    _check_rate_limit("tb")
    # #region debug-point D:tb-request-download-entry
    _debug_report("D", "app/services/debrid.py:tb_request_download", "tb_request_download entry", {"torrent_id": str(torrent_id), "file_id": str(file_id)})
    # #endregion
    r = requests.get(
        f"{TB_BASE}/torrents/requestdl",
        headers=_tb_headers(api_key),
        params={
            "token": api_key,
            "torrent_id": torrent_id,
            "file_id": file_id,
            "zip_link": "false",
            "redirect": "false",
        },
        timeout=15,
    )
    r.raise_for_status()

    try:
        payload = r.json()
    except ValueError:
        # #region debug-point D:tb-request-download-text
        _debug_report("D", "app/services/debrid.py:tb_request_download", "tb_request_download text payload", {"torrent_id": str(torrent_id), "file_id": str(file_id), "status_code": r.status_code, "text_sample": r.text[:200]})
        # #endregion
        return r.text.strip()

    data = _tb_extract_data(payload)
    # #region debug-point D:tb-request-download-json
    _debug_report("D", "app/services/debrid.py:tb_request_download", "tb_request_download json payload", {"torrent_id": str(torrent_id), "file_id": str(file_id), "status_code": r.status_code, "payload_type": type(data).__name__})
    # #endregion
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return data.get("url") or data.get("link") or ""
    return ""


def tb_delete_torrent(api_key: str, torrent_id: Union[int, str]) -> None:
    """Delete a torrent from TorBox."""
    try:
        normalized_id: Union[int, str] = int(torrent_id)
    except (TypeError, ValueError):
        normalized_id = torrent_id

    _tb_request(
        "POST",
        "/torrents/controltorrent",
        api_key,
        json={"torrent_id": normalized_id, "operation": "delete"},
    )


# ---------------------------------------------------------------------------
# Real-Debrid instant availability
# ---------------------------------------------------------------------------

def check_instant_availability(api_key: str, hashes: list[str]) -> dict[str, bool]:
    """Check which hashes are instantly available (cached) on Real-Debrid.

    Returns a dict of {hash: True/False}.
    """
    if not hashes:
        return {}

    result = {}
    # RD accepts up to ~100 hashes per request via path segments
    batch_size = 50
    for i in range(0, len(hashes), batch_size):
        batch = hashes[i:i + batch_size]
        # Normalize hashes to lowercase for consistency
        batch = [h.lower() for h in batch]
        hash_path = "/".join(batch)
        try:
            _check_rate_limit("rd")
            r = requests.get(
                f"{RD_BASE}/torrents/instantAvailability/{hash_path}",
                headers=_rd_headers(api_key),
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                for h in batch:
                    # RD returns the hash as key with hosters as value
                    entry = data.get(h) or {}
                    # If there are any cached file variants, it's instant
                    if isinstance(entry, dict) and entry.get("rd"):
                        result[h] = True
                    elif isinstance(entry, list) and len(entry) > 0:
                        result[h] = True
                    else:
                        result[h] = False
            else:
                for h in batch:
                    result[h] = False
        except Exception as e:
            logger.warning(f"Instant availability check failed: {e}")
            for h in batch:
                result[h] = False

    return result


# ---------------------------------------------------------------------------
# Real-Debrid torrent / magnet operations
# ---------------------------------------------------------------------------

def add_magnet(api_key: str, info_hash: str) -> dict:
    """Add a magnet link to Real-Debrid."""
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    try:
        _check_rate_limit("rd")
        r = requests.post(
            f"{RD_BASE}/torrents/addMagnet",
            headers=_rd_headers(api_key),
            data={"magnet": magnet},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid Real-Debrid API key")
        raise


def select_files(api_key: str, torrent_id: str, file_ids: str = "all") -> None:
    """Select files to download from a torrent."""
    try:
        _check_rate_limit("rd")
        r = requests.post(
            f"{RD_BASE}/torrents/selectFiles/{torrent_id}",
            headers=_rd_headers(api_key),
            data={"files": file_ids},
            timeout=15,
        )
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid Real-Debrid API key")
        raise


def get_torrent_info(api_key: str, torrent_id: str) -> dict:
    """Get torrent status and links."""
    try:
        _check_rate_limit("rd")
        # #region debug-point B:rd-torrent-info-entry
        _debug_report("B", "app/services/debrid.py:get_torrent_info", "rd get_torrent_info entry", {"torrent_id": str(torrent_id)})
        # #endregion
        r = requests.get(
            f"{RD_BASE}/torrents/info/{torrent_id}",
            headers=_rd_headers(api_key),
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
        # #region debug-point B:rd-torrent-info-success
        _debug_report("B", "app/services/debrid.py:get_torrent_info", "rd get_torrent_info success", {"torrent_id": str(torrent_id), "status_code": r.status_code, "status": str(payload.get("status", "")), "progress": payload.get("progress"), "links_count": len(payload.get("links", []) or [])})
        # #endregion
        return payload
    except requests.exceptions.HTTPError as e:
        # #region debug-point B:rd-torrent-info-http-error
        _debug_report("B", "app/services/debrid.py:get_torrent_info", "rd get_torrent_info http error", {"torrent_id": str(torrent_id), "status_code": getattr(e.response, "status_code", None), "body_sample": (e.response.text[:200] if getattr(e, "response", None) is not None and getattr(e.response, "text", None) else "")})
        # #endregion
        if r.status_code == 401:
            raise DebridAuthError("Invalid Real-Debrid API key")
        raise


def unrestrict_link(api_key: str, link: str) -> dict:
    """Unrestrict a hoster link to get a direct download URL."""
    try:
        _check_rate_limit("rd")
        # #region debug-point C:rd-unrestrict-entry
        _debug_report("C", "app/services/debrid.py:unrestrict_link", "rd unrestrict entry", {"link_prefix": link[:120]})
        # #endregion
        r = requests.post(
            f"{RD_BASE}/unrestrict/link",
            headers=_rd_headers(api_key),
            data={"link": link},
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
        # #region debug-point C:rd-unrestrict-success
        _debug_report("C", "app/services/debrid.py:unrestrict_link", "rd unrestrict success", {"status_code": r.status_code, "has_download": bool(payload.get("download")), "filename": payload.get("filename", "")[:120]})
        # #endregion
        return payload
    except requests.exceptions.HTTPError as e:
        # #region debug-point C:rd-unrestrict-http-error
        _debug_report("C", "app/services/debrid.py:unrestrict_link", "rd unrestrict http error", {"status_code": getattr(e.response, "status_code", None), "body_sample": (e.response.text[:200] if getattr(e, "response", None) is not None and getattr(e.response, "text", None) else ""), "link_prefix": link[:120]})
        # #endregion
        if r.status_code == 401:
            raise DebridAuthError("Invalid Real-Debrid API key")
        raise


def get_rd_downloads(api_key: str, page: int = 1, limit: int = 50) -> list[dict]:
    """Get user's download history from Real-Debrid."""
    try:
        _check_rate_limit("rd")
        r = requests.get(
            f"{RD_BASE}/downloads",
            headers=_rd_headers(api_key),
            params={"page": page, "limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid Real-Debrid API key")
        raise


def get_rd_torrents(api_key: str, page: int = 1, limit: int = 50) -> list[dict]:
    """Get user's torrent list from Real-Debrid."""
    try:
        _check_rate_limit("rd")
        r = requests.get(
            f"{RD_BASE}/torrents",
            headers=_rd_headers(api_key),
            params={"page": page, "limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid Real-Debrid API key")
        raise


def delete_rd_torrent(api_key: str, torrent_id: str) -> None:
    """Delete a torrent from Real-Debrid."""
    try:
        _check_rate_limit("rd")
        r = requests.delete(
            f"{RD_BASE}/torrents/delete/{torrent_id}",
            headers=_rd_headers(api_key),
            timeout=15,
        )
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid Real-Debrid API key")
        raise


# ---------------------------------------------------------------------------
# AllDebrid API functions (v4 - latest)
# ---------------------------------------------------------------------------

def ad_get_user(api_key: str) -> dict:
    """Get AllDebrid account info."""
    try:
        _check_rate_limit("ad")
        r = requests.get(
            f"{AD_BASE}/user",
            headers=_ad_headers(api_key),
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "error":
            raise DebridAuthError(data.get("error", {}).get("message", "AllDebrid error"))
        return data.get("data", {}).get("user", {})
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid or expired AllDebrid API key")
        raise DebridAuthError(f"AllDebrid auth failed: {str(e)}")
    except Exception as e:
        raise DebridAuthError(f"AllDebrid connection failed: {str(e)}")


def ad_add_magnet(api_key: str, info_hash: str) -> dict:
    """Add a magnet link to AllDebrid."""
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    try:
        _check_rate_limit("ad")
        r = requests.post(
            f"{AD_BASE}/magnet/upload",
            headers=_ad_headers(api_key),
            data={"magnets[]": magnet},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "error":
            raise Exception(data.get("error", {}).get("message", "AllDebrid error"))
        magnets = data.get("data", {}).get("magnets", [])
        if magnets:
            return magnets[0]
        return {}
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid AllDebrid API key")
        raise


def ad_get_magnet_status(api_key: str, magnet_id: str) -> dict:
    """Get AllDebrid magnet status."""
    try:
        _check_rate_limit("ad")
        # #region debug-point E:ad-magnet-status-entry
        _debug_report("E", "app/services/debrid.py:ad_get_magnet_status", "ad_get_magnet_status entry", {"magnet_id": str(magnet_id)})
        # #endregion
        r = requests.post(
            f"{AD_BASE_V41}/magnet/status",
            headers=_ad_headers(api_key),
            data={"id": magnet_id},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        # #region debug-point E:ad-magnet-status-success
        _debug_report("E", "app/services/debrid.py:ad_get_magnet_status", "ad_get_magnet_status success", {"magnet_id": str(magnet_id), "status_code": r.status_code, "top_level_keys": sorted(list(data.keys()))[:20], "ad_status": str(data.get("status", ""))})
        # #endregion
        if data.get("status") == "error":
            raise Exception(data.get("error", {}).get("message", "AllDebrid error"))
        magnets = data.get("data", {}).get("magnets", [])
        if isinstance(magnets, list) and len(magnets) > 0:
            return magnets[0]
        if isinstance(magnets, dict):
            return magnets
        return {}
    except requests.exceptions.HTTPError as e:
        # #region debug-point E:ad-magnet-status-http-error
        _debug_report("E", "app/services/debrid.py:ad_get_magnet_status", "ad_get_magnet_status http error", {"magnet_id": str(magnet_id), "status_code": getattr(e.response, "status_code", None), "body_sample": (e.response.text[:200] if getattr(e, "response", None) is not None and getattr(e.response, "text", None) else "")})
        # #endregion
        if r.status_code == 401:
            raise DebridAuthError("Invalid AllDebrid API key")
        raise


def _ad_flatten_file_tree(entries, prefix: str = "") -> list[dict]:
    out: list[dict] = []

    if isinstance(entries, dict):
        entries = entries.get("files") or entries.get("e") or entries.get("entries") or entries.get("children") or []

    if not isinstance(entries, list):
        return out

    for item in entries:
        if not isinstance(item, dict):
            continue

        name = item.get("n") or item.get("filename") or item.get("name") or ""
        link = item.get("l") or item.get("link") or item.get("url") or ""
        size = item.get("s") or item.get("size") or item.get("bytes") or 0

        path = prefix
        if name:
            path = f"{prefix}/{name}" if prefix else name

        children = item.get("e") or item.get("entries") or item.get("files") or item.get("children")
        if children:
            out.extend(_ad_flatten_file_tree(children, path))
            continue

        if link:
            try:
                size_i = int(size or 0)
            except Exception:
                size_i = 0
            out.append({"filename": path or name, "size": size_i, "link": link})

    return out


def ad_get_magnet_files(api_key: str, magnet_id: str) -> list[dict]:
    try:
        _check_rate_limit("ad")
        r = requests.post(
            f"{AD_BASE}/magnet/files",
            headers=_ad_headers(api_key),
            data=[("id[]", magnet_id)],
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("status") == "error":
            raise Exception(payload.get("error", {}).get("message", "AllDebrid error"))

        magnets = payload.get("data", {}).get("magnets")
        magnet = None
        if isinstance(magnets, list):
            for m in magnets:
                if str(m.get("id")) == str(magnet_id):
                    magnet = m
                    break
            if magnet is None and magnets:
                magnet = magnets[0]
        elif isinstance(magnets, dict):
            magnet = magnets.get(str(magnet_id)) or magnets.get(magnet_id) or magnets

        if isinstance(magnet, dict):
            file_tree = magnet.get("files") or magnet.get("links") or magnet
            return _ad_flatten_file_tree(file_tree)

        if isinstance(payload.get("data", {}), dict):
            return _ad_flatten_file_tree(payload.get("data", {}))

        return []
    except requests.exceptions.HTTPError as e:
        if getattr(e.response, "status_code", None) == 401:
            raise DebridAuthError("Invalid AllDebrid API key")
        raise


def ad_unrestrict_link(api_key: str, link: str) -> dict:
    """Unrestrict a link via AllDebrid."""
    try:
        _check_rate_limit("ad")
        # #region debug-point E:ad-unrestrict-entry
        _debug_report("E", "app/services/debrid.py:ad_unrestrict_link", "ad_unrestrict entry", {"link_prefix": link[:120]})
        # #endregion
        r = requests.post(
            f"{AD_BASE}/link/unlock",
            headers=_ad_headers(api_key),
            data={"link": link},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        # #region debug-point E:ad-unrestrict-success
        _debug_report("E", "app/services/debrid.py:ad_unrestrict_link", "ad_unrestrict success", {"status_code": r.status_code, "top_level_keys": sorted(list(data.keys()))[:20], "ad_status": str(data.get("status", ""))})
        # #endregion
        if data.get("status") == "error":
            raise Exception(data.get("error", {}).get("message", "AllDebrid error"))
        return data.get("data", {})
    except requests.exceptions.HTTPError as e:
        # #region debug-point E:ad-unrestrict-http-error
        _debug_report("E", "app/services/debrid.py:ad_unrestrict_link", "ad_unrestrict http error", {"status_code": getattr(e.response, "status_code", None), "body_sample": (e.response.text[:200] if getattr(e, "response", None) is not None and getattr(e.response, "text", None) else ""), "link_prefix": link[:120]})
        # #endregion
        if r.status_code == 401:
            raise DebridAuthError("Invalid AllDebrid API key")
        raise


def ad_check_instant(api_key: str, hashes: list[str]) -> dict[str, bool]:
    """Check AllDebrid instant availability."""
    if not hashes:
        return {}
    
    result = {}  # FIXED: Initialize result dict before using it
    try:
        data = {"magnets": hashes}
        _check_rate_limit("ad")
        r = requests.post(
            f"{AD_BASE}/magnet/instant",
            headers=_ad_headers(api_key),
            data=data,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            for m in data.get("data", {}).get("magnets", []):
                if m.get("ready"):
                    h = m.get("hash", "").lower()
                    if h:
                        result[h] = True
                    # Clean up: delete after checking
                    try:
                        ad_delete_magnet(api_key, str(m.get("id", "")))
                    except Exception as e:
                        logger.debug(f"Failed to delete AllDebrid magnet {m.get('id')}: {e}")
                else:
                    mid = str(m.get("id", ""))
                    if mid:
                        try:
                            ad_delete_magnet(api_key, mid)
                        except Exception as e:
                            logger.debug(f"Failed to delete AllDebrid magnet {mid}: {e}")
            
            # Build result dict with hash -> availability mapping
            magnets = data.get("data", {}).get("magnets", [])
            for m in magnets:
                h = m.get("hash", m.get("magnet", "")).lower()
                if h and h not in result:  # Don't overwrite ready magnets
                    result[h] = m.get("instant", False)
    except requests.exceptions.HTTPError as e:
        logger.warning(f"AllDebrid instant check failed: {e}")
        if r.status_code == 401:
            raise DebridAuthError("Invalid AllDebrid API key")
    except Exception as e:
        logger.warning(f"AllDebrid instant check failed: {e}")
    
    return result


def ad_delete_magnet(api_key: str, magnet_id: str) -> None:
    """Delete a magnet from AllDebrid."""
    try:
        _check_rate_limit("ad")
        r = requests.post(
            f"{AD_BASE}/magnet/delete",
            headers=_ad_headers(api_key),
            data={"id": magnet_id},
            timeout=15,
        )
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 401:
            raise DebridAuthError("Invalid AllDebrid API key")
        logger.warning(f"Failed to delete AllDebrid magnet {magnet_id}: {e}")


# ---------------------------------------------------------------------------
# Download management - download from debrid to Pi
# ---------------------------------------------------------------------------

def _get_category_from_filename(filename: str) -> str:
    """Determine media category from file extension."""
    ext = os.path.splitext(filename)[1].lower()
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.m2ts', '.mts', '.wmv', '.flv', '.3gp', '.mpg', '.mpeg', '.mpe', '.vob'}
    music_exts = {'.mp3', '.flac', '.wav', '.m4a', '.ogg', '.aac'}
    book_exts = {'.pdf', '.epub', '.mobi', '.cbz', '.cbr'}

    if ext in video_exts:
        return "movies"
    elif ext in music_exts:
        return "music"
    elif ext in book_exts:
        return "books"
    return "files"


def _sanitize_filename(name: str, max_length: int = 200) -> str:
    """Remove invalid filesystem characters and ensure cross-platform compatibility."""
    # Remove invalid characters
    name = re.sub(r'[<>:"/\\|?*\x00]', '_', name)
    
    # Remove null bytes
    name = name.replace('\0', '')
    
    # Handle Unicode safely - encode/decode to ensure filesystem compatibility
    try:
        name = name.encode('utf-8', errors='ignore').decode('utf-8')
    except Exception:
        pass
    
    # Truncate to max length (accounting for extension)
    if len(name) > max_length:
        name = name[:max_length]
    
    # Remove trailing dots/spaces
    name = name.strip('. ')
    
    # Handle Windows reserved names
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM9', 'LPT1', 'LPT9'}
    if name.upper() in reserved:
        name = f"_{name}"
    
    return name


def is_safe_external_url(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(str(url))
        if p.scheme not in ("http", "https"):
            return False
        host = p.hostname
        if not host:
            return False
        if host in ("localhost",):
            return False
        if host.endswith(".local"):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return False
            return True
        except ValueError:
            pass

        addrs = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
        for _family, _type, _proto, _canonname, sockaddr in addrs:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                    return False
            except ValueError:
                return False
        return True
    except Exception:
        return False


def safe_head(url: str, timeout: int = 10, max_redirects: int = 3) -> requests.Response:
    if not is_safe_external_url(url):
        raise ValueError("Unsafe URL")
    current = url
    for _ in range(max_redirects + 1):
        r = requests.head(current, allow_redirects=False, timeout=timeout)
        if r.is_redirect or r.is_permanent_redirect:
            loc = r.headers.get("Location") or r.headers.get("location") or ""
            if not loc:
                return r
            nxt = urllib.parse.urljoin(current, loc)
            if not is_safe_external_url(nxt):
                raise ValueError("Unsafe redirect URL")
            current = nxt
            continue
        return r
    return r


def clean_media_filename(raw_filename: str, title: str = "",
                          year: str = "", media_type: str = "movie",
                          season: int = 0, episode: int = 0) -> str:
    """Produce a clean filename from RD's raw release name and search metadata.

    Movies  → "Title (Year).ext"
    Series  → "Title S01E01.ext"

    Falls back to basic cleanup if metadata is missing.
    """
    ext = os.path.splitext(raw_filename)[1].lower() or ".mkv"

    # If we have title metadata, use it for a clean name
    if title:
        clean = title.strip()
        if media_type == "series" and season and episode:
            clean = f"{clean} S{int(season):02d}E{int(episode):02d}"
        elif year:
            clean = f"{clean} ({year})"
        return _sanitize_filename(clean) + ext

    # Fallback: extract title from the raw filename
    name = os.path.splitext(raw_filename)[0]

    # Remove common torrent tags
    # Match year first to separate title from tags
    year_match = re.search(r'[\.\s\-_\(]*((?:19|20)\d{2})[\.\s\-_\)]*', name)
    if year_match:
        title_part = name[:year_match.start()].strip()
        found_year = year_match.group(1)
    else:
        # Try to remove everything after first quality/source tag
        tag_match = re.search(
            r'[\.\s\-_](?:2160p|1080p|720p|480p|4K|BluRay|WEB-DL|WEBRip|'
            r'HDRip|BRRip|DVDRip|HDTV|RERIP|REMUX|x264|x265|h\.?264|'
            r'h\.?265|HEVC|AAC|DTS|TrueHD|Atmos|HDR|DV|10bit|SDR)',
            name, re.IGNORECASE
        )
        if tag_match:
            title_part = name[:tag_match.start()].strip()
        else:
            title_part = name
        title_part = re.sub(r'^\[.*?\]\s*', '', title_part).strip()
        title_part = re.sub(r'\s{2,}', ' ', title_part).strip()
        found_year = None

    if not title_part:
        return _sanitize_filename(raw_filename)

    if found_year:
        clean = f"{title_part} ({found_year})"
    else:
        clean = title_part

    return _sanitize_filename(clean) + ext


def download_to_pi(api_key: str, download_url: str, filename: str,
                   category: str = "auto", is_show: bool = False) -> str:
    """Download a file from Real-Debrid to the Pi's media library.

    Returns the download_id for tracking progress.
    """
    from app.routers import media
    raw_filename = str(filename or "").strip()

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
            "audio/mpeg": ".mp3",
            "audio/flac": ".flac",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/aac": ".aac",
        }
        return mapping.get(ct, "")

    if raw_filename and not os.path.splitext(raw_filename)[1]:
        try:
            r = safe_head(download_url, timeout=10)
            cd = r.headers.get("Content-Disposition") or r.headers.get("content-disposition") or ""
            ct = r.headers.get("Content-Type") or r.headers.get("content-type") or ""
            header_name = _cd_filename(cd)
            if header_name:
                raw_filename = header_name
            if raw_filename and not os.path.splitext(raw_filename)[1]:
                ext = _ext_from_content_type(ct)
                if ext:
                    raw_filename = raw_filename + ext
        except Exception:
            pass

    filename = _sanitize_filename(raw_filename or "download")

    if category == "auto":
        if is_show:
            category = "shows"
        else:
            category = _get_category_from_filename(filename)

    # Build destination path
    base_dir = media.BASE_DIR
    if category in ("movies", "shows"):
        folder_name = os.path.splitext(filename)[0]
        dest_dir = os.path.join(base_dir, category, folder_name)
    else:
        dest_dir = os.path.join(base_dir, category)

    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)

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

    t = threading.Thread(target=_download_worker, args=(download_id, download_url, dest_path, category), daemon=True)
    t.start()

    return download_id


def _download_worker(download_id: str, url: str, dest_path: str, category: str):
    """Background worker that downloads a file with retry logic and updates progress."""
    from app.routers import media

    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            r = requests.get(url, stream=True, timeout=30)
            r.raise_for_status()

            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            last_update = time.time()
            last_bytes = 0

            with _downloads_lock:
                if download_id in _downloads:
                    _downloads[download_id]["size_total"] = total

            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1000):
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

            try:
                web_path = f"/data/{os.path.relpath(dest_path, media.BASE_DIR).replace(os.sep, '/')}"
                st = os.stat(dest_path)
                folder = os.path.relpath(os.path.dirname(dest_path), os.path.join(media.BASE_DIR, category)).replace(os.sep, '/')
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
            return  # Success, exit retries

        except requests.exceptions.Timeout:
            logger.warning(f"Download timeout (attempt {attempt + 1}/{max_retries}): {download_id}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                error_msg = "Download failed: Request timeout after multiple retries"
                with _downloads_lock:
                    if download_id in _downloads:
                        _downloads[download_id].update({
                            "status": "failed",
                            "error": error_msg,
                        })
                logger.error(f"{error_msg} for {download_id}")
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Download connection error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                error_msg = f"Download failed: Connection error - {str(e)}"
                with _downloads_lock:
                    if download_id in _downloads:
                        _downloads[download_id].update({
                            "status": "failed",
                            "error": error_msg,
                        })
                logger.error(f"{error_msg} for {download_id}")
        except requests.exceptions.HTTPError as e:
            status_code = getattr(e.response, 'status_code', None)
            if status_code in (401, 403):
                error_msg = f"Download failed: Link expired or access denied (HTTP {status_code}). Try refreshing the link or changing Debrid service."
            elif status_code == 404:
                error_msg = "Download failed: File not found on Debrid server (HTTP 404). Link might have been deleted."
            else:
                error_msg = f"Download failed: Debrid server error (HTTP {status_code})"

            logger.error(f"{error_msg} for {download_id}")
            with _downloads_lock:
                if download_id in _downloads:
                    _downloads[download_id].update({
                        "status": "failed",
                        "error": error_msg,
                    })
            return # Don't retry auth/not-found errors
        except Exception as e:
            logger.error(f"Download failed for {download_id}: {e}")
            with _downloads_lock:
                if download_id in _downloads:
                    _downloads[download_id].update({
                        "status": "failed",
                        "error": f"Internal Error: {str(e)}",
                    })
            return


def get_download_status(download_id: str) -> Optional[dict]:
    with _downloads_lock:
        return _downloads.get(download_id, {}).copy() if download_id in _downloads else None


def get_all_downloads() -> list[dict]:
    with _downloads_lock:
        return [d.copy() for d in _downloads.values()]


def cancel_download(download_id: str) -> bool:
    with _downloads_lock:
        if download_id in _downloads:
            _downloads[download_id]["status"] = "cancelled"
            return True
    return False


def clear_completed() -> int:
    with _downloads_lock:
        to_remove = [k for k, v in _downloads.items() if v["status"] in ("completed", "failed", "cancelled")]
        for k in to_remove:
            del _downloads[k]
        return len(to_remove)
