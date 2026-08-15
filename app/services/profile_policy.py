"""Backend household/profile content-policy enforcement.

The existing profiles table already stores ``parental_controls``. This module
normalises that JSON and provides a FastAPI dependency that can be attached to
media/playback/debrid routers. Main-account requests without a profile context
retain existing behaviour; requests carrying an active profile context are
checked before the endpoint executes.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request

from app import database
from app.routers.auth import get_current_user_id


DEFAULT_POLICY = {
    "enabled": False,
    "allowed_libraries": [],
    "blocked_libraries": [],
    "blocked_terms": [],
    "max_age": None,
    "block_unrated": False,
    "allow_debrid": True,
    "allow_downloads": True,
    "allow_offline_sync": True,
    "allow_delete": True,
}

RATING_AGES = {
    "U": 0, "G": 0, "TV-Y": 0, "TV-Y7": 7,
    "PG": 8, "TV-PG": 8,
    "12": 12, "12A": 12, "PG-13": 13, "TV-14": 14,
    "15": 15, "16": 16, "R": 17, "TV-MA": 17, "NC-17": 17,
    "18": 18, "R18": 18,
}


def _connect():
    conn = sqlite3.connect(database.DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _json(value, default):
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed
    except Exception:
        return default


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _list(value):
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower() for item in value if str(item).strip()]


def normalise_policy(raw: Any) -> Dict[str, Any]:
    data = _json(raw, {})
    if not isinstance(data, dict):
        data = {}
    policy = dict(DEFAULT_POLICY)
    # Support a few historical/obvious aliases without requiring a migration.
    enabled = data.get("enabled", data.get("parental_controls_enabled", bool(data)))
    policy["enabled"] = _bool(enabled, False)
    policy["allowed_libraries"] = _list(data.get("allowed_libraries", data.get("libraries")))
    policy["blocked_libraries"] = _list(data.get("blocked_libraries"))
    policy["blocked_terms"] = _list(data.get("blocked_terms", data.get("blocked_keywords")))
    max_age = data.get("max_age", data.get("max_rating_age"))
    try:
        policy["max_age"] = max(0, min(21, int(max_age))) if max_age is not None else None
    except (TypeError, ValueError):
        policy["max_age"] = None
    policy["block_unrated"] = _bool(data.get("block_unrated"), False)
    policy["allow_debrid"] = _bool(data.get("allow_debrid"), True)
    policy["allow_downloads"] = _bool(data.get("allow_downloads"), True)
    policy["allow_offline_sync"] = _bool(data.get("allow_offline_sync", data.get("allow_offline")), True)
    policy["allow_delete"] = _bool(data.get("allow_delete"), True)
    return policy


def get_profile_policy(user_id: int, profile_id: int) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()}
        if not {"id", "user_id"}.issubset(columns):
            return None
        controls_col = "parental_controls" if "parental_controls" in columns else None
        name_col = "name" if "name" in columns else None
        selected = ["id", "user_id"]
        if name_col: selected.append(name_col)
        if controls_col: selected.append(controls_col)
        row = conn.execute(
            f"SELECT {','.join(selected)} FROM profiles WHERE id=? AND user_id=?",
            (int(profile_id), int(user_id)),
        ).fetchone()
        if not row:
            return None
        policy = normalise_policy(row[controls_col] if controls_col else {})
        policy["profile_id"] = int(row["id"])
        policy["profile_name"] = row[name_col] if name_col else f"Profile {profile_id}"
        return policy
    finally:
        conn.close()


def _library_from_path(path: str) -> Optional[str]:
    value = str(path or "").lower().replace("\\", "/")
    for library in ("movies", "shows", "music", "books", "gallery", "files"):
        if f"/data/{library}/" in value or value.endswith(f"/data/{library}"):
            return library
    # External media can still be classified from the route category when the
    # actual file path is outside /data.
    return None


def _library_from_request(request: Request, payload: Dict[str, Any]) -> Optional[str]:
    path = request.url.path.lower()
    for library in ("movies", "shows", "music", "books", "gallery", "files"):
        if f"/{library}" in path:
            return library
    candidate = payload.get("path") or request.query_params.get("path") or ""
    return _library_from_path(candidate)


def _feature_for_request(request: Request) -> Optional[str]:
    path = request.url.path.lower()
    if "/debrid" in path or "/stream-keep" in path:
        return "debrid"
    if "/offline" in path:
        return "offline_sync"
    if request.method.upper() == "DELETE" and ("/media/" in path or "/playback/" in path):
        return "delete"
    if "download" in path:
        return "downloads"
    return None


def rating_to_age(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text or text in {"N/A", "NR", "UNRATED", "NOT RATED"}:
        return None
    # Handle values like "Rated PG-13", "15 (UK)", "TV-14".
    text = re.sub(r"^RATED\s+", "", text)
    for label, age in sorted(RATING_AGES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?<![A-Z0-9]){re.escape(label)}(?![A-Z0-9])", text):
            return age
    match = re.search(r"(?<!\d)(?:AGE\s*)?(\d{1,2})(?!\d)", text)
    if match:
        age = int(match.group(1))
        return age if 0 <= age <= 21 else None
    return None


def _metadata_rating(path: str) -> Optional[int]:
    if not path:
        return None
    conn = _connect()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(file_metadata)").fetchall()}
        if not columns or "path" not in columns:
            return None
        useful = [name for name in ("rating", "rated", "certification", "content_rating", "metadata", "metadata_json") if name in columns]
        if not useful:
            return None
        row = conn.execute(
            f"SELECT {','.join(useful)} FROM file_metadata WHERE path=? LIMIT 1",
            (path,),
        ).fetchone()
        if not row:
            return None
        for name in ("rating", "rated", "certification", "content_rating"):
            if name in useful:
                age = rating_to_age(row[name])
                if age is not None:
                    return age
        for name in ("metadata", "metadata_json"):
            if name not in useful:
                continue
            data = _json(row[name], {})
            if isinstance(data, dict):
                for key in ("rated", "rating", "certification", "content_rating", "mpaa"):
                    age = rating_to_age(data.get(key))
                    if age is not None:
                        return age
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None


def assert_policy(policy: Dict[str, Any], *, request: Request, payload: Dict[str, Any]) -> None:
    if not policy or not policy.get("enabled"):
        return
    feature = _feature_for_request(request)
    if feature == "debrid" and not policy.get("allow_debrid", True):
        raise HTTPException(status_code=403, detail="This profile cannot use remote/debrid acquisition")
    if feature == "offline_sync" and not policy.get("allow_offline_sync", True):
        raise HTTPException(status_code=403, detail="This profile cannot prepare offline copies")
    if feature == "downloads" and not policy.get("allow_downloads", True):
        raise HTTPException(status_code=403, detail="Downloads are disabled for this profile")
    if feature == "delete" and not policy.get("allow_delete", True):
        raise HTTPException(status_code=403, detail="Deleting media is disabled for this profile")

    library = _library_from_request(request, payload)
    allowed = set(policy.get("allowed_libraries") or [])
    blocked = set(policy.get("blocked_libraries") or [])
    if library and allowed and library not in allowed:
        raise HTTPException(status_code=403, detail=f"The {library} library is not available to this profile")
    if library and library in blocked:
        raise HTTPException(status_code=403, detail=f"The {library} library is blocked for this profile")

    candidate = str(payload.get("path") or request.query_params.get("path") or payload.get("title") or request.query_params.get("q") or "")
    lowered = candidate.lower()
    for term in policy.get("blocked_terms") or []:
        if term and term in lowered:
            raise HTTPException(status_code=403, detail="This item is blocked for the active profile")

    max_age = policy.get("max_age")
    if max_age is not None and candidate:
        age = _metadata_rating(str(payload.get("path") or request.query_params.get("path") or ""))
        if age is None and policy.get("block_unrated"):
            raise HTTPException(status_code=403, detail="Unrated media is blocked for this profile")
        if age is not None and age > int(max_age):
            raise HTTPException(status_code=403, detail=f"This title exceeds the profile age limit ({max_age})")


async def profile_policy_guard(
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    raw_profile = request.headers.get("X-Nomad-Profile-ID") or request.query_params.get("profile_id")
    if not raw_profile:
        return None
    try:
        profile_id = int(raw_profile)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid profile context")
    policy = get_profile_policy(user_id, profile_id)
    if policy is None:
        raise HTTPException(status_code=403, detail="Profile does not belong to this account")

    payload: Dict[str, Any] = {}
    if request.method.upper() in {"POST", "PUT", "PATCH"}:
        try:
            body = await request.body()
            if body:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    payload = parsed
        except Exception:
            payload = {}
    assert_policy(policy, request=request, payload=payload)
    request.state.nomad_profile_policy = policy
    return policy
