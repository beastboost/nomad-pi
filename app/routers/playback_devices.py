"""Persistent playback-device presence and two-phase handoff API."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers import playback_core as core
from app.services.playback.devices import PlaybackDeviceStore


router = APIRouter()
device_store = PlaybackDeviceStore()


class DeviceRegisterRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="web", min_length=1, max_length=40)
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    current_session_id: Optional[str] = Field(default=None, max_length=100)


class DeviceHeartbeatRequest(BaseModel):
    current_session_id: Optional[str] = Field(default=None, max_length=100)


class CommandAckRequest(BaseModel):
    status: str = Field(default="completed", max_length=20)
    result: Dict[str, Any] = Field(default_factory=dict)


class HandoffRequest(BaseModel):
    target_device_id: str = Field(min_length=1, max_length=200)
    position: Optional[float] = Field(default=None, ge=0)
    quality: Optional[str] = Field(default=None, max_length=32)
    audio_track: Optional[int] = Field(default=None, ge=0)
    subtitle_track: Optional[int] = Field(default=None, ge=0)
    subtitle_burned: Optional[bool] = None


@router.post("/devices/register")
def register_playback_device(
    request: DeviceRegisterRequest,
    user_id: int = Depends(get_current_user_id),
):
    device_store.cleanup()
    device = device_store.register(
        user_id=user_id,
        device_id=request.device_id,
        name=request.name,
        kind=request.kind,
        capabilities=request.capabilities,
        current_session_id=request.current_session_id,
    )
    return {"device": device.to_dict()}


@router.post("/devices/{device_id}/heartbeat")
def heartbeat_playback_device(
    device_id: str,
    request: DeviceHeartbeatRequest,
    user_id: int = Depends(get_current_user_id),
):
    if not device_store.touch(
        user_id=user_id,
        device_id=device_id,
        current_session_id=request.current_session_id,
    ):
        raise HTTPException(status_code=404, detail="Playback device is not registered")
    return {"status": "ok"}


@router.get("/devices")
def list_playback_devices(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: int = Depends(get_current_user_id),
):
    return {
        "devices": [device.to_dict() for device in device_store.list_for_user(user_id, limit)]
    }


@router.get("/devices/{device_id}/commands")
def claim_playback_commands(
    device_id: str,
    limit: int = Query(default=5, ge=1, le=20),
    user_id: int = Depends(get_current_user_id),
):
    device = device_store.get(user_id=user_id, device_id=device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Playback device is not registered")
    device_store.touch(
        user_id=user_id,
        device_id=device_id,
        current_session_id=device.current_session_id,
    )
    commands = device_store.claim(
        user_id=user_id,
        target_device_id=device_id,
        limit=limit,
    )
    return {"commands": [command.to_dict() for command in commands]}


@router.post("/devices/{device_id}/commands/{command_id}/ack")
def acknowledge_playback_command(
    device_id: str,
    command_id: str,
    request: CommandAckRequest,
    user_id: int = Depends(get_current_user_id),
):
    command = device_store.acknowledge(
        user_id=user_id,
        target_device_id=device_id,
        command_id=command_id,
        status=request.status,
        result=request.result,
    )
    if not command:
        raise HTTPException(status_code=404, detail="Playback command not found")
    return {"command": command.to_dict()}


@router.get("/commands/{command_id}")
def playback_command_status(
    command_id: str,
    user_id: int = Depends(get_current_user_id),
):
    command = device_store.get_command(user_id=user_id, command_id=command_id)
    if not command:
        raise HTTPException(status_code=404, detail="Playback command not found")
    return {"command": command.to_dict()}


@router.post("/sessions/{session_id}/handoff")
def handoff_playback_session(
    session_id: str,
    request: HandoffRequest,
    user_id: int = Depends(get_current_user_id),
):
    session = core.session_store.get(session_id, user_id=user_id)
    if not session or session.state == "stopped":
        raise HTTPException(status_code=404, detail="Active playback session not found")

    target = device_store.get(user_id=user_id, device_id=request.target_device_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target playback device not found")
    if not target.to_dict().get("online"):
        raise HTTPException(status_code=409, detail="Target playback device is offline")
    if session.device_id and session.device_id == target.device_id:
        raise HTTPException(status_code=409, detail="Playback is already on this device")

    metadata = session.metadata or {}
    source_subtitle = metadata.get("burn_subtitle")
    position = float(request.position if request.position is not None else session.position or 0)
    quality = request.quality or session.quality or "auto"
    audio_track = request.audio_track if request.audio_track is not None else session.audio_track
    subtitle_track = request.subtitle_track if request.subtitle_track is not None else session.subtitle_track
    subtitle_burned = (
        request.subtitle_burned
        if request.subtitle_burned is not None
        else bool(source_subtitle)
    )

    command = device_store.enqueue(
        user_id=user_id,
        target_device_id=target.device_id,
        source_device_id=session.device_id,
        command="handoff",
        payload={
            "source_session_id": session.id,
            "source_device_id": session.device_id,
            "path": session.path,
            "position": max(0.0, position),
            "duration": session.duration,
            "quality": quality,
            "audio_track": audio_track,
            "subtitle_track": subtitle_track,
            "subtitle_burned": bool(subtitle_burned),
            "adaptive": bool(metadata.get("abr")) or quality == "adaptive",
        },
    )
    return {
        "status": "queued",
        "command": command.to_dict(),
        "target": target.to_dict(),
    }
