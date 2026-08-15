"""Resumable local-copy downloader used by Stream + Keep.

Unlike the legacy debrid downloader this worker writes to a stable ``.part``
file and can continue it after a Nomad process restart when the remote host
honours HTTP byte ranges. A tiny sidecar stores the remote validator so resumed
requests can use ``If-Range`` and safely fall back to a clean restart if the
provider serves a different object.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import uuid
from typing import Dict, Optional
from urllib.parse import urljoin

import requests

from app.services import debrid

logger = logging.getLogger(__name__)

_states: Dict[str, dict] = {}
_cancelled: set[str] = set()
_lock = threading.Lock()


def _copy_state(download_id: str) -> Optional[dict]:
    with _lock:
        state = _states.get(download_id)
        return dict(state) if state else None


def get_status(download_id: str) -> Optional[dict]:
    return _copy_state(download_id)


def list_status() -> list[dict]:
    with _lock:
        return [dict(value) for value in _states.values()]


def cancel(download_id: str) -> bool:
    with _lock:
        if download_id not in _states:
            return False
        _cancelled.add(download_id)
        _states[download_id]["status"] = "cancelled"
        _states[download_id]["speed"] = 0
        return True


def _cancel_requested(download_id: str) -> bool:
    with _lock:
        return download_id in _cancelled or _states.get(download_id, {}).get("status") == "cancelled"


def _update(download_id: str, **values) -> None:
    with _lock:
        if download_id in _states:
            _states[download_id].update(values)


def _safe_get(url: str, *, headers: Optional[dict] = None, timeout=(10, 45), max_redirects: int = 5):
    current = str(url)
    request_headers = {"User-Agent": "NomadPi/2.0"}
    request_headers.update(headers or {})
    for _ in range(max_redirects + 1):
        if not debrid.is_safe_external_url(current):
            raise ValueError("Unsafe Stream + Keep download URL")
        response = requests.get(
            current,
            headers=request_headers,
            stream=True,
            allow_redirects=False,
            timeout=timeout,
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location") or response.headers.get("location")
            response.close()
            if not location:
                raise ValueError("Remote redirect had no destination")
            current = urljoin(current, location)
            continue
        return response
    raise ValueError("Too many Stream + Keep redirects")


def _parse_content_range(value: str) -> tuple[Optional[int], Optional[int]]:
    """Return (start, total) for ``bytes START-END/TOTAL`` or ``bytes */TOTAL``."""
    text = str(value or "").strip()
    match = re.match(r"bytes\s+(\d+)-\d+/(\d+|\*)$", text, flags=re.I)
    if match:
        total = None if match.group(2) == "*" else int(match.group(2))
        return int(match.group(1)), total
    match = re.match(r"bytes\s+\*/(\d+)$", text, flags=re.I)
    if match:
        return None, int(match.group(1))
    return None, None


def _sidecar_path(final_path: str) -> str:
    return f"{final_path}.resume.json"


def _part_path(final_path: str) -> str:
    return f"{final_path}.part"


def _load_sidecar(final_path: str) -> dict:
    try:
        with open(_sidecar_path(final_path), "r", encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_sidecar(final_path: str, *, etag: str, last_modified: str, total: int, url: str) -> None:
    path = _sidecar_path(final_path)
    tmp = f"{path}.tmp"
    payload = {
        "etag": str(etag or ""),
        "last_modified": str(last_modified or ""),
        "total": int(total or 0),
        # The URL is internal state only. It never leaves the server API.
        "url": str(url or ""),
        "updated_at": time.time(),
    }
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _remove_sidecar(final_path: str) -> None:
    try:
        os.remove(_sidecar_path(final_path))
    except OSError:
        pass


def _category(filename: str, category: str, is_show: bool) -> str:
    if category and category != "auto":
        return category
    if is_show:
        return "shows"
    return debrid._get_category_from_filename(filename)  # shared legacy classifier


def choose_destination(filename: str, category: str = "auto", is_show: bool = False) -> tuple[str, str]:
    """Choose a stable final destination once; callers persist it for recovery."""
    from app.routers import media

    clean = debrid._sanitize_filename(str(filename or "download"))
    resolved_category = _category(clean, category, is_show)
    root = media.pick_effective_storage_root_fs(resolved_category)
    if resolved_category in {"movies", "shows"}:
        dest_dir = os.path.join(root, os.path.splitext(clean)[0])
    else:
        dest_dir = root
    os.makedirs(dest_dir, exist_ok=True)
    final_path = media.pick_unique_dest(os.path.join(dest_dir, clean))
    return final_path, resolved_category


def _web_path(final_path: str) -> str:
    from app.routers import media

    abs_base = os.path.abspath(media.BASE_DIR)
    abs_dest = os.path.abspath(final_path)
    try:
        if os.path.commonpath([abs_base, abs_dest]) == abs_base:
            rel = os.path.relpath(abs_dest, abs_base).replace(os.sep, "/")
            return f"/data/{rel}"
    except ValueError:
        pass

    ext_root = os.path.join(media.BASE_DIR, "external")
    if os.path.isdir(ext_root):
        for item in os.listdir(ext_root):
            link_path = os.path.join(ext_root, item)
            if not os.path.islink(link_path):
                continue
            target = os.path.realpath(link_path)
            try:
                if os.path.commonpath([target, abs_dest]) == target:
                    rel = os.path.relpath(abs_dest, target).replace(os.sep, "/")
                    return f"/data/external/{item}/{rel}"
            except ValueError:
                continue
    return abs_dest


def _index_completed(final_path: str, category: str) -> str:
    from app.routers import media

    web_path = _web_path(final_path)
    st = os.stat(final_path)
    root = media.pick_effective_storage_root_fs(category)
    try:
        folder = os.path.relpath(os.path.dirname(final_path), root).replace(os.sep, "/")
    except ValueError:
        folder = ""
    if folder == ".":
        folder = ""
    media.database.upsert_library_index_item({
        "path": web_path,
        "category": category,
        "name": os.path.basename(final_path),
        "folder": folder,
        "source": "debrid",
        "poster": None,
        "mtime": float(st.st_mtime),
        "size": int(st.st_size),
    })
    return web_path


def start_download(
    *,
    url: str,
    filename: str,
    category: str = "auto",
    is_show: bool = False,
    dest_path: Optional[str] = None,
    download_id: Optional[str] = None,
) -> str:
    if not debrid.is_safe_external_url(url):
        raise ValueError("Refusing to download from a non-public URL")

    resolved_category = _category(debrid._sanitize_filename(filename or "download"), category, is_show)
    if dest_path:
        final_path = os.path.abspath(dest_path)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
    else:
        final_path, resolved_category = choose_destination(filename, resolved_category, is_show)

    ident = download_id or f"sk_{uuid.uuid4().hex}"
    partial = _part_path(final_path)
    existing = os.path.getsize(partial) if os.path.isfile(partial) else 0
    with _lock:
        _cancelled.discard(ident)
        _states[ident] = {
            "id": ident,
            "filename": os.path.basename(final_path),
            "category": resolved_category,
            "dest_path": final_path,
            "part_path": partial,
            "status": "downloading",
            "progress": 0.0,
            "speed": 0,
            "size_total": 0,
            "size_downloaded": existing,
            "resumed_from": existing,
            "range_supported": None,
            "error": None,
            "started_at": time.time(),
        }

    threading.Thread(
        target=_worker,
        args=(ident, str(url), final_path, resolved_category),
        daemon=True,
        name=f"stream-keep-download-{ident[-8:]}",
    ).start()
    return ident


def _finalize(download_id: str, final_path: str, category: str, downloaded: int, total: int) -> None:
    partial = _part_path(final_path)
    if os.path.isfile(partial):
        os.replace(partial, final_path)
    _remove_sidecar(final_path)
    web_path = _index_completed(final_path, category)
    size = os.path.getsize(final_path)
    _update(
        download_id,
        status="completed",
        progress=100.0,
        speed=0,
        size_total=int(total or size),
        size_downloaded=int(size),
        local_path=web_path,
        error=None,
    )


def _worker(download_id: str, url: str, final_path: str, category: str) -> None:
    max_retries = 4
    retry_delay = 3
    partial = _part_path(final_path)

    for attempt in range(max_retries):
        response = None
        try:
            if _cancel_requested(download_id):
                return

            existing = os.path.getsize(partial) if os.path.isfile(partial) else 0
            sidecar = _load_sidecar(final_path)
            headers = {}
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
                validator = sidecar.get("etag") or sidecar.get("last_modified")
                if validator:
                    headers["If-Range"] = str(validator)

            response = _safe_get(url, headers=headers)
            if response.status_code == 416 and existing > 0:
                _start, remote_total = _parse_content_range(response.headers.get("Content-Range", ""))
                response.close()
                response = None
                if remote_total and existing == remote_total:
                    _finalize(download_id, final_path, category, existing, remote_total)
                    return
                # The partial no longer matches the remote object. Restart it.
                try:
                    os.remove(partial)
                except OSError:
                    pass
                _remove_sidecar(final_path)
                continue

            response.raise_for_status()
            range_start, range_total = _parse_content_range(response.headers.get("Content-Range", ""))
            resumed = bool(existing > 0 and response.status_code == 206 and range_start == existing)

            # If the host ignored Range/If-Range it deliberately returned 200.
            # Truncate the partial rather than appending a second copy.
            if existing > 0 and not resumed:
                existing = 0
                try:
                    os.remove(partial)
                except OSError:
                    pass
                _remove_sidecar(final_path)

            content_length = int(response.headers.get("Content-Length") or response.headers.get("content-length") or 0)
            total = int(range_total or ((existing + content_length) if response.status_code == 206 else content_length) or sidecar.get("total") or 0)
            etag = response.headers.get("ETag") or response.headers.get("etag") or ""
            last_modified = response.headers.get("Last-Modified") or response.headers.get("last-modified") or ""
            _save_sidecar(final_path, etag=etag, last_modified=last_modified, total=total, url=url)

            downloaded = existing
            last_bytes = downloaded
            last_time = time.monotonic()
            _update(
                download_id,
                status="downloading",
                size_total=total,
                size_downloaded=downloaded,
                resumed_from=existing,
                range_supported=(response.status_code == 206),
                error=None,
            )

            mode = "ab" if resumed else "wb"
            with open(partial, mode) as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if _cancel_requested(download_id):
                        _update(download_id, status="cancelled", speed=0, size_downloaded=downloaded)
                        return
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    elapsed = now - last_time
                    if elapsed >= 0.75:
                        speed = int((downloaded - last_bytes) / max(elapsed, 0.001))
                        pct = (downloaded / total * 100.0) if total > 0 else 0.0
                        _update(
                            download_id,
                            progress=round(min(99.9, pct), 1),
                            speed=speed,
                            size_downloaded=downloaded,
                            size_total=total,
                        )
                        last_time = now
                        last_bytes = downloaded
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass

            if total > 0 and downloaded < total:
                raise requests.ConnectionError(
                    f"Remote stream ended early at {downloaded}/{total} bytes"
                )

            _finalize(download_id, final_path, category, downloaded, total)
            logger.info("Stream + Keep local copy complete: %s", final_path)
            return

        except Exception as exc:
            if _cancel_requested(download_id):
                return
            logger.warning(
                "Stream + Keep download attempt %s/%s failed for %s: %s",
                attempt + 1, max_retries, download_id, exc,
            )
            _update(
                download_id,
                status="interrupted" if attempt < max_retries - 1 else "failed",
                speed=0,
                error=str(exc),
                size_downloaded=(os.path.getsize(partial) if os.path.isfile(partial) else 0),
            )
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
