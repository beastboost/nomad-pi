"""Runtime-mode capability boundaries shared by native and Docker installs."""

import os

from fastapi import HTTPException, Request


HOST_ONLY_MARKERS = (
    "/wifi",
    "/network/",
    "/storage/format",
    "/storage/mount",
    "/storage/unmount",
    "/mount/",
    "/unmount/",
    "/control",
    "/reboot",
    "/shutdown",
    "/restart",
    "/tailscale",
    "/minidlna",
    "/samba",
    "/update",
)


def runtime_mode() -> str:
    value = os.environ.get("NOMAD_RUNTIME_MODE", "native").strip().lower()
    return value if value in {"native", "server"} else "native"


def runtime_capabilities() -> dict:
    mode = runtime_mode()
    return {
        "mode": mode,
        "media_server": True,
        "playback": True,
        "host_management": mode == "native",
        "wifi_management": mode == "native",
        "disk_management": mode == "native",
        "systemd_management": mode == "native",
        "self_update": mode == "native",
    }


async def system_runtime_guard(request: Request):
    if runtime_mode() != "server":
        return
    path = request.url.path.lower()
    if any(marker in path for marker in HOST_ONLY_MARKERS):
        raise HTTPException(
            status_code=409,
            detail="This system-management action is unavailable in Docker/server mode; use a native Nomad installation for host control",
        )
