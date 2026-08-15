"""Persistent prepared-offline-copy jobs for Nomad Pi.

Jobs create portable MP4 travel copies from local media. The worker prefers
stream copy when the source is already H.264/AAC and within the requested
quality cap, otherwise it uses the same conservative SBC hardware-encoder
selection policy as playback with software fallback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from typing import Dict, List, Optional

from app import database
from app.services.playback.encoders import video_encoder_args, video_encoder_candidates
from app.services.playback.probe import MediaProbe, ProbeError, probe_media


QUALITY = {
    "original": {"label": "Original", "max_width": None, "max_height": None, "bitrate": None},
    "1080p": {"label": "1080p", "max_width": 1920, "max_height": 1080, "bitrate": 8_000_000},
    "720p": {"label": "720p", "max_width": 1280, "max_height": 720, "bitrate": 4_000_000},
    "480p": {"label": "480p", "max_width": 854, "max_height": 480, "bitrate": 2_000_000},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_stem(path: str) -> str:
    stem = Path(path).stem.strip() or "offline-media"
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._")
    return stem[:160] or "offline-media"


@dataclass(frozen=True)
class OfflineJob:
    id: str
    user_id: int
    source_path: str
    source_fs_path: str
    quality: str
    status: str
    output_path: Optional[str]
    output_name: Optional[str]
    progress: float
    duration: float
    size_bytes: int
    error: Optional[str]
    metadata: dict
    created_at: str
    updated_at: str

    def to_dict(self, *, include_fs: bool = False) -> dict:
        data = asdict(self)
        if not include_fs:
            data.pop("source_fs_path", None)
        return data


class OfflineSyncStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or database.DB_PATH
        self._ready = False
        self._lock = threading.Lock()

    def _connect(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def ensure_schema(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS offline_sync_jobs (
                        id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        source_path TEXT NOT NULL,
                        source_fs_path TEXT NOT NULL,
                        quality TEXT NOT NULL,
                        status TEXT NOT NULL,
                        output_path TEXT,
                        output_name TEXT,
                        progress REAL NOT NULL DEFAULT 0,
                        duration REAL NOT NULL DEFAULT 0,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        error TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_offline_sync_user
                        ON offline_sync_jobs(user_id, updated_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_offline_sync_source
                        ON offline_sync_jobs(user_id, source_path, quality);
                    """
                )
                # A process restart cannot preserve a Popen object. Requeue
                # running/preparing jobs; the worker removes partial output.
                conn.execute(
                    "UPDATE offline_sync_jobs SET status='queued', error=NULL, updated_at=? WHERE status IN ('running','preparing')",
                    (_now(),),
                )
                conn.commit()
                self._ready = True
            finally:
                conn.close()

    @staticmethod
    def _row(row) -> OfflineJob:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            metadata = {}
        return OfflineJob(
            id=row["id"], user_id=int(row["user_id"]), source_path=row["source_path"],
            source_fs_path=row["source_fs_path"], quality=row["quality"], status=row["status"],
            output_path=row["output_path"], output_name=row["output_name"],
            progress=float(row["progress"] or 0), duration=float(row["duration"] or 0),
            size_bytes=int(row["size_bytes"] or 0), error=row["error"],
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def create(self, *, user_id: int, source_path: str, source_fs_path: str, quality: str, metadata: Optional[dict] = None) -> OfflineJob:
        self.ensure_schema()
        job_id = uuid.uuid4().hex
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO offline_sync_jobs
                    (id,user_id,source_path,source_fs_path,quality,status,metadata_json,created_at,updated_at)
                VALUES (?,?,?,?,?,'queued',?,?,?)
                """,
                (job_id, int(user_id), source_path, source_fs_path, quality,
                 json.dumps(metadata or {}, separators=(",", ":")), now, now),
            )
            conn.commit()
            return self.get(job_id, user_id=user_id)
        finally:
            conn.close()

    def get(self, job_id: str, *, user_id: Optional[int] = None) -> Optional[OfflineJob]:
        self.ensure_schema()
        conn = self._connect()
        try:
            if user_id is None:
                row = conn.execute("SELECT * FROM offline_sync_jobs WHERE id=?", (job_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM offline_sync_jobs WHERE id=? AND user_id=?", (job_id, int(user_id))
                ).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def find_existing(self, *, user_id: int, source_path: str, quality: str) -> Optional[OfflineJob]:
        self.ensure_schema()
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM offline_sync_jobs
                WHERE user_id=? AND source_path=? AND quality=? AND status NOT IN ('cancelled','deleted')
                ORDER BY created_at DESC LIMIT 1
                """,
                (int(user_id), source_path, quality),
            ).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def list_for_user(self, user_id: int, limit: int = 200) -> List[OfflineJob]:
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM offline_sync_jobs WHERE user_id=? AND status<>'deleted' ORDER BY updated_at DESC LIMIT ?",
                (int(user_id), max(1, min(1000, int(limit)))),
            ).fetchall()
            return [self._row(r) for r in rows]
        finally:
            conn.close()

    def queued(self, limit: int = 20) -> List[OfflineJob]:
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM offline_sync_jobs WHERE status='queued' ORDER BY created_at ASC LIMIT ?",
                (max(1, min(100, int(limit))),),
            ).fetchall()
            return [self._row(r) for r in rows]
        finally:
            conn.close()

    def update(self, job_id: str, *, user_id: Optional[int] = None, **fields) -> Optional[OfflineJob]:
        allowed = {"status", "output_path", "output_name", "progress", "duration", "size_bytes", "error", "metadata_json"}
        values = {k: v for k, v in fields.items() if k in allowed}
        values["updated_at"] = _now()
        where = "id=?"
        params = list(values.values()) + [job_id]
        if user_id is not None:
            where += " AND user_id=?"
            params.append(int(user_id))
        conn = self._connect()
        try:
            cur = conn.execute(
                f"UPDATE offline_sync_jobs SET {','.join(f'{k}=?' for k in values)} WHERE {where}", params
            )
            conn.commit()
            return self.get(job_id, user_id=user_id) if cur.rowcount else None
        finally:
            conn.close()


