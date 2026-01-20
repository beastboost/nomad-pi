from fastapi import FastAPI, Depends, Request, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from app import database
import sys
import traceback

# Wrap startup in a global try-except to catch invisible crashes
try:
    # Initialize database immediately
    database.init_db()

    # Now import routers and services
    from app.routers import auth
    # Ensure admin user exists after DB is ready
    auth.ensure_admin_user()

    from app.services import ingest
    from app.routers import media, system, uploads, dashboard
except Exception as e:
    print(f"CRITICAL STARTUP ERROR: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    # Log to file as well if possible
    try:
        with open("data/startup_error.log", "a") as f:
            f.write(f"\n--- {e} ---\n")
            traceback.print_exc(file=f)
    except (OSError, IOError, PermissionError) as log_err:
        print(f"WARNING: Could not write to startup_error.log: {log_err}", file=sys.stderr)
    sys.exit(1)
import os
import threading
import mimetypes
import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler

# Configure logging
LOG_FILE = "data/app.log"
os.makedirs("data", exist_ok=True)

# Ensure log file is writable
try:
    with open(LOG_FILE, "a") as f:
        pass
except Exception as e:
    print(f"CRITICAL: Cannot write to log file {LOG_FILE}: {e}")
    # Fallback to a location we can likely write to
    LOG_FILE = os.path.join(os.path.expanduser("~"), "nomad-pi.log")
    print(f"Falling back to log file: {LOG_FILE}")

# Export LOG_FILE for other modules
os.environ["NOMAD_LOG_FILE"] = LOG_FILE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("nomad")
logger.info("Nomad Pi starting up...")

def check_environment():
    """Perform basic environment checks on startup"""
    results = {"status": "ok", "checks": []}
    
    # 1. Check data directory writability
    try:
        test_file = "data/.write_test"
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        logger.info("Environment check: data directory is writable")
        results["checks"].append({"name": "data_writable", "status": "pass"})
    except Exception as e:
        logger.error(f"Environment check FAILED: data directory is NOT writable: {e}")
        results["checks"].append({"name": "data_writable", "status": "fail", "error": str(e)})
        results["status"] = "error"

    # 2. Check Database
    try:
        from app.database import get_db, return_db
        conn = get_db()
        try:
            conn.execute("SELECT 1").fetchone()
            logger.info("Environment check: Database is accessible")
            results["checks"].append({"name": "database", "status": "pass"})
        finally:
            return_db(conn)
    except Exception as e:
        logger.error(f"Environment check FAILED: Database error: {e}")
        results["checks"].append({"name": "database", "status": "fail", "error": str(e)})
        results["status"] = "error"
        
    # 3. Check for external tools (Linux only)
    if os.name != 'nt':
        # ffmpeg
        try:
            import subprocess
            result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Environment check: ffmpeg is available")
                results["checks"].append({"name": "ffmpeg", "status": "pass"})
            else:
                logger.warning("Environment check: ffmpeg is NOT available")
                results["checks"].append({"name": "ffmpeg", "status": "warn"})
        except Exception:
            results["checks"].append({"name": "ffmpeg", "status": "fail"})

        # NetworkManager (for WiFi management)
        try:
            result = subprocess.run(["nmcli", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Environment check: nmcli is available")
                results["checks"].append({"name": "nmcli", "status": "pass"})
            else:
                logger.warning("Environment check: nmcli is NOT available")
                results["checks"].append({"name": "nmcli", "status": "warn"})
        except Exception:
            results["checks"].append({"name": "nmcli", "status": "fail"})
            
    # 4. Load settings from database into environment
    try:
        omdb_key = database.get_setting("omdb_api_key")
        if omdb_key:
            os.environ["OMDB_API_KEY"] = omdb_key
            logger.info("Loaded OMDb API Key from settings")
    except Exception as e:
        logger.error(f"Failed to load settings on startup: {e}")

    return results

# Run check and store results for status endpoint
ENV_CHECK_RESULTS = check_environment()

# Add common media types for Windows compatibility
mimetypes.add_type('audio/mpeg', '.mp3')
mimetypes.add_type('audio/mp4', '.m4a')
mimetypes.add_type('audio/ogg', '.ogg')
mimetypes.add_type('audio/wav', '.wav')
mimetypes.add_type('audio/flac', '.flac')
mimetypes.add_type('video/mp4', '.mp4')
mimetypes.add_type('video/x-matroska', '.mkv')
mimetypes.add_type('video/webm', '.webm')
mimetypes.add_type('image/jpeg', '.jpg')
mimetypes.add_type('image/jpeg', '.jpeg')
mimetypes.add_type('image/png', '.png')
mimetypes.add_type('image/gif', '.gif')
mimetypes.add_type('application/pdf', '.pdf')

app = FastAPI(title="Nomad Pi")

# Global Scheduler
scheduler = BackgroundScheduler()

def cleanup_old_uploads():
    """Clean up uploads older than 24 hours"""
    UPLOAD_DIR = Path("data/uploads")
    if not UPLOAD_DIR.exists():
        return
        
    cutoff = datetime.now() - timedelta(hours=24)
    logger.info(f"Running cleanup task for old uploads in {UPLOAD_DIR}...")
    
    count = 0
    for item in UPLOAD_DIR.glob("*"):
        try:
            # Check both files and directories
            mtime = datetime.fromtimestamp(item.stat().st_mtime)
            if mtime < cutoff:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                count += 1
                logger.info(f"Cleaned up old upload: {item}")
        except Exception as e:
            logger.error(f"Failed to cleanup {item}: {e}")
            
    if count > 0:
        logger.info(f"Cleanup finished. Removed {count} items.")

# Global Exception Handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check logs for details."}
    )

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=404,
        content={"detail": "Resource not found"}
    )

# Initialize Database immediately
database.init_db()

# CORS - Restrict origins for security
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '').split(',') if os.getenv('ALLOWED_ORIGINS') else ['*']
if ALLOWED_ORIGINS != ['*']:
    # If specific origins are set, enable credentials
    ALLOW_CREDENTIALS = True
