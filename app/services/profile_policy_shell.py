"""Synchronous profile-policy shell for legacy authenticated endpoints.

``get_current_user_id`` calls this after authentication. It deliberately avoids
reading request bodies; it enforces session binding, feature permissions,
library routing and query/path restrictions. New endpoints that need body-aware
checks additionally use ``profile_policy_guard``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request

from app import database
from app.services.household_profiles import HouseholdProfileStore
from app.services.profile_policy import _legacy_profile_policy, assert_policy, normalise_policy


def _header(request: Request, name: str) -> Optional[str]:
    try:
        return (request.headers or {}).get(name)
    except Exception:
        return None


def enforce_request_policy_shell(request: Request, user_id: int, token: str):
    path = request.url.path.lower()
    # Profile selection/management must remain reachable so a restricted
    # profile can switch back to an adult profile after valid PIN verification.
    if "/profile" in path:
        return None

    household = HouseholdProfileStore(database.DB_PATH)
    try:
        bound = household.binding(user_id=int(user_id), token=token)
    except Exception:
        bound = None

    raw = _header(request, "X-Nomad-Profile-ID") or request.query_params.get("profile_id")
    requested_id = None
    if raw:
        try:
            requested_id = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid profile context")

    if bound and requested_id is not None and requested_id != bound.id:
        raise HTTPException(
            status_code=409,
            detail="This login session is bound to another profile; use the profile switch action",
        )

    # A login has already proven the account password. If a client has never
    # selected a household profile, bind the account's default immediately so
    # API clients cannot bypass policy simply by omitting the profile header.
    if bound is None and requested_id is None:
        default = household.default(int(user_id))
        bound = household.bind(user_id=int(user_id), token=token, profile_id=default.id)

    active_id = bound.id if bound else requested_id
    if active_id is None:
        return None

    profile = household.get(int(user_id), int(active_id))
    is_default_profile = True
    if profile is None:
        policy = _legacy_profile_policy(int(user_id), int(active_id))
        if policy is None:
            raise HTTPException(status_code=403, detail="Profile does not belong to this account")
    else:
        is_default_profile = bool(profile.is_default)
        if not bound:
            if profile.pin_required:
                raise HTTPException(
                    status_code=423,
                    detail="This profile requires its PIN; use the profile switch action",
                )
            household.bind(user_id=int(user_id), token=token, profile_id=profile.id)
        policy = normalise_policy(profile.parental_controls)
        policy.update({
            "profile_id": profile.id,
            "profile_name": profile.name,
            "pin_required": profile.pin_required,
        })

    # Photos are now a profile-private subsystem. The old generic gallery index
    # had no ownership model, so leaving it reachable would let one household
    # profile bypass the Photos API and enumerate another profile's filenames.
    # All Gallery UI traffic goes through /api/playback/gallery instead.
    if path.startswith("/api/media/library/gallery"):
        raise HTTPException(status_code=410, detail="Gallery is profile-private; use the Photos library")

    requested_path = str(request.query_params.get("path") or "").replace("\\", "/").lower()
    if requested_path.startswith("/data/.nomad_gallery"):
        raise HTTPException(status_code=403, detail="Profile photos must be opened from the Photos library")
    if requested_path.startswith("/data/gallery") and not is_default_profile:
        raise HTTPException(status_code=403, detail="This photo library belongs to another profile")

    # A personal photo library is not age-rated entertainment. Existing child
    # profile presets predate Gallery and therefore omit it from
    # allowed_libraries. Treat Gallery as allowed unless an admin explicitly
    # puts it in blocked_libraries. This lets every profile have its own photos
    # without weakening movie/show/music restrictions.
    if "gallery" not in set(policy.get("blocked_libraries") or []):
        allowed = list(policy.get("allowed_libraries") or [])
        if allowed and "gallery" not in allowed:
            policy["allowed_libraries"] = [*allowed, "gallery"]

    # This shell intentionally supplies no body payload. Query/path based
    # library and feature restrictions still cover legacy browse/stream/delete
    # and all debrid routes. Body-aware playback creation is checked again by
    # profile_policy_guard.
    assert_policy(policy, request=request, payload={})
    request.state.nomad_profile_policy = policy
    return policy
