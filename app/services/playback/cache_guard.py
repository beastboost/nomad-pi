"""Storage-pressure guard for HLS and adaptive playback caches.

This is installed before the optional playback routers create their managers.
It keeps cache placement policy out of the transcoder implementations while
making every HLSManager/ABRManager instance use the same storage reserve and
external-failover behaviour.
"""

from __future__ import annotations

from pathlib import Path
import errno
import os
import shutil
import threading
import time
from typing import Optional

from app.services.cache_storage import (
    CacheStorageError,
    cache_root_candidates,
    choose_cache_root,
)
from app.services.playback.hls import HLSJobError, HLSManager
from app.services.playback.abr import ABRJobError, ABRManager


_INSTALLED = False
_INSTALL_LOCK = threading.Lock()


def _session_map(manager) -> dict[str, Path]:
    mapping = getattr(manager, "_nomad_session_dirs", None)
    if mapping is None:
        mapping = {}
        setattr(manager, "_nomad_session_dirs", mapping)
    return mapping


def _active_ids(manager) -> set[str]:
    jobs = getattr(manager, "_jobs", {}) or {}
    return {
        str(session_id)
        for session_id, job in jobs.items()
        if getattr(job, "process", None) is not None
        and job.process.poll() is None
    }


def _cleanup_roots(manager, *, ttl_seconds: Optional[float] = None, force: bool = False) -> int:
    if ttl_seconds is None:
        try:
            ttl_seconds = float(os.environ.get("NOMAD_HLS_CACHE_TTL", "3600"))
        except (TypeError, ValueError):
            ttl_seconds = 3600.0
    ttl_seconds = max(0.0 if force else 60.0, float(ttl_seconds))
    cutoff = time.time() - ttl_seconds
    active = _active_ids(manager)
    removed = 0

    roots = cache_root_candidates(getattr(manager, "root"))
    # Include roots already selected for active/recent sessions even if the
    # failover setting was changed after those sessions started.
    for directory in _session_map(manager).values():
        root = directory.parent
        if root not in roots:
            roots.append(root)

    for root in roots:
        try:
            children = list(Path(root).iterdir())
        except OSError:
            continue
        for directory in children:
            if not directory.is_dir() or directory.name in active:
                continue
            try:
                newest = directory.stat().st_mtime
                for item in directory.iterdir():
                    try:
                        newest = max(newest, item.stat().st_mtime)
                    except OSError:
                        pass
                if not force and newest >= cutoff:
                    continue
                shutil.rmtree(directory, ignore_errors=True)
                if not directory.exists():
                    removed += 1
                    # A stale mapping must not keep pointing at a deleted dir.
                    _session_map(manager).pop(directory.name, None)
            except OSError:
                continue
    return removed


def _select_session_dir(manager, session_id: str, error_type):
    mapping = _session_map(manager)
    existing = mapping.get(session_id)
    if existing is not None:
        return existing

    # Normal cleanup first. Under pressure, retry after evicting every inactive
    # session immediately; a crashed playback session should never strand GBs
    # of cache for an hour while the boot filesystem is full.
    _cleanup_roots(manager)
    try:
        volume = choose_cache_root(getattr(manager, "root"))
    except CacheStorageError:
        _cleanup_roots(manager, ttl_seconds=0, force=True)
        try:
            volume = choose_cache_root(getattr(manager, "root"))
        except CacheStorageError as exc:
            raise error_type(str(exc)) from exc

    directory = Path(volume.root) / session_id
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise error_type(
                "Playback cache volume ran out of space before the stream could start"
            ) from exc
        raise
    mapping[session_id] = directory
    return directory


def _install_manager_guard(cls, error_type):
    if getattr(cls, "_nomad_cache_guard_installed", False):
        return

    original_session_dir = cls.session_dir
    original_ensure = cls.ensure_job
    original_stop = cls.stop

    def session_dir(self, session_id: str):
        mapped = _session_map(self).get(str(session_id))
        if mapped is not None:
            return mapped
        return original_session_dir(self, session_id)

    def cleanup_cache(self, ttl_seconds: Optional[float] = None):
        return _cleanup_roots(self, ttl_seconds=ttl_seconds)

    def ensure_job(self, *args, **kwargs):
        session_id = kwargs.get("session_id")
        if session_id is None and args:
            # Both current managers expose session_id as keyword-only, but keep
            # this defensive path for older installs/tests.
            session_id = args[0]
        session_id = str(session_id or "")
        if not session_id:
            raise error_type("Playback cache session id is missing")

        _select_session_dir(self, session_id, error_type)
        try:
            return original_ensure(self, *args, **kwargs)
        except OSError as exc:
            if exc.errno != errno.ENOSPC:
                raise
            # A concurrent download can consume the last free blocks between
            # selection and mkdir/FFmpeg startup. Evict stale caches once, then
            # convert the raw OS exception into a useful playback error.
            _cleanup_roots(self, ttl_seconds=0, force=True)
            raise error_type(
                "Playback cache ran out of space. Free storage or enable an external failover volume."
            ) from exc

    def stop(self, session_id: str, *, remove_cache: bool = False):
        try:
            return original_stop(self, session_id, remove_cache=remove_cache)
        finally:
            if remove_cache:
                _session_map(self).pop(str(session_id), None)

    cls.session_dir = session_dir
    cls.cleanup_cache = cleanup_cache
    cls.ensure_job = ensure_job
    cls.stop = stop
    cls._nomad_cache_guard_installed = True


def install_playback_cache_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_manager_guard(HLSManager, HLSJobError)
        _install_manager_guard(ABRManager, ABRJobError)
        _INSTALLED = True
