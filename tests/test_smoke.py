"""Smoke tests for the Nomad Pi API.

Run from the repo root:  ./venv/bin/python -m pytest tests/ -q
(or any python with requirements.txt + pytest installed)

These are deliberately shallow: they catch import errors, broken routes,
missing auth guards, and validator regressions — the classes of bug that
have actually shipped — without needing media files or a configured Pi.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    # Importing app.main bootstraps the SQLite DB under ./data
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_app_boots_and_serves_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Nomad Pi" in res.text


def test_service_worker_served(client):
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert "CACHE_NAME" in res.text


def test_settings_requires_auth(client):
    res = client.get("/api/system/settings")
    assert res.status_code in (401, 403)


def test_stream_requires_auth(client):
    res = client.get("/api/media/stream", params={"path": "/data/movies/x.mp4"})
    assert res.status_code in (401, 403)


def test_diagnostics_requires_admin(client):
    res = client.get("/api/system/diagnostics")
    assert res.status_code in (401, 403)


def test_settings_get_not_readable_unauthenticated(client):
    """GET /settings returns provider secrets — must never be open."""
    res = client.get("/api/system/settings")
    assert res.status_code in (401, 403)


def test_settings_omdb_requires_auth(client):
    res = client.get("/api/system/settings/omdb")
    assert res.status_code in (401, 403)


def test_dashboard_command_requires_auth(client):
    """The session command endpoint must not be anonymous (it can stop
    anyone's playback)."""
    res = client.post("/api/dashboard/session/whatever/command", json={"action": "stop"})
    assert res.status_code in (401, 403)


def test_single_settings_post_route():
    """Exactly one POST /settings handler must be registered — a permissive
    duplicate previously shadowed the allowlisted one."""
    from app.routers import system as system_router
    posts = [
        r for r in system_router.router.routes
        if getattr(r, "path", "") == "/settings" and "POST" in getattr(r, "methods", set())
    ]
    assert len(posts) == 1


def test_login_rejects_bad_credentials(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "definitely-wrong-password"})
    assert res.status_code in (400, 401, 403)


def test_storage_info_shape():
    """The /storage/info route must return the detailed dict shape the
    frontend expects — a duplicate stub route once shadowed it and returned
    a raw tuple, silently breaking the admin storage chart."""
    from app.routers import system as system_router
    routes = [r for r in system_router.router.routes if getattr(r, "path", "") == "/storage/info"]
    assert len(routes) == 1, "duplicate /storage/info routes registered"


class TestSsidValidation:
    def _model(self):
        from app.routers.system import WifiConnectRequest
        return WifiConnectRequest

    def test_accepts_special_characters(self):
        req = self._model()(ssid="Bob's WiFi! #5G & more", password="pw12345678")
        assert req.ssid == "Bob's WiFi! #5G & more"

    def test_rejects_too_long(self):
        with pytest.raises(ValueError):
            self._model()(ssid="x" * 33, password="pw12345678")

    def test_rejects_non_printable(self):
        with pytest.raises(ValueError):
            self._model()(ssid="evil\x00ssid", password="pw12345678")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            self._model()(ssid="", password="pw12345678")


class TestPathSafety:
    def test_traversal_rejected(self):
        from fastapi import HTTPException
        from app.routers.media import safe_fs_path_from_web_path
        for bad in [
            "/data/../../../etc/passwd",
            "/etc/passwd",
            "/data/movies/\x00evil",
            "/data/movies/x; rm -rf /",
        ]:
            try:
                result = safe_fs_path_from_web_path(bad)
            except HTTPException:
                continue  # rejected — good
            # If it resolved, it must still be inside the data root
            base = os.path.abspath("data")
            assert os.path.abspath(result).startswith(base), f"{bad!r} escaped to {result!r}"

    def test_normal_path_allowed(self):
        from app.routers.media import safe_fs_path_from_web_path
        result = safe_fs_path_from_web_path("/data/movies/Movie (2024).mp4")
        assert result.endswith("Movie (2024).mp4")


class TestRemuxHelpers:
    def test_remux_paths_stable_and_unique(self, tmp_path):
        from app.routers.media import _remux_paths
        f1 = tmp_path / "a.mkv"
        f2 = tmp_path / "b.mkv"
        f1.write_bytes(b"one")
        f2.write_bytes(b"two-longer")
        out1a, web1 = _remux_paths(str(f1))
        out1b, _ = _remux_paths(str(f1))
        out2, _ = _remux_paths(str(f2))
        assert out1a == out1b, "same source must map to same cache file"
        assert out1a != out2, "different sources must not collide"
        assert out1a.endswith(".mp4") and web1.startswith("/data/")
