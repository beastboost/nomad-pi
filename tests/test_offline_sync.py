from pathlib import Path

from app.services.offline_sync import OfflineSyncManager, OfflineSyncStore, QUALITY
from app.services.playback.planner import MediaProbe


def test_offline_store_persists_and_is_user_scoped(tmp_path):
    db = str(tmp_path / "offline.db")
    first = OfflineSyncStore(db_path=db)
    job = first.create(
        user_id=4,
        source_path="/data/movies/Test.mkv",
        source_fs_path=str(tmp_path / "Test.mkv"),
        quality="720p",
        metadata={"source_name": "Test.mkv"},
    )
    first.update(job.id, user_id=4, status="running", progress=25.5, duration=120.0)

    # A fresh store represents a service restart; in-flight work is requeued.
    second = OfflineSyncStore(db_path=db)
    restored = second.get(job.id, user_id=4)
    assert restored is not None
    assert restored.status == "queued"
    assert restored.progress == 25.5
    assert restored.duration == 120.0
    assert second.get(job.id, user_id=99) is None


def test_find_existing_deduplicates_active_or_ready_copy(tmp_path):
    store = OfflineSyncStore(db_path=str(tmp_path / "offline.db"))
    job = store.create(
        user_id=1,
        source_path="/data/movies/A.mkv",
        source_fs_path="/tmp/A.mkv",
        quality="1080p",
    )
    assert store.find_existing(user_id=1, source_path=job.source_path, quality="1080p").id == job.id
    store.update(job.id, user_id=1, status="cancelled")
    assert store.find_existing(user_id=1, source_path=job.source_path, quality="1080p") is None


def test_scale_filter_preserves_aspect_and_never_upscales(tmp_path):
    manager = OfflineSyncManager(
        OfflineSyncStore(db_path=str(tmp_path / "offline.db")),
        root=str(tmp_path / "out"),
    )
    source_4k = MediaProbe(container="mkv", video_codec="hevc", audio_codec="ac3", width=3840, height=2160)
    assert manager._scale_filter(source_4k, QUALITY["1080p"]) == "scale=1920:1080"
    assert manager._scale_filter(source_4k, QUALITY["720p"]) == "scale=1280:720"
    source_720 = MediaProbe(container="mp4", video_codec="h264", audio_codec="aac", width=1280, height=720)
    assert manager._scale_filter(source_720, QUALITY["1080p"]) is None


def test_compatible_h264_aac_uses_stream_copy(monkeypatch, tmp_path):
    store = OfflineSyncStore(db_path=str(tmp_path / "offline.db"))
    manager = OfflineSyncManager(store, root=str(tmp_path / "out"))
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"x")
    job = store.create(
        user_id=1,
        source_path="/data/movies/movie.mp4",
        source_fs_path=str(source),
        quality="original",
    )
    probe = MediaProbe(container="mp4", video_codec="h264", audio_codec="aac", width=1920, height=1080)
    output = tmp_path / "out.mp4"
    commands = manager._commands(job, probe, output)
    assert len(commands) == 1
    label, cmd = commands[0]
    assert label == "copy"
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "-vf" not in cmd


def test_incompatible_source_builds_hardware_then_software_candidates(monkeypatch, tmp_path):
    store = OfflineSyncStore(db_path=str(tmp_path / "offline.db"))
    manager = OfflineSyncManager(store, root=str(tmp_path / "out"))
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"x")
    job = store.create(
        user_id=1,
        source_path="/data/movies/movie.mkv",
        source_fs_path=str(source),
        quality="720p",
    )
    probe = MediaProbe(container="mkv", video_codec="hevc", audio_codec="ac3", width=3840, height=2160)
    monkeypatch.setattr(
        "app.services.offline_sync.video_encoder_candidates",
        lambda codec: ["h264_v4l2m2m", "libx264"],
    )
    monkeypatch.setattr(
        "app.services.offline_sync.video_encoder_args",
        lambda encoder, max_bitrate=None: ["-b:v", str(max_bitrate or 1)],
    )
    commands = manager._commands(job, probe, tmp_path / "out.mp4")
    assert [label for label, _ in commands] == ["h264_v4l2m2m", "libx264"]
    for _label, cmd in commands:
        assert cmd[cmd.index("-c:a") + 1] == "aac"
        assert cmd[cmd.index("-vf") + 1] == "scale=1280:720"
        assert cmd[cmd.index("-b:v") + 1] == "4000000"


def test_retry_only_requeues_failed_or_cancelled(tmp_path):
    store = OfflineSyncStore(db_path=str(tmp_path / "offline.db"))
    manager = OfflineSyncManager(store, root=str(tmp_path / "out"))
    job = store.create(
        user_id=1,
        source_path="/data/movies/movie.mkv",
        source_fs_path="/missing/movie.mkv",
        quality="480p",
    )
    # Do not actually launch a worker in this focused state test.
    manager.start = lambda _job: None
    assert manager.retry(job).status == "queued"
    failed = store.update(job.id, user_id=1, status="failed", error="boom")
    retried = manager.retry(failed)
    assert retried.status == "queued"
    assert retried.progress == 0
    assert retried.error is None
