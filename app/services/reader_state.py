"""Persistent per-user reading state for books/comics/PDFs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional

from app import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ReadingProgress:
    user_id: int
    path: str
    position: Dict[str, Any]
    percent: float
    updated_at: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ReaderMark:
    id: str
    user_id: int
    path: str
    kind: str
    label: str
    note: str
    position: Dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self):
        return asdict(self)


class ReaderStateStore:
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
                    CREATE TABLE IF NOT EXISTS reading_progress_v2 (
                        user_id INTEGER NOT NULL,
                        path TEXT NOT NULL,
                        position_json TEXT NOT NULL DEFAULT '{}',
                        percent REAL NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, path)
                    );
                    CREATE INDEX IF NOT EXISTS idx_reading_progress_updated
                        ON reading_progress_v2(user_id, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS reader_marks (
                        id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        path TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        label TEXT NOT NULL DEFAULT '',
                        note TEXT NOT NULL DEFAULT '',
                        position_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_reader_marks_path
                        ON reader_marks(user_id, path, kind, created_at DESC);
                    """
                )
                conn.commit()
                self._ready = True
            finally:
                conn.close()

    @staticmethod
    def _position(raw) -> Dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def get_progress(self, *, user_id: int, path: str) -> Optional[ReadingProgress]:
        self.ensure_schema()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM reading_progress_v2 WHERE user_id=? AND path=?",
                (int(user_id), path),
            ).fetchone()
            if not row:
                return None
            return ReadingProgress(
                user_id=int(row["user_id"]), path=row["path"],
                position=self._position(row["position_json"]),
                percent=float(row["percent"] or 0), updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    def save_progress(self, *, user_id: int, path: str, position: Dict[str, Any], percent: float) -> ReadingProgress:
        self.ensure_schema()
        now = _now()
        pct = max(0.0, min(100.0, float(percent or 0)))
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO reading_progress_v2 (user_id,path,position_json,percent,updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(user_id,path) DO UPDATE SET
                    position_json=excluded.position_json,
                    percent=excluded.percent,
                    updated_at=excluded.updated_at
                """,
                (int(user_id), path, json.dumps(position or {}, separators=(",", ":")), pct, now),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_progress(user_id=user_id, path=path)

    def recent(self, user_id: int, limit: int = 50) -> List[ReadingProgress]:
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM reading_progress_v2 WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                (int(user_id), max(1, min(500, int(limit)))),
            ).fetchall()
            return [ReadingProgress(
                user_id=int(row["user_id"]), path=row["path"],
                position=self._position(row["position_json"]),
                percent=float(row["percent"] or 0), updated_at=row["updated_at"],
            ) for row in rows]
        finally:
            conn.close()

    def add_mark(self, *, user_id: int, path: str, kind: str, label: str, note: str, position: Dict[str, Any]) -> ReaderMark:
        self.ensure_schema()
        mark_id = uuid.uuid4().hex
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO reader_marks (id,user_id,path,kind,label,note,position_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (mark_id, int(user_id), path, kind, label[:300], note[:10000], json.dumps(position or {}, separators=(",", ":")), now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM reader_marks WHERE id=?", (mark_id,)).fetchone()
            return self._mark(row)
        finally:
            conn.close()

    def list_marks(self, *, user_id: int, path: str, kind: str = "") -> List[ReaderMark]:
        self.ensure_schema()
        conn = self._connect()
        try:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM reader_marks WHERE user_id=? AND path=? AND kind=? ORDER BY created_at DESC",
                    (int(user_id), path, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reader_marks WHERE user_id=? AND path=? ORDER BY created_at DESC",
                    (int(user_id), path),
                ).fetchall()
            return [self._mark(row) for row in rows]
        finally:
            conn.close()

    def delete_mark(self, *, user_id: int, mark_id: str) -> bool:
        self.ensure_schema()
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM reader_marks WHERE id=? AND user_id=?", (mark_id, int(user_id)))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def _mark(self, row) -> ReaderMark:
        return ReaderMark(
            id=row["id"], user_id=int(row["user_id"]), path=row["path"], kind=row["kind"],
            label=row["label"], note=row["note"], position=self._position(row["position_json"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
