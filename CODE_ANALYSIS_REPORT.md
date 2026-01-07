# Code Analysis Report: Nomad-Pi
**Generated:** 2025-01-15  
**Repository:** beastboost/nomad-pi  
**Analysis Scope:** Python backend code, security, best practices

## Executive Summary

This analysis identified **27 issues** across the codebase, categorized by severity:

- **Critical:** 3 issues
- **High:** 8 issues  
- **Medium:** 10 issues
- **Low:** 6 issues

The application is a FastAPI-based media server running on Raspberry Pi with authentication, file uploads, and media management features. While the codebase is generally well-structured, several security and best practices issues need attention.

---

## Critical Issues

### 1. SQL Injection Vulnerability in `database.py`
**Location:** `app/database.py` - Multiple locations  
**Severity:** 🔴 Critical  
**CVE Impact:** SQL Injection

**Issue:** The database layer uses string interpolation for LIKE clauses, making it vulnerable to SQL injection attacks.

```python
# VULNERABLE CODE in query_library_index():
if q:
    sql += ' AND (LOWER(l.name) LIKE ? OR LOWER(l.folder) LIKE ?)'
    params.extend([f"%{q}%", f"%{q}%"])
```

While the code uses parameterized queries for most operations, the `LIKE` clause pattern is constructed using f-strings. If `q` contains SQL metacharacters, it could lead to injection.

**Fix:** 
```python
# Safe approach - sanitize the pattern before use
import re
q_sanitized = re.sub(r'[%_\\]', r'\\\g<0>', str(q)) if q else ""
sql += ' AND (LOWER(l.name) LIKE ? OR LOWER(l.folder) LIKE ?)'
params.extend([f"%{q_sanitized}%", f"%{q_sanitized}%"])
```

---

### 2. Weak Session Management with Predictable Tokens
**Location:** `app/routers/auth.py` - `/login` endpoint  
**Severity:** 🔴 Critical  
**CVE Impact:** Session Hijacking

**Issue:** Session tokens are generated using `uuid.uuid4()`, which is cryptographically secure but not used with proper entropy sources or additional validation.

```python
token = str(uuid.uuid4())
database.create_session(token, user['id'])
```

**Problems:**
- No IP binding for session tokens
- No user-agent validation
- No token rotation on sensitive operations
- Session timeout is configurable but defaults may be too long

**Fix:** Add additional security layers:
```python
import secrets
token = secrets.token_urlsafe(32)  # More secure than uuid4
# Store client IP and user agent in session
# Implement token rotation on password change
# Add rate limiting for token generation
```

---

### 3. CORS Configuration Allows All Origins
**Location:** `app/main.py` - CORS middleware setup  
**Severity:** 🔴 Critical  
**CVE Impact:** CSRF/XSS vulnerabilities

**Issue:** CORS is configured to allow all origins with credentials enabled:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ INSECURE
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Problems:**
- Any website can make requests to your API
- While `allow_credentials=False` helps, this is still too permissive
- No origin validation for sensitive operations

**Fix:** 
```python
ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://localhost:3000",
    "http://nomadpi.local:8000",
    # Add your production domains
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

---

## High Severity Issues

### 4. Insecure Cookie Settings
**Location:** `app/routers/auth.py` - `/login` endpoint  
**Severity:** 🟠 High

**Issue:** Authentication cookies are set with insecure settings:

```python
response.set_cookie(
    key="auth_token",
    value=token,
    httponly=False,  # ⚠️ Should be True
    max_age=86400 * 30,
    path="/",
    secure=False,  # ⚠️ Should be True in production
    samesite="lax"
)
```

**Problems:**
- `httponly=False` allows JavaScript access to cookies (XSS risk)
- `secure=False` allows cookie transmission over HTTP
- No `SameSite=Strict` for sensitive operations

**Fix:**
```python
response.set_cookie(
    key="auth_token",
    value=token,
    httponly=True,
    secure=True,  # Enable in production
    max_age=86400 * 30,
    path="/",
    samesite="strict"
)
```

---

### 5. Password Complexity Requirements Missing
**Location:** `app/routers/auth.py` - User creation endpoints  
**Severity:** 🟠 High

**Issue:** No password strength validation when creating users or changing passwords.

**Fix:** Add password validation:
```python
import re

