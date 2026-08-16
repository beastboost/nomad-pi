"""Compatibility facade for the legacy Nomad Pi system router.

The original system router has grown large and is being split incrementally.
For now its implementation lives unchanged in ``system_legacy.py``.  This
facade preserves the public ``app.routers.system`` import while applying small,
well-tested routing fixes without rewriting unrelated system-management code.
"""

import os
import subprocess
import sys

from fastapi import Depends

from app.routers.auth import get_current_admin
from app.routers import system_legacy as _legacy
from app.routers.system_storage_policy import router as _storage_policy_router


# The legacy body-form route was registered with ordinary user authentication
# and then called system_control(..., user_id=...), although system_control's
# actual dependency/signature is admin=.  Remove that APIRoute before the
# router is included in the FastAPI application and replace it with the
# correctly guarded delegate below.
def _is_broken_body_control_route(route) -> bool:
    return (
        getattr(route, "path", None) == "/control"
        and "POST" in getattr(route, "methods", set())
    )


_legacy.router.routes[:] = [
    route for route in _legacy.router.routes
    if not _is_broken_body_control_route(route)
]


def system_control_body(
    request: _legacy.ControlRequest,
    admin: dict = Depends(get_current_admin),
):
    """Execute a privileged system action submitted in JSON body form."""
    return _legacy.system_control(request.action, admin=admin)


# Keep introspection/import compatibility and register the repaired endpoint.
_legacy.system_control_body = system_control_body
_legacy.router.add_api_route(
    "/control",
    system_control_body,
    methods=["POST"],
    name="system_control_body",
)

# New storage policy controls live in a focused module but share /api/system.
_legacy.router.include_router(_storage_policy_router)


# Runtime privilege is what matters, not the historical filename of a sudoers
# fragment. Older NomadOS images can have an equivalent rule under a different
# name, which made the legacy diagnostics falsely report "Sudoers file not
# found" even while web-admin sudo commands were succeeding.
_original_dependency_diagnostics = _legacy._dependency_diagnostics


def _dependency_diagnostics_runtime() -> dict:
    data = _original_dependency_diagnostics()
    deps = data.setdefault("dependencies", {})

    sudo_ok = False
    sudo_error = ""
    if os.name == "posix":
        try:
            result = subprocess.run(
                ["sudo", "-n", "true"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            sudo_ok = result.returncode == 0
            sudo_error = (result.stderr or result.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            sudo_error = str(exc)

    canonical_rule = os.path.exists("/etc/sudoers.d/nomad-pi")
    deps["sudo_permissions"] = {
        "status": "ok" if sudo_ok else "missing",
        "description": "Passwordless sudo for system operations",
        "runtime_ok": sudo_ok,
        "canonical_rule": canonical_rule,
    }

    # Replace the legacy filename-only warning with a real capability result.
    warnings = [
        item for item in data.get("warnings", [])
        if item.get("component") != "System Permissions"
    ]
    if not sudo_ok:
        warnings.append({
            "severity": "warning",
            "component": "System Permissions",
            "message": "Non-interactive sudo is unavailable",
            "fix": "Run ./update.sh from a sudo-capable shell to restore Nomad web-admin permissions",
            "impact": "Reboot, mount, Wi-Fi and other privileged web controls may fail",
        })
    data["warnings"] = warnings

    # Raspberry Pi Connect's WayVNC helper is optional for Nomad. A failed user
    # service that restarts every few seconds wastes CPU and floods the journal
    # on a 512 MB Zero 2 W, so surface it as a cleanup recommendation without
    # silently disabling a user-selected remote-access feature.
    if os.name == "posix":
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-failed", "rpi-connect-wayvnc.service"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if (result.stdout or "").strip() == "failed":
                warnings.append({
                    "severity": "warning",
                    "component": "Raspberry Pi Connect",
                    "message": "WayVNC is crash-looping in the background",
                    "fix": "If you do not use Raspberry Pi Connect screen sharing, run: systemctl --user disable --now rpi-connect-wayvnc.service",
                    "impact": "Repeated restarts add journal noise and unnecessary work on tiny-memory hardware",
                })
        except (OSError, subprocess.TimeoutExpired):
            pass

    if warnings and data.get("status") == "healthy":
        data["status"] = "warnings"
    return data


_legacy._dependency_diagnostics = _dependency_diagnostics_runtime

# Consumers importing ``app.routers.system`` should receive the implementation
# module itself.  This keeps monkeypatching of module globals (used by tests and
# maintenance helpers) behaving exactly as it did before the split.
sys.modules[__name__] = _legacy
