"""Household profile switching, policy and PIN-management API."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import database
from app.routers import auth
from app.routers.auth import get_current_user_id
from app.services.household_profiles import HouseholdProfileStore
from app.services.profile_policy import get_profile_policy


router = APIRouter()
store = HouseholdProfileStore()
_pin_attempts = defaultdict(list)
PIN_MAX_ATTEMPTS = 6
PIN_LOCKOUT_MINUTES = 10


class SwitchProfileRequest(BaseModel):
    profile_id: int = Field(gt=0)
    pin: Optional[str] = Field(default=None, max_length=8)


class CreateProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    avatar: Optional[str] = Field(default=None, max_length=500)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    parental_controls: Dict[str, Any] = Field(default_factory=dict)
    account_password: str = Field(min_length=1, max_length=500)


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    avatar: Optional[str] = Field(default=None, max_length=500)
    preferences: Optional[Dict[str, Any]] = None
    parental_controls: Optional[Dict[str, Any]] = None
    account_password: str = Field(min_length=1, max_length=500)


class ProfilePinRequest(BaseModel):
    pin: Optional[str] = Field(default=None, max_length=8)
    account_password: str = Field(min_length=1, max_length=500)


class DeleteProfileRequest(BaseModel):
    account_password: str = Field(min_length=1, max_length=500)


def _request_token(request: Request) -> str:
    token = auth._extract_auth_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token


def _profile_public(profile) -> dict:
    data = profile.to_dict()
    # The hash itself is never exposed; callers only need to know whether a PIN
    # prompt is required when switching into this profile.
    return data


def _verify_account_password(user_id: int, password: str) -> None:
    user = database.get_user_by_id(int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        valid = auth.pwd_context.verify(password, user["password_hash"])
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(status_code=403, detail="Account password is incorrect")


def _pin_key(request: Request, user_id: int, profile_id: int) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{int(user_id)}:{int(profile_id)}"


def _check_pin_rate(request: Request, user_id: int, profile_id: int) -> str:
    key = _pin_key(request, user_id, profile_id)
    cutoff = datetime.now() - timedelta(minutes=PIN_LOCKOUT_MINUTES)
    _pin_attempts[key] = [item for item in _pin_attempts[key] if item >= cutoff]
    if len(_pin_attempts[key]) >= PIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many incorrect profile PIN attempts. Try again in {PIN_LOCKOUT_MINUTES} minutes.",
        )
    return key


def _clear_pin_attempts(key: str) -> None:
    _pin_attempts[key] = []


@router.get("/profile-policy")
def profile_policy(
    profile_id: int = Query(..., gt=0),
    user_id: int = Depends(get_current_user_id),
):
    policy = get_profile_policy(user_id, profile_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"policy": policy}


@router.get("/profiles")
def list_profiles(
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    token = _request_token(request)
    profiles = store.list(user_id)
    current = store.binding(user_id=user_id, token=token)
    if current is None:
        # A freshly authenticated login has already proven the account password,
        # so binding its default profile does not require that profile's PIN.
        current = store.bind(user_id=user_id, token=token, profile_id=store.default(user_id).id)
    return {
        "profiles": [_profile_public(profile) for profile in profiles],
        "current": _profile_public(current),
    }


@router.get("/profiles/current")
def current_profile(
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    token = _request_token(request)
    current = store.binding(user_id=user_id, token=token)
    if current is None:
        current = store.bind(user_id=user_id, token=token, profile_id=store.default(user_id).id)
    return {"profile": _profile_public(current)}


@router.post("/profiles/switch")
def switch_profile(
    body: SwitchProfileRequest,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    token = _request_token(request)
    target = store.get(user_id, body.profile_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    current = store.binding(user_id=user_id, token=token)
    if current and current.id == target.id:
        return {"profile": _profile_public(target), "changed": False}

    if target.pin_required:
        key = _check_pin_rate(request, user_id, target.id)
        if not store.verify_pin(user_id=user_id, profile_id=target.id, pin=body.pin):
            _pin_attempts[key].append(datetime.now())
            raise HTTPException(status_code=403, detail="Incorrect profile PIN")
        _clear_pin_attempts(key)

    selected = store.bind(user_id=user_id, token=token, profile_id=target.id)
    return {"profile": _profile_public(selected), "changed": True}


@router.post("/profiles")
def create_profile(
    body: CreateProfileRequest,
    user_id: int = Depends(get_current_user_id),
):
    _verify_account_password(user_id, body.account_password)
    try:
        profile = store.create(
            user_id=user_id,
            name=body.name,
            avatar=body.avatar,
            preferences=body.preferences,
            parental_controls=body.parental_controls,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"profile": _profile_public(profile)}


@router.put("/profiles/{profile_id}")
def update_profile(
    profile_id: int,
    body: UpdateProfileRequest,
    user_id: int = Depends(get_current_user_id),
):
    _verify_account_password(user_id, body.account_password)
    profile = store.update(
        user_id=user_id,
        profile_id=profile_id,
        name=body.name,
        avatar=body.avatar,
        preferences=body.preferences,
        parental_controls=body.parental_controls,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"profile": _profile_public(profile)}


@router.post("/profiles/{profile_id}/pin")
def set_profile_pin(
    profile_id: int,
    body: ProfilePinRequest,
    user_id: int = Depends(get_current_user_id),
):
    _verify_account_password(user_id, body.account_password)
    try:
        profile = store.set_pin(user_id=user_id, profile_id=profile_id, pin=body.pin)
    except KeyError:
        raise HTTPException(status_code=404, detail="Profile not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"profile": _profile_public(profile)}


@router.post("/profiles/{profile_id}/delete")
def delete_profile(
    profile_id: int,
    body: DeleteProfileRequest,
    user_id: int = Depends(get_current_user_id),
):
    _verify_account_password(user_id, body.account_password)
    try:
        deleted = store.delete(user_id=user_id, profile_id=profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"deleted": True}
