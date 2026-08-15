"""Persistent playback-device presence and handoff command queue."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional

from app import database


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PlaybackDevice:
    user_id: int
    device_id: str
    name: str
    kind: str
    capabilities: Dict[str, Any]
    current_session_id: Optional[str]
    registered_at: str
    last_seen: str

    def to_dict(self, *, online_seconds: int = 45) -> Dict[str, Any]:
        data = asdict(self)
        last = _parse_time(self.last_seen)
        data["online"] = bool(
            last and datetime.now(timezone.utc) - last <= timedelta(seconds=max(5, online_seconds))
        )
        return data


@dataclass(frozen=True)
class PlaybackCommand:
    id: str
    user_id: int
    target_device_id: str
    source_device_id: Optional[str]
    command: str
    payload: Dict[str, Any]
    created_at: str
    claimed_at: Optional[str]
    acknowledged_at: Optional[str]
    status: str
    result: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PlaybackDeviceStore:
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
                    CREATE TABLE IF NOT EXISTS playback_devices (
                        user_id INTEGER NOT NULL,
                        device_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'web',
                        capabilities_json TEXT NOT NULL DEFAULT '{}',
                        current_session_id TEXT,
                        registered_at TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        PRIMARY KEY (user_id, device_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_playback_devices_seen
                        ON playback_devices(user_id, last_seen DESC);

                    CREATE TABLE IF NOT EXISTS playback_device_commands (
                        id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        target_device_id TEXT NOT NULL,
                        source_device_id TEXT,
                        command TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        claimed_at TEXT,
                        acknowledged_at TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        result_json TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_playback_commands_target
                        ON playback_device_commands(user_id, target_device_id, acknowledged_at, created_at);
                    """
                )
                conn.commit()
                self._schema_ready = True
            finally:
                conn.close()

    @staticmethod
    def _device(row: sqlite3.Row) -> PlaybackDevice:
        try:
            caps = json.loads(row["capabilities_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            caps = {}
        return PlaybackDevice(
            user_id=int(row["user_id"]),
            device_id=row["device_id"],
            name=row["name"],
            kind=row["kind"],
            capabilities=caps if isinstance(caps, dict) else {},
            current_session_id=row["current_session_id"],
            registered_at=row["registered_at"],
            last_seen=row["last_seen"],
        )

    @staticmethod
    def _command(row: sqlite3.Row) -> PlaybackCommand:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        try:
            result = json.loads(row["result_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            result = {}
        return PlaybackCommand(
            id=row["id"],
            user_id=int(row["user_id"]),
            target_device_id=row["target_device_id"],
            source_device_id=row["source_device_id"],
            command=row["command"],
            payload=payload if isinstance(payload, dict) else {},
            created_at=row["created_at"],
            claimed_at=row["claimed_at"],
            acknowledged_at=row["acknowledged_at"],
            status=row["status"],
            result=result if isinstance(result, dict) else {},
        )

    def register(
        self,
        *,
        user_id: int,
        device_id: str,
        name: str,
        kind: str = "web",
        capabilities: Optional[Dict[str, Any]] = None,
        current_session_id: Optional[str] = None,
    ) -> PlaybackDevice:
        self.ensure_schema()
        now = _utcnow()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO playback_devices
                    (user_id, device_id, name, kind, capabilities_json,
                     current_session_id, registered_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, device_id) DO UPDATE SET
                    name=excluded.name,
                    kind=excluded.kind,
                    capabilities_json=excluded.capabilities_json,
                    current_session_id=excluded.current_session_id,
                    last_seen=excluded.last_seen
                """,
                (
                    int(user_id), device_id, name, kind,
                    json.dumps(capabilities or {}, separators=(",", ":")),
                    current_session_id, now, now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM playback_devices WHERE user_id=? AND device_id=?",
                (int(user_id), device_id),
            ).fetchone()
            return self._device(row)
        finally:
            conn.close()

    def touch(
        self,
        *,
        user_id: int,
        device_id: str,
        current_session_id: Optional[str] = None,
    ) -> bool:
        self.ensure_schema()
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                UPDATE playback_devices
                SET last_seen=?, current_session_id=?
                WHERE user_id=? AND device_id=?
                """,
                (_utcnow(), current_session_id, int(user_id), device_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get(self, *, user_id: int, device_id: str) -> Optional[PlaybackDevice]:
        self.ensure_schema()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM playback_devices WHERE user_id=? AND device_id=?",
                (int(user_id), device_id),
            ).fetchone()
            return self._device(row) if row else None
        finally:
            conn.close()

    def list_for_user(self, user_id: int, limit: int = 50) -> List[PlaybackDevice]:
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM playback_devices
                WHERE user_id=?
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (int(user_id), max(1, min(200, int(limit)))),
            ).fetchall()
            return [self._device(row) for row in rows]
        finally:
            conn.close()

    def enqueue(
        self,
        *,
        user_id: int,
        target_device_id: str,
        command: str,
        payload: Dict[str, Any],
        source_device_id: Optional[str] = None,
    ) -> PlaybackCommand:
        self.ensure_schema()
        command_id = uuid.uuid4().hex
        now = _utcnow()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO playback_device_commands
                    (id, user_id, target_device_id, source_device_id, command,
                     payload_json, created_at, status, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', '{}')
                """,
                (
                    command_id, int(user_id), target_device_id, source_device_id,
                    command, json.dumps(payload, separators=(",", ":")), now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM playback_device_commands WHERE id=?",
                (command_id,),
            ).fetchone()
            return self._command(row)
        finally:
            conn.close()

    def claim(
        self,
        *,
        user_id: int,
        target_device_id: str,
        limit: int = 5,
        retry_after_seconds: int = 30,
    ) -> List[PlaybackCommand]:
        """Claim pending commands, retrying abandoned claims after a grace period."""
        self.ensure_schema()
        retry_before = (
            datetime.now(timezone.utc) - timedelta(seconds=max(5, retry_after_seconds))
        ).isoformat()
        now = _utcnow()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT * FROM playback_device_commands
                WHERE user_id=? AND target_device_id=?
                  AND acknowledged_at IS NULL
                  AND status IN ('pending', 'claimed')
                  AND (claimed_at IS NULL OR claimed_at < ?)
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (int(user_id), target_device_id, retry_before, max(1, min(20, int(limit)))),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE playback_device_commands SET claimed_at=?, status='claimed' WHERE id IN ({placeholders})",
                    (now, *ids),
                )
            conn.commit()
            if not ids:
                return []
            refreshed = conn.execute(
                f"SELECT * FROM playback_device_commands WHERE id IN ({placeholders}) ORDER BY created_at ASC",
                ids,
            ).fetchall()
            return [self._command(row) for row in refreshed]
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def acknowledge(
        self,
        *,
        user_id: int,
        target_device_id: str,
        command_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[PlaybackCommand]:
        self.ensure_schema()
        final_status = status if status in {"completed", "failed", "rejected"} else "completed"
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                UPDATE playback_device_commands
                SET acknowledged_at=?, status=?, result_json=?
                WHERE id=? AND user_id=? AND target_device_id=?
                """,
                (
                    _utcnow(), final_status,
                    json.dumps(result or {}, separators=(",", ":")),
                    command_id, int(user_id), target_device_id,
                ),
            )
            conn.commit()
            if cur.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM playback_device_commands WHERE id=? AND user_id=?",
                (command_id, int(user_id)),
            ).fetchone()
            return self._command(row) if row else None
        finally:
            conn.close()

    def get_command(self, *, user_id: int, command_id: str) -> Optional[PlaybackCommand]:
        self.ensure_schema()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM playback_device_commands WHERE id=? AND user_id=?",
                (command_id, int(user_id)),
            ).fetchone()
            return self._command(row) if row else None
        finally:
            conn.close()

    def cleanup(self, max_age_days: int = 7) -> int:
        self.ensure_schema()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, max_age_days))).isoformat()
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM playback_device_commands WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return int(cur.rowcount or 0)
        finally:
            conn.close()
