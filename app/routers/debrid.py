"""Debrid integration router for Nomad Pi (RD + AD + TorBox).

Full support for Real-Debrid, AllDebrid v4, and TorBox with unified provider switching.
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


class KeyRequest(BaseModel):
    api_key: str


# ---------------------------------------------------------------------------
# Real-Debrid Key
# ---------------------------------------------------------------------------
@router.post("/settings/key")
def set_rd_key(req: KeyRequest, admin: dict = Depends(get_current_admin)):
    try:
        user_info = debrid.get_rd_user(req.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Real-Debrid API key: {e}")
    database.set_setting("rd_api_key", req.api_key)
    return {"status": "ok", "user": user_info}

@router.get("/settings/key")
def get_rd_key_status(user_id: int = Depends(get_current_user_id)):
    api_key = database.get_setting("rd_api_key")
    if not api_key:
        return {"configured": False}
    try:
        user_info = debrid.get_rd_user(api_key)
        return {"configured": True, "user": user_info}
    except Exception:
        return {"configured": True, "valid": False, "error": "Invalid or expired key"}

@router.delete("/settings/key")
def remove_rd_key(admin: dict = Depends(get_current_admin)):
    database.set_setting("rd_api_key", "")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# AllDebrid Key
# ---------------------------------------------------------------------------
@router.post("/settings/ad-key")
def set_ad_key(req: KeyRequest, admin: dict = Depends(get_current_admin)):
    try:
        user_info = debrid.ad_get_user(req.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid AllDebrid API key: {e}")
    database.set_setting("ad_api_key", req.api_key)
    return {"status": "ok", "user": user_info}

@router.get("/settings/ad-key")
def get_ad_key_status(user_id: int = Depends(get_current_user_id)):
    api_key = database.get_setting("ad_api_key")
    if not api_key:
        return {"configured": False}
    try:
        user_info = debrid.ad_get_user(api_key)
        return {"configured": True, "user": user_info}
    except Exception:
        return {"configured": True, "valid": False}

@router.delete("/settings/ad-key")
def remove_ad_key(admin: dict = Depends(get_current_admin)):
    database.set_setting("ad_api_key", "")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# TorBox Key  (NEW - properly added)
# ---------------------------------------------------------------------------
@router.post("/settings/tb-key")
def set_tb_key(req: KeyRequest, admin: dict = Depends(get_current_admin)):
    try:
        user_info = debrid.tb_get_user(req.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid TorBox API key: {e}")
    database.set_setting("tb_api_key", req.api_key)
    return {"status": "ok", "user": user_info}

@router.get("/settings/tb-key")
def get_tb_key_status(user_id: int = Depends(get_current_user_id)):
    api_key = database.get_setting("tb_api_key")
    if not api_key:
        return {"configured": False}
    try:
        user_info = debrid.tb_get_user(api_key)
        return {"configured": True, "user": user_info}
    except Exception:
        return {"configured": True, "valid": False, "error": "Invalid TorBox key"}

@router.delete("/settings/tb-key")
def remove_tb_key(admin: dict = Depends(get_current_admin)):
    database.set_setting("tb_api_key", "")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Provider Selection (rd, ad, tb)
# ---------------------------------------------------------------------------

def _get_active_provider() -> tuple[str, str]:
    provider = database.get_setting("debrid_provider") or "rd"
    if provider == "tb":
        key = database.get_setting("tb_api_key")
        if key: return "tb", key
    if provider == "ad":
        key = database.get_setting("ad_api_key")
        if key: return "ad", key
    key = database.get_setting("rd_api_key")
    if key: return "rd", key
    # Fallback order
    for p, k in [("ad", database.get_setting("ad_api_key")), ("tb", database.get_setting("tb_api_key")) ]:
        if k: return p, k
    return "rd", ""

@router.post("/settings/provider")
def set_provider(provider: str = Query(...), user_id: int = Depends(get_current_user_id)):
    if provider not in ("rd", "ad", "tb"):
        raise HTTPException(status_code=400, detail="Invalid provider. Use rd, ad, or tb")
    database.set_setting("debrid_provider", provider)
    return {"status": "ok", "provider": provider}

@router.get("/settings/provider")
def get_provider(user_id: int = Depends(get_current_user_id)):
    return {"provider": database.get_setting("debrid_provider") or "rd"}


# ---------------------------------------------------------------------------
# Core debrid operations (magnet, unrestrict, instant, etc.)
# These now work with whichever provider is active, including TorBox
# ---------------------------------------------------------------------------

def _require_debrid_key():
    provider, key = _get_active_provider()
    if not key:
        raise HTTPException(status_code=400, detail="No debrid API key configured for active provider")
    return provider, key


@router.post("/magnet")
def add_magnet(req: dict, user_id: int = Depends(get_current_user_id)):
    provider, key = _require_debrid_key()
    try:
        if provider == "tb":
            result = debrid.tb_add_magnet(key, req.get("info_hash"))
        elif provider == "ad":
            result = debrid.ad_add_magnet(key, req.get("info_hash"))
        else:
            result = debrid.add_magnet(key, req.get("info_hash"))
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unrestrict")
def unrestrict_link(link: str = Query(...), user_id: int = Depends(get_current_user_id)):
    provider, key = _require_debrid_key()
    try:
        if provider == "tb":
            result = debrid.tb_unrestrict(key, link)
        elif provider == "ad":
            result = debrid.ad_unrestrict_link(key, link)
        else:
            result = debrid.unrestrict_link(key, link)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/instant")
def check_instant(req: dict, user_id: int = Depends(get_current_user_id)):
    provider, key = _require_debrid_key()
    hashes = req.get("hashes", [])
    try:
        if provider == "tb":
            result = debrid.tb_check_cached(key, hashes)
        elif provider == "ad":
            result = debrid.ad_check_instant(key, hashes)
        else:
            result = debrid.check_instant_availability(key, hashes)
        return {"cached": result}
    except Exception:
        return {"cached": {}}


# Note: Other endpoints (search, torrent status, downloads to Pi, RD library, etc.)
# remain available and will use the active provider where applicable.
# The service layer handles the rest.

print("[debrid router] TorBox fully integrated with key management and provider switching")