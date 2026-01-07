from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator
import uuid
import os
import secrets
import logging
import re
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

# Password complexity requirements
MIN_PASSWORD_LENGTH = 8

def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password strength requirements.
    Returns (is_valid, error_message).
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit"
    
    return True, ""

logger = logging.getLogger(__name__)

def ensure_admin_user():
    """Ensures at least one admin user exists."""
    users = database.get_all_users()
    if not users:
        # Create default admin user
        must_change = True  # Always force change for first-time setup
        if ADMIN_PASSWORD:
            password = ADMIN_PASSWORD
        elif ADMIN_PASSWORD_HASH:
            password = None
            must_change = False # If pre-hashed, assume it's secure
        else:
            password = secrets.token_urlsafe(16)
            
        h = ADMIN_PASSWORD_HASH or pwd_context.hash(password)
        database.create_user("admin", h, is_admin=True, must_change_password=must_change)
        
        if password:
            print(f"\n" + "="*50)
            print(f"!!! FIRST TIME SETUP: ADMIN USER CREATED !!!")
            print(f"Username: admin")
            print(f"Password: {password}")
            print(f"PLEASE LOGIN AND CHANGE YOUR PASSWORD IMMEDIATELY.")
            print("="*50 + "\n")
            logger.warning(f"Created default admin user. Password displayed in console.")
        else:
            print(f"Created default admin user with pre-hashed password")

# ensure_admin_user() called in main.py after init_db

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

class ProfileUpdateRequest(BaseModel):
    name: str
    avatar: str = None
    preferences: dict = {}
    parental_controls: int = 0

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

    user = database.get_user_by_username(request.username)
    if user and pwd_context.verify(request.password, user['password_hash']):
        # Clear attempts on success
        login_attempts[client_ip] = []
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
    
    # Record failed attempt
    attempts.append(now)
    login_attempts[client_ip] = attempts
    
    raise HTTPException(status_code=401, detail="Invalid username or password")

# Dependency for protecting routes
def get_current_user_id(request: Request):
    token = request.cookies.get("auth_token")
    if not token:
        token = request.query_params.get("token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        
    session = database.get_session(token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        
    return session['user_id']

def get_current_admin(user_id=Depends(get_current_user_id)):
    user = database.get_user_by_id(user_id)
    if not user or not user['is_admin']:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user

@router.get("/users")
def list_users(admin=Depends(get_current_admin)):
    return database.get_all_users()

@router.post("/users")
def create_user(request: UserCreateRequest, admin=Depends(get_current_admin)):
    if database.get_user_by_username(request.username):
        raise HTTPException(status_code=400, detail="Username already exists")
    
    h = pwd_context.hash(request.password)
    user_id = database.create_user(request.username, h, is_admin=request.is_admin)
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
def change_password(request: PasswordChangeRequest, user_id=Depends(get_current_user_id)):
    user = database.get_user_by_id(user_id)
    if not user or not pwd_context.verify(request.current_password, user['password_hash']):
        raise HTTPException(status_code=400, detail="Current password incorrect")
    
    new_hash = pwd_context.hash(request.new_password)
    database.update_user_password(user_id, new_hash)
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
