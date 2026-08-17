"""Low-overhead runtime fixes for the legacy in-memory debrid download queue.

The legacy cancel operation only changed the visible status; its worker never
checked that status and could continue writing the file to disk. This overlay
keeps the existing API and one-thread-per-active-download design, but makes
cancel/clear authoritative and removes cancelled partial files.
"""

from __future__ import annotations

import os

from app.services import debrid


_TERMINAL = {"completed", "failed", "error", "cancelled"}
_INSTALLED = False


def _cancelled(download_id: str) -> bool:
    with debrid._downloads_lock:
        info = debrid._downloads.get(download_id)
        # Removing an entry from the queue while its worker is winding down is
        # also an explicit cancellation. Never let the worker recreate state.
        return info is None or str(info.get("status") or "").lower() == "cancelled"


def _remove_partial(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _set_failed(download_id: str, message: str) -> None:
    with debrid._downloads_lock:
        info = debrid._downloads.get(download_id)
        if info is not None and str(info.get("status") or "").lower() != "cancelled":
            info.update({"status": "failed", "error": message, "speed": 0})


def _index_completed(dest_path: str, category: str) -> None:
    from app.routers import media

    try:
        abs_base = os.path.abspath(media.BASE_DIR)
        abs_dest = os.path.abspath(dest_path)
        if abs_dest.startswith(abs_base):
            rel_path = os.path.relpath(abs_dest, abs_base).replace(os.sep, "/")
            web_path = f"/data/{rel_path}"
        else:
            web_path = abs_dest
            ext_root = os.path.join(media.BASE_DIR, "external")
            if os.path.exists(ext_root):
                for item in os.listdir(ext_root):
                    link_path = os.path.join(ext_root, item)
                    if not os.path.islink(link_path):
                        continue
                    target = os.path.realpath(link_path)
                    if abs_dest.startswith(target):
                        rel_to_target = os.path.relpath(abs_dest, target).replace(os.sep, "/")
                        web_path = f"/data/external/{item}/{rel_to_target}"
                        break

        stat = os.stat(dest_path)
        dest_root = media.pick_effective_storage_root_fs(category)
        if dest_path.startswith(dest_root):
            folder = os.path.relpath(os.path.dirname(dest_path), dest_root).replace(os.sep, "/")
        else:
            folder = "."
        if folder == ".":
            folder = ""
        media.database.upsert_library_index_item({
            "path": web_path,
            "category": category,
            "name": os.path.basename(dest_path),
            "folder": folder,
            "source": "debrid",
            "poster": None,
            "mtime": float(stat.st_mtime),
            "size": int(stat.st_size),
        })
        debrid.logger.info("Debrid download indexed: %s", web_path)
    except Exception as exc:
        debrid.logger.error("Failed to index debrid download: %s", exc)


def _download_worker(download_id: str, url: str, dest_path: str, category: str):
    max_retries = 3
    retry_delay = 5

    for attempt in range(max_retries):
        if _cancelled(download_id):
            _remove_partial(dest_path)
            return
        try:
            with debrid.requests.get(url, stream=True, timeout=30) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                last_update = debrid.time.time()
                last_bytes = 0

                with debrid._downloads_lock:
                    info = debrid._downloads.get(download_id)
                    if info is not None:
                        info["size_total"] = total

                with open(dest_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1000):
                        if _cancelled(download_id):
                            _remove_partial(dest_path)
                            return
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)

                        now = debrid.time.time()
                        elapsed = now - last_update
                        if elapsed >= 1.0:
                            speed = (downloaded - last_bytes) / elapsed
                            progress = (downloaded / total * 100) if total > 0 else 0
                            with debrid._downloads_lock:
                                info = debrid._downloads.get(download_id)
                                if info is not None and str(info.get("status") or "").lower() != "cancelled":
                                    info.update({
                                        "progress": round(progress, 1),
                                        "speed": round(speed),
                                        "size_downloaded": downloaded,
                                    })
                            last_update = now
                            last_bytes = downloaded

            if _cancelled(download_id):
                _remove_partial(dest_path)
                return

            with debrid._downloads_lock:
                info = debrid._downloads.get(download_id)
                if info is None or str(info.get("status") or "").lower() == "cancelled":
                    _remove_partial(dest_path)
                    return
                info.update({
                    "status": "completed",
                    "progress": 100,
                    "size_downloaded": downloaded,
                    "speed": 0,
                })

            _index_completed(dest_path, category)
            debrid.logger.info("Download complete: %s", dest_path)
            return

        except debrid.requests.exceptions.Timeout:
            if _cancelled(download_id):
                _remove_partial(dest_path)
                return
            debrid.logger.warning("Download timeout (attempt %s/%s): %s", attempt + 1, max_retries, download_id)
            if attempt < max_retries - 1:
                debrid.time.sleep(retry_delay)
            else:
                _set_failed(download_id, "Download failed: Request timeout after multiple retries")
        except debrid.requests.exceptions.ConnectionError as exc:
            if _cancelled(download_id):
                _remove_partial(dest_path)
                return
            debrid.logger.warning("Download connection error (attempt %s/%s): %s", attempt + 1, max_retries, exc)
            if attempt < max_retries - 1:
                debrid.time.sleep(retry_delay)
            else:
                _set_failed(download_id, f"Download failed: Connection error - {exc}")
        except debrid.requests.exceptions.HTTPError as exc:
            if _cancelled(download_id):
                _remove_partial(dest_path)
                return
            status_code = getattr(exc.response, "status_code", None)
            if status_code in (401, 403):
                message = f"Download failed: Link expired or access denied (HTTP {status_code}). Try refreshing the link or changing Debrid service."
            elif status_code == 404:
                message = "Download failed: File not found on Debrid server (HTTP 404). Link might have been deleted."
            else:
                message = f"Download failed: Debrid server error (HTTP {status_code})"
            _set_failed(download_id, message)
            return
        except Exception as exc:
            if _cancelled(download_id):
                _remove_partial(dest_path)
                return
            debrid.logger.error("Download failed for %s: %s", download_id, exc)
            _set_failed(download_id, f"Internal Error: {exc}")
            return


def _cancel_download(download_id: str) -> bool:
    with debrid._downloads_lock:
        info = debrid._downloads.get(download_id)
        if info is None:
            return False
        info.update({"status": "cancelled", "speed": 0, "error": None})
        return True


def _clear_completed() -> int:
    with debrid._downloads_lock:
        remove = [
            key for key, value in debrid._downloads.items()
            if str(value.get("status") or "").lower() in _TERMINAL
        ]
        for key in remove:
            debrid._downloads.pop(key, None)
        return len(remove)


def install_download_queue_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    debrid._download_worker = _download_worker
    debrid.cancel_download = _cancel_download
    debrid.clear_completed = _clear_completed
    _INSTALLED = True
