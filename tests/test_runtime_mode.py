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
