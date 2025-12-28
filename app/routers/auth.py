from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uuid
import os
from passlib.context import CryptContext
from app import database

router = APIRouter()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Authentication configuration
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ALLOW_INSECURE_DEFAULT = os.environ.get("ALLOW_INSECURE_DEFAULT", "true").lower() == "true"

def get_admin_password_hash():
    """Returns the current admin password hash based on priority:
    1. Environment Variable ADMIN_PASSWORD_HASH
    2. Environment Variable ADMIN_PASSWORD (hashed)
    3. Database setting 'admin_password_hash'
    4. Default password 'nomad' (if allowed)
    """
    # 1. Check environment variables (highest priority)
    if ADMIN_PASSWORD_HASH:
        return ADMIN_PASSWORD_HASH
    if ADMIN_PASSWORD:
        return pwd_context.hash(ADMIN_PASSWORD)
    
    # 2. Check database
    stored_hash = database.get_setting("admin_password_hash")
    if stored_hash:
        return stored_hash
    
    # 3. Handle default if allowed
    if ALLOW_INSECURE_DEFAULT:
        default_pass = "nomad"
        h = pwd_context.hash(default_pass)
        # Store it so it's persistent and can be changed
        database.set_setting("admin_password_hash", h)
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
def login(request: LoginRequest):
    current_hash = get_admin_password_hash()
        
    if pwd_context.verify(request.password, current_hash):
        token = str(uuid.uuid4())
        database.create_session(token)
        response = JSONResponse(content={"status": "ok"})
        response.set_cookie(key="auth_token", value=token, httponly=True, max_age=86400 * 30) # 30 days
        return response
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
