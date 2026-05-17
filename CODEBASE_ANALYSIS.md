# Codebase Analysis: nomad-pi
**Date:** 2026-05-17  
**Focus:** Debrid API, General API Usage, and Critical Issues

---

## Executive Summary

Your codebase has **several critical issues** related to Debrid API integration, error handling, and security. Below are the key findings organized by severity.

---

## 🔴 CRITICAL ISSUES

### 1. **Debrid Router is Non-Functional (BLOCKING)**
**File:** `app/routers/debrid.py`  
**Severity:** CRITICAL

```python
# Debrid router - placeholder (reverted state)
# All TorBox + multi-provider changes reverted as requested.

from fastapi import APIRouter
router = APIRouter(prefix="/api/debrid", tags=["debrid"])

print("[router] Debrid router reverted to placeholder")
```

**Problem:**
- The debrid router is **completely empty** — just a placeholder with no endpoints
- The UI (`app/static/js/app.js`) expects endpoints like:
  - `GET /api/debrid/settings/key`
  - `POST /api/debrid/settings/key`
  - `GET /api/debrid/settings/provider`
  - POST `/api/debrid/settings/ad-key`
  - And many more torrent/download endpoints

**Impact:**
- **Debrid features don't work at all**
- Users cannot save API keys, search torrents, or download files
- Frontend will crash with 404 errors

**Fix Required:**
Implement the debrid router endpoints. The service layer exists (`app/services/debrid.py`), but no router exposes it.

---

### 2. **AllDebrid API Deprecation Not Handled**
**File:** `app/services/debrid.py` (lines 265-374)  
**Severity:** CRITICAL

**The Issue:**
In your README, you state:
> **Deprecation Notice:** AllDebrid's v4 API has been discontinued. Please migrate to the newest API.

But your code uses:
```python
AD_BASE = "https://api.alldebrid.com/v4.1"
```

**Problems:**
1. **API endpoint is outdated** — v4.1 is deprecated
2. **Authentication may fail** — If AllDebrid changed auth requirements, Bearer token auth may not work
3. **Response format mismatch** — Deprecated API responses may differ from current version
4. **Silent failures** — Error handling checks `data.get("status") == "error"`, but if API format changed, this won't catch issues

**Example Vulnerable Code:**
```python
def ad_get_user(api_key: str) -> dict:
    r = requests.get(
        f"{AD_BASE}/user",  # ← Uses deprecated v4.1
        headers=_ad_headers(api_key),
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "error":  # ← May not catch new error format
        raise Exception(data.get("error", {}).get("message", "AllDebrid error"))
    return data.get("data", {}).get("user", {})
```

