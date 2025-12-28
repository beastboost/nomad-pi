from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from app.routers import media, system, auth, uploads
from app.services import ingest
from app import database
import os
import threading
import mimetypes
from datetime import datetime

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

# Initialize Database immediately
database.init_db()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Changed to False since we use token in URL or it's same-origin
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
