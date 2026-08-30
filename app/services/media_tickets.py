"""Short-lived signed tickets for URLs that cannot carry a header.

A `<video src>`, a CSS background, an `<a download>` and a handoff to VLC all
authenticate through the URL itself. Nomad used to put the raw session token
there — a 30-day credential for the whole API, pasted into browser history,
proxy logs, `Referer` headers and any screenshot of the address bar. A leaked
stream URL was a leaked account.

A media ticket is the narrow version of that: signed, bound to one user, valid
for hours rather than a month, and accepted only by endpoints that serve
bytes. It cannot log in, change a password, or reach the admin API.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from hashlib import sha256
from typing import Any, Dict, Optional

from app.services.playback.tickets import load_or_create_secret

PURPOSE = "media"
DEFAULT_TTL_SECONDS = int(os.environ.get("NOMAD_MEDIA_TICKET_TTL", "21600"))  # 6 hours


class MediaTicketError(ValueError):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))
    except Exception as exc:
        raise MediaTicketError("Malformed media ticket") from exc


def issue(user_id: int, *, ttl_seconds: Optional[int] = None, now: Optional[int] = None) -> str:
    issued = int(time.time() if now is None else now)
    ttl = int(DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds)
    payload = {
        "v": 1,
        "purpose": PURPOSE,
        "uid": int(user_id),
        "iat": issued,
        "exp": issued + max(60, ttl),
        "nonce": secrets.token_urlsafe(6),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64encode(body)
    signature = hmac.new(load_or_create_secret(), encoded.encode("ascii"), sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify(ticket: str, *, now: Optional[int] = None) -> Dict[str, Any]:
    """Return the payload of a valid ticket, or raise MediaTicketError."""
    if not ticket or not isinstance(ticket, str):
        raise MediaTicketError("Media ticket required")
    try:
        encoded, signature = ticket.split(".", 1)
    except ValueError as exc:
        raise MediaTicketError("Malformed media ticket") from exc

    expected = hmac.new(load_or_create_secret(), encoded.encode("ascii"), sha256).digest()
    if not hmac.compare_digest(_b64decode(signature), expected):
        raise MediaTicketError("Invalid media ticket")

    try:
        payload = json.loads(_b64decode(encoded))
    except ValueError as exc:
        raise MediaTicketError("Malformed media ticket") from exc
    if not isinstance(payload, dict):
        raise MediaTicketError("Malformed media ticket")

    # Display tokens and playback stream tickets share this secret, so the
    # purpose check is what keeps the three from being interchangeable.
    if payload.get("purpose") != PURPOSE:
        raise MediaTicketError("Token is not a media ticket")

    moment = int(time.time() if now is None else now)
    if int(payload.get("exp", 0)) <= moment:
        raise MediaTicketError("Media ticket has expired")
    try:
        payload["uid"] = int(payload["uid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaTicketError("Malformed media ticket") from exc
    return payload


def user_id_from(ticket: str) -> int:
    return verify(ticket)["uid"]
