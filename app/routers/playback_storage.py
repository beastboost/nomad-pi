"""Playback storage health checks used only when a stream fails.

There is intentionally no polling loop here. The browser asks this endpoint
only after a direct stream error so a disconnected USB disk can be identified
without adding background I/O during healthy playback.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
import psutil

from app.routers.auth import get_current_user_id
from app.routers import playback_core as core
from app.services.playback.appliance_runtime import (
    appliance_memory_class,
    assert_source_readable,
    is_storage_error,
    storage_error_detail,
)


router = APIRouter()


def _mount_for(path: str) -> dict:
    resolved = os.path.realpath(path)
    best = None
    for part in psutil.disk_partitions(all=True):
        mount = os.path.realpath(part.mountpoint)
        if resolved == mount or resolved.startswith(mount.rstrip(os.sep) + os.sep):
            if best is None or len(mount) > len(os.path.realpath(best.mountpoint)):
                best = part
    if best is None:
        return {"mountpoint": None, "device": None, "fstype": None}
    return {
        "mountpoint": best.mountpoint,
        "device": best.device,
        "fstype": best.fstype,
    }


@router.get("/storage/source-health")
def playback_source_health(
    path: str = Query(..., min_length=1, max_length=4096),
    user_id: int = Depends(get_current_user_id),
):
    try:
        fs_path = core.safe_fs_path_from_web_path(path)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media path")

    try:
        size = assert_source_readable(fs_path)
        mount = _mount_for(fs_path)
        if mount.get("mountpoint"):
            # statvfs forces the kernel to touch the mounted filesystem and is a
            # cheap way to catch a stale/disconnected mount after path lookup.
            os.statvfs(mount["mountpoint"])
    except HTTPException:
        raise
    except OSError as exc:
        if is_storage_error(exc):
            raise HTTPException(status_code=503, detail=storage_error_detail(fs_path, exc))
        raise HTTPException(status_code=503, detail=f"Storage check failed: {exc}")

    return {
        "ok": True,
        "path": path,
        "size": size,
        "memory_class": appliance_memory_class(),
        "storage": mount,
    }
