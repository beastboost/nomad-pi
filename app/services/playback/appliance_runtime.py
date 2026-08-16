"""Runtime guardrails for tiny/lightweight Nomad appliances.

The normal playback planner already prefers direct play. This module adds the
operational boundaries that keep failures and fallbacks from turning a small
SBC into a busy transcode/cache machine: bounded HLS concurrency, smaller
buffers/cache lifetime on tiny-memory hosts, explicit storage-I/O errors, and
smaller direct-stream chunks.
"""

from __future__ import annotations

import errno
import logging
import os
import stat
import threading
import weakref

import psutil
from fastapi import HTTPException

from app.services.playback.hls import HLSJobError, HLSManager
from app.services.playback.planner import PlaybackMode


logger = logging.getLogger(__name__)
_INSTALLED = False
_MANAGERS: "weakref.WeakSet[HLSManager]" = weakref.WeakSet()
_REGISTRY_LOCK = threading.Lock()
_ORIGINAL_HLS_INIT = HLSManager.__init__
_ORIGINAL_HLS_ENSURE = HLSManager.ensure_job

_STORAGE_ERRNOS = {
    errno.EIO,
    errno.ENXIO,
    errno.ENODEV,
    errno.ESTALE,
    errno.EROFS,
}


def total_ram_bytes() -> int:
    try:
        return int(psutil.virtual_memory().total)
    except Exception:
        return 0


def appliance_memory_class() -> str:
    total = total_ram_bytes()
    if not total or total < 768 * 1024 ** 2:
        return "tiny"
    if total < 2 * 1024 ** 3:
        return "lite"
    return "normal"


def is_storage_error(exc: BaseException | str) -> bool:
    if isinstance(exc, OSError) and exc.errno in _STORAGE_ERRNOS:
        return True
    text = str(exc or "").lower()
    return any(term in text for term in (
        "input/output error",
        "no such device",
        "stale file handle",
        "transport endpoint is not connected",
        "read-only file system",
        "device or resource busy",
    ))


def storage_error_detail(path: str, exc: BaseException | str) -> str:
    # Keep the literal Input/output error phrase: the browser runtime recognises
    # it as a hard storage failure and deliberately avoids legacy playback retry.
    return f"Storage unavailable (Input/output error) while reading {path}: {exc}"


