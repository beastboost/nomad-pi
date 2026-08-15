"""Household profiles, optional switch PINs and per-login profile binding.

The legacy ``profiles`` table is intentionally left untouched because it has a
UNIQUE(user_id) constraint. The first time this service is used it mirrors that
legacy row into ``household_profiles`` using the same numeric id where possible,
so existing clients keep their profile identity while an account can add more
profiles safely.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from passlib.context import CryptContext

from app import database

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _json(value, default):
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed
    except Exception:
        return default


@dataclass(frozen=True)
class HouseholdProfile:
    id: int
    user_id: int
    name: str
    avatar: Optional[str]
    preferences: Dict[str, Any]
    parental_controls: Dict[str, Any]
    pin_required: bool
    is_default: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class HouseholdProfileStore:
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

    def ensure_schema(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS household_profiles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        avatar TEXT,
                        preferences_json TEXT NOT NULL DEFAULT '{}',
                        parental_controls_json TEXT NOT NULL DEFAULT '{}',
                        pin_hash TEXT,
                        is_default INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_household_profiles_user
                        ON household_profiles(user_id, is_default DESC, id ASC);

                    CREATE TABLE IF NOT EXISTS profile_session_bindings (
                        token_hash TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        profile_id INTEGER NOT NULL,
                        bound_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_profile_bindings_user
                        ON profile_session_bindings(user_id, updated_at DESC);
                    """
                )
                conn.commit()
                self._ready = True
            finally:
                conn.close()

    @staticmethod
    def _profile(row: sqlite3.Row) -> HouseholdProfile:
        prefs = _json(row["preferences_json"], {})
        controls = _json(row["parental_controls_json"], {})
        return HouseholdProfile(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=row["name"],
            avatar=row["avatar"],
            preferences=prefs if isinstance(prefs, dict) else {},
            parental_controls=controls if isinstance(controls, dict) else {},
            pin_required=bool(row["pin_hash"]),
            is_default=bool(row["is_default"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _ensure_default(self, user_id: int) -> None:
        self.ensure_schema()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM household_profiles WHERE user_id=? LIMIT 1",
                (int(user_id),),
            ).fetchone()
            if existing:
                return

            legacy = None
            try:
                legacy = conn.execute(
                    "SELECT id,name,avatar,preferences,parental_controls FROM profiles WHERE user_id=? LIMIT 1",
                    (int(user_id),),
                ).fetchone()
            except sqlite3.Error:
                legacy = None
            user = conn.execute("SELECT username FROM users WHERE id=?", (int(user_id),)).fetchone()
            name = (legacy["name"] if legacy and legacy["name"] else (user["username"] if user else "Profile"))
            avatar = legacy["avatar"] if legacy else None
            preferences = _json(legacy["preferences"], {}) if legacy else {}
            controls = _json(legacy["parental_controls"], {}) if legacy else {}
            now = _now()
            inserted = False
            if legacy:
                try:
                    conn.execute(
                        """
                        INSERT INTO household_profiles
                            (id,user_id,name,avatar,preferences_json,parental_controls_json,pin_hash,is_default,created_at,updated_at)
                        VALUES (?,?,?,?,?,? ,NULL,1,?,?)
                        """,
                        (
                            int(legacy["id"]), int(user_id), str(name), avatar,
                            json.dumps(preferences if isinstance(preferences, dict) else {}, separators=(",", ":")),
                            json.dumps(controls if isinstance(controls, dict) else {}, separators=(",", ":")),
                            now, now,
                        ),
                    )
                    inserted = True
                except sqlite3.IntegrityError:
                    inserted = False
            if not inserted:
                conn.execute(
                    """
                    INSERT INTO household_profiles
                        (user_id,name,avatar,preferences_json,parental_controls_json,pin_hash,is_default,created_at,updated_at)
                    VALUES (?,?,?,?,?,NULL,1,?,?)
                    """,
                    (
                        int(user_id), str(name), avatar,
                        json.dumps(preferences if isinstance(preferences, dict) else {}, separators=(",", ":")),
                        json.dumps(controls if isinstance(controls, dict) else {}, separators=(",", ":")),
                        now, now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def list(self, user_id: int) -> List[HouseholdProfile]:
        self._ensure_default(user_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM household_profiles WHERE user_id=? ORDER BY is_default DESC, id ASC",
                (int(user_id),),
            ).fetchall()
            return [self._profile(row) for row in rows]
        finally:
            conn.close()

    def get(self, user_id: int, profile_id: int) -> Optional[HouseholdProfile]:
        self._ensure_default(user_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM household_profiles WHERE id=? AND user_id=?",
                (int(profile_id), int(user_id)),
            ).fetchone()
            return self._profile(row) if row else None
        finally:
            conn.close()

    def default(self, user_id: int) -> HouseholdProfile:
        profiles = self.list(user_id)
        if not profiles:
            raise RuntimeError("Could not create default household profile")
        return next((p for p in profiles if p.is_default), profiles[0])

    def create(
        self,
        *,
        user_id: int,
        name: str,
        avatar: Optional[str] = None,
        preferences: Optional[Dict[str, Any]] = None,
        parental_controls: Optional[Dict[str, Any]] = None,
    ) -> HouseholdProfile:
        self._ensure_default(user_id)
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Profile name is required")
        now = _now()
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO household_profiles
                    (user_id,name,avatar,preferences_json,parental_controls_json,pin_hash,is_default,created_at,updated_at)
                VALUES (?,?,?,?,?,NULL,0,?,?)
                """,
                (
                    int(user_id), clean_name[:100], avatar,
                    json.dumps(preferences or {}, separators=(",", ":")),
                    json.dumps(parental_controls or {}, separators=(",", ":")),
                    now, now,
                ),
            )
            conn.commit()
            return self.get(user_id, int(cur.lastrowid))
        finally:
            conn.close()

    def update(
        self,
        *,
        user_id: int,
        profile_id: int,
        name: Optional[str] = None,
        avatar: Optional[str] = None,
        preferences: Optional[Dict[str, Any]] = None,
        parental_controls: Optional[Dict[str, Any]] = None,
    ) -> Optional[HouseholdProfile]:
        current = self.get(user_id, profile_id)
        if not current:
            return None
        values = {
            "name": (str(name).strip()[:100] if name is not None else current.name),
            "avatar": (avatar if avatar is not None else current.avatar),
            "preferences_json": json.dumps(preferences if preferences is not None else current.preferences, separators=(",", ":")),
            "parental_controls_json": json.dumps(parental_controls if parental_controls is not None else current.parental_controls, separators=(",", ":")),
            "updated_at": _now(),
        }
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE household_profiles
                SET name=?,avatar=?,preferences_json=?,parental_controls_json=?,updated_at=?
                WHERE id=? AND user_id=?
                """,
                (
                    values["name"], values["avatar"], values["preferences_json"],
                    values["parental_controls_json"], values["updated_at"],
                    int(profile_id), int(user_id),
                ),
            )
            conn.commit()
            return self.get(user_id, profile_id)
        finally:
            conn.close()

    def delete(self, *, user_id: int, profile_id: int) -> bool:
        profiles = self.list(user_id)
        target = next((p for p in profiles if p.id == int(profile_id)), None)
        if not target:
            return False
        if len(profiles) <= 1:
            raise ValueError("An account must keep at least one profile")
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM household_profiles WHERE id=? AND user_id=?",
                (int(profile_id), int(user_id)),
            )
            conn.execute(
                "DELETE FROM profile_session_bindings WHERE user_id=? AND profile_id=?",
                (int(user_id), int(profile_id)),
            )
            if target.is_default:
                replacement = conn.execute(
                    "SELECT id FROM household_profiles WHERE user_id=? ORDER BY id ASC LIMIT 1",
                    (int(user_id),),
                ).fetchone()
                if replacement:
                    conn.execute("UPDATE household_profiles SET is_default=1 WHERE id=?", (int(replacement["id"]),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_pin(self, *, user_id: int, profile_id: int, pin: Optional[str]) -> HouseholdProfile:
        profile = self.get(user_id, profile_id)
        if not profile:
            raise KeyError("Profile not found")
        clean = str(pin or "").strip()
        if clean and (not clean.isdigit() or not 4 <= len(clean) <= 8):
            raise ValueError("Profile PIN must be 4–8 digits")
        pin_hash = _pwd.hash(clean) if clean else None
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE household_profiles SET pin_hash=?,updated_at=? WHERE id=? AND user_id=?",
                (pin_hash, _now(), int(profile_id), int(user_id)),
            )
            conn.commit()
            return self.get(user_id, profile_id)
        finally:
            conn.close()

    def verify_pin(self, *, user_id: int, profile_id: int, pin: Optional[str]) -> bool:
        self._ensure_default(user_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT pin_hash FROM household_profiles WHERE id=? AND user_id=?",
                (int(profile_id), int(user_id)),
            ).fetchone()
            if not row:
                return False
            hashed = row["pin_hash"]
            if not hashed:
                return True
            try:
                return bool(_pwd.verify(str(pin or ""), hashed))
            except Exception:
                return False
        finally:
            conn.close()

    def binding(self, *, user_id: int, token: str) -> Optional[HouseholdProfile]:
        if not token:
            return None
        self._ensure_default(user_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT profile_id FROM profile_session_bindings WHERE token_hash=? AND user_id=?",
                (token_fingerprint(token), int(user_id)),
            ).fetchone()
            if not row:
                return None
            return self.get(user_id, int(row["profile_id"]))
        finally:
            conn.close()

    def bind(self, *, user_id: int, token: str, profile_id: int) -> HouseholdProfile:
        if not token:
            raise ValueError("Authenticated session token is required")
        profile = self.get(user_id, profile_id)
        if not profile:
            raise KeyError("Profile not found")
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO profile_session_bindings (token_hash,user_id,profile_id,bound_at,updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(token_hash) DO UPDATE SET
                    user_id=excluded.user_id,
                    profile_id=excluded.profile_id,
                    bound_at=excluded.bound_at,
                    updated_at=excluded.updated_at
                """,
                (token_fingerprint(token), int(user_id), int(profile_id), now, now),
            )
            conn.commit()
            return profile
        finally:
            conn.close()

    def unbind(self, *, user_id: int, token: str) -> None:
        if not token:
            return
        self.ensure_schema()
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM profile_session_bindings WHERE token_hash=? AND user_id=?",
                (token_fingerprint(token), int(user_id)),
            )
            conn.commit()
        finally:
            conn.close()


store = HouseholdProfileStore()