else:
    # If wildcard, disable credentials for security
    ALLOW_CREDENTIALS = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Create data directories if not exist
DATA_DIRS = ["data/movies", "data/shows", "data/music", "data/books", "data/files", "data/external", "data/gallery", "data/uploads"]
for d in DATA_DIRS:
    os.makedirs(d, exist_ok=True)

# Routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
# Public system endpoints
app.include_router(system.public_router, prefix="/api/system", tags=["system"])
app.include_router(media.public_router, prefix="/api/media", tags=["media"])
# Protect these routes
app.include_router(media.router, prefix="/api/media", tags=["media"], dependencies=[Depends(auth.get_current_user_id)])
app.include_router(system.router, prefix="/api/system", tags=["system"], dependencies=[Depends(auth.get_current_user_id)])
app.include_router(uploads.router, dependencies=[Depends(auth.get_current_user_id)])
app.include_router(dashboard.router)  # Dashboard has its own prefix and auth where needed

@app.on_event("startup")
def _startup_tasks():
    # Restore persistent mounts
    try:
        import json
        import subprocess
        import platform
        
        if platform.system() == "Linux":
            mounts_file = "data/mounts.json"
            if os.path.exists(mounts_file):
                logger.info("Restoring persistent mounts...")
                try:
                    with open(mounts_file, "r") as f:
                        mounts = json.load(f)
                        
                    for device, target in mounts.items():
                        try:
                            if not os.path.exists(device):
                                logger.warning(f"Skipping mount: device {device} not found")
                                continue
                                
                            if os.path.ismount(target):
                                logger.info(f"Drive {device} already mounted at {target}")
                                continue
                                
                            os.makedirs(target, exist_ok=True)
                            subprocess.run(["sudo", "-n", "/usr/bin/mount", device, target], check=True)
                            logger.info(f"Restored mount: {device} -> {target}")
                        except Exception as e:
                            logger.error(f"Failed to restore mount {device}: {e}")
                except Exception as e:
                    logger.error(f"Failed to load persistent mounts: {e}")
    except Exception as e:
        logger.error(f"Error during mount restoration: {e}")

    # Start scheduler
    scheduler.add_job(cleanup_old_uploads, 'interval', hours=12) # Reduced frequency for SBCs
    scheduler.start()
    logger.info("Background scheduler started")
    
    # 1. Start Discovery Service
    try:
        from app.services import discovery
        discovery.service.start()
    except Exception as e:
        logger.error(f"Failed to start discovery service: {e}")

    # 2. Staggered background tasks to prevent OOM on SBCs
    def run_staggered():
        # Wait a bit for the main web server to settle
        time.sleep(10)
        
        # Clean up stale sessions
        try:
            media.database.cleanup_sessions()
        except (OSError, IOError) as e:
            logger.warning(f"Failed to cleanup sessions: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during session cleanup: {e}")
        
        # Run cleanup task once
        cleanup_old_uploads()
        
        # 2. Delayed Indexer logic
        def needs_build(category: str):
            try:
                state = media.database.get_library_index_state(category)
            except Exception: return True
            if not state: return True
            scanned_at = state.get("scanned_at")
            if not isinstance(scanned_at, str) or not scanned_at: return True
            try:
                ts = datetime.fromisoformat(scanned_at)
            except Exception: return True
            return (datetime.now() - ts) >= media.INDEX_TTL

        # Only index one category at a time with delays
        for category in ["movies", "shows", "music", "books"]:
            if needs_build(category):
                try:
                    logger.info(f"Startup: Indexing {category}...")
                    media.build_library_index(category)
                    # Small breath between categories
                    time.sleep(5)
                except MemoryError as e:
                    logger.error(f"Memory error while indexing {category}: {e}")
                    logger.warning("Skipping remaining indexing to prevent crash")
                    break  # Stop indexing if we run out of memory
                except (OSError, IOError) as e:
                    logger.warning(f"File system error while indexing {category}: {e}")
                except Exception as e:
                    logger.error(f"Error indexing {category}: {e}")
                    continue  # Continue with next category on other errors

        # 3. Start ingest service LAST
        try:
            ingest.start_ingest_service()
        except MemoryError as e:
            logger.error(f"Memory error starting ingest service: {e}")
            logger.warning("Ingest service may not be available")
        except (OSError, IOError) as e:
            logger.error(f"File system error starting ingest service: {e}")
        except Exception as e:
            logger.error(f"Failed to start ingest service: {e}")

    threading.Thread(target=run_staggered, daemon=True).start()