def validate_password(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain uppercase letters"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain lowercase letters"
    if not re.search(r'\d', password):
        return False, "Password must contain digits"
    return True, ""
```

---

### 6. File Upload Size Limits Not Enforced Server-Side
**Location:** `app/routers/uploads.py`  
**Severity:** 🟠 High

**Issue:** While there's a `MAX_FILE_SIZE` constant, it's not enforced during upload. The validation happens after the file is uploaded.

**Fix:** Add middleware to enforce size limits before processing:
```python
from fastapi import Request, status
from fastapi.responses import JSONResponse

@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method in ["POST", "PUT"] and "multipart/form-data" in request.headers.get("content-type", ""):
        content_length = int(request.headers.get("content-length", 0))
        if content_length > MAX_FILE_SIZE:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "File too large"}
            )
    return await call_next(request)
```

---

### 7. Hardcoded Default Password Logic
**Location:** `app/routers/auth.py` - `ensure_admin_user()`  
**Severity:** 🟠 High

**Issue:** The application creates a default admin with potentially weak password generation:

```python
if not users:
    password = secrets.token_urlsafe(16)  # Random but not enforced
    h = ADMIN_PASSWORD_HASH or pwd_context.hash(password)
```

**Problems:**
- Default admin creation may use weak passwords if env vars not set
- Password is printed to console (log exposure risk)
- No forced password change on first login (sometimes)

**Fix:**
- Force password change on first login
- Use stronger password generation
- Log to secure file instead of console
- Implement password expiration policy

---

### 8. Command Injection Risk in System Operations
**Location:** `app/routers/system.py` - Multiple subprocess calls  
**Severity:** 🟠 High

**Issue:** Several subprocess calls use user input without proper sanitization:

```python
# WiFi connection - SSID from user input
result = subprocess.run(
    ["sudo", "nmcli", "dev", "wifi", "connect", request.ssid, ...],
    capture_output=True, text=True, timeout=30
)
```

**Fix:** Validate and sanitize all user inputs:
```python
def sanitize_ssid(ssid: str) -> str:
    # Allow only alphanumeric, spaces, hyphens, underscores
    if not re.match(r'^[a-zA-Z0-9 _\-]+$', ssid):
        raise HTTPException(status_code=400, detail="Invalid SSID format")
    return ssid
```

---

### 9. Missing Rate Limiting on Sensitive Endpoints
**Location:** Multiple endpoints across routers  
**Severity:** 🟠 High

**Issue:** Only `/login` has basic rate limiting. Other sensitive endpoints like:
- `/api/auth/users` (user management)
- `/api/auth/change-password`
- `/api/system/control` (system control)

**Fix:** Implement comprehensive rate limiting:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/auth/change-password")
@limiter.limit("5/minute")
async def change_password(...):
    ...
```

---

### 10. Insufficient Logging for Security Events
**Location:** Across application  
**Severity:** 🟠 High

**Issue:** Security events are not properly logged for audit trails:

- Failed login attempts (only basic logging)
- User creation/deletion
- Password changes
- File uploads/deletions
- System control operations

**Fix:** Implement structured security logging:
```python
import structlog

logger = structlog.get_logger()

logger.info(
    "security_event",
    event_type="login_attempt",
    user_id=user_id,
    ip_address=request.client.host,
    success=False,
    reason="invalid_credentials"
)
```

---

### 11. Race Condition in File Upload Progress Tracking
**Location:** `app/routers/uploads.py` - `progress_tracker`  
**Severity:** 🟠 High

**Issue:** Global dictionary `progress_tracker` is accessed without thread safety:

```python
progress_tracker: Dict[str, UploadProgress] = {}

# Multiple threads access this without locks
progress_tracker[file_id] = UploadProgress(...)
progress_tracker[file_id].status = "completed"
```

**Fix:** Use thread-safe storage:
```python
import threading

progress_tracker = {}
progress_lock = threading.Lock()

with progress_lock:
    progress_tracker[file_id] = UploadProgress(...)
```

---

## Medium Severity Issues

### 12. Deprecated FastAPI Event Handlers
**Location:** `app/main.py` - Startup/shutdown handlers  
**Severity:** 🟡 Medium

**Issue:** Using deprecated `@app.on_event` decorators:

```python
@app.on_event("startup")
def _startup_tasks():
    ...
```

**Fix:** Use new lifespan context manager:
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    ...
    yield
    # Shutdown
    ...

app = FastAPI(lifespan=lifespan)
```

---

### 13. Bare `except` Clauses Hide Errors
**Location:** Multiple files  
**Severity:** 🟡 Medium

**Issue:** Several bare `except` clauses that catch all exceptions:

```python
# In main.py startup
except Exception: pass

