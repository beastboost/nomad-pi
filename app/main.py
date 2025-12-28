from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from app.routers import media, system, auth, uploads
from app.services import ingest
import os
import threading
from datetime import datetime

app = FastAPI(title="Nomad Pi")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create data directories if not exist
DATA_DIRS = ["data/movies", "data/shows", "data/music", "data/books", "data/files", "data/external", "data/gallery", "data/uploads"]
for d in DATA_DIRS:
    os.makedirs(d, exist_ok=True)

# Routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
# Protect these routes
app.include_router(media.router, prefix="/api/media", tags=["media"], dependencies=[Depends(auth.get_current_user)])
app.include_router(system.router, prefix="/api/system", tags=["system"], dependencies=[Depends(auth.get_current_user)])
app.include_router(uploads.router, dependencies=[Depends(auth.get_current_user)])

@app.on_event("startup")
def _startup_tasks():
    # Indexer logic
    def needs_build(category: str):
        try:
            state = media.database.get_library_index_state(category)
        except Exception:
            return True
        if not state:
            return True
        scanned_at = state.get("scanned_at")
        if not isinstance(scanned_at, str) or not scanned_at:
            return True
        try:
            ts = datetime.fromisoformat(scanned_at)
        except Exception:
            return True
        return (datetime.now() - ts) >= media.INDEX_TTL

    def run():
        # Clean up stale sessions on startup
        try:
            media.database.cleanup_sessions()
        except Exception:
            pass
            
        for category in ["movies", "shows"]:
            if needs_build(category):
                try:
                    media.build_library_index(category)
                except Exception:
                    pass

    threading.Thread(target=run, daemon=True).start()

    # Start ingest service
    try:
        ingest.start_ingest_service()
    except Exception as e:
        print(f"Failed to start ingest service: {e}")

@app.on_event("shutdown")
def _shutdown_tasks():
    ingest.stop_ingest_service()

@app.middleware("http")
async def protect_data(request: Request, call_next):
    if request.url.path.startswith("/data/"):
        token = request.cookies.get("auth_token")
        if not token or token not in auth.SESSIONS:
            return Response(status_code=401)
    response = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith(".html") or p.endswith(".js") or p.endswith(".css"):
        response.headers["Cache-Control"] = "no-store"
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
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, loop="auto", http="auto")
