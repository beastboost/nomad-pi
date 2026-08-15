"""Persistent same-account Watch Together rooms.

The first implementation intentionally synchronizes devices signed into the
same Nomad account. That keeps authorization simple and avoids exposing a
private library through public room codes while still covering phone/tablet/TV
watch parties on a household server.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from app import database


ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_TTL_MINUTES = 20


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _parse(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


@dataclass(frozen=True)
class WatchParty:
    id: str
    user_id: int
    host_device_id: str
    host_name: str
    path: str
    state: str
    position: float
    rate: float
    quality: str
    adaptive: bool
    audio_track: Optional[int]
    subtitle_track: Optional[int]
    subtitle_burned: bool
    revision: int
    created_at: str
    updated_at: str
    expires_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WatchPartyMember:
    party_id: str
    user_id: int
    device_id: str
    name: str
    joined_at: str
    last_seen: str
    last_revision: int

    def to_dict(self, online_seconds: int = 12) -> Dict[str, Any]:
        data = asdict(self)
        seen = _parse(self.last_seen)
        data["online"] = bool(
            seen and _now_dt() - seen <= timedelta(seconds=max(5, online_seconds))
        )
        return data


class WatchPartyStore:
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
                    CREATE TABLE IF NOT EXISTS watch_parties (
                        id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        host_device_id TEXT NOT NULL,
                        host_name TEXT NOT NULL DEFAULT '',
                        path TEXT NOT NULL,
                        state TEXT NOT NULL DEFAULT 'paused',
                        position REAL NOT NULL DEFAULT 0,
                        rate REAL NOT NULL DEFAULT 1,
                        quality TEXT NOT NULL DEFAULT 'auto',
                        adaptive INTEGER NOT NULL DEFAULT 0,
                        audio_track INTEGER,
                        subtitle_track INTEGER,
                        subtitle_burned INTEGER NOT NULL DEFAULT 0,
                        revision INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_watch_parties_user
                        ON watch_parties(user_id, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS watch_party_members (
                        party_id TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        device_id TEXT NOT NULL,
                        name TEXT NOT NULL DEFAULT '',
                        joined_at TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        last_revision INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (party_id, user_id, device_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_watch_party_members_seen
                        ON watch_party_members(party_id, last_seen DESC);
                    """
                )
                conn.commit()
                self._ready = True
            finally:
                conn.close()

    @staticmethod
    def _party(row) -> WatchParty:
        return WatchParty(
            id=row["id"], user_id=int(row["user_id"]),
            host_device_id=row["host_device_id"], host_name=row["host_name"],
            path=row["path"], state=row["state"], position=float(row["position"] or 0),
            rate=float(row["rate"] or 1), quality=row["quality"], adaptive=bool(row["adaptive"]),
            audio_track=(int(row["audio_track"]) if row["audio_track"] is not None else None),
            subtitle_track=(int(row["subtitle_track"]) if row["subtitle_track"] is not None else None),
            subtitle_burned=bool(row["subtitle_burned"]), revision=int(row["revision"] or 0),
            created_at=row["created_at"], updated_at=row["updated_at"], expires_at=row["expires_at"],
        )

    @staticmethod
    def _member(row) -> WatchPartyMember:
        return WatchPartyMember(
            party_id=row["party_id"], user_id=int(row["user_id"]), device_id=row["device_id"],
            name=row["name"], joined_at=row["joined_at"], last_seen=row["last_seen"],
            last_revision=int(row["last_revision"] or 0),
        )

    def cleanup(self) -> int:
        self.ensure_schema()
        now = _now()
        conn = self._connect()
        try:
            expired = [row["id"] for row in conn.execute(
                "SELECT id FROM watch_parties WHERE expires_at < ?", (now,)
            ).fetchall()]
            if expired:
                placeholders = ",".join("?" for _ in expired)
                conn.execute(f"DELETE FROM watch_party_members WHERE party_id IN ({placeholders})", expired)
                conn.execute(f"DELETE FROM watch_parties WHERE id IN ({placeholders})", expired)
            # Old member presence can be discarded separately from the room.
            cutoff = (_now_dt() - timedelta(hours=8)).isoformat()
            conn.execute("DELETE FROM watch_party_members WHERE last_seen < ?", (cutoff,))
            conn.commit()
            return len(expired)
        finally:
            conn.close()

    def _new_code(self, conn) -> str:
        for _ in range(30):
            code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
            if not conn.execute("SELECT 1 FROM watch_parties WHERE id=?", (code,)).fetchone():
                return code
        raise RuntimeError("Could not allocate Watch Together code")

    def create(
        self,
        *,
        user_id: int,
        host_device_id: str,
        host_name: str,
        path: str,
        state: str,
        position: float,
        rate: float = 1.0,
        quality: str = "auto",
        adaptive: bool = False,
        audio_track: Optional[int] = None,
        subtitle_track: Optional[int] = None,
        subtitle_burned: bool = False,
    ) -> WatchParty:
        self.cleanup()
        now = _now_dt()
        expires = (now + timedelta(minutes=ROOM_TTL_MINUTES)).isoformat()
        conn = self._connect()
        try:
            code = self._new_code(conn)
            conn.execute(
                """
                INSERT INTO watch_parties
                    (id,user_id,host_device_id,host_name,path,state,position,rate,quality,adaptive,
                     audio_track,subtitle_track,subtitle_burned,revision,created_at,updated_at,expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)
                """,
                (
                    code, int(user_id), host_device_id, host_name[:150], path,
                    state if state in {"playing","paused"} else "paused",
                    max(0.0, float(position or 0)), max(0.25, min(4.0, float(rate or 1))),
                    str(quality or "auto")[:32], 1 if adaptive else 0,
                    audio_track, subtitle_track, 1 if subtitle_burned else 0,
                    now.isoformat(), now.isoformat(), expires,
                ),
            )
            conn.execute(
                """
                INSERT INTO watch_party_members
                    (party_id,user_id,device_id,name,joined_at,last_seen,last_revision)
                VALUES (?,?,?,?,?,?,1)
                """,
                (code, int(user_id), host_device_id, host_name[:150], now.isoformat(), now.isoformat()),
            )
            conn.commit()
            return self.get(user_id=user_id, party_id=code)
        finally:
            conn.close()

    def get(self, *, user_id: int, party_id: str) -> Optional[WatchParty]:
        self.ensure_schema()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM watch_parties WHERE id=? AND user_id=?",
                (str(party_id).upper(), int(user_id)),
            ).fetchone()
            if not row:
                return None
            party = self._party(row)
            expiry = _parse(party.expires_at)
            if expiry and expiry < _now_dt():
                return None
            return party
        finally:
            conn.close()

    def members(self, *, user_id: int, party_id: str) -> List[WatchPartyMember]:
        self.ensure_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM watch_party_members WHERE party_id=? AND user_id=? ORDER BY joined_at ASC",
                (str(party_id).upper(), int(user_id)),
            ).fetchall()
            return [self._member(row) for row in rows]
        finally:
            conn.close()

    def join(self, *, user_id: int, party_id: str, device_id: str, name: str) -> Optional[WatchParty]:
        party = self.get(user_id=user_id, party_id=party_id)
        if not party:
            return None
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO watch_party_members
                    (party_id,user_id,device_id,name,joined_at,last_seen,last_revision)
                VALUES (?,?,?,?,?,?,0)
                ON CONFLICT(party_id,user_id,device_id) DO UPDATE SET
                    name=excluded.name,last_seen=excluded.last_seen
                """,
                (party.id, int(user_id), device_id, name[:150], now, now),
            )
            conn.commit()
            return party
        finally:
            conn.close()

    def touch_member(
        self,
        *,
        user_id: int,
        party_id: str,
        device_id: str,
        revision: Optional[int] = None,
    ) -> bool:
        self.ensure_schema()
        conn = self._connect()
        try:
            if revision is None:
                cur = conn.execute(
                    "UPDATE watch_party_members SET last_seen=? WHERE party_id=? AND user_id=? AND device_id=?",
                    (_now(), str(party_id).upper(), int(user_id), device_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE watch_party_members SET last_seen=?,last_revision=? WHERE party_id=? AND user_id=? AND device_id=?",
                    (_now(), int(revision), str(party_id).upper(), int(user_id), device_id),
                )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def host_update(
        self,
        *,
        user_id: int,
        party_id: str,
        host_device_id: str,
        state: str,
        position: float,
        rate: float,
        quality: Optional[str] = None,
        adaptive: Optional[bool] = None,
        audio_track: Optional[int] = None,
        subtitle_track: Optional[int] = None,
        subtitle_burned: Optional[bool] = None,
    ) -> Optional[WatchParty]:
        party = self.get(user_id=user_id, party_id=party_id)
        if not party or party.host_device_id != host_device_id:
            return None
        now = _now_dt()
        revision = party.revision + 1
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE watch_parties SET
                    state=?,position=?,rate=?,quality=?,adaptive=?,audio_track=?,subtitle_track=?,
                    subtitle_burned=?,revision=?,updated_at=?,expires_at=?
                WHERE id=? AND user_id=? AND host_device_id=?
                """,
                (
                    state if state in {"playing","paused"} else party.state,
                    max(0.0, float(position or 0)), max(0.25, min(4.0, float(rate or 1))),
                    str(quality if quality is not None else party.quality)[:32],
                    1 if (party.adaptive if adaptive is None else adaptive) else 0,
                    party.audio_track if audio_track is None else audio_track,
                    party.subtitle_track if subtitle_track is None else subtitle_track,
                    1 if (party.subtitle_burned if subtitle_burned is None else subtitle_burned) else 0,
                    revision, now.isoformat(), (now + timedelta(minutes=ROOM_TTL_MINUTES)).isoformat(),
                    party.id, int(user_id), host_device_id,
                ),
            )
            conn.execute(
                "UPDATE watch_party_members SET last_seen=?,last_revision=? WHERE party_id=? AND user_id=? AND device_id=?",
                (now.isoformat(), revision, party.id, int(user_id), host_device_id),
            )
            conn.commit()
            return self.get(user_id=user_id, party_id=party.id)
        finally:
            conn.close()

    def leave(self, *, user_id: int, party_id: str, device_id: str) -> bool:
        self.ensure_schema()
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM watch_party_members WHERE party_id=? AND user_id=? AND device_id=?",
                (str(party_id).upper(), int(user_id), device_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def close(self, *, user_id: int, party_id: str, host_device_id: str) -> bool:
        party = self.get(user_id=user_id, party_id=party_id)
        if not party or party.host_device_id != host_device_id:
            return False
        conn = self._connect()
        try:
            conn.execute("DELETE FROM watch_party_members WHERE party_id=? AND user_id=?", (party.id, int(user_id)))
            cur = conn.execute("DELETE FROM watch_parties WHERE id=? AND user_id=?", (party.id, int(user_id)))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


store = WatchPartyStore()
