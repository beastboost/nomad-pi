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

if not ADMIN_PASSWORD_HASH and not ADMIN_PASSWORD:
    print("WARNING: No ADMIN_PASSWORD or ADMIN_PASSWORD_HASH found. Using default: nomad")
    ADMIN_PASSWORD = "nomad"

class LoginRequest(BaseModel):
    password: str

@router.post("/login")
def login(request: LoginRequest):
    is_valid = False
    if ADMIN_PASSWORD_HASH:
        is_valid = pwd_context.verify(request.password, ADMIN_PASSWORD_HASH)
    elif ADMIN_PASSWORD:
        is_valid = (request.password == ADMIN_PASSWORD)
        
    if is_valid:
        token = str(uuid.uuid4())
        database.create_session(token)
        response = JSONResponse(content={"status": "ok"})
        response.set_cookie(key="auth_token", value=token, httponly=True, max_age=86400 * 30) # 30 days
        return response
    raise HTTPException(status_code=401, detail="Invalid password")

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

# Dependency for protecting routes
def get_current_user(request: Request):
    token = request.cookies.get("auth_token")
    if not token or not database.get_session(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return token
