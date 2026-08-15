"""Compatibility facade for the legacy Nomad Pi system router.

The original system router has grown large and is being split incrementally.
For now its implementation lives unchanged in ``system_legacy.py``.  This
facade preserves the public ``app.routers.system`` import while applying small,
well-tested routing fixes without rewriting unrelated system-management code.
"""

import sys

from fastapi import Depends

from app.routers.auth import get_current_admin
from app.routers import system_legacy as _legacy


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

# Consumers importing ``app.routers.system`` should receive the implementation
# module itself.  This keeps monkeypatching of module globals (used by tests and
# maintenance helpers) behaving exactly as it did before the split.
sys.modules[__name__] = _legacy
