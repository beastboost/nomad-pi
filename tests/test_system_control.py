"""Regression tests for privileged system-control routing."""

import inspect

from fastapi.params import Depends


def _dependency_name(parameter) -> str:
    default = parameter.default
    if not isinstance(default, Depends):
        return ""
    dependency = default.dependency
    return getattr(dependency, "__name__", str(dependency))


def test_system_control_body_requires_admin():
    """POST /api/system/control must be admin-only just like /control/{action}."""
    from app.routers import system

    params = inspect.signature(system.system_control_body).parameters
    dependency_names = {_dependency_name(p) for p in params.values()}

    assert "get_current_admin" in dependency_names, (
        "system_control_body must depend on get_current_admin; a normal user "
        "must not be able to reboot, shut down, update, or restart the server"
    )


def test_system_control_body_delegates_with_admin(monkeypatch):
    """The body-form route must call the action handler with its real signature.

    A previous implementation passed user_id=... to system_control(), which has
    no user_id parameter and therefore raised TypeError before performing the
    requested action.
    """
    from app.routers import system

    calls = []

    def fake_system_control(action, admin):
        calls.append((action, admin))
        return {"status": "ok", "action": action}

    monkeypatch.setattr(system, "system_control", fake_system_control)
    admin = {"id": 7, "username": "admin", "is_admin": 1}

    result = system.system_control_body(system.ControlRequest(action="restart"), admin=admin)

    assert result == {"status": "ok", "action": "restart"}
    assert calls == [("restart", admin)]