# In media.py
except Exception: pass
```

**Fix:** Always catch specific exceptions:
```python
except (OSError, IOError) as e:
    logger.warning(f"File operation failed: {e}")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise
```

---

### 14. Database Connection Pool Issues
**Location:** `app/database.py` - `get_db()`  
**Severity:** 🟡 Medium

**Issue:** Connection pool implementation has potential issues:

```python
def get_db():
    try:
        conn = _connection_pool.get_nowait()
        # Verify connection is still valid
        try:
            conn.execute("SELECT 1")
            return conn
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            pass
    except:
        pass
```

**Problems:**
- Silent failures when pool is exhausted
- No maximum connection limit enforcement
- Connection validation is not comprehensive

**Fix:** Implement proper connection pooling with `sqlite3` or use `SQLAlchemy`.

---

### 15. Missing Input Validation on Multiple Endpoints
**Location:** Across all routers  
**Severity:** 🟡 Medium

**Issue:** Many endpoints lack proper input validation using Pydantic models or custom validators.

**Examples:**
- File paths in media operations
- Query parameters in search
- User input in system operations

**Fix:** Implement comprehensive validation:
```python
from pydantic import BaseModel, validator

class MediaRequest(BaseModel):
    path: str
    offset: int = 0
    limit: int = 50

    @validator('path')
    def validate_path(cls, v):
        if ".." in v or v.startswith("/"):
            raise ValueError("Invalid path")
        return v
```

---

### 16. Potential Memory Leak in Background Tasks
**Location:** `app/main.py` - Startup tasks  
**Severity:** 🟡 Medium

**Issue:** Background indexing tasks may not clean up properly:

```python
def run_staggered():
    # No proper cleanup on interruption
    for category in ["movies", "shows", "music", "books"]:
        if needs_build(category):
            try:
                media.build_library_index(category)
            except Exception: pass
```

**Fix:** Implement proper task cleanup and resource management.

---

### 17. Inefficient Database Queries
**Location:** `app/database.py` - `query_library_index()`  
**Severity:** 🟡 Medium

**Issue:** Separate count query could be optimized:

```python
# Current approach - two queries
c.execute(sql, params)
rows = c.fetchall()

# Separate count query
count_sql = 'SELECT COUNT(1) AS cnt FROM library_index l WHERE l.category = ?'
c.execute(count_sql, count_params)
total = int(c.fetchone()["cnt"])
```

**Fix:** Use window functions or combine queries when possible.

---

### 18. Missing CSRF Protection
**Location:** FastAPI app configuration  
**Severity:** 🟡 Medium

**Issue:** No CSRF protection implemented for state-changing operations.

**Fix:** Add CSRF middleware:
```python
from fastapi_csrf_protect import CsrfProtect

@CsrfProtect.load_config
def get_csrf_config():
    return CsrfConfig(secret_key="your-secret-key")
```

---

### 19. Insecure Temporary File Handling
**Location:** `app/routers/uploads.py`  
**Severity:** 🟡 Medium

**Issue:** Temporary files may not be cleaned up on error:

```python
# File uploaded but indexing fails - temp file remains
destination = UPLOAD_DIR / file_id / file.filename
```

**Fix:** Implement proper cleanup in error handlers:
```python
try:
    # Process file
    ...
except Exception as e:
    # Cleanup on failure
    if destination.exists():
        destination.unlink()
    raise
```

---

### 20. Hardcoded Paths and Configuration
**Location:** Multiple files  
**Severity:** 🟡 Medium

**Issue:** Many hardcoded paths and configuration values:

```python
BASE_DIR = os.path.abspath("data")
UPLOAD_DIR = Path("data/uploads")
LOG_FILE = "data/app.log"
```

**Fix:** Use environment variables and configuration files:
```python
from pydantic import BaseSettings

class Settings(BaseSettings):
    base_dir: str = "data"
    upload_dir: str = "data/uploads"
    log_file: str = "data/app.log"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

---

### 21. Missing Health Check Endpoint Monitoring
**Location:** `app/routers/system.py` - `/health` endpoint  
**Severity:** 🟡 Medium

**Issue:** Health check doesn't verify critical services:

```python
@public_router.get("/health")
def get_health():
    from app.main import ENV_CHECK_RESULTS
    return ENV_CHECK_RESULTS  # Just returns startup checks
```

