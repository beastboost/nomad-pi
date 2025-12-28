from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uuid

router = APIRouter()

# In-memory session store
# In a real app, use a proper DB or Redis
SESSIONS = set()

# Default admin password
ADMIN_PASSWORD = "nomad" 

class LoginRequest(BaseModel):
    password: str

@router.post("/login")
def login(request: LoginRequest):
    if request.password == ADMIN_PASSWORD:
        token = str(uuid.uuid4())
        SESSIONS.add(token)
        response = JSONResponse(content={"status": "ok"})
        response.set_cookie(key="auth_token", value=token, httponly=True, max_age=86400 * 30) # 30 days
        return response
    raise HTTPException(status_code=401, detail="Invalid password")

@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get("auth_token")
    if token in SESSIONS:
        SESSIONS.remove(token)
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie("auth_token")
    return response

@router.get("/check")
def check_auth(request: Request):
    token = request.cookies.get("auth_token")
    if token in SESSIONS:
        return {"authenticated": True}
    return {"authenticated": False}

# Dependency for protecting routes
def get_current_user(request: Request):
    token = request.cookies.get("auth_token")
    if not token or token not in SESSIONS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return token
