from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import runtime_mode


class FakeRequest:
    def __init__(self, path):
        self.url = SimpleNamespace(path=path)


def test_native_mode_keeps_host_management(monkeypatch):
    monkeypatch.setenv("NOMAD_RUNTIME_MODE", "native")
    caps = runtime_mode.runtime_capabilities()
    assert caps["mode"] == "native"
    assert caps["host_management"] is True


def test_server_mode_reports_media_without_host_management(monkeypatch):
    monkeypatch.setenv("NOMAD_RUNTIME_MODE", "server")
    caps = runtime_mode.runtime_capabilities()
    assert caps["media_server"] is True
    assert caps["playback"] is True
    assert caps["host_management"] is False
    assert caps["wifi_management"] is False


@pytest.mark.asyncio
async def test_server_mode_blocks_host_control(monkeypatch):
    monkeypatch.setenv("NOMAD_RUNTIME_MODE", "server")
    with pytest.raises(HTTPException) as exc:
        await runtime_mode.system_runtime_guard(FakeRequest("/api/system/control/reboot"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_server_mode_allows_stats(monkeypatch):
    monkeypatch.setenv("NOMAD_RUNTIME_MODE", "server")
    assert await runtime_mode.system_runtime_guard(FakeRequest("/api/system/stats")) is None


# ── the guard must actually be attached to something ─────────────────────
# system_runtime_guard was written, tested and documented in DOCKER.md but
# never used as a dependency, so NOMAD_RUNTIME_MODE=server enforced nothing:
# in a container /api/system/control/reboot returned 200 and genuinely tried
# to reboot the host.

def test_the_guard_is_attached_to_the_system_router():
    from app.main import app

    # A router-level dependency lives on the include context, not on each
    # route's own dependant.
    attached = []
    for route in app.routes:
        ctx = getattr(route, "include_context", None)
        if ctx is None:
            continue
        names = [d.dependency.__name__ for d in getattr(ctx, "dependencies", []) if d.dependency]
        if "system_runtime_guard" in names:
            attached.append(ctx.prefix)

    assert attached, "system_runtime_guard is not a dependency of any router"
    assert "/api/system" in attached


def test_server_mode_refuses_host_control_over_http(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers import auth

    monkeypatch.setenv("NOMAD_RUNTIME_MODE", "server")
    app.dependency_overrides[auth.get_current_user_id] = lambda: 1
    try:
        client = TestClient(app, raise_server_exceptions=False)
        assert client.post("/api/system/control/reboot").status_code == 409
        assert client.get("/api/system/wifi/saved").status_code == 409
        assert client.get("/api/system/tailscale/status").status_code == 409
        # Media and monitoring are the point of server mode; they stay open.
        assert client.get("/api/system/stats").status_code == 200
        assert client.get("/api/media/library/movies").status_code == 200
    finally:
        app.dependency_overrides.pop(auth.get_current_user_id, None)


def test_native_mode_leaves_host_control_reachable(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers import auth

    monkeypatch.delenv("NOMAD_RUNTIME_MODE", raising=False)
    app.dependency_overrides[auth.get_current_user_id] = lambda: 1
    try:
        client = TestClient(app, raise_server_exceptions=False)
        # Not 409: on a real Pi these do host management. The status here
        # depends on whether nmcli/tailscale exist, which is not the point.
        assert client.get("/api/system/tailscale/status").status_code != 409
        assert client.get("/api/system/wifi/saved").status_code != 409
    finally:
        app.dependency_overrides.pop(auth.get_current_user_id, None)
