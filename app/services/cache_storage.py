"""Storage-aware placement for transient Nomad caches.

Playback caches must never be allowed to consume the appliance filesystem just
because persistent media failover exists elsewhere. This module deliberately
shares the storage.failover policy without importing the very large media
router, keeping playback services free of router-level circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
from typing import Optional

from app import database


class CacheStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class CacheVolume:
    root: Path
    external: bool
    free_bytes: int
    total_bytes: int
    free_percent: float


_CATEGORIES = ("movies", "shows", "music", "books", "gallery", "files")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _data_root() -> Path:
    return (_repo_root() / "data").resolve()


def _setting_int(key: str, default: int) -> int:
    try:
        return int(str(database.get_setting(key) or default).strip())
    except (TypeError, ValueError):
        return int(default)


def _failover_enabled() -> bool:
    return bool(_setting_int("storage.failover.enabled", 0))


def _reserve_percent() -> int:
    return max(5, min(50, _setting_int("storage.failover.threshold_free_percent", 20)))


def _web_to_fs(value: str) -> Optional[Path]:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return None
    if raw == "/data" or raw.startswith("/data/"):
        rel = raw[len("/data"):].lstrip("/")
        return (_data_root() / rel).resolve()
    if raw == "/media" or raw.startswith("/media/") or raw == "/mnt" or raw.startswith("/mnt/"):
        return Path(raw).resolve()
    return None


def configured_failover_root() -> Optional[Path]:
    """Return the common external root configured by Storage & Drives."""
    roots: list[Path] = []
    for category in _CATEGORIES:
        target = _web_to_fs(database.get_setting(f"storage.failover.target.{category}") or "")
        if target is not None:
            roots.append(target.parent)
    if not roots:
        return None
    first = roots[0]
    if all(path == first for path in roots[1:]):
        return first
    files = _web_to_fs(database.get_setting("storage.failover.target.files") or "")
    return files.parent if files is not None else first


def _usage(path: Path):
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(str(probe))


def _volume(path: Path, *, external: bool) -> CacheVolume:
    usage = _usage(path)
    pct = (usage.free / usage.total * 100.0) if usage.total else 0.0
    return CacheVolume(
        root=path,
        external=external,
        free_bytes=int(usage.free),
        total_bytes=int(usage.total),
        free_percent=float(pct),
    )


def _minimum_free_bytes() -> int:
    raw = str(os.environ.get("NOMAD_CACHE_MIN_FREE_MB", "256")).strip()
    try:
        mb = max(64, min(16384, int(raw)))
    except (TypeError, ValueError):
        mb = 256
    return mb * 1024 * 1024


def cache_root_candidates(primary_root: str | Path) -> list[Path]:
    """Return primary plus the configured external equivalent, without mkdir."""
    primary = Path(primary_root).resolve()
    roots = [primary]
    if _failover_enabled():
        external = configured_failover_root()
        if external is not None:
            kind = primary.name
            candidate = (external / ".nomad_cache" / kind).resolve()
            if candidate != primary:
                roots.append(candidate)
    return roots


def choose_cache_root(
    primary_root: str | Path,
    *,
    expected_bytes: int = 0,
) -> CacheVolume:
    """Choose a safe volume for a new transient cache session.

    ``expected_bytes`` is a conservative estimate of how much this session may
    write.  A local remux can approach the source file size, so checking only
    the current free percentage is not sufficient to protect a small boot disk.
    """
    primary = Path(primary_root).resolve()
    reserve = _reserve_percent()
    minimum = _minimum_free_bytes()
    expected = max(0, int(expected_bytes or 0))

    override = str(os.environ.get("NOMAD_CACHE_ROOT", "")).strip()
    if override:
        base = Path(override).expanduser().resolve()
        candidate = base / primary.name
        vol = _volume(candidate, external=not str(candidate).startswith(str(_data_root())))
        required = minimum + expected
        if vol.free_bytes < required:
            raise CacheStorageError(
                f"Configured cache volume has only {vol.free_bytes // (1024 * 1024)} MB free; "
                f"this session needs about {required // (1024 * 1024)} MB including safety headroom"
            )
        candidate.mkdir(parents=True, exist_ok=True)
        return vol

    primary_vol = _volume(primary, external=False)
    reserve_bytes = max(minimum, int(primary_vol.total_bytes * (reserve / 100.0)))
    safe_headroom = max(0, primary_vol.free_bytes - reserve_bytes)
    primary_safe = (
        primary_vol.free_percent > reserve
        and primary_vol.free_bytes >= minimum
        and (expected <= safe_headroom if expected else True)
    )
    if primary_safe:
        try:
            primary.mkdir(parents=True, exist_ok=True)
            return primary_vol
        except OSError:
            pass

    if _failover_enabled():
        external_base = configured_failover_root()
        if external_base is not None:
            external_root = (external_base / ".nomad_cache" / primary.name).resolve()
            ext = _volume(external_root, external=True)
            # Keep an absolute reserve on the external drive, but do not waste
            # a fixed percentage of a multi-terabyte media disk.
            required = minimum + expected
            if ext.free_bytes >= required:
                try:
                    external_root.mkdir(parents=True, exist_ok=True)
                    return ext
                except OSError:
                    pass

    free_mb = primary_vol.free_bytes // (1024 * 1024)
    expected_mb = expected // (1024 * 1024)
    footprint = f"; estimated session cache {expected_mb} MB" if expected else ""
    suffix = (
        " and no usable external failover cache is configured"
        if not _failover_enabled()
        else " and the configured external failover cache is unavailable or lacks enough headroom"
    )
    raise CacheStorageError(
        f"Internal storage cannot preserve the {reserve}% safety reserve ({free_mb} MB free{footprint}){suffix}. "
        "Free space or configure Storage & Drives → Automatic storage failover."
    )
