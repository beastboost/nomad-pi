__version__ = "2.0.0-debridmastercoder"

import logging
import time
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

RD_BASE = "https://api.real-debrid.com/rest/1.0"
AD_BASE = "https://api.alldebrid.com/v4"
TB_BASE = "https://api.torbox.app/v1"

def _headers(api_key: str, provider: str = "rd") -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}

def _request(method: str, url: str, api_key: str, provider: str = "rd", **kwargs) -> Dict[str, Any]:
    headers = _headers(api_key, provider)
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise Exception(data.get("error", "Unknown error"))
        return data
    except Exception as e:
        logger.error(f"{provider.upper()} API error: {e}")
        raise

def clean_media_filename(raw: str, title: str = "", year: str = "", media_type: str = "movie", season: int = 0, episode: int = 0) -> str:
    if not raw: return f"{title or 'media'}.{year or ''}".strip('.')
    import re
    name = re.sub(r'[^\w\s.-]', '', raw)
    name = re.sub(r'\s+', ' ', name).strip()
    return name or raw

# REAL-DEBRID
def get_rd_user(api_key: str) -> Dict[str, Any]:
    return _request("GET", f"{RD_BASE}/user", api_key, "rd")

def add_magnet(api_key: str, info_hash: str) -> Dict[str, Any]:
    return _request("POST", f"{RD_BASE}/torrents/addMagnet", api_key, "rd", data={"magnet": f"magnet:?xt=urn:btih:{info_hash}"})

def get_torrent_info(api_key: str, torrent_id: str) -> Dict[str, Any]:
    return _request("GET", f"{RD_BASE}/torrents/info/{torrent_id}", api_key, "rd")

def select_files(api_key: str, torrent_id: str, file_ids: str = "all") -> Dict[str, Any]:
    return _request("POST", f"{RD_BASE}/torrents/selectFiles/{torrent_id}", api_key, "rd", data={"files": file_ids})

def unrestrict_link(api_key: str, link: str) -> Dict[str, Any]:
    return _request("POST", f"{RD_BASE}/unrestrict/link", api_key, "rd", data={"link": link})

def check_instant_availability(api_key: str, hashes: List[str]) -> Dict[str, Any]:
    hash_str = "/".join(hashes) if hashes else ""
    try: return _request("GET", f"{RD_BASE}/torrents/instantAvailability/{hash_str}", api_key, "rd")
    except: return {}

def get_rd_downloads(api_key: str, page: int = 1, limit: int = 50) -> List[Dict]:
    return _request("GET", f"{RD_BASE}/downloads", api_key, "rd", params={"page": page, "limit": limit})

def get_rd_torrents(api_key: str, page: int = 1, limit: int = 50) -> List[Dict]:
    return _request("GET", f"{RD_BASE}/torrents", api_key, "rd", params={"page": page, "limit": limit})

def delete_rd_torrent(api_key: str, torrent_id: str) -> None:
    _request("DELETE", f"{RD_BASE}/torrents/delete/{torrent_id}", api_key, "rd")

# ALLDEBRID
def ad_get_user(api_key: str) -> Dict[str, Any]:
    data = _request("GET", f"{AD_BASE}/user", api_key, "ad")
    return data.get("data", data)

def ad_add_magnet(api_key: str, info_hash: str) -> Dict[str, Any]:
    data = _request("POST", f"{AD_BASE}/magnet/upload", api_key, "ad", data={"magnets": [f"magnet:?xt=urn:btih:{info_hash}"]})
    magnets = data.get("data", {}).get("magnets", [])
    return magnets[0] if magnets else {}

def ad_get_magnet_status(api_key: str, magnet_id: str) -> Dict[str, Any]:
    data = _request("GET", f"{AD_BASE}/magnet/status", api_key, "ad", params={"id": magnet_id})
    magnets = data.get("data", {}).get("magnets", [])
    return magnets[0] if magnets else {}

def ad_unrestrict_link(api_key: str, link: str) -> Dict[str, Any]:
    data = _request("POST", f"{AD_BASE}/link/unlock", api_key, "ad", data={"link": link})
    return data.get("data", data)

def ad_check_instant(api_key: str, hashes: List[str]) -> Dict[str, Any]:
    try:
        data = _request("POST", f"{AD_BASE}/magnet/instant", api_key, "ad", data={"magnets": hashes})
        return data.get("data", {})
    except: return {}

# TORBOX (Full)
def tb_get_user(api_key: str) -> Dict[str, Any]:
    try: return _request("GET", f"{TB_BASE}/user/me", api_key, "tb")
    except: return {}

def tb_add_magnet(api_key: str, info_hash: str) -> Dict[str, Any]:
    try: return _request("POST", f"{TB_BASE}/createtorrent", api_key, "tb", data={"magnet": f"magnet:?xt=urn:btih:{info_hash}", "seed": 1})
    except Exception as e: logger.warning(f"TorBox error: {e}"); return {}

def tb_get_status(api_key: str, torrent_id: str) -> Dict[str, Any]:
    try: return _request("GET", f"{TB_BASE}/torrents/{torrent_id}", api_key, "tb")
    except: return {}

def tb_unrestrict(api_key: str, link: str) -> Dict[str, Any]:
    try: return _request("POST", f"{TB_BASE}/requestdl", api_key, "tb", data={"link": link})
    except: return {}

def tb_check_cached(api_key: str, hashes: List[str]) -> Dict[str, Any]:
    try: return _request("POST", f"{TB_BASE}/torrents/checkcached", api_key, "tb", json={"hashes": hashes})
    except: return {}

# UNIFIED
def get_user(provider: str, api_key: str) -> Dict[str, Any]:
    if provider == "rd": return get_rd_user(api_key)
    if provider == "ad": return ad_get_user(api_key)
    if provider == "tb": return tb_get_user(api_key)
    raise ValueError(provider)

def add_magnet_unified(provider: str, api_key: str, info_hash: str) -> Dict[str, Any]:
    if provider == "rd": return add_magnet(api_key, info_hash)
    if provider == "ad": return ad_add_magnet(api_key, info_hash)
    if provider == "tb": return tb_add_magnet(api_key, info_hash)
    raise ValueError(provider)

def unrestrict_unified(provider: str, api_key: str, link: str) -> Dict[str, Any]:
    if provider == "rd": return unrestrict_link(api_key, link)
    if provider == "ad": return ad_unrestrict_link(api_key, link)
    if provider == "tb": return tb_unrestrict(api_key, link)
    raise ValueError(provider)

def check_instant_unified(provider: str, api_key: str, hashes: List[str]) -> Dict[str, Any]:
    if provider == "rd": return check_instant_availability(api_key, hashes)
    if provider == "ad": return ad_check_instant(api_key, hashes)
    if provider == "tb": return tb_check_cached(api_key, hashes)
    return {}

# Local downloads
_downloads: Dict[str, Dict] = {}
def download_to_pi(api_key: str, download_url: str, filename: str, category: str = "auto", is_show: bool = False) -> str:
    did = str(int(time.time()*1000))
    _downloads[did] = {"id":did,"url":download_url,"filename":filename,"category":category,"is_show":is_show,"status":"queued","progress":0,"created_at":time.time()}
    return did

def get_all_downloads(): return list(_downloads.values())
def get_download_status(did): return _downloads.get(did)
def cancel_download(did):
    if did in _downloads: _downloads[did]["status"]="cancelled"; return True
    return False
def clear_completed():
    global _downloads
    b = len(_downloads)
    _downloads = {k:v for k,v in _downloads.items() if v.get("status") not in ("completed","cancelled")}
    return b - len(_downloads)

def search_torrentio(*a,**k): return []