"""Signed, revocable read-only tokens for wall displays.

The dashboard websocket and its public snapshot were open to anyone who could
reach the port: no auth at all, streaming every session's title, poster and
progress. That was a deliberate concession to the ESP32 display, which cannot
hold an interactive login — but "no auth" is a much bigger grant than that
device needs.

A display token is an HMAC over a tiny payload, carrying a read-only scope and
a generation counter. It is long-lived because a picture frame on a shelf must
survive a reboot without a human, and revocable because bumping the stored
generation invalidates every token ever issued. It is signed with the same
secret as stream tickets but carries a distinct ``purpose``, so neither kind
can be replayed as the other.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from hashlib import sha256
from typing import Any, Dict, Optional

from app import database
from app.services.playback.tickets import load_or_create_secret

PURPOSE = "display"
GENERATION_SETTING = "display_token_generation"
DEFAULT_TTL_DAYS = 365


class DisplayTokenError(ValueError):
    """Raised when a presented token is missing, malformed, stale or revoked."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))
    except Exception as exc:
        raise DisplayTokenError("Malformed display token") from exc


def current_generation() -> int:
    """The generation every valid token must carry. Bumping it revokes all."""
    try:
        return int(database.get_setting(GENERATION_SETTING) or 1)
    except (TypeError, ValueError):
        return 1


def revoke_all() -> int:
    """Invalidate every issued display token; returns the new generation."""
    generation = current_generation() + 1
    database.set_setting(GENERATION_SETTING, str(generation))
    return generation


def issue(*, label: str = "display", ttl_days: int = DEFAULT_TTL_DAYS, now: Optional[int] = None) -> str:
    issued = int(time.time() if now is None else now)
    payload = {
        "v": 1,
        "purpose": PURPOSE,
        "scope": "read",
        "label": str(label)[:64],
        "gen": current_generation(),
        "iat": issued,
        "exp": issued + int(ttl_days) * 86400,
        "nonce": secrets.token_urlsafe(6),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64encode(body)
    signature = hmac.new(load_or_create_secret(), encoded.encode("ascii"), sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify(token: str, *, now: Optional[int] = None) -> Dict[str, Any]:
    """Return the payload of a valid token, or raise DisplayTokenError."""
    if not token or not isinstance(token, str):
        raise DisplayTokenError("Display token required")
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise DisplayTokenError("Malformed display token") from exc

    expected = hmac.new(load_or_create_secret(), encoded.encode("ascii"), sha256).digest()
    if not hmac.compare_digest(_b64decode(signature), expected):
        raise DisplayTokenError("Invalid display token")

    try:
        payload = json.loads(_b64decode(encoded))
    except ValueError as exc:
        raise DisplayTokenError("Malformed display token") from exc
    if not isinstance(payload, dict):
        raise DisplayTokenError("Malformed display token")

    # A stream ticket is signed with the same key, so the purpose check is what
    # stops one being presented as the other.
    if payload.get("purpose") != PURPOSE:
        raise DisplayTokenError("Token is not a display token")
    if payload.get("gen") != current_generation():
        raise DisplayTokenError("Display token has been revoked")

    moment = int(time.time() if now is None else now)
    if int(payload.get("exp", 0)) <= moment:
        raise DisplayTokenError("Display token has expired")
    return payload
