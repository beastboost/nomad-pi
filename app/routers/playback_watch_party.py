"""Authenticated same-account Watch Together synchronization API."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers import playback_core as core
from app.services.profile_policy import profile_policy_guard
from app.services.watch_party import store


router = APIRouter()


class CreatePartyRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    device_id: str = Field(min_length=1, max_length=200)
    device_name: str = Field(default="Device", max_length=150)
    position: float = Field(default=0, ge=0)
    state: str = Field(default="paused", pattern="^(playing|paused)$")
    rate: float = Field(default=1.0, ge=0.25, le=4.0)


class JoinPartyRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)
    device_name: str = Field(default="Device", max_length=150)


class PartyStateRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)
    position: float = Field(ge=0)
    state: str = Field(pattern="^(playing|paused)$")
    rate: float = Field(default=1.0, ge=0.25, le=4.0)
    quality: Optional[str] = Field(default=None, max_length=32)
    adaptive: Optional[bool] = None
    audio_track: Optional[int] = Field(default=None, ge=0)
    subtitle_track: Optional[int] = Field(default=None, ge=0)
    subtitle_burned: Optional[bool] = None


class LeavePartyRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)


def _public(party, user_id: int) -> dict:
    return {
        "party": party.to_dict(),
        "members": [member.to_dict() for member in store.members(user_id=user_id, party_id=party.id)],
    }


@router.post("/watch-party")
def create_watch_party(
    body: CreatePartyRequest,
    user_id: int = Depends(get_current_user_id),
    _policy=Depends(profile_policy_guard),
):
    session = core.session_store.get(body.session_id, user_id=user_id)
    if not session or session.state == "stopped":
        raise HTTPException(status_code=404, detail="Active playback session not found")
    metadata = session.metadata or {}
    party = store.create(
        user_id=user_id,
        host_device_id=body.device_id,
        host_name=body.device_name,
        path=session.path,
        state=body.state,
        position=body.position,
        rate=body.rate,
        quality=session.quality or "auto",
        adaptive=bool(metadata.get("abr")),
        audio_track=session.audio_track,
        subtitle_track=session.subtitle_track,
        subtitle_burned=bool(metadata.get("burn_subtitle")),
    )
    return _public(party, user_id)


@router.post("/watch-party/{party_id}/join")
def join_watch_party(
    party_id: str,
    body: JoinPartyRequest,
    user_id: int = Depends(get_current_user_id),
    _policy=Depends(profile_policy_guard),
):
    party = store.join(
        user_id=user_id,
        party_id=party_id,
        device_id=body.device_id,
        name=body.device_name,
    )
    if not party:
        raise HTTPException(status_code=404, detail="Watch Together room not found or expired")
    return _public(party, user_id)


@router.get("/watch-party/{party_id}")
def get_watch_party(
    party_id: str,
    device_id: str = Query(..., min_length=1, max_length=200),
    revision: Optional[int] = Query(default=None, ge=0),
    user_id: int = Depends(get_current_user_id),
):
    party = store.get(user_id=user_id, party_id=party_id)
    if not party:
        raise HTTPException(status_code=404, detail="Watch Together room not found or expired")
    if not store.touch_member(
        user_id=user_id,
        party_id=party.id,
        device_id=device_id,
        revision=revision,
    ):
        raise HTTPException(status_code=409, detail="This device has not joined the Watch Together room")
    return _public(party, user_id)


@router.post("/watch-party/{party_id}/state")
def update_watch_party_state(
    party_id: str,
    body: PartyStateRequest,
    user_id: int = Depends(get_current_user_id),
):
    party = store.host_update(
        user_id=user_id,
        party_id=party_id,
        host_device_id=body.device_id,
        state=body.state,
        position=body.position,
        rate=body.rate,
        quality=body.quality,
        adaptive=body.adaptive,
        audio_track=body.audio_track,
        subtitle_track=body.subtitle_track,
        subtitle_burned=body.subtitle_burned,
    )
    if not party:
        raise HTTPException(status_code=403, detail="Only the room host can publish playback state")
    return _public(party, user_id)


@router.post("/watch-party/{party_id}/leave")
def leave_watch_party(
    party_id: str,
    body: LeavePartyRequest,
    user_id: int = Depends(get_current_user_id),
):
    party = store.get(user_id=user_id, party_id=party_id)
    if not party:
        return {"left": True, "closed": True}
    if party.host_device_id == body.device_id:
        return {"left": True, "closed": store.close(user_id=user_id, party_id=party.id, host_device_id=body.device_id)}
    return {"left": store.leave(user_id=user_id, party_id=party.id, device_id=body.device_id), "closed": False}


@router.delete("/watch-party/{party_id}")
def close_watch_party(
    party_id: str,
    device_id: str = Query(..., min_length=1, max_length=200),
    user_id: int = Depends(get_current_user_id),
):
    if not store.close(user_id=user_id, party_id=party_id, host_device_id=device_id):
        raise HTTPException(status_code=403, detail="Only the room host can close this Watch Together room")
    return {"closed": True}
