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
    """802.11 SSIDs are up to 32 *bytes* of arbitrary data, in practice UTF-8.
    An ASCII-only rule here made real networks unjoinable — notably every
    iPhone hotspot, which is named with U+2019 ("Conner\u2019s iPhone")."""

    def _model(self):
        from app.routers.system import WifiConnectRequest
        return WifiConnectRequest

    @pytest.mark.parametrize("ssid", [
        "Conner\u2019s iPhone",   # the reported failure — typographic apostrophe
        "Conner's iPhone",        # straight apostrophe
        "Bob's WiFi! #5G & more", # punctuation
        "caf\u00e9 wifi",          # accented latin
        "\u6211\u7684\u7f51\u7edc",              # CJK
        "\U0001F4F6 hotspot",         # emoji
        "RUT200_EC4B",
        "x" * 32,                 # exactly at the byte limit
    ])
    def test_accepts_real_world_ssids(self, ssid):
        assert self._model()(ssid=ssid, password="pw12345678").ssid == ssid

    def test_rejects_over_32_bytes(self):
        with pytest.raises(ValueError):
            self._model()(ssid="x" * 33, password="pw12345678")

    def test_limit_is_bytes_not_characters(self):
        """11 CJK characters are only 11 chars but 33 UTF-8 bytes."""
        with pytest.raises(ValueError):
            self._model()(ssid="\u4e2d" * 11, password="pw12345678")

    @pytest.mark.parametrize("ssid", ["evil\x00ssid", "bad\nssid", "tab\tssid"])
    def test_rejects_control_characters(self, ssid):
        with pytest.raises(ValueError):
            self._model()(ssid=ssid, password="pw12345678")

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


class TestProgressStorage:
    """`current_time` is a reserved SQLite keyword (CURRENT_TIME). Written
    unquoted in SQL, SQLite substitutes the clock value, so playback offsets
    were stored as '18:26:57' and every Continue-watching item was silently
    dropped when float() threw. Guard both the write and the read."""

    def test_progress_roundtrip_is_numeric(self, tmp_path, monkeypatch):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.execute(
            'CREATE TABLE progress (user_id INT, path TEXT, "current_time" REAL,'
            ' duration REAL, last_played TIMESTAMP, play_count INT,'
            ' UNIQUE(user_id, path))'
        )
        # The quoted form used by database.update_progress
        q = ('INSERT INTO progress (user_id, path, "current_time", duration, last_played, play_count)'
             ' VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 0)'
             ' ON CONFLICT(user_id, path) DO UPDATE SET'
             '   "current_time" = excluded."current_time",'
             '   duration = COALESCE(NULLIF(excluded.duration, 0), progress.duration),'
             '   last_played = CURRENT_TIMESTAMP')
        conn.execute(q, (1, "/data/movies/x.mp4", 300.0, 1800.0))
        got = conn.execute('SELECT "current_time" FROM progress').fetchone()[0]
        assert got == 300.0, f"insert stored {got!r} instead of the offset"

        conn.execute(q, (1, "/data/movies/x.mp4", 450.0, 1800.0))
        got = conn.execute('SELECT "current_time" FROM progress').fetchone()[0]
        assert got == 450.0, f"upsert stored {got!r} instead of the offset"

    def test_database_sql_quotes_current_time(self):
        """No SQL statement in database.py may reference current_time unquoted."""
        import re
        src = open("app/database.py").read()
        # Strip the python signature/kwarg uses; look only at SQL string bodies
        sql_blocks = re.findall(r"'''(.*?)'''", src, re.S) + re.findall(r'"""(.*?)"""', src, re.S)
        offenders = []
        for block in sql_blocks:
            for line in block.splitlines():
                if re.search(r'(?<!["\w.])current_time(?!["\w])', line):
                    offenders.append(line.strip())
        assert not offenders, "unquoted current_time in SQL:\n" + "\n".join(offenders)
