"""Persistent Stream + Keep orchestration for debrid-backed media.

A job exposes the remote debrid object immediately through a short-lived Nomad
stream ticket while a dedicated resumable worker saves/indexes a local copy.
The remote URL never appears in public job dictionaries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from app import database
from app.services import stream_keep_download


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StreamKeepJob:
    id: str
    user_id: int
    provider: str
    remote_url: str
    filename: str
    category: str
    is_show: bool
    status: str
    download_id: Optional[str]
    local_path: Optional[str]
    progress: float
    size_total: int
    size_downloaded: int
    speed: int
    error: Optional[str]
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self, *, include_remote: bool = False) -> Dict[str, Any]:
        data = asdict(self)
        if not include_remote:
            data.pop("remote_url", None)
            # Filesystem destinations are internal implementation details.
            if isinstance(data.get("metadata"), dict):
                data["metadata"] = {
                    key: value for key, value in data["metadata"].items()
                    if key not in {"download_dest_path", "remote_url"}
                }
        return data


class StreamKeepStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or database.DB_PATH
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS stream_keep_jobs (
                        id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        provider TEXT NOT NULL,
                        remote_url TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT 'auto',
                        is_show INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL,
                        download_id TEXT,
                        local_path TEXT,
                        progress REAL NOT NULL DEFAULT 0,
                        size_total INTEGER NOT NULL DEFAULT 0,
                        size_downloaded INTEGER NOT NULL DEFAULT 0,
                        speed INTEGER NOT NULL DEFAULT 0,
                        error TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_stream_keep_user
                        ON stream_keep_jobs(user_id, updated_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_stream_keep_download
                        ON stream_keep_jobs(download_id);
                    """
                )
                conn.commit()
                self._schema_ready = True
            finally:
                conn.close()

    @staticmethod
    def _job(row: sqlite3.Row) -> StreamKeepJob:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        return StreamKeepJob(
            id=row["id"],
            user_id=int(row["user_id"]),
            provider=row["provider"],
            remote_url=row["remote_url"],
            filename=row["filename"],
            category=row["category"],
            is_show=bool(row["is_show"]),
            status=row["status"],
            download_id=row["download_id"],
            local_path=row["local_path"],
            progress=float(row["progress"] or 0),
            size_total=int(row["size_total"] or 0),
            size_downloaded=int(row["size_downloaded"] or 0),
            speed=int(row["speed"] or 0),
            error=row["error"],
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create(
        self,
        *,
        user_id: int,
        provider: str,
        remote_url: str,
        filename: str,
        category: str,
        is_show: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StreamKeepJob:
        self.ensure_schema()
        job_id = uuid.uuid4().hex
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO stream_keep_jobs (
                    id,user_id,provider,remote_url,filename,category,is_show,status,
                    metadata_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,'starting',?,?,?)
                """,
                (
                    job_id, int(user_id), provider, remote_url, filename, category,
                    1 if is_show else 0,
                    json.dumps(metadata or {}, separators=(",", ":")), now, now,
                ),
            )
            conn.commit()
            return self.get(job_id, user_id=user_id, include_remote=True)
        finally:
            conn.close()

    def get(
        self,
        job_id: str,
        *,
        user_id: Optional[int] = None,
        include_remote: bool = True,
    ) -> Optional[StreamKeepJob]:
        self.ensure_schema()
        conn = self._connect()
        try:
            if user_id is None:
                row = conn.execute("SELECT * FROM stream_keep_jobs WHERE id=?", (job_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM stream_keep_jobs WHERE id=? AND user_id=?",
                    (job_id, int(user_id)),
                ).fetchone()
            return self._job(row) if row else None
        finally:
            conn.close()

    def list_for_user(self, user_id: int, limit: int = 100) -> List[StreamKeepJob]:
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM stream_keep_jobs WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                (int(user_id), max(1, min(500, int(limit)))),
            ).fetchall()
            return [self._job(row) for row in rows]
        finally:
            conn.close()

    def list_recoverable(self, limit: int = 200) -> List[StreamKeepJob]:
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM stream_keep_jobs
                WHERE status IN ('starting','downloading','interrupted')
                ORDER BY updated_at ASC LIMIT ?
                """,
                (max(1, min(1000, int(limit))),),
            ).fetchall()
            return [self._job(row) for row in rows]
        finally:
            conn.close()

    def update(self, job_id: str, *, user_id: Optional[int] = None, **fields) -> Optional[StreamKeepJob]:
        self.ensure_schema()
        allowed = {
            "status", "download_id", "local_path", "progress", "size_total",
            "size_downloaded", "speed", "error", "metadata_json", "filename",
            "category", "remote_url",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        values["updated_at"] = _now()
        assignments = ",".join(f"{key}=?" for key in values)
        params = list(values.values())
        where = "id=?"
        params.append(job_id)
        if user_id is not None:
            where += " AND user_id=?"
            params.append(int(user_id))
        conn = self._connect()
        try:
            cur = conn.execute(f"UPDATE stream_keep_jobs SET {assignments} WHERE {where}", params)
            conn.commit()
            if cur.rowcount <= 0:
                return None
            return self.get(job_id, user_id=user_id, include_remote=True)
        finally:
            conn.close()

    def delete(self, job_id: str, *, user_id: int) -> bool:
        self.ensure_schema()
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM stream_keep_jobs WHERE id=? AND user_id=?",
                (job_id, int(user_id)),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


class StreamKeepManager:
    MAX_RECOVERY_RESTARTS = 4

    def __init__(self, store: Optional[StreamKeepStore] = None, *, auto_recover: bool = False):
        self.store = store or StreamKeepStore()
        self._monitors: Dict[str, threading.Thread] = {}
        self._recovering: set[str] = set()
        self._lock = threading.Lock()
        if auto_recover:
            self.schedule_recovery()

    @staticmethod
    def _metadata(job: StreamKeepJob) -> Dict[str, Any]:
        return dict(job.metadata or {})

    def start_download(self, job: StreamKeepJob, *, recovery: bool = False) -> StreamKeepJob:
        metadata = self._metadata(job)
        dest_path = metadata.get("download_dest_path")
        restart_count = int(metadata.get("download_restart_count") or 0)
        if recovery:
            restart_count += 1
            metadata["download_restart_count"] = restart_count
        try:
            download_id = stream_keep_download.start_download(
                url=job.remote_url,
                filename=job.filename,
                category=job.category,
                is_show=job.is_show,
                dest_path=str(dest_path) if dest_path else None,
            )
            info = stream_keep_download.get_status(download_id) or {}
            if info.get("dest_path"):
                metadata["download_dest_path"] = info["dest_path"]
            metadata["resume_supported"] = info.get("range_supported")
        except Exception as exc:
            updated = self.store.update(
                job.id,
                user_id=job.user_id,
                status="failed",
                error=str(exc),
                metadata_json=json.dumps(metadata, separators=(",", ":")),
            )
            return updated or job

        updated = self.store.update(
            job.id,
            user_id=job.user_id,
            status="downloading",
            download_id=download_id,
            error=None,
            metadata_json=json.dumps(metadata, separators=(",", ":")),
        ) or job
        self._start_monitor(updated.id, updated.user_id, download_id)
        return updated

    def _start_monitor(self, job_id: str, user_id: int, download_id: str) -> None:
        with self._lock:
            existing = self._monitors.get(job_id)
            if existing and existing.is_alive():
                return
            thread = threading.Thread(
                target=self._monitor,
                args=(job_id, user_id, download_id),
                daemon=True,
                name=f"stream-keep-{job_id[:8]}",
            )
            self._monitors[job_id] = thread
            thread.start()

    def _monitor(self, job_id: str, user_id: int, download_id: str) -> None:
        try:
            missing_count = 0
            while True:
                info = stream_keep_download.get_status(download_id)
                if info is None:
                    missing_count += 1
                    if missing_count >= 8:
                        self.store.update(
                            job_id,
                            user_id=user_id,
                            status="interrupted",
                            error="Download worker state disappeared before completion",
                            speed=0,
                        )
                        return
                    time.sleep(1)
                    continue
                missing_count = 0
                status = str(info.get("status") or "downloading")
                job = self.store.get(job_id, user_id=user_id)
                metadata = self._metadata(job) if job else {}
                if info.get("dest_path"):
                    metadata["download_dest_path"] = info["dest_path"]
                if info.get("range_supported") is not None:
                    metadata["resume_supported"] = bool(info.get("range_supported"))
                if info.get("resumed_from"):
                    metadata["last_resumed_from"] = int(info.get("resumed_from") or 0)
                common = {
                    "progress": float(info.get("progress") or 0),
                    "size_total": int(info.get("size_total") or 0),
                    "size_downloaded": int(info.get("size_downloaded") or 0),
                    "speed": int(info.get("speed") or 0),
                    "error": info.get("error"),
                    "metadata_json": json.dumps(metadata, separators=(",", ":")),
                }
                if status == "completed":
                    self.store.update(
                        job_id,
                        user_id=user_id,
                        status="local_ready",
                        local_path=info.get("local_path"),
                        progress=100.0,
                        speed=0,
                        size_total=common["size_total"],
                        size_downloaded=common["size_downloaded"],
                        error=None,
                        metadata_json=common["metadata_json"],
                    )
                    return
                if status in {"failed", "cancelled"}:
                    self.store.update(job_id, user_id=user_id, status=status, **common)
                    return
                if status == "interrupted":
                    self.store.update(job_id, user_id=user_id, status="interrupted", **common)
                    time.sleep(1)
                    continue
                self.store.update(job_id, user_id=user_id, status="downloading", **common)
                time.sleep(1)
        finally:
            with self._lock:
                self._monitors.pop(job_id, None)

    def _recover_job(self, job: StreamKeepJob) -> StreamKeepJob:
        with self._lock:
            if job.id in self._recovering:
                return job
            monitor = self._monitors.get(job.id)
            if monitor and monitor.is_alive():
                return job
            self._recovering.add(job.id)
        try:
            metadata = self._metadata(job)
            restart_count = int(metadata.get("download_restart_count") or 0)
            if restart_count >= self.MAX_RECOVERY_RESTARTS:
                return self.store.update(
                    job.id,
                    user_id=job.user_id,
                    status="failed",
                    speed=0,
                    error="Stream + Keep exceeded automatic recovery limit",
                ) or job
            return self.start_download(job, recovery=True)
        finally:
            with self._lock:
                self._recovering.discard(job.id)

    def recover_pending(self) -> int:
        recovered = 0
        for job in self.store.list_recoverable():
            current = stream_keep_download.get_status(job.download_id) if job.download_id else None
            if current is not None:
                self._start_monitor(job.id, job.user_id, job.download_id)
                continue
            updated = self._recover_job(job)
            if updated.download_id != job.download_id or updated.status == "downloading":
                recovered += 1
        return recovered

    def schedule_recovery(self, delay_seconds: float = 3.0) -> None:
        def run():
            time.sleep(max(0.0, float(delay_seconds)))
            try:
                self.recover_pending()
            except Exception:
                # Recovery is best-effort; status reconciliation can retry later.
                pass
        threading.Thread(target=run, daemon=True, name="stream-keep-recovery").start()

    def reconcile(self, job: StreamKeepJob) -> StreamKeepJob:
        """Refresh/recover downloader state without exposing the remote URL."""
        if job.status == "local_ready" and job.local_path:
            return job
        if job.download_id:
            info = stream_keep_download.get_status(job.download_id)
            if info is not None:
                self._start_monitor(job.id, job.user_id, job.download_id)
                refreshed = self.store.get(job.id, user_id=job.user_id)
                return refreshed or job
        if job.status in {"starting", "downloading", "interrupted"}:
            return self._recover_job(job)
        return job

    def cancel(self, job: StreamKeepJob) -> StreamKeepJob:
        if job.download_id:
            stream_keep_download.cancel(job.download_id)
        return self.store.update(
            job.id, user_id=job.user_id, status="cancelled", speed=0
        ) or job