**Fix Required:**
1. Update `AD_BASE` to the latest AllDebrid API version
2. Check [AllDebrid Documentation](https://docs.alldebrid.com) for current auth & response format
3. Add regression tests for both RD and AD endpoints

---

### 3. **Missing Error Handling in AllDebrid Instant Check**
**File:** `app/services/debrid.py` (lines 336-373)  
**Severity:** HIGH

```python
def ad_check_instant(api_key: str, hashes: list[str]) -> dict[str, bool]:
    # ... code omitted ...
    try:
        data = {"magnets": hashes}
        r = requests.post(
            f"{AD_BASE}/magnet/instant",
            headers=_ad_headers(api_key),
            data=data,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            for m in data.get("data", {}).get("magnets", []):
                if m.get("ready"):
                    h = m.get("hash", "").lower()
                    if h in result:  # ← BUG: 'result' not initialized in this branch
                        result[h] = True
```

**Problems:**
1. **Variable used before initialization** — `result[h]` is called but `result` dict may not exist if previous initialization failed
2. **Unhandled exceptions** — If `requests.post()` fails, exception is caught but silently returns empty dict
3. **Resource leak** — Magnets are auto-deleted but errors aren't properly logged

---

### 4. **Torrentio Search Returns Empty Without IMDb ID**
**File:** `app/services/debrid.py` (lines 55-130)  
**Severity:** HIGH

```python
def search_torrentio(query: str, media_type: str = "movie", imdb_id: Optional[str] = None,
                     season: Optional[int] = None, episode: Optional[int] = None) -> list[dict]:
    results = []

    if not imdb_id:
        return results  # ← Returns empty list immediately!
```

**Problem:**
- If no IMDb ID is provided, the function **always returns an empty list**
- No fallback search mechanism
- Frontend requires IMDb ID, but what if TMDB/OMDb lookup fails?

**Impact:**
- Users can't search by keyword alone
- Any error in IMDb lookup breaks torrent search

**Fix Required:**
Implement fallback search using a hash-based torrent API or add keyword-to-IMDb resolution.

---

## 🟠 HIGH SEVERITY ISSUES

### 5. **No Timeout Handling for AllDebrid Magnet Deletion**
**File:** `app/services/debrid.py` (line 357-366)  
**Severity:** HIGH

```python
for m in data.get("data", {}).get("magnets", []):
    if m.get("ready"):
        h = m.get("hash", "").lower()
        try:
            ad_delete_magnet(api_key, str(m.get("id", "")))  # ← Can timeout/fail silently
        except Exception:
            pass  # ← Silently ignores all errors
```

**Problem:**
- Orphaned magnets left on AllDebrid account
- Silent failures hide API issues
- No logging of deletion attempts

**Fix:**
```python
try:
    ad_delete_magnet(api_key, str(m.get("id", "")))
except Exception as e:
    logger.warning(f"Failed to delete AllDebrid magnet {m.get('id')}: {e}")
```

---

### 6. **Real-Debrid Instant Availability Check Doesn't Handle Case Sensitivity**
**File:** `app/services/debrid.py` (lines 137-177)  
**Severity:** MEDIUM-HIGH

```python
def check_instant_availability(api_key: str, hashes: list[str]) -> dict[str, bool]:
    # ...
    for h in batch:
        entry = data.get(h) or data.get(h.lower()) or {}  # ← Works, but inconsistent
```

**Problem:**
- RD API sometimes returns lowercase hashes, sometimes uppercase
- Code works but is brittle — relies on fallback logic
- No normalization of hashes before sending to API

**Better Approach:**
```python
normalized_hashes = [h.lower() for h in hashes]
# Send normalized_hashes to API
# Store mapping original → normalized for results
```

---

### 7. **Download Filename Sanitization is Incomplete**
**File:** `app/services/debrid.py` (lines 407-465)  
**Severity:** MEDIUM

```python
def _sanitize_filename(name: str) -> str:
    """Remove invalid filesystem characters."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')
```

**Problems:**
1. **Doesn't handle Unicode** — Some filesystems fail on certain Unicode chars
2. **No length limits** — Filename may exceed OS limits (255 chars on Linux/Mac, 260 on Windows)
3. **No reserved word handling** — Windows reserved names (CON, PRN, AUX) not handled

**Better Implementation:**
```python
def _sanitize_filename(name: str, max_length: int = 200) -> str:
    """Sanitize filename for all platforms."""
    # Remove invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    
    # Remove null bytes
    name = name.replace('\0', '')
    
    # Encode/decode for safety
    name = name.encode('utf-8', errors='ignore').decode('utf-8')
    
    # Truncate to max length (accounting for extension)
    if len(name) > max_length:
        name = name[:max_length]
    
    # Remove trailing dots/spaces
    name = name.strip('. ')
    
    # Handle Windows reserved names
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM9', 'LPT1', 'LPT9'}
    if name.upper() in reserved:
        name = f"_{name}"
    
    return name
```

---

### 8. **Download Worker Has No Retry Logic**
**File:** `app/services/debrid.py` (lines 523-599)  
**Severity:** MEDIUM

```python
def _download_worker(download_id: str, url: str, dest_path: str, category: str):
    try:
        r = requests.get(url, stream=True, timeout=30)  # ← Single attempt, no retry
        r.raise_for_status()
        # ... download ...
    except Exception as e:
        logger.error(f"Download failed for {download_id}: {e}")
        # ← No retry logic, download marked as failed immediately
```

**Problems:**
1. **Network timeouts fail immediately** — Should retry with exponential backoff
2. **Large files may timeout** — 30-second timeout too short for large downloads
3. **No resume capability** — Failed downloads restart from 0

**Fix Required:**
Implement retry logic with exponential backoff and optional resume support.

---

## 🟡 MEDIUM SEVERITY ISSUES

### 9. **API Key Storage Security Issues**
**Files:** `app/database.py`, `app/routers/system.py`  
**Severity:** MEDIUM

**Problem:**
API keys are stored in the database as plain text (based on code review). While you have session/auth tokens protected, sensitive API keys should be encrypted at rest.

**Current Code:**
```python
database.set_setting("debrid_api_key", api_key)  # ← Likely stored in plain text
```

**Recommendation:**
```python
from cryptography.fernet import Fernet

def encrypt_setting(key: str, value: str) -> str:
    cipher = Fernet(encryption_key)  # Load from secure store
    return cipher.encrypt(value.encode()).decode()

def decrypt_setting(key: str, encrypted: str) -> str:
    cipher = Fernet(encryption_key)
    return cipher.decrypt(encrypted.encode()).decode()
```

---

### 10. **No Rate Limiting on Debrid API Calls**
**File:** `app/services/debrid.py`  
**Severity:** MEDIUM

**Problem:**
- Multiple concurrent requests to RD/AD without throttling
- Could hit API rate limits and cause cascading failures
- No backoff strategy for 429 (rate limit) responses

**Fix:**
Implement a simple rate limiter:
```python
import asyncio
from datetime import datetime, timedelta

class APIRateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = []
    
    async def wait_if_needed(self):
        now = datetime.now()
        # Remove old requests outside window
        self.requests = [r for r in self.requests if now - r < timedelta(seconds=self.window_seconds)]
        
        if len(self.requests) >= self.max_requests:
            wait_time = (self.requests[0] + timedelta(seconds=self.window_seconds) - now).total_seconds()
            await asyncio.sleep(wait_time)
        
        self.requests.append(now)
```

---

### 11. **AllDebrid Bearer Token Not Validated on Startup**
**File:** `app/routers/debrid.py` + `app/services/debrid.py`  
**Severity:** MEDIUM

**Problem:**
- No validation that API key is correct when saved
- User won't know key is invalid until attempting to use it
- TMDB router does validate (line 24 in tmdb.py), but debrid doesn't

**Current TMDB (Good Example):**
```python
@router.post("/settings/key")
def set_tmdb_key(req: TMDBKeyRequest, admin: dict = Depends(get_current_admin)):
    try:
        import httpx
        r = httpx.get(
            f"{tmdb.TMDB_BASE}/configuration",
            params={"api_key": req.api_key},
            timeout=10,
        )
        r.raise_for_status()  # ← Validates key before saving
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid TMDB API key: {e}")
```

**Apply Same Pattern to Debrid:**
```python
@router.post("/settings/key")
def set_rd_key(req: DebridKeyRequest, admin: dict = Depends(get_current_admin)):
    try:
        user_info = debrid.get_rd_user(req.api_key)  # ← Validate first
        if not user_info:
            raise HTTPException(status_code=400, detail="Invalid Real-Debrid API key")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Real-Debrid API key: {e}")
    
    database.set_setting("debrid_api_key", req.api_key)
    return {"status": "ok", "user": user_info}
```

---

### 12. **No Circuit Breaker for Debrid API Failures**
**Severity:** MEDIUM

**Problem:**
- If Debrid APIs are down, repeated requests will fail
- No exponential backoff or circuit breaker pattern
- Could cause cascading failures

**Recommendation:**
Implement circuit breaker:
```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
            else:
                raise Exception("Circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise
    
    def on_success(self):
        self.failure_count = 0
        self.state = "closed"
    
    def on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
```

---

## 🟢 LOWER PRIORITY ISSUES

### 13. **Inconsistent Timeout Values**
**Files:** `app/services/debrid.py`, `app/services/tmdb.py`

- RD calls use 15s timeout
- Some calls use 10s
- Download uses 30s
- No centralized timeout config

**Recommendation:** Create a config module with timeout constants.

---

### 14. **Missing Type Hints in Some Functions**
**File:** `app/routers/debrid.py` (once implemented)

Current codebase has good typing, but some debrid functions need better hints.

---

### 15. **Logging is Inconsistent**
**File:** `app/services/debrid.py`

Some functions log errors, others don't. Add logging to all error paths.

---

## 📋 QUICK FIX PRIORITY LIST

| Priority | Issue | Time Est. | Impact |
|----------|-------|-----------|--------|
| 🔴 P0 | Implement debrid router endpoints | 2-3 hrs | **BLOCKING** - Debrid features don't work |
| 🔴 P0 | Fix AllDebrid v4 API deprecation | 1-2 hrs | **BLOCKING** - AD features may not work |
| 🟠 P1 | Add rate limiting for Debrid APIs | 1 hr | Prevents API abuse/timeouts |
| 🟠 P1 | Validate API keys on save | 30 min | Better UX + error handling |
| 🟠 P1 | Fix ad_check_instant() result initialization | 15 min | Crash prevention |
| 🟡 P2 | Add retry logic to downloads | 1-2 hrs | Better reliability |
| 🟡 P2 | Encrypt stored API keys | 1-2 hrs | Security hardening |
| 🟡 P2 | Improve filename sanitization | 30 min | Cross-platform compatibility |

---

## 🔍 Testing Recommendations

1. **Unit Tests for Debrid Services:**
   ```python
   # test_debrid.py
   def test_sanitize_filename_unicode():
       assert len(_sanitize_filename("x" * 300)) <= 255
   
   def test_ad_check_instant_initializes_result():
       # Ensure 'result' dict is always initialized
       pass
   ```

2. **Integration Tests:**
   - Test with real RD/AD accounts in staging
   - Verify error handling for invalid keys
   - Test timeout scenarios

3. **Load Testing:**
   - Multiple concurrent downloads
   - Rapid API calls to check rate limiting

---

## Conclusion

Your codebase is **mostly well-structured**, but has **critical gaps** in the Debrid integration. The router is non-functional, and the AllDebrid API is using a deprecated endpoint. These must be fixed immediately for Debrid features to work.

Start with **Priority 0** items, then move through the rest systematically.

