"""Short-lived signed stream tickets for media URLs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any, Dict, Optional


class TicketError(ValueError):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))
    except Exception as exc:
        raise TicketError("Malformed stream ticket") from exc


def load_or_create_secret() -> bytes:
    configured = os.environ.get("NOMAD_STREAM_TICKET_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")

    secret_path = Path(os.environ.get("NOMAD_STREAM_TICKET_SECRET_FILE", "data/.stream_ticket_secret"))
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing.encode("utf-8")
    except FileNotFoundError:
        pass

    value = secrets.token_urlsafe(48)
    try:
        fd = os.open(str(secret_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
    except FileExistsError:
        value = secret_path.read_text(encoding="utf-8").strip()
    try:
        os.chmod(secret_path, 0o600)
    except OSError:
        pass
    return value.encode("utf-8")


class StreamTicketSigner:
    def __init__(self, secret: Optional[bytes] = None, ttl_seconds: Optional[int] = None):
        self.secret = secret or load_or_create_secret()
        configured_ttl = int(os.environ.get("NOMAD_STREAM_TICKET_TTL", "21600"))
        self.ttl_seconds = int(ttl_seconds if ttl_seconds is not None else configured_ttl)
        if self.ttl_seconds < 60:
            raise ValueError("Stream ticket TTL must be at least 60 seconds")

    def issue(self, *, session_id: str, user_id: int, now: Optional[int] = None) -> str:
        issued = int(time.time() if now is None else now)
        payload = {
            "v": 1,
            "purpose": "stream",
            "sid": str(session_id),
            "uid": int(user_id),
            "iat": issued,
            "exp": issued + self.ttl_seconds,
            "nonce": secrets.token_urlsafe(8),
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encoded = _b64encode(body)
        signature = hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_b64encode(signature)}"

    def verify(
        self,
        ticket: str,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        now: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            encoded, supplied_sig = ticket.split(".", 1)
        except (AttributeError, ValueError) as exc:
            raise TicketError("Malformed stream ticket") from exc

        expected_sig = hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, _b64decode(supplied_sig)):
            raise TicketError("Invalid stream ticket signature")

        try:
            payload = json.loads(_b64decode(encoded).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise TicketError("Malformed stream ticket payload") from exc

        current = int(time.time() if now is None else now)
        if payload.get("v") != 1 or payload.get("purpose") != "stream":
            raise TicketError("Unsupported stream ticket")
        if not isinstance(payload.get("exp"), int) or payload["exp"] < current:
            raise TicketError("Stream ticket expired")
        if session_id is not None and payload.get("sid") != str(session_id):
            raise TicketError("Stream ticket is for another playback session")
        if user_id is not None and payload.get("uid") != int(user_id):
            raise TicketError("Stream ticket is for another user")
        return payload
