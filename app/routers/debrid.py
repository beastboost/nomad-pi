"""Debrid router with full TorBox + RD + AD support."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import database
from app.routers.auth import get_current_user_id, get_current_admin
from app.services import debrid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/debrid", tags=["debrid"])

class KeyRequest(BaseModel):
    api_key: str

# RD Key
@router.post("/settings/key")
def set_rd_key(req: KeyRequest, admin: dict = Depends(get_current_admin)):
    try: user = debrid.get_rd_user(req.api_key)
    except Exception as e: raise HTTPException(400, f"Invalid RD key: {e}")
    database.set_setting("rd_api_key", req.api_key)
    return {"status": "ok", "user": user}

@router.get("/settings/key")
def get_rd_key(user_id: int = Depends(get_current_user_id)):
    key = database.get_setting("rd_api_key")
    if not key: return {"configured": False}
    try: return {"configured": True, "user": debrid.get_rd_user(key)}
    except: return {"configured": True, "valid": False}

@router.delete("/settings/key")
def remove_rd_key(admin: dict = Depends(get_current_admin)):
    database.set_setting("rd_api_key", ""); return {"status": "ok"}

# AD Key
@router.post("/settings/ad-key")
def set_ad_key(req: KeyRequest, admin: dict = Depends(get_current_admin)):
    try: user = debrid.ad_get_user(req.api_key)
    except Exception as e: raise HTTPException(400, f"Invalid AD key: {e}")
    database.set_setting("ad_api_key", req.api_key)
    return {"status": "ok", "user": user}

@router.get("/settings/ad-key")
def get_ad_key(user_id: int = Depends(get_current_user_id)):
    key = database.get_setting("ad_api_key")
    if not key: return {"configured": False}
    try: return {"configured": True, "user": debrid.ad_get_user(key)}
    except: return {"configured": True, "valid": False}

@router.delete("/settings/ad-key")
def remove_ad_key(admin: dict = Depends(get_current_admin)):
    database.set_setting("ad_api_key", ""); return {"status": "ok"}

# TorBox Key (Full)
@router.post("/settings/tb-key")
def set_tb_key(req: KeyRequest, admin: dict = Depends(get_current_admin)):
    try: user = debrid.tb_get_user(req.api_key)
    except Exception as e: raise HTTPException(400, f"Invalid TorBox key: {e}")
    database.set_setting("tb_api_key", req.api_key)
    return {"status": "ok", "user": user}

@router.get("/settings/tb-key")
def get_tb_key(user_id: int = Depends(get_current_user_id)):
    key = database.get_setting("tb_api_key")
    if not key: return {"configured": False}
    try: return {"configured": True, "user": debrid.tb_get_user(key)}
    except: return {"configured": True, "valid": False}

@router.delete("/settings/tb-key")
def remove_tb_key(admin: dict = Depends(get_current_admin)):
    database.set_setting("tb_api_key", ""); return {"status": "ok"}

# Provider

def _get_active_provider():
    p = database.get_setting("debrid_provider") or "rd"
    if p == "tb" and database.get_setting("tb_api_key"): return "tb", database.get_setting("tb_api_key")
    if p == "ad" and database.get_setting("ad_api_key"): return "ad", database.get_setting("ad_api_key")
    if database.get_setting("rd_api_key"): return "rd", database.get_setting("rd_api_key")
    if database.get_setting("ad_api_key"): return "ad", database.get_setting("ad_api_key")
    if database.get_setting("tb_api_key"): return "tb", database.get_setting("tb_api_key")
    return "rd", ""

@router.post("/settings/provider")
def set_provider(provider: str = Query(...), user_id: int = Depends(get_current_user_id)):
    if provider not in ("rd", "ad", "tb"): raise HTTPException(400, "Invalid provider")
    database.set_setting("debrid_provider", provider)
    return {"status": "ok", "provider": provider}

@router.get("/settings/provider")
def get_provider(user_id: int = Depends(get_current_user_id)):
    return {"provider": database.get_setting("debrid_provider") or "rd"}

# Core operations with provider dispatch
def _require_key():
    p, k = _get_active_provider()
    if not k: raise HTTPException(400, "No debrid key configured")
    return p, k

@router.post("/magnet")
def add_magnet(req: dict, user_id: int = Depends(get_current_user_id)):
    p, k = _require_key()
    try:
        if p == "tb": res = debrid.tb_add_magnet(k, req.get("info_hash"))
        elif p == "ad": res = debrid.ad_add_magnet(k, req.get("info_hash"))
        else: res = debrid.add_magnet(k, req.get("info_hash"))
        return {"status": "ok", "result": res}
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/unrestrict")
def unrestrict(link: str = Query(...), user_id: int = Depends(get_current_user_id)):
    p, k = _require_key()
    try:
        if p == "tb": res = debrid.tb_unrestrict(k, link)
        elif p == "ad": res = debrid.ad_unrestrict_link(k, link)
        else: res = debrid.unrestrict_link(k, link)
        return {"status": "ok", "result": res}
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/instant")
def instant(req: dict, user_id: int = Depends(get_current_user_id)):
    p, k = _require_key()
    hashes = req.get("hashes", [])
    try:
        if p == "tb": res = debrid.tb_check_cached(k, hashes)
        elif p == "ad": res = debrid.ad_check_instant(k, hashes)
        else: res = debrid.check_instant_availability(k, hashes)
        return {"cached": res}
    except: return {"cached": {}}

print("[debrid] TorBox fully merged to main")