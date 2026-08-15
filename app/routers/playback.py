"""Nomad Pi 2.x playback-core API.

The first endpoint exposes the planner only. It does not start a playback or
transcode job yet; callers can ask the server how a source *would* be played.
"""

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers.media import safe_fs_path_from_web_path
from app.services.playback import ClientCapabilities, PlaybackPlanner
from app.services.playback.probe import ProbeError, probe_media


router = APIRouter(prefix="/api/playback", tags=["playback"])
planner = PlaybackPlanner()


class ClientCapabilitiesRequest(BaseModel):
    containers: List[str] = Field(default_factory=list)
    video_codecs: List[str] = Field(default_factory=list)
    audio_codecs: List[str] = Field(default_factory=list)
    subtitle_formats: List[str] = Field(default_factory=list)
    max_width: Optional[int] = Field(default=None, gt=0)
    max_height: Optional[int] = Field(default=None, gt=0)
    max_bitrate: Optional[int] = Field(default=None, gt=0)


class PlaybackPlanRequest(BaseModel):
    path: str
    capabilities: ClientCapabilitiesRequest


@router.post("/plan")
def create_playback_plan(
    request: PlaybackPlanRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Inspect a local source and return the cheapest viable playback mode."""
    try:
        fs_path = safe_fs_path_from_web_path(request.path)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media path")

    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Media file not found")

    try:
        source = probe_media(fs_path)
    except ProbeError as exc:
        message = str(exc)
        status_code = 503 if "not installed" in message else 422
        raise HTTPException(status_code=status_code, detail=message)

    caps = request.capabilities
    client = ClientCapabilities.from_values(
        containers=caps.containers,
        video_codecs=caps.video_codecs,
        audio_codecs=caps.audio_codecs,
        subtitle_formats=caps.subtitle_formats,
        max_width=caps.max_width,
        max_height=caps.max_height,
        max_bitrate=caps.max_bitrate,
    )
    plan = planner.plan(source, client)

    return {
        "mode": plan.mode.value,
        "requires_ffmpeg": plan.requires_ffmpeg,
        "reasons": list(plan.reasons),
        "source": {
            "container": source.container,
            "video_codec": source.video_codec,
            "audio_codec": source.audio_codec,
            "width": source.width,
            "height": source.height,
            "bitrate": source.bitrate,
        },
        "target": {
            "container": plan.target_container,
            "video_codec": plan.target_video_codec,
            "audio_codec": plan.target_audio_codec,
        },
    }