@app.on_event("shutdown")
def _shutdown_tasks():
    ingest.stop_ingest_service()

@app.middleware("http")
async def protect_data(request: Request, call_next):
    # Allow OPTIONS requests for CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    if request.url.path.startswith("/data/"):
        token = request.cookies.get("auth_token") or request.query_params.get("token")
        
        if not token:
            print(f"Unauthorized access attempt (no token): {request.url.path}")
            return Response(status_code=401)
        
        session = database.get_session(token)
        if not session:
            # Mask token for logging
            masked_token = (token[:4] + "...") if token and len(token) > 4 else "****"
            print(f"Unauthorized access attempt (invalid session): {request.url.path} | Token: {masked_token}")
            return Response(status_code=401)
    
    response = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith(".html") or p.endswith(".js") or p.endswith(".css"):
        response.headers["Cache-Control"] = "no-store"
    if p.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    ct = (response.headers.get("content-type") or "").strip().lower()
    if ct == "application/json":
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

# Mount data for direct access (streaming)
# Note: Protecting StaticFiles via dependency is tricky without a custom middleware or proxy.
# For a home server, we'll leave media accessible if URL is known, but API is protected.
app.mount("/data", StaticFiles(directory="data"), name="data")

# Mount frontend
# We check if index.html exists, if not we might want to return a placeholder or 404
# But StaticFiles with html=True will serve index.html
if os.path.exists("app/static"):
    app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # 8000 for dev, 80 for prod (requires sudo on linux)
    # Optimized settings for better upload performance
    uvicorn.run(
        "app.main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=False, 
        loop="auto", 
        http="auto",
        limit_concurrency=1000,  # Allow more concurrent connections
        limit_max_requests=10000,  # Prevent memory leaks
        timeout_keep_alive=75,  # Keep connections alive longer
        backlog=2048  # Increase connection queue
    )
