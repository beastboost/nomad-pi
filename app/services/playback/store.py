"""Persistent playback sessions for Nomad Pi 2.x."""

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


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PlaybackSession:
    id: str
    user_id: int
    path: str
    mode: str
    state: str
    position: float
    duration: float
    audio_track: Optional[int]
    subtitle_track: Optional[int]
    quality: Optional[str]
    device_id: Optional[str]
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str
    last_seen: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PlaybackSessionStore:
    """Small SQLite-backed store independent from the legacy DB monolith.

    Production defaults to the same SQLite database as the rest of Nomad, but
    tests can point this class at a temporary database without touching global
    connection-pool state.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or database.DB_PATH
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
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
                    CREATE TABLE IF NOT EXISTS playback_sessions (
                        id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        path TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        state TEXT NOT NULL DEFAULT 'starting',
                        position REAL NOT NULL DEFAULT 0,
                        duration REAL NOT NULL DEFAULT 0,
                        audio_track INTEGER,
                        subtitle_track INTEGER,
                        quality TEXT,
                        device_id TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_seen TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_playback_sessions_user
                        ON playback_sessions(user_id, last_seen DESC);
                    CREATE INDEX IF NOT EXISTS idx_playback_sessions_state
                        ON playback_sessions(state, last_seen DESC);
                    """
                )
                conn.commit()
                self._schema_ready = True
            finally:
                conn.close()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> PlaybackSession:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        return PlaybackSession(
            id=row["id"],
            user_id=int(row["user_id"]),
            path=row["path"],
            mode=row["mode"],
            state=row["state"],
            position=float(row["position"] or 0),
            duration=float(row["duration"] or 0),
            audio_track=row["audio_track"],
            subtitle_track=row["subtitle_track"],
            quality=row["quality"],
            device_id=row["device_id"],
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_seen=row["last_seen"],
        )

    def create(
        self,
        *,
        user_id: int,
        path: str,
        mode: str,
        duration: float = 0,
        position: float = 0,
        audio_track: Optional[int] = None,
        subtitle_track: Optional[int] = None,
        quality: Optional[str] = None,
        device_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PlaybackSession:
        self.ensure_schema()
        session_id = str(uuid.uuid4())
        now = _utcnow()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO playback_sessions (
                    id, user_id, path, mode, state, position, duration,
                    audio_track, subtitle_track, quality, device_id,
                    metadata_json, created_at, updated_at, last_seen
                ) VALUES (?, ?, ?, ?, 'starting', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    int(user_id),
                    path,
                    mode,
                    float(position or 0),
                    float(duration or 0),
                    audio_track,
                    subtitle_track,
                    quality,
                    device_id,
                    json.dumps(metadata or {}, separators=(",", ":")),
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        session = self.get(session_id, user_id=user_id)
        if not session:
            raise RuntimeError("Playback session could not be created")
        return session

    def get(self, session_id: str, user_id: Optional[int] = None) -> Optional[PlaybackSession]:
        self.ensure_schema()
        conn = self._connect()
        try:
            if user_id is None:
                row = conn.execute(
                    "SELECT * FROM playback_sessions WHERE id = ?", (session_id,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM playback_sessions WHERE id = ? AND user_id = ?",
                    (session_id, int(user_id)),
                ).fetchone()
            return self._from_row(row) if row else None
        finally:
            conn.close()

    def list_for_user(self, user_id: int, limit: int = 50) -> List[PlaybackSession]:
        self.ensure_schema()
        limit = max(1, min(int(limit), 200))
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM playback_sessions
                WHERE user_id = ?
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (int(user_id), limit),
            ).fetchall()
            return [self._from_row(row) for row in rows]
        finally:
            conn.close()

    def update(
        self,
        session_id: str,
        *,
        user_id: Optional[int] = None,
        state: Optional[str] = None,
        position: Optional[float] = None,
        duration: Optional[float] = None,
        audio_track: Optional[int] = None,
        subtitle_track: Optional[int] = None,
        quality: Optional[str] = None,
        touch: bool = True,
    ) -> Optional[PlaybackSession]:
        self.ensure_schema()
        fields = []
        values: List[Any] = []
        if state is not None:
            fields.append("state = ?")
            values.append(str(state))
        if position is not None:
            fields.append("position = ?")
            values.append(max(0.0, float(position)))
        if duration is not None:
            fields.append("duration = ?")
            values.append(max(0.0, float(duration)))
        if audio_track is not None:
            fields.append("audio_track = ?")
            values.append(int(audio_track))
        if subtitle_track is not None:
            fields.append("subtitle_track = ?")
            values.append(int(subtitle_track))
        if quality is not None:
            fields.append("quality = ?")
            values.append(str(quality))
        now = _utcnow()
        fields.append("updated_at = ?")
        values.append(now)
        if touch:
            fields.append("last_seen = ?")
            values.append(now)

        where = "id = ?"
        values.append(session_id)
        if user_id is not None:
            where += " AND user_id = ?"
            values.append(int(user_id))

        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE playback_sessions SET {', '.join(fields)} WHERE {where}", values
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(session_id, user_id=user_id)

    def delete(self, session_id: str, user_id: Optional[int] = None) -> bool:
        self.ensure_schema()
        conn = self._connect()
        try:
            if user_id is None:
                cur = conn.execute("DELETE FROM playback_sessions WHERE id = ?", (session_id,))
            else:
                cur = conn.execute(
                    "DELETE FROM playback_sessions WHERE id = ? AND user_id = ?",
                    (session_id, int(user_id)),
                )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
