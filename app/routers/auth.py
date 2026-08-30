from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Optional
import uuid
import os
import secrets
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from passlib.context import CryptContext
from app import database

router = APIRouter()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Simple in-memory rate limiter
login_attempts = defaultdict(list)
password_change_attempts = defaultdict(list)
user_creation_attempts = defaultdict(list)
MAX_LOGIN_ATTEMPTS = 5
MAX_PASSWORD_CHANGE_ATTEMPTS = 3
MAX_USER_CREATION_ATTEMPTS = 10
LOCKOUT_MINUTES = 15


def check_rate_limit(attempts_dict: dict, client_ip: str, max_attempts: int, lockout_minutes: int = LOCKOUT_MINUTES) -> None:
    """
    Check if an IP has exceeded rate limits.
    Raises HTTPException if rate limit is exceeded.
    """
    now = datetime.now()
    attempts = attempts_dict[client_ip]
    attempts = [t for t in attempts if now - t < timedelta(minutes=lockout_minutes)]
    attempts_dict[client_ip] = attempts
    if len(attempts) >= max_attempts:
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {lockout_minutes} minutes."
        )


def record_attempt(attempts_dict: dict, client_ip: str) -> None:
    attempts_dict[client_ip].append(datetime.now())


def clear_attempts(attempts_dict: dict, client_ip: str) -> None:
    attempts_dict[client_ip] = []


ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ALLOW_INSECURE_DEFAULT = os.environ.get("ALLOW_INSECURE_DEFAULT", "true").lower() == "true"
MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str) -> tuple[bool, str]:
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
    return True, ""


logger = logging.getLogger(__name__)


def ensure_admin_user():
    """Ensures at least one admin user exists."""
    users = database.get_all_users()
    if not users:
        must_change = True
        if ADMIN_PASSWORD:
            password = ADMIN_PASSWORD
        elif ADMIN_PASSWORD_HASH:
            password = None
            must_change = False
        else:
            if ALLOW_INSECURE_DEFAULT:
                password = "nomad"
            else:
                password = secrets.token_urlsafe(16)

        h = ADMIN_PASSWORD_HASH or pwd_context.hash(password)
        database.create_user("admin", h, is_admin=True, must_change_password=must_change)

        if password:
            print("\n" + "=" * 50)
            print("!!! FIRST TIME SETUP: ADMIN USER CREATED !!!")
            print("Username: admin")
            print(f"Password: {password}")
            print("PLEASE LOGIN AND CHANGE YOUR PASSWORD IMMEDIATELY.")
            print("=" * 50 + "\n")
            logger.warning("Created default admin user. Password displayed in console.")
        else:
            print("Created default admin user with pre-hashed password")


class LoginRequest(BaseModel):
    username: str = "admin"
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @validator('new_password')
    def validate_new_password(cls, v):
        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class UserCreateRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False

    @validator('password')
    def validate_password(cls, v):
        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class UserRoleRequest(BaseModel):
    is_admin: bool


class UserPasswordResetRequest(BaseModel):
    new_password: str

    @validator('new_password')
    def validate_new_password(cls, v):
        is_valid, error_msg = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class ProfileUpdateRequest(BaseModel):
    name: str
    avatar: Optional[str] = None
    preferences: dict = Field(default_factory=dict)
    parental_controls: int = 0


