import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.stream_keep import StreamKeepManager, StreamKeepStore
from app.routers import playback_stream_keep


def test_stream_keep_store_is_persistent_and_user_scoped(tmp_path):
    db = str(tmp_path / "stream-keep.db")
    first = StreamKeepStore(db_path=db)
    created = first.create(
        user_id=7,
        provider="rd",
        remote_url="https://cdn.example.test/movie.mkv?secret=abc",
        filename="Movie.mkv",
        category="movies",
        is_show=False,
        metadata={"title": "Movie"},
    )
    first.update(created.id, user_id=7, status="downloading", progress=12.5, download_id="dl-1")

    second = StreamKeepStore(db_path=db)
    restored = second.get(created.id, user_id=7)
    assert restored is not None
    assert restored.status == "downloading"
    assert restored.progress == 12.5
    assert restored.download_id == "dl-1"
    assert restored.metadata["title"] == "Movie"
    assert second.get(created.id, user_id=99) is None


def test_public_stream_keep_dict_never_exposes_remote_url(tmp_path):
    store = StreamKeepStore(db_path=str(tmp_path / "stream-keep.db"))
    job = store.create(
        user_id=1,
        provider="ad",
        remote_url="https://cdn.example.test/private-token/file.mp4",
        filename="file.mp4",
        category="movies",
        is_show=False,
    )
    assert "remote_url" not in job.to_dict()
    assert job.to_dict(include_remote=True)["remote_url"].startswith("https://")


def test_start_download_reuses_existing_debrid_worker(monkeypatch, tmp_path):
    store = StreamKeepStore(db_path=str(tmp_path / "stream-keep.db"))
    manager = StreamKeepManager(store)
    job = store.create(
        user_id=1,
        provider="tb",
        remote_url="https://cdn.example.test/file.mkv",
        filename="file.mkv",
        category="movies",
        is_show=False,
    )
    calls = []
    monkeypatch.setattr(
        "app.services.stream_keep.debrid.download_to_pi",
        lambda provider, url, filename, category, is_show: calls.append((provider, url, filename, category, is_show)) or "dl-123",
    )
    # Prevent a real monitor thread for this focused orchestration test.
    monkeypatch.setattr(manager, "_start_monitor", lambda *args, **kwargs: None)

    updated = manager.start_download(job)
    assert updated.status == "downloading"
    assert updated.download_id == "dl-123"
    assert calls == [("", job.remote_url, "file.mkv", "movies", False)]


def test_monitor_promotes_completed_download_to_local_ready(monkeypatch, tmp_path):
    store = StreamKeepStore(db_path=str(tmp_path / "stream-keep.db"))
    manager = StreamKeepManager(store)
    job = store.create(
        user_id=1,
        provider="rd",
        remote_url="https://cdn.example.test/file.mkv",
        filename="file.mkv",
        category="movies",
        is_show=False,
    )
    job = store.update(job.id, user_id=1, status="downloading", download_id="dl-1")
    monkeypatch.setattr(
        "app.services.stream_keep.debrid.get_download_status",
        lambda download_id: {
            "status": "completed",
            "progress": 100,
            "size_total": 1000,
            "size_downloaded": 1000,
            "speed": 0,
            "dest_path": "/tmp/local/Movie/file.mkv",
            "error": None,
        },
    )
    monkeypatch.setattr(manager, "_web_path_from_dest", lambda path: "/data/movies/Movie/file.mkv")

    manager._monitor(job.id, 1, "dl-1")
    restored = store.get(job.id, user_id=1)
    assert restored.status == "local_ready"
    assert restored.local_path == "/data/movies/Movie/file.mkv"
    assert restored.progress == 100


def test_cancel_stops_underlying_keep_download(monkeypatch, tmp_path):
    store = StreamKeepStore(db_path=str(tmp_path / "stream-keep.db"))
    manager = StreamKeepManager(store)
    job = store.create(
        user_id=1,
        provider="rd",
        remote_url="https://cdn.example.test/file.mkv",
        filename="file.mkv",
        category="movies",
        is_show=False,
    )
    job = store.update(job.id, user_id=1, status="downloading", download_id="dl-9")
    cancelled = []
    monkeypatch.setattr(
        "app.services.stream_keep.debrid.cancel_download",
        lambda download_id: cancelled.append(download_id) or True,
    )
    updated = manager.cancel(job)
    assert cancelled == ["dl-9"]
    assert updated.status == "cancelled"


def test_remote_url_validation_rejects_private_redirect(monkeypatch):
    monkeypatch.setattr(playback_stream_keep.debrid, "is_safe_external_url", lambda url: not url.startswith("http://127."))
    fake = SimpleNamespace(url="http://127.0.0.1/admin", close=lambda: None)
    monkeypatch.setattr(playback_stream_keep.debrid, "safe_head", lambda *args, **kwargs: fake)
    with pytest.raises(HTTPException) as exc:
        playback_stream_keep._validated_remote_url("https://public.example.test/file")
    assert exc.value.status_code == 400


def test_remote_url_validation_returns_safe_final_url(monkeypatch):
    monkeypatch.setattr(playback_stream_keep.debrid, "is_safe_external_url", lambda url: url.startswith("https://"))
    fake = SimpleNamespace(url="https://cdn2.example.test/final.mkv", close=lambda: None)
    monkeypatch.setattr(playback_stream_keep.debrid, "safe_head", lambda *args, **kwargs: fake)
    assert playback_stream_keep._validated_remote_url("https://public.example.test/file") == "https://cdn2.example.test/final.mkv"
