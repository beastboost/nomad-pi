"""Authenticated Library Intelligence API mounted below /api/playback."""

from fastapi import APIRouter, Depends, Query

from app.routers.auth import get_current_user_id
from app.services import library_intelligence as intelligence


router = APIRouter()


@router.get("/intelligence/status")
def intelligence_status(user_id: int = Depends(get_current_user_id)):
    intelligence.start_scan(False)
    return {"scan": intelligence.status()}


@router.post("/intelligence/scan")
def intelligence_scan(
    force: bool = Query(default=False),
    user_id: int = Depends(get_current_user_id),
):
    return {"started": intelligence.start_scan(force=force), "scan": intelligence.status()}


@router.get("/intelligence/summary")
def intelligence_summary(user_id: int = Depends(get_current_user_id)):
    return intelligence.summary()


@router.get("/intelligence/duplicates")
def intelligence_duplicates(user_id: int = Depends(get_current_user_id)):
    return intelligence.duplicates()


@router.get("/intelligence/missing-episodes")
def intelligence_missing_episodes(user_id: int = Depends(get_current_user_id)):
    intelligence.start_scan(False)
    return {"groups": intelligence.missing_episodes(), "scan": intelligence.status()}


@router.get("/intelligence/issues")
def intelligence_issues(
    kind: str = Query(default="", max_length=80),
    limit: int = Query(default=500, ge=1, le=2000),
    user_id: int = Depends(get_current_user_id),
):
    intelligence.start_scan(False)
    return {"items": intelligence.issues(kind=kind, limit=limit), "scan": intelligence.status()}