def _extract_auth_token(request: Request, allow_query: bool = True) -> Optional[str]:
    token = request.cookies.get("auth_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
    if not token and allow_query:
        token = request.query_params.get("token")
    return token or None


@router.post("/login")
def login(request: LoginRequest, request_obj: Request):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    check_rate_limit(login_attempts, client_ip, MAX_LOGIN_ATTEMPTS)
    user = database.get_user_by_username(request.username)
    verified = False
    if user:
        try:
            verified = pwd_context.verify(request.password, user['password_hash'])
        except Exception as e:
            logger.error(f"Password verification failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Password verification backend error. Check logs.")
    if user and verified:
        clear_attempts(login_attempts, client_ip)
        token = str(uuid.uuid4())
        database.create_session(token, user['id'])
        response = JSONResponse(content={
            "status": "ok",
            "token": token,
            "user": {
                "id": user['id'],
                "username": user['username'],
                "is_admin": bool(user['is_admin']),
                "must_change_password": bool(user.get('must_change_password', 0))
            }
        })
        response.set_cookie(
            key="auth_token",
            value=token,
            httponly=True,
            max_age=86400 * 30,
            path="/",
            secure=os.getenv('NOMAD_SECURE_COOKIES', 'false').lower() == 'true',
            samesite="lax"
        )
        return response
    record_attempt(login_attempts, client_ip)
    raise HTTPException(status_code=401, detail="Invalid username or password")


def get_current_user_id(request: Request):
    token = _extract_auth_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    session = database.get_session(token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user_id = session['user_id']
    from app.services.profile_policy_shell import enforce_request_policy_shell
    enforce_request_policy_shell(request, user_id, token)
    return user_id


def get_current_admin(user_id=Depends(get_current_user_id)):
    user = database.get_user_by_id(user_id)
    if not user or not user['is_admin']:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user


@router.get("/users")
def list_users(admin=Depends(get_current_admin)):
    return database.get_all_users()


@router.post("/users")
def create_user(request: UserCreateRequest, request_obj: Request, admin=Depends(get_current_admin)):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    check_rate_limit(user_creation_attempts, client_ip, MAX_USER_CREATION_ATTEMPTS, lockout_minutes=5)
    if database.get_user_by_username(request.username):
        raise HTTPException(status_code=400, detail="Username already exists")
    h = pwd_context.hash(request.password)
    user_id = database.create_user(request.username, h, is_admin=request.is_admin)
    record_attempt(user_creation_attempts, client_ip)
    return {"status": "ok", "user_id": user_id}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin=Depends(get_current_admin)):
    if user_id == admin['id']:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    database.delete_user(user_id)
    return {"status": "ok"}


@router.post("/users/{user_id}/role")
def update_user_role(user_id: int, request: UserRoleRequest, admin=Depends(get_current_admin)):
    if user_id == admin['id']:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    database.update_user_role(user_id, request.is_admin)
    # A role change is a privilege boundary: sessions minted under the old role
    # must not keep running. Password changes already do this; promotion and
    # demotion did not, so a demoted admin stayed an admin until their token
    # aged out, and a promotion did not take effect until they logged in again.
    database.delete_user_sessions(user_id)
    return {"status": "ok", "sessions_revoked": True}


@router.post("/users/{user_id}/password")
def reset_user_password(user_id: int, request: UserPasswordResetRequest, admin=Depends(get_current_admin)):
    h = pwd_context.hash(request.new_password)
    database.update_user_password(user_id, h)
    database.delete_user_sessions(user_id)
    return {"status": "ok"}


@router.get("/profile")
def get_profile(user_id=Depends(get_current_user_id)):
    profile = database.get_profile(user_id)
    if not profile:
        user = database.get_user_by_id(user_id)
        return {"user_id": user_id, "name": user['username'], "avatar": None, "preferences": {}, "parental_controls": 0}
    return profile


@router.post("/profile")
def update_profile(request: ProfileUpdateRequest, user_id=Depends(get_current_user_id)):
    database.upsert_profile(
        user_id,
        request.name,
        avatar=request.avatar,
        preferences=request.preferences,
        parental_controls=request.parental_controls
    )
    return {"status": "ok"}


@router.post("/change-password")
def change_password(request: PasswordChangeRequest, request_obj: Request, user_id=Depends(get_current_user_id)):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    check_rate_limit(password_change_attempts, client_ip, MAX_PASSWORD_CHANGE_ATTEMPTS)
    user = database.get_user_by_id(user_id)
    if not user or not pwd_context.verify(request.current_password, user['password_hash']):
        record_attempt(password_change_attempts, client_ip)
        raise HTTPException(status_code=400, detail="Current password incorrect")
    clear_attempts(password_change_attempts, client_ip)
    new_hash = pwd_context.hash(request.new_password)
    database.update_user_password(user_id, new_hash)
    current_token = _extract_auth_token(request_obj)
    database.delete_user_sessions(user_id)
    if current_token:
        database.create_session(current_token, user_id)
    return {"status": "ok", "message": "Password changed successfully"}


@router.post("/logout")
def logout(request: Request):
    token = _extract_auth_token(request)
    if token:
        # Binding cleanup is best-effort. logout must remain usable even in unit
        # tests or recovery scenarios where the sessions/profile tables have not
        # been initialised yet.
        try:
            session = database.get_session(token)
        except Exception:
            session = None
        if session:
            try:
                from app.services.household_profiles import HouseholdProfileStore
                HouseholdProfileStore(database.DB_PATH).unbind(user_id=session['user_id'], token=token)
            except Exception:
                pass
        database.delete_session(token)
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie("auth_token")
    return response


@router.get("/me")
def get_me(user_id: int = Depends(get_current_user_id)):
    user = database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user": {
            "id": user['id'],
            "username": user['username'],
            "is_admin": bool(user['is_admin']),
            "must_change_password": bool(user.get('must_change_password', 0))
        }
    }


@router.get("/check")
def check_auth(request: Request):
    token = _extract_auth_token(request, allow_query=False)
    if token:
        session = database.get_session(token)
        if session:
            user = database.get_user_by_id(session['user_id'])
            if user:
                return {
                    "authenticated": True,
                    "user": {
                        "id": user['id'],
                        "username": user['username'],
                        "is_admin": bool(user['is_admin']),
                        "must_change_password": bool(user.get('must_change_password', 0))
                    }
                }
    return {"authenticated": False}