def assert_source_readable(path: str) -> int:
    try:
        info = os.stat(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Media file not found")
    except OSError as exc:
        if is_storage_error(exc):
            raise HTTPException(status_code=503, detail=storage_error_detail(path, exc))
        raise
    if not stat.S_ISREG(info.st_mode):
        raise HTTPException(status_code=404, detail="Media file not found")

    # Opening the source catches a dead/disconnected mount before ffprobe or
    # FFmpeg gets a chance to spawn and repeatedly hammer it.
    try:
        fd = os.open(path, os.O_RDONLY)
        os.close(fd)
    except OSError as exc:
        if is_storage_error(exc):
            raise HTTPException(status_code=503, detail=storage_error_detail(path, exc))
        raise
    return int(info.st_size)


def _apply_memory_defaults() -> None:
    kind = appliance_memory_class()
    if kind == "tiny":
        os.environ.setdefault("NOMAD_HLS_CACHE_TTL", "3600")
        os.environ.setdefault("NOMAD_HLS_PREBUFFER_SEGMENTS", "2")
        os.environ.setdefault("NOMAD_HLS_PREBUFFER_TIMEOUT", "8")
        os.environ.setdefault("NOMAD_HLS_START_TIMEOUT", "15")
        os.environ.setdefault("NOMAD_HLS_READRATE", "1.5")
    elif kind == "lite":
        os.environ.setdefault("NOMAD_HLS_CACHE_TTL", "7200")
        os.environ.setdefault("NOMAD_HLS_PREBUFFER_SEGMENTS", "3")
        os.environ.setdefault("NOMAD_HLS_PREBUFFER_TIMEOUT", "10")
        os.environ.setdefault("NOMAD_HLS_START_TIMEOUT", "18")


def _register_manager(manager: HLSManager) -> None:
    with _REGISTRY_LOCK:
        _MANAGERS.add(manager)


def _patched_hls_init(self, *args, **kwargs):
    _ORIGINAL_HLS_INIT(self, *args, **kwargs)
    _register_manager(self)


def _active_jobs() -> int:
    total = 0
    with _REGISTRY_LOCK:
        managers = list(_MANAGERS)
    for manager in managers:
        try:
            with manager._lock:
                total += sum(
                    1 for job in manager._jobs.values()
                    if job.process and job.process.poll() is None
                )
        except Exception:
            continue
    return total


def _same_session_active(manager: HLSManager, session_id: str) -> bool:
    try:
        with manager._lock:
            job = manager._jobs.get(session_id)
            return bool(job and job.process and job.process.poll() is None)
    except Exception:
        return False


def _bounded_ensure_job(self, *args, **kwargs):
    session_id = str(kwargs.get("session_id") or "")
    if session_id and _same_session_active(self, session_id):
        return _ORIGINAL_HLS_ENSURE(self, *args, **kwargs)

    mode_raw = kwargs.get("mode")
    try:
        mode = mode_raw if isinstance(mode_raw, PlaybackMode) else PlaybackMode(mode_raw)
    except Exception:
        mode = None

    kind = appliance_memory_class()
    active = _active_jobs()
    if mode == PlaybackMode.TRANSCODE_VIDEO:
        # An explicit live-transcode opt-in should still never spawn multiple
        # video encoders on tiny/lite appliances.
        limit = 1 if kind in {"tiny", "lite"} else 2
    else:
        # Two cheap jobs allow a brief seek/hand-over without letting remuxes
        # pile up across tabs/devices.
        limit = 2 if kind in {"tiny", "lite"} else 4
    if active >= limit:
        raise HLSJobError(
            f"Playback converter busy ({active}/{limit} active jobs); direct-play media is still available"
        )
    return _ORIGINAL_HLS_ENSURE(self, *args, **kwargs)


def install_appliance_runtime(core_module) -> None:
    """Install resource/storage guardrails into the already-imported core."""
    global _INSTALLED
    if _INSTALLED:
        _register_manager(core_module.hls_manager)
        return

    _apply_memory_defaults()
    _register_manager(core_module.hls_manager)
    HLSManager.__init__ = _patched_hls_init
    HLSManager.ensure_job = _bounded_ensure_job

    def resilient_resolve_and_probe(web_path: str):
        try:
            fs_path = core_module.safe_fs_path_from_web_path(web_path)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid media path")

        assert_source_readable(fs_path)
        try:
            source = core_module.probe_media(fs_path)
        except core_module.ProbeError as exc:
            message = str(exc)
            if is_storage_error(exc):
                raise HTTPException(status_code=503, detail=storage_error_detail(fs_path, exc))
            status_code = 503 if "not installed" in message else 422
            raise HTTPException(status_code=status_code, detail=message)
        except OSError as exc:
            if is_storage_error(exc):
                raise HTTPException(status_code=503, detail=storage_error_detail(fs_path, exc))
            raise
        return fs_path, source

    def resilient_file_chunks(path: str, start: int, length: int, chunk_size: int | None = None):
        if chunk_size is None:
            chunk_size = 256 * 1024 if appliance_memory_class() == "tiny" else 512 * 1024
        remaining = length
        try:
            with open(path, "rb", buffering=0) as handle:
                handle.seek(start)
                while remaining > 0:
                    chunk = handle.read(min(int(chunk_size), remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        except OSError as exc:
            if is_storage_error(exc):
                logger.error("Direct playback storage read failed for %s: %s", path, exc)
            raise

    core_module._resolve_and_probe = resilient_resolve_and_probe
    core_module._file_chunks = resilient_file_chunks
    _INSTALLED = True
