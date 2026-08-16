from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import cache_storage
from app.services.playback import cache_guard
from app.services.playback.hls import HLSJobError, HLSManager


def _volume(path: Path, *, external: bool, free_mb: int, total_mb: int = 1024):
    free = free_mb * 1024 * 1024
    total = total_mb * 1024 * 1024
    return cache_storage.CacheVolume(
        root=path,
        external=external,
        free_bytes=free,
        total_bytes=total,
        free_percent=(free / total * 100.0),
    )


def test_cache_uses_external_failover_when_internal_hits_reserve(tmp_path, monkeypatch):
    primary = tmp_path / "internal" / ".nomad_cache" / "hls"
    external = tmp_path / "usb"

    monkeypatch.setattr(cache_storage, "_reserve_percent", lambda: 20)
    monkeypatch.setattr(cache_storage, "_minimum_free_bytes", lambda: 64 * 1024 * 1024)
    monkeypatch.setattr(cache_storage, "_failover_enabled", lambda: True)
    monkeypatch.setattr(cache_storage, "configured_failover_root", lambda: external)

    def fake_volume(path, *, external):
        path = Path(path)
        if external:
            return _volume(path, external=True, free_mb=800)
        return _volume(path, external=False, free_mb=100)

    monkeypatch.setattr(cache_storage, "_volume", fake_volume)
    selected = cache_storage.choose_cache_root(primary)

    assert selected.external is True
    assert selected.root == (external / ".nomad_cache" / "hls").resolve()
    assert selected.root.is_dir()


def test_cache_refuses_to_fill_internal_disk_without_failover(tmp_path, monkeypatch):
    primary = tmp_path / "internal" / ".nomad_cache" / "hls"
    monkeypatch.setattr(cache_storage, "_reserve_percent", lambda: 20)
    monkeypatch.setattr(cache_storage, "_minimum_free_bytes", lambda: 64 * 1024 * 1024)
    monkeypatch.setattr(cache_storage, "_failover_enabled", lambda: False)
    monkeypatch.setattr(
        cache_storage,
        "_volume",
        lambda path, external: _volume(Path(path), external=False, free_mb=20),
    )

    with pytest.raises(cache_storage.CacheStorageError, match="safety reserve"):
        cache_storage.choose_cache_root(primary)


def test_hls_guard_converts_full_disk_into_playback_error(tmp_path, monkeypatch):
    cache_guard.install_playback_cache_guard()
    manager = HLSManager(root=str(tmp_path / "hls"))

    monkeypatch.setattr(
        cache_guard,
        "choose_cache_root",
        lambda _root: (_ for _ in ()).throw(cache_storage.CacheStorageError("disk full safely")),
    )
    monkeypatch.setattr(cache_guard, "_cleanup_roots", lambda *args, **kwargs: 0)

    with pytest.raises(HLSJobError, match="disk full safely"):
        cache_guard._select_session_dir(manager, "session-1", HLSJobError)


def test_force_cleanup_keeps_active_session(tmp_path):
    root = tmp_path / "hls"
    active_dir = root / "active"
    stale_dir = root / "stale"
    active_dir.mkdir(parents=True)
    stale_dir.mkdir(parents=True)
    (active_dir / "segment_00001.m4s").write_bytes(b"active")
    (stale_dir / "segment_00001.m4s").write_bytes(b"stale")

    manager = SimpleNamespace(
        root=root,
        _jobs={"active": SimpleNamespace(process=SimpleNamespace(poll=lambda: None))},
        _nomad_session_dirs={},
    )

    removed = cache_guard._cleanup_roots(manager, ttl_seconds=0, force=True)
    assert removed == 1
    assert active_dir.exists()
    assert not stale_dir.exists()
