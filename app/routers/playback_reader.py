"""Authenticated reading progress, bookmarks and annotations API."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.services.reader_state import ReaderStateStore


router = APIRouter()
store = ReaderStateStore()


class ProgressRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4000)
    position: Dict[str, Any] = Field(default_factory=dict)
    percent: float = Field(default=0, ge=0, le=100)


class MarkRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4000)
    kind: str = Field(default="bookmark", pattern="^(bookmark|annotation)$")
    label: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=10000)
    position: Dict[str, Any] = Field(default_factory=dict)


@router.get("/reader/progress")
def get_reader_progress(
    path: str = Query(...),
    user_id: int = Depends(get_current_user_id),
):
    progress = store.get_progress(user_id=user_id, path=path)
    return {"progress": progress.to_dict() if progress else None}


@router.post("/reader/progress")
def save_reader_progress(
    request: ProgressRequest,
    user_id: int = Depends(get_current_user_id),
):
    progress = store.save_progress(
        user_id=user_id,
        path=request.path,
        position=request.position,
        percent=request.percent,
    )
    return {"progress": progress.to_dict()}


@router.get("/reader/recent")
def recent_reader_progress(
    limit: int = Query(default=50, ge=1, le=500),
    user_id: int = Depends(get_current_user_id),
):
    return {"items": [item.to_dict() for item in store.recent(user_id, limit)]}


@router.get("/reader/marks")
def list_reader_marks(
    path: str = Query(...),
    kind: str = Query(default=""),
    user_id: int = Depends(get_current_user_id),
):
    return {"items": [item.to_dict() for item in store.list_marks(user_id=user_id, path=path, kind=kind)]}


@router.post("/reader/marks")
def create_reader_mark(
    request: MarkRequest,
    user_id: int = Depends(get_current_user_id),
):
    item = store.add_mark(
        user_id=user_id,
        path=request.path,
        kind=request.kind,
        label=request.label,
        note=request.note,
        position=request.position,
    )
    return {"item": item.to_dict()}


@router.delete("/reader/marks/{mark_id}")
def delete_reader_mark(
    mark_id: str,
    user_id: int = Depends(get_current_user_id),
):
    if not store.delete_mark(user_id=user_id, mark_id=mark_id):
        raise HTTPException(status_code=404, detail="Reader bookmark/annotation not found")
    return {"deleted": True}
