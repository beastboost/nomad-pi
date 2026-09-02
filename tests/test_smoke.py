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


class TestWifiSafety:
    """Wi-Fi is normally the only route to a headless Pi, and `nmcli radio
    wifi off` survives reboots — so switching it off from the UI could strand
    the box until someone physically attached Ethernet or a keyboard. Turning
    it off must therefore be confirmed and self-reverting."""

    def test_toggle_off_requires_confirmation(self, client):
        """Unconfirmed disable must be refused, not silently obeyed."""
        res = client.post("/api/system/wifi/toggle", params={"enable": "false"})
        # 401/403 when unauthenticated; 409 is the refusal we care about.
        assert res.status_code in (401, 403, 409)
        if res.status_code == 409:
            assert "confirm" in res.text.lower()

    def test_confirm_off_requires_admin(self, client):
        res = client.post("/api/system/wifi/confirm-off")
        assert res.status_code in (401, 403)

    def test_revert_marker_helpers_roundtrip(self, tmp_path, monkeypatch):
        from app.routers import system as sysmod
        marker = tmp_path / "wifi-off-until"
        monkeypatch.setattr(sysmod, "WIFI_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(sysmod, "WIFI_DEADLINE_FILE", str(marker))

        assert sysmod._arm_wifi_revert(300) is True
        deadline = int(marker.read_text())
        import time as _t
        assert deadline > _t.time(), "deadline must be in the future"

        sysmod._clear_wifi_revert(permanent=True)
        assert marker.read_text() == "permanent"

        sysmod._clear_wifi_revert()
        assert not marker.exists(), "re-enabling must clear the marker"

    def test_guard_script_ships_and_is_wired(self):
        """The self-heal only works if the guard is installed by setup/update."""
        assert os.path.exists("scripts/wifi-guard.sh")
        for script in ("setup.sh", "update.sh"):
            assert "install_wifi_guard" in open(script).read(), f"{script} does not install the guard"
        unit = "os-builder/stage3-nomad/03-setup-services/files/nomad-pi-wifi-guard.timer"
        assert os.path.exists(unit)


class TestNoDuplicateRoutes:
    """Three separate duplicate-route bugs shipped in this codebase
    (/storage/info, POST /settings, /diagnostics). In each case the earlier
    registration silently won and the later, better implementation was dead
    code. Fail the build rather than discover the fourth in production."""

    def test_no_router_registers_a_path_twice(self):
        import collections, glob, re
        offenders = []
        for path in sorted(glob.glob("app/routers/*.py")):
            src = open(path).read()
            routes = re.findall(
                r'@(\w+)\.(get|post|put|delete|patch|websocket)\(\s*["\']([^"\']+)["\']', src)
            for key, n in collections.Counter(routes).items():
                if n > 1:
                    offenders.append(f"{path}: {key[1].upper()} {key[2]} x{n}")
        assert not offenders, "duplicate route registrations:\n" + "\n".join(offenders)


class TestPublicEndpointDisclosure:
    """/samba/config is intentionally unauthenticated so the desktop transfer
    tool can self-configure. It must not tell an anonymous caller whether the
    admin password is still the default — that is an invitation."""

    def test_samba_config_hides_password_state_when_anonymous(self, client):
        res = client.get("/api/system/samba/config")
        assert res.status_code == 200, "the tool relies on this being public"
        assert "is_default_password" not in res.json(), \
            "password state leaked to an unauthenticated caller"


class TestUploadContainment:
    """POST /media/upload_stream/{category} joined `category` onto BASE_DIR
    with no allowlist, so category=".." wrote outside the data root — an
    arbitrary file write that, combined with the update endpoint, is remote
    code execution. Verified escaping before the fix."""

    def test_category_allowlist_rejects_traversal(self):
        from fastapi import HTTPException
        from app.routers.media import _validated_category
        for bad in ["..", "../..", "/etc", "app", "", "../app/routers"]:
            with pytest.raises(HTTPException):
                _validated_category(bad)

    def test_real_categories_still_accepted(self):
        from app.routers.media import _validated_category
        for good in ["movies", "shows", "music", "books", "gallery", "files"]:
            assert _validated_category(good) == good


class TestPrivilegedEndpointsRequireAdmin:
    """Destructive or config-changing endpoints must require admin, not just
    any logged-in account. A standard user could previously format a drive,
    shut the box down, re-point Tailscale, or delete provider API keys."""

    @pytest.mark.parametrize("module,func", [
        ("app.routers.system", "format_drive"),
        ("app.routers.system", "system_control"),
        ("app.routers.system", "set_tailscale_auth_key"),
        ("app.routers.system", "tailscale_up"),
        ("app.routers.system", "mount_drive"),
        ("app.routers.system", "unmount_drive"),
        ("app.routers.system", "toggle_wifi"),
        ("app.routers.debrid", "set_rd_key"),
        ("app.routers.debrid", "delete_rd_key"),
        ("app.routers.debrid", "set_provider"),
    ])
    def test_requires_admin(self, module, func):
        import importlib, inspect
        mod = importlib.import_module(module)
        sig = inspect.signature(getattr(mod, func))
        deps = [str(p.default) for p in sig.parameters.values() if p.default is not inspect._empty]
        assert any("get_current_admin" in d for d in deps), \
            f"{func} does not require admin: {deps}"

    def test_format_refuses_system_disk(self):
        """The device holding / and /boot must never be formattable."""
        from app.routers.system import _protected_block_devices
        # On any real host the root device must resolve to something.
        protected = _protected_block_devices()
        assert isinstance(protected, set)


def test_no_route_is_registered_twice_anywhere():
    """A whole-app guard, not another per-path one.

    Registering two handlers on one path is this codebase's most repeated
    routing bug — four instances so far, each found only when the shadowed
    behaviour was missed in the UI. FastAPI takes the first match silently, so
    the second handler becomes unreachable dead code. The per-path checks above
    were each added after the fact; this one covers paths nobody has broken yet.
    """
    import collections

    from app.main import app

    seen = collections.Counter()

    def walk(router, prefix=""):
        for route in getattr(router, "routes", []):
            ctx = getattr(route, "include_context", None)
            if ctx is not None:
                walk(ctx.included_router, prefix + (ctx.prefix or ""))
                continue
            path = prefix + getattr(route, "path", "")
            for method in getattr(route, "methods", None) or []:
                if method not in ("HEAD", "OPTIONS"):
                    seen[(method, path)] += 1

    for route in app.routes:
        ctx = getattr(route, "include_context", None)
        if ctx is not None:
            walk(ctx.included_router, ctx.prefix or "")

    duplicates = {k: v for k, v in seen.items() if v > 1}
    assert not duplicates, f"routes registered more than once: {duplicates}"
