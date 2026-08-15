"""External-storage failover policy for Nomad Pi.

The legacy media layer already understands storage.failover.* settings.  This
router makes that policy visible/configurable and only accepts currently
mounted external volumes as automatic failover roots.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import database
from app.routers.auth import get_current_admin


router = APIRouter()
CATEGORIES = ("movies", "shows", "music", "books", "gallery", "files")
PSEUDO_FS = {"tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "cgroup", "cgroup2"}


class StoragePolicyRequest(BaseModel):
    enabled: bool = False
    threshold_free_percent: int = Field(default=20, ge=5, le=50)
    failover_mount: Optional[str] = Field(default=None, max_length=4096)


def _data_root() -> str:
    return os.path.abspath("data")


def _setting_int(key: str, default: int) -> int:
    try:
        return int(str(database.get_setting(key) or default).strip())
    except (TypeError, ValueError):
        return int(default)


def _web_root_for_mount(resolved: Path) -> str:
    """Convert a filesystem mount into the path form media.py accepts."""
    data_root = Path(_data_root()).resolve()
    try:
        rel = resolved.relative_to(data_root)
        # Nomad-mounted volumes live under data/external/<name>.  Store them
        # as /data/... rather than /home/.../data/... so media.py's guarded
        # path resolver can consume the setting.
        return "/data/" + rel.as_posix().lstrip("/")
    except ValueError:
        return str(resolved)


def _candidate_mounts() -> list[dict]:
    data_root = Path(_data_root()).resolve()
    candidates: list[dict] = []
    seen = set()

    for part in psutil.disk_partitions(all=False):
        mountpoint = part.mountpoint or ""
        if not mountpoint or mountpoint in seen or part.fstype.lower() in PSEUDO_FS:
            continue
        seen.add(mountpoint)
        try:
            resolved = Path(mountpoint).resolve()
            usage = psutil.disk_usage(str(resolved))
        except (OSError, PermissionError):
            continue

        # Treat standard removable mount roots and explicit mounts below
        # data/external as external-storage candidates. Never offer / itself as
        # a failover target for the data filesystem.
        is_external = str(resolved).startswith(("/media/", "/mnt/"))
        try:
            resolved.relative_to(data_root / "external")
            is_external = True
        except ValueError:
            pass
        if not is_external:
            continue

        candidates.append({
            "mountpoint": str(resolved),
            "web_root": _web_root_for_mount(resolved),
            "device": part.device,
            "fstype": part.fstype,
            "total": int(usage.total),
            "used": int(usage.used),
            "free": int(usage.free),
            "free_percent": round((usage.free / usage.total) * 100, 1) if usage.total else 0,
        })

    candidates.sort(key=lambda item: item["free"], reverse=True)
    return candidates


def _current_policy() -> dict:
    data_root = _data_root()
    try:
        usage = psutil.disk_usage(data_root)
        primary = {
            "path": data_root,
            "total": int(usage.total),
            "used": int(usage.used),
            "free": int(usage.free),
            "free_percent": round((usage.free / usage.total) * 100, 1) if usage.total else 0,
        }
    except (OSError, PermissionError):
        primary = {"path": data_root, "total": 0, "used": 0, "free": 0, "free_percent": 0}

    targets = {
        category: (database.get_setting(f"storage.failover.target.{category}") or "")
        for category in CATEGORIES
    }
    configured_target_root = ""
    nonempty = [value for value in targets.values() if value]
    if nonempty:
        parents = {str(Path(value).parent) for value in nonempty}
        if len(parents) == 1:
            configured_target_root = parents.pop()

    candidates = _candidate_mounts()
    configured_mount = ""
    for candidate in candidates:
        if candidate.get("web_root") == configured_target_root or candidate.get("mountpoint") == configured_target_root:
            configured_mount = candidate["mountpoint"]
            break

    threshold = max(5, min(50, _setting_int("storage.failover.threshold_free_percent", 20)))
    enabled = bool(_setting_int("storage.failover.enabled", 0))
    effective_failover = enabled and primary["free_percent"] <= threshold and bool(nonempty)

    return {
        "enabled": enabled,
        "threshold_free_percent": threshold,
        "configured_mount": configured_mount,
        "configured_target_root": configured_target_root,
        "targets": targets,
        "primary": primary,
        "failover_active": effective_failover,
        "candidates": candidates,
    }


@router.get("/storage/policy")
def get_storage_policy(admin: dict = Depends(get_current_admin)):
    return _current_policy()


@router.post("/storage/policy")
def set_storage_policy(
    request: StoragePolicyRequest,
    admin: dict = Depends(get_current_admin),
):
    candidate_items = _candidate_mounts()
    candidates = {item["mountpoint"]: item for item in candidate_items}
    mount = str(request.failover_mount or "").rstrip("/")
    target_root = ""

    if request.enabled:
        if not mount:
            raise HTTPException(status_code=400, detail="Choose a mounted external volume before enabling failover")
        try:
            resolved = str(Path(mount).resolve())
        except OSError:
            raise HTTPException(status_code=400, detail="Invalid failover mount")
        candidate = candidates.get(resolved)
        if not candidate:
            raise HTTPException(status_code=400, detail="Failover target is not a currently mounted external volume")
        mount = resolved
        target_root = str(candidate["web_root"]).rstrip("/")
    elif mount:
        try:
            resolved = str(Path(mount).resolve())
        except OSError:
            resolved = ""
        candidate = candidates.get(resolved)
        if candidate:
            target_root = str(candidate["web_root"]).rstrip("/")

    database.set_setting("storage.failover.enabled", "1" if request.enabled else "0")
    database.set_setting("storage.failover.threshold_free_percent", str(int(request.threshold_free_percent)))

    if target_root:
        for category in CATEGORIES:
            database.set_setting(
                f"storage.failover.target.{category}",
                f"{target_root}/{category}",
            )

    return {"status": "ok", "policy": _current_policy()}