class OfflineSyncManager:
    def __init__(self, store: Optional[OfflineSyncStore] = None, root: str = "data/.nomad_offline"):
        self.store = store or OfflineSyncStore()
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._processes: Dict[str, subprocess.Popen] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._dispatcher_started = False

    def start_dispatcher(self):
        with self._lock:
            if self._dispatcher_started:
                return
            self._dispatcher_started = True
        threading.Thread(target=self._dispatch_loop, daemon=True, name="nomad-offline-dispatch").start()

    def _dispatch_loop(self):
        while True:
            try:
                for job in self.store.queued(limit=4):
                    self.start(job)
            except Exception:
                pass
            time.sleep(1)

    def start(self, job: OfflineJob):
        with self._lock:
            thread = self._threads.get(job.id)
            if thread and thread.is_alive():
                return
            thread = threading.Thread(target=self._run_job, args=(job.id,), daemon=True, name=f"offline-{job.id[:8]}")
            self._threads[job.id] = thread
            thread.start()

    def _output(self, job: OfflineJob) -> tuple[Path, str]:
        directory = self.root / str(job.user_id) / job.id
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{_safe_stem(job.source_path)} [{job.quality}].mp4"
        return directory / name, name

    @staticmethod
    def _scale_filter(probe: MediaProbe, profile: dict) -> Optional[str]:
        max_w, max_h = profile.get("max_width"), profile.get("max_height")
        if not max_w and not max_h:
            return None
        if not probe.width or not probe.height:
            return None
        scale = 1.0
        if max_w and probe.width > max_w:
            scale = min(scale, max_w / probe.width)
        if max_h and probe.height > max_h:
            scale = min(scale, max_h / probe.height)
        if scale >= 1.0:
            return None
        width = max(2, int(probe.width * scale) // 2 * 2)
        height = max(2, int(probe.height * scale) // 2 * 2)
        return f"scale={width}:{height}"

    def _commands(self, job: OfflineJob, probe: MediaProbe, output: Path) -> list[tuple[str, list[str]]]:
        profile = QUALITY[job.quality]
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        scale = self._scale_filter(probe, profile)
        source_copyable = probe.video_codec == "h264" and (probe.audio_codec in {None, "aac"}) and scale is None
        base = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y", "-i", job.source_fs_path, "-map", "0:v:0?", "-map", "0:a:0?", "-map", "0:s?", "-sn"]
        progress = ["-progress", "pipe:1", "-nostats", "-movflags", "+faststart", str(output)]
        if source_copyable:
            return [("copy", base + ["-c:v", "copy", "-c:a", "copy"] + progress)]

        commands = []
        candidates = video_encoder_candidates("h264") or (["libx264"] if shutil.which("ffmpeg") else [])
        for encoder in candidates:
            cmd = list(base)
            cmd += ["-c:v", encoder]
            cmd += video_encoder_args(encoder, max_bitrate=profile.get("bitrate"))
            if scale:
                cmd += ["-vf", scale]
            cmd += ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]
            cmd += progress
            commands.append((encoder, cmd))
        return commands

    def _run_job(self, job_id: str):
        try:
            job = self.store.get(job_id)
            if not job or job.status != "queued":
                return
            if not os.path.isfile(job.source_fs_path):
                self.store.update(job.id, status="failed", error="Source media no longer exists")
                return
            try:
                probe = probe_media(job.source_fs_path)
            except ProbeError as exc:
                self.store.update(job.id, status="failed", error=str(exc))
                return
            output, output_name = self._output(job)
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
            self.store.update(job.id, status="preparing", duration=float(probe.duration or 0), output_name=output_name, error=None)
            commands = self._commands(job, probe, output)
            if not commands:
                self.store.update(job.id, status="failed", error="No H.264 encoder is available for an offline copy")
                return

            last_error = ""
            for label, cmd in commands:
                self.store.update(job.id, status="running", error=None)
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
                )
                with self._lock:
                    self._processes[job.id] = process
                duration = float(probe.duration or 0)
                try:
                    if process.stdout:
                        for line in process.stdout:
                            line = line.strip()
                            if line.startswith("out_time_ms=") and duration > 0:
                                try:
                                    seconds = int(line.split("=", 1)[1]) / 1_000_000
                                    self.store.update(job.id, progress=min(99.5, max(0, seconds / duration * 100)))
                                except ValueError:
                                    pass
                            current = self.store.get(job.id)
                            if current and current.status == "cancelled":
                                process.terminate()
                                break
                    stderr = process.stderr.read() if process.stderr else ""
                    rc = process.wait()
                finally:
                    with self._lock:
                        self._processes.pop(job.id, None)
                current = self.store.get(job.id)
                if current and current.status == "cancelled":
                    try: output.unlink(missing_ok=True)
                    except OSError: pass
                    return
                if rc == 0 and output.is_file() and output.stat().st_size > 0:
                    self.store.update(
                        job.id, status="ready", progress=100.0, output_path=str(output),
                        size_bytes=output.stat().st_size, error=None,
                        metadata_json=json.dumps({**(job.metadata or {}), "encoder": label}, separators=(",", ":")),
                    )
                    return
                last_error = (stderr or f"ffmpeg exited with code {rc}")[-4000:]
                try: output.unlink(missing_ok=True)
                except OSError: pass
            self.store.update(job.id, status="failed", error=last_error or "Offline conversion failed")
        finally:
            with self._lock:
                self._threads.pop(job_id, None)

    def cancel(self, job: OfflineJob) -> OfflineJob:
        updated = self.store.update(job.id, user_id=job.user_id, status="cancelled", error=None) or job
        with self._lock:
            process = self._processes.get(job.id)
        if process and process.poll() is None:
            process.terminate()
        if job.output_path:
            try: Path(job.output_path).unlink(missing_ok=True)
            except OSError: pass
        return updated

    def delete(self, job: OfflineJob) -> OfflineJob:
        self.cancel(job)
        directory = self.root / str(job.user_id) / job.id
        shutil.rmtree(directory, ignore_errors=True)
        return self.store.update(job.id, user_id=job.user_id, status="deleted", output_path=None, size_bytes=0) or job

    def retry(self, job: OfflineJob) -> OfflineJob:
        if job.status not in {"failed", "cancelled"}:
            return job
        updated = self.store.update(job.id, user_id=job.user_id, status="queued", progress=0, error=None) or job
        self.start(updated)
        return updated
