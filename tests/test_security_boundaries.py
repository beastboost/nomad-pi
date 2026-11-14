"""Regression tests for file exposure and host-management authorization.

The fast checks protect critical invariants even on CI without real SBC
hardware. Integration tests exercise routes with signed media tickets.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.media_access import PublicMediaStaticFiles, is_public_media_file


@pytest.mark.parametrize("relative", [
    "nomad.db", "nomad.db-wal", "app.log", "mounts.json",
    ".stream_ticket_secret", ".nomad_cache/hls/session.m3u8",
    "gallery/family.jpg", "movies/.hidden.jpg", "movies/backup.db",
    ".nomad_offline/session.mp4", "private/gallery/child.jpg",
])
def test_private_files_are_not_public_media(tmp_path, relative):
    assert not is_public_media_file(
        tmp_path / "data" / relative, data_root=tmp_path / "data"
    )


@pytest.mark.parametrize("relative", [
    "movies/Film/Film.mkv", "shows/Series/S01E01.mp4",
    "music/Artist/Track.flac", "books/Book.epub", "files/notes.txt",
    "cache/posters/abc.jpg", "cache/music-art/abc.webp",
    ".cache/comics/abc/1.jpg", ".nomad_cache/ios/abc.mp4",
    "external/USB/Film.mp4", "media/movies/Film.mkv",
])
def test_media_playback_paths_remain_available(tmp_path, relative):
    assert is_public_media_file(
        tmp_path / "data" / relative, data_root=tmp_path / "data"
    )


def test_symlink_outside_media_roots_is_denied(tmp_path):
    data = tmp_path / "data"
    (data / "movies").mkdir(parents=True)
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"not a public picture")
    (data / "movies" / "secret.jpg").symlink_to(secret)
    assert not is_public_media_file(data / "movies" / "secret.jpg", data_root=data)


def test_legacy_static_mount_never_serves_private_files(tmp_path):
    data = tmp_path / "data"
    (data / "movies").mkdir(parents=True)
    (data / "movies" / "film.mp4").write_bytes(b"film")
    (data / "nomad.db").write_bytes(b"sensitive")
    (data / ".stream_ticket_secret").write_text("sensitive")
    (data / "gallery").mkdir()
    (data / "gallery" / "child.jpg").write_bytes(b"sensitive")

    app = FastAPI()
    app.mount("/data", PublicMediaStaticFiles(directory=str(data)))
    with TestClient(app) as client:
        assert client.get("/data/movies/film.mp4").status_code == 200
        for relative in ("nomad.db", ".stream_ticket_secret", "gallery/child.jpg"):
            assert client.get("/data/" + relative).status_code == 404


def test_stream_and_subtitle_use_same_private_file_guard():
    from app.routers import media
    import inspect
    assert "is_public_media_file" in inspect.getsource(media.stream_media)
    assert "is_public_media_file" in inspect.getsource(media.serve_subtitle)


@pytest.mark.parametrize("name", [
    "restart_wifi", "toggle_hotspot", "reconnect_wifi",
    "tailscale_service_control", "delete_tailscale_auth_key", "restart_dlna",
])
def test_host_changing_system_routes_require_admin(name):
    import inspect
    from fastapi.params import Depends
    from app.routers import system

    parameters = inspect.signature(getattr(system, name)).parameters.values()
    dependencies = [
        item.default.dependency
        for item in parameters if isinstance(item.default, Depends)
    ]
    from app.routers.auth import get_current_admin
    assert get_current_admin in dependencies, name


def test_service_worker_never_intercepts_account_api_or_media():
    source = Path("app/static/sw.js").read_text(encoding="utf-8")
    assert "url.pathname.startsWith('/api/')" in source
    assert "url.pathname.startsWith('/data/')" in source
    assert "API_CACHE_WHITELIST" not in source