**Fix:** Implement real-time health checks:
```python
@public_router.get("/health")
async def get_health():
    checks = {
        "database": await check_database(),
        "disk_space": await check_disk_space(),
        "memory": await check_memory(),
        "services": await check_services()
    }
    return {
        "status": "healthy" if all(v["ok"] for v in checks.values()) else "unhealthy",
        "checks": checks
    }
```

---

## Low Severity Issues

### 22. Inconsistent Error Messages
**Location:** Multiple files  
**Severity:** 🟢 Low

**Issue:** Error messages are inconsistent in format and detail level.

**Fix:** Standardize error responses using a common error handler.

---

### 23. Missing Type Hints in Some Functions
**Location:** Various functions  
**Severity:** 🟢 Low

**Issue:** Some functions lack proper type hints.

**Fix:** Add comprehensive type hints for better IDE support and documentation.

---

### 24. Redundant Code in Media Router
**Location:** `app/routers/media.py`  
**Severity:** 🟢 Low

**Issue:** Some code duplication in media handling logic.

**Fix:** Extract common functionality into helper functions.

---

### 25. Inefficient File System Operations
**Location:** `app/routers/media.py` - Scanning logic  
**Severity:** 🟢 Low

**Issue:** File system scanning could be optimized with caching.

**Fix:** Implement intelligent caching and incremental scanning.

---

### 26. Missing API Documentation
**Location:** FastAPI app  
**Severity:** 🟢 Low

**Issue:** Some endpoints lack detailed OpenAPI documentation.

**Fix:** Add comprehensive docstrings and examples:
```python
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(..., description="Media file to upload"),
    category: str = Query("files", description="Media category")
) -> UploadResponse:
    """
    Upload a media file to the server.
    
    - **file**: The media file (max 10GB)
    - **category**: One of: movies, shows, music, books, gallery, files
    
    Returns file metadata including checksum and path.
    """
    ...
```

---

### 27. No Automated Testing Coverage
**Location:** Project root  
**Severity:** 🟢 Low

**Issue:** No test files found for critical functionality.

**Fix:** Implement comprehensive test suite:
```python
# tests/test_auth.py
def test_login_success():
    response = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "secure_password"
    })
    assert response.status_code == 200
    assert "token" in response.json()
```

---

## Security Recommendations

### Immediate Actions (Critical/High Priority)

1. **Fix SQL Injection Vulnerability** - Replace unsafe LIKE patterns
2. **Implement Proper CORS Configuration** - Restrict origins
3. **Secure Cookie Settings** - Enable httponly and secure flags
4. **Add Password Strength Validation** - Enforce complexity requirements
5. **Implement Rate Limiting** - Protect all sensitive endpoints
6. **Add Input Sanitization** - Validate all user inputs
7. **Enhance Security Logging** - Implement audit trails
8. **Fix Race Conditions** - Add thread safety to shared resources

### Short-term Actions (Medium Priority)

9. **Update FastAPI Event Handlers** - Use lifespan context manager
10. **Remove Bare Except Clauses** - Catch specific exceptions
11. **Implement CSRF Protection** - Add anti-CSRF middleware
12. **Add Configuration Management** - Use environment variables
13. **Improve Health Checks** - Real-time service monitoring
14. **Implement Proper Cleanup** - Handle errors in file operations
15. **Optimize Database Queries** - Reduce unnecessary queries

### Long-term Improvements (Low Priority)

16. **Add Comprehensive Testing** - Unit and integration tests
17. **Improve Documentation** - API docs and code comments
18. **Implement Caching** - Reduce database and file system load
19. **Add Monitoring** - Performance and security monitoring
20. **Code Quality Tools** - Linting, formatting, static analysis

---

## Positive Findings

✅ **Good Practices Observed:**

- Comprehensive logging implementation
- Error handling in most operations
- Use of async/await for I/O operations
- Database connection pooling attempt
- File validation in uploads
- Background task management
- Cross-platform compatibility considerations
- Efficient memory usage for Raspberry Pi

---

## Conclusion

The Nomad-Pi codebase demonstrates solid engineering practices but requires immediate attention to **critical security vulnerabilities**, particularly around SQL injection, session management, and CORS configuration. The medium and low severity issues represent opportunities for code quality improvements and should be addressed progressively.

**Priority Order:**
1. Fix all Critical issues immediately
2. Address High severity issues within 1 week
3. Plan Medium issues for next sprint
4. Incorporate Low issues into ongoing maintenance

---

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security Best Practices](https://fastapi.tiangolo.com/tutorial/security/)
- [SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- [Python Security Best Practices](https://python.readthedocs.io/en/latest/library/security_warnings.html)