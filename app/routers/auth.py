from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uuid
import os
from datetime import datetime, timedelta
from collections import defaultdict
from passlib.context import CryptContext
from app import database

router = APIRouter()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Simple in-memory rate limiter
login_attempts = defaultdict(list)
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Authentication configuration
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ALLOW_INSECURE_DEFAULT = os.environ.get("ALLOW_INSECURE_DEFAULT", "true").lower() == "true"

# Cache for the hashed admin password to avoid re-hashing on every call
_CACHED_ADMIN_HASH = None

def get_admin_password_hash():
    """Returns the current admin password hash based on priority:
    1. Environment Variable ADMIN_PASSWORD_HASH
    2. Environment Variable ADMIN_PASSWORD (hashed)
    3. Database setting 'admin_password_hash'
    4. Default password 'nomad' (if allowed)
    """
    global _CACHED_ADMIN_HASH
    
    # Return cached hash if available
    if _CACHED_ADMIN_HASH:
        return _CACHED_ADMIN_HASH

    # 1. Check environment variables (highest priority)
    if ADMIN_PASSWORD_HASH:
        _CACHED_ADMIN_HASH = ADMIN_PASSWORD_HASH
        return _CACHED_ADMIN_HASH
    if ADMIN_PASSWORD:
        _CACHED_ADMIN_HASH = pwd_context.hash(ADMIN_PASSWORD)
        return _CACHED_ADMIN_HASH
    
    # 2. Check database
    stored_hash = database.get_setting("admin_password_hash")
    if stored_hash:
        _CACHED_ADMIN_HASH = stored_hash
        return _CACHED_ADMIN_HASH
    
    # 3. Handle default if allowed
    if ALLOW_INSECURE_DEFAULT:
        default_pass = "nomad"
        h = pwd_context.hash(default_pass)
        # Store it so it's persistent and can be changed
        database.set_setting("admin_password_hash", h)
        _CACHED_ADMIN_HASH = h
        return h
    
    # 4. Fail fast
    import sys
    print("FATAL: No ADMIN_PASSWORD, ADMIN_PASSWORD_HASH, or stored password found.")
    print("Security policy requires credentials to be set.")
    print("To bypass this (NOT RECOMMENDED), set ALLOW_INSECURE_DEFAULT=true")
    sys.exit(1)

# Log security status at startup
def log_security_status():
    if not ADMIN_PASSWORD_HASH and not ADMIN_PASSWORD:
        stored_hash = database.get_setting("admin_password_hash")
        if not stored_hash and ALLOW_INSECURE_DEFAULT:
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            print("WARNING: Using insecure default password: 'nomad'")
            print("Please change this immediately via the UI or set ADMIN_PASSWORD")
            print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        elif not stored_hash:
             print("Security: No credentials found. Server will fail fast on next access.")

log_security_status()

class LoginRequest(BaseModel):
    password: str

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

@router.post("/login")
def login(request: LoginRequest, request_obj: Request):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    
    # Rate limiting
    now = datetime.now()
    attempts = login_attempts[client_ip]
    attempts = [t for t in attempts if now - t < timedelta(minutes=LOCKOUT_MINUTES)]
    
    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429, 
            detail=f"Too many login attempts. Try again in {LOCKOUT_MINUTES} minutes."
        )

    current_hash = get_admin_password_hash()
        
    if pwd_context.verify(request.password, current_hash):
        # Clear attempts on success
        login_attempts[client_ip] = []
        token = str(uuid.uuid4())
        database.create_session(token)
        # We set httponly=False so the frontend can read the token for media requests (audio/video elements)
        response = JSONResponse(content={"status": "ok", "token": token})
        response.set_cookie(
            key="auth_token", 
            value=token, 
            httponly=False, 
            max_age=86400 * 30,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax"
        )
        return response
    
    # Record failed attempt
    attempts.append(now)
    login_attempts[client_ip] = attempts
    
    raise HTTPException(status_code=401, detail="Invalid password")

# Dependency for protecting routes
def get_current_user(request: Request):
    token = request.cookies.get("auth_token")
    if not token or not database.get_session(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return token

@router.post("/change-password")
def change_password(request: PasswordChangeRequest, current_user=Depends(get_current_user)):
    current_hash = get_admin_password_hash()
    if not pwd_context.verify(request.current_password, current_hash):
        raise HTTPException(status_code=400, detail="Current password incorrect")
    
    new_hash = pwd_context.hash(request.new_password)
    database.set_setting("admin_password_hash", new_hash)
    return {"status": "ok", "message": "Password changed successfully"}

@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get("auth_token")
    if token:
        database.delete_session(token)
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie("auth_token")
    return response

@router.get("/check")
def check_auth(request: Request):
    token = request.cookies.get("auth_token")
    if token and database.get_session(token):
        return {"authenticated": True}
    return {"authenticated": False}
