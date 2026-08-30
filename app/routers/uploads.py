"""
Optimized file upload router with chunked buffering, async I/O, and progress tracking.

Features:
- Chunked buffering for efficient memory usage
- Async I/O operations for non-blocking uploads
- Real-time progress tracking
- File validation and security checks
- Support for single and multiple file uploads
"""

import os
import hashlib
import logging
import threading
from pathlib import Path
from typing import Optional, AsyncGenerator, Dict, List
from datetime import datetime


from fastapi import APIRouter, UploadFile, File, HTTPException, Query, BackgroundTasks, Depends
import aiofiles
import aiofiles.os
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

# Configuration
UPLOAD_DIR = Path("data/uploads")


CHUNK_SIZE = 16 * 1024 * 1024  # 16MB chunks (optimized for WiFi throughput)
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10GB
BUFFER_SIZE = 64 * 1024  # 64KB buffer for file I/O
ALLOWED_EXTENSIONS = {
    "txt",
    "pdf",
    "epub",
    "mobi",
    "cbz",
    "cbr",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "mp3",
    "flac",
    "wav",
    "m4a",
    "mp4",
    "mkv",
    "avi",
    "mov",
    "webm",
    "m4v",
    "ts",
    "wmv",
    "flv",
    "3gp",
    "mpg",
    "mpeg",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "zip",
    "csv",
    "json",
    "xml",
}

# Ensure upload directory exists
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# Pydantic models
class UploadProgress(BaseModel):
    """Model for tracking upload progress."""
    file_id: str
    filename: str
    total_size: int
    uploaded_size: int
    # Required-with-no-default made every upload 500 on construction: the one
    # site that builds this model reports size as it goes and fills the
    # percentage in on later updates.
    percentage: float = Field(default=0.0, ge=0, le=100)
    status: str = Field(default="uploading")
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class UploadResponse(BaseModel):
    """Model for upload response."""
    file_id: str
    filename: str
    size: int
    path: str
    checksum: str
    upload_time: float
    status: str = "success"


class MultipleUploadResponse(BaseModel):
    """Model for multiple files upload response."""
    files: List[UploadResponse]
    total_size: int
    total_time: float
    success_count: int
    failed_count: int


# Global progress tracking with thread safety (in production, use Redis or similar)
progress_tracker: Dict[str, UploadProgress] = {}
progress_lock = threading.Lock()

# The only directories an upload may target. ``category`` arrives straight off
# a query string, and it used to be pasted into a filesystem path unchecked, so
# "../../etc" resolved outside data/ and mkdir(parents=True) then created it.
UPLOAD_CATEGORIES = ("movies", "shows", "music", "books", "gallery", "files")


def _validated_category(category: str) -> str:
    normalized = (category or "files").strip().lower() or "files"
    if normalized not in UPLOAD_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Allowed: {', '.join(UPLOAD_CATEGORIES)}",
        )
    return normalized


def _detect_category(requested_category: str, filename: str) -> str:
    category = _validated_category(requested_category)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if category != "files":
        return category

    if ext in ["mp3", "flac", "wav", "m4a"]:
        return "music"
    if ext in ["jpg", "jpeg", "png", "gif"]:
        return "gallery"
    if ext in ["pdf", "epub", "mobi", "cbz", "cbr"]:
        return "books"
    if ext in ["mp4", "mkv", "avi", "mov", "webm", "m4v", "ts", "wmv", "flv", "3gp", "mpg", "mpeg"]:
        try:
            from app.routers import media as media_router

            s, e = media_router.parse_season_episode(filename)
            if s is not None or e is not None:
                return "shows"
            if media_router.parse_episode_only(filename) is not None:
                return "shows"
        except Exception:
            pass
        return "movies"

    return "files"


def _contain(destination: Path, base_dir: Path) -> Path:
    """Refuse any destination that escaped its category directory.

    auto_dest_rel() derives sub-paths from the *filename*, so this backstops
    the category allow-list against a crafted name as well.
    """
    resolved = destination.resolve()
    base = base_dir.resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=400, detail="Invalid upload destination")
    return resolved


def _compute_destination(category: str, filename: str) -> Path:
    cat = _validated_category(category)
    safe_name = os.path.basename(filename)
    base_dir = Path("data") / cat
    base_dir.mkdir(parents=True, exist_ok=True)

    if cat in ["movies", "shows"]:
        from app.routers import media as media_router

        dest_rel = media_router.auto_dest_rel(cat, safe_name, rename_files=True)
        dest_abs = (base_dir / Path(dest_rel)).resolve()
        dest_abs_str = media_router.pick_unique_dest(str(dest_abs))
        return _contain(Path(dest_abs_str), base_dir)

    dest_abs = (base_dir / safe_name).resolve()
    try:
        from app.routers import media as media_router

        dest_abs_str = media_router.pick_unique_dest(str(dest_abs))
        return _contain(Path(dest_abs_str), base_dir)
    except HTTPException:
        raise
    except Exception:
        i = 2
        base, ext = os.path.splitext(str(dest_abs))
        while Path(dest_abs).exists() and i < 1000:
            dest_abs = Path(f"{base} ({i}){ext}")
            i += 1
        return _contain(Path(dest_abs), base_dir)


async def validate_file(filename: str, file_size: int) -> tuple[bool, Optional[str]]:
    """
    Validate file before upload.
    
    Args:
        filename: Name of the file
        file_size: Size of the file in bytes
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check file extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File extension '.{ext}' not allowed"
    
    # Check file size
    if file_size > MAX_FILE_SIZE:
        return False, f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
    
    # Check for path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return False, "Invalid filename detected"
    
    return True, None


async def iter_file_chunks(file, chunk_size: int = CHUNK_SIZE) -> AsyncGenerator[bytes, None]:
    """
    Read file in chunks asynchronously.
    
    Args:
        file: File object
        chunk_size: Size of each chunk
        
    Yields:
        File chunks
    """
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        yield chunk


async def save_upload_file(
    upload_file: UploadFile,
    file_id: str,
    destination: Path,
) -> tuple[int, str]:
    """
    Save uploaded file with chunked buffering and progress tracking.
    
    Args:
        upload_file: FastAPI UploadFile object
        file_id: Unique file identifier
        destination: Destination path for the file
        
    Returns:
        Tuple of (file_size, checksum)
    """
    hash_sha256 = hashlib.sha256()
    total_size = 0
    
    try:
        # Initialize progress tracker with thread safety
        with progress_lock:
            progress_tracker[file_id] = UploadProgress(
                file_id=file_id,
                filename=upload_file.filename,
                total_size=0,
                uploaded_size=0,
                status="uploading"
            )
        
        # Create parent directories if needed
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file with chunked buffering and optimized I/O
        async with aiofiles.open(destination, "wb", buffering=BUFFER_SIZE) as f:
            while True:
                # UploadFile.read() is the awaitable one; UploadFile.file is the
                # raw SpooledTemporaryFile and its read() returns bytes, so
                # awaiting it raised TypeError on the first chunk of every upload.
                chunk = await upload_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                
                # Write chunk
                await f.write(chunk)
                hash_sha256.update(chunk)
                total_size += len(chunk)
                
                # Update progress less frequently to reduce overhead
                if total_size % (CHUNK_SIZE * 4) == 0:
                    with progress_lock:
                        if file_id in progress_tracker:
                            progress_tracker[file_id].uploaded_size = total_size
                            progress_tracker[file_id].percentage = (total_size / max(upload_file.size or total_size, 1)) * 100
        
        # Calculate final checksum
        checksum = hash_sha256.hexdigest()
        
        # Update progress to completed
        with progress_lock:
            if file_id in progress_tracker:
                progress_tracker[file_id].status = "completed"
                progress_tracker[file_id].percentage = 100.0
        
        logger.info(f"File uploaded successfully: {upload_file.filename} ({total_size} bytes)")
        return total_size, checksum
        
    except Exception as e:
        logger.error(f"Error uploading file {upload_file.filename}: {str(e)}")
        with progress_lock:
            if file_id in progress_tracker:
                progress_tracker[file_id].status = "failed"
                progress_tracker[file_id].error = str(e)
        raise


def cleanup_old_uploads(background_tasks: BackgroundTasks, file_path: Path, delay: int = 3600):
    """
    Schedule cleanup of uploaded file after delay.
    
    Args:
        background_tasks: FastAPI BackgroundTasks
        file_path: Path to file to cleanup
        delay: Delay in seconds before cleanup (default 1 hour)
    """
    async def cleanup():
        import asyncio
        await asyncio.sleep(delay)
        try:
            if await aiofiles.os.path.exists(file_path):
                await aiofiles.os.remove(file_path)
                logger.info(f"Cleaned up uploaded file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {str(e)}")
    
    background_tasks.add_task(cleanup)


# API Endpoints

@router.post("/single", response_model=UploadResponse)
async def upload_single_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    file_id: Optional[str] = Query(None),
    category: str = Query("files"),
    user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    """
    Upload a single file with progress tracking.
    
    Args:
        file: The file to upload
        file_id: Optional unique identifier for tracking
        category: Media category (music, movies, etc.)
        
    Returns:
        UploadResponse with file details
    """
    import time
    start_time = time.time()
    
    # Generate file_id if not provided
    if not file_id:
        file_id = hashlib.md5(f"{file.filename}{datetime.utcnow()}".encode()).hexdigest()
    
    # Validate file
    is_valid, error_msg = await validate_file(file.filename, file.size or 0)
    if not is_valid:
        logger.warning(f"File validation failed: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    resolved_category = _detect_category(category, file.filename or "")
    destination = _compute_destination(resolved_category, file.filename or "")
    
    try:
        # Save file
        file_size, checksum = await save_upload_file(file, file_id, destination)
        
        upload_time = time.time() - start_time
        
        # Integrate with library index
        try:
            from app import database
            import os

            rel_path = os.path.relpath(destination, "data").replace(os.sep, "/")
            web_path = f"/data/{rel_path}"
            cat_root = os.path.join("data", resolved_category)
            folder = os.path.relpath(os.path.dirname(destination), cat_root).replace(os.sep, "/")

            database.upsert_library_index_item({
                "path": web_path,
                "category": resolved_category,
                "name": file.filename,
                "folder": folder if folder else ".",
                "source": "local",
                "poster": None,
                "mtime": float(os.path.getmtime(destination)),
                "size": file_size,
            })
        except Exception as e:
            logger.error(f"Failed to index uploaded file: {e}")
            
        # Trigger MiniDLNA rescan and auto-organization
        try:
            from app.routers.media import trigger_dlna_rescan, trigger_auto_organize
            background_tasks.add_task(trigger_dlna_rescan)
            if resolved_category in ["shows", "movies"]:
                background_tasks.add_task(trigger_auto_organize)
        except ImportError:
            logger.warning("Could not import triggers from media router")
            
        return UploadResponse(
            file_id=file_id,
            filename=file.filename,
            size=file_size,
            path=str(destination),
            checksum=checksum,
            upload_time=round(upload_time, 2),
            status="success"
        )
    
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail="File upload failed")


@router.post("/multiple", response_model=MultipleUploadResponse)
async def upload_multiple_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    category: str = Query("files"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Upload multiple files with individual progress tracking.
    
    Args:
        files: List of files to upload
        category: Media category
        
    Returns:
        MultipleUploadResponse with details for all files
    """
    import time
    start_time = time.time()
    
    uploaded_files: List[UploadResponse] = []
    failed_count = 0
    total_size = 0
    organize_after = False
    
    from app import database
    import os

    for file in files:
        file_id = hashlib.md5(f"{file.filename}{datetime.utcnow()}".encode()).hexdigest()
        
        # Validate file
        is_valid, error_msg = await validate_file(file.filename, file.size or 0)
        if not is_valid:
            logger.warning(f"File validation failed for {file.filename}: {error_msg}")
            failed_count += 1
            continue
        
        resolved_category = _detect_category(category, file.filename or "")
        if resolved_category in ["shows", "movies"]:
            organize_after = True
        destination = _compute_destination(resolved_category, file.filename or "")
        
        try:
            # Save file
            file_size, checksum = await save_upload_file(file, file_id, destination)
            total_size += file_size
            
            # Index the file
            try:
                rel_path = os.path.relpath(destination, "data").replace(os.sep, "/")
                web_path = f"/data/{rel_path}"
                cat_root = os.path.join("data", resolved_category)
                folder = os.path.relpath(os.path.dirname(destination), cat_root).replace(os.sep, "/")
                
                database.upsert_library_index_item({
                    "path": web_path,
                    "category": resolved_category,
                    "name": file.filename,
                    "folder": folder if folder else ".",
                    "source": "local",
                    "poster": None,
                    "mtime": float(os.path.getmtime(destination)),
                    "size": file_size,
                })
            except Exception as e:
                logger.error(f"Failed to index uploaded file {file.filename}: {e}")

            uploaded_files.append(UploadResponse(
                file_id=file_id,
                filename=file.filename,
                size=file_size,
                path=str(destination),
                checksum=checksum,
                upload_time=0.0,
                status="success"
            ))
        
        except Exception as e:
            logger.error(f"Upload failed for {file.filename}: {str(e)}")
            failed_count += 1
    
    total_time = time.time() - start_time
    
    # Trigger MiniDLNA rescan and auto-organization if any files were uploaded
    if uploaded_files:
        try:
            from app.routers.media import trigger_dlna_rescan, trigger_auto_organize
            background_tasks.add_task(trigger_dlna_rescan)
            if organize_after:
                background_tasks.add_task(trigger_auto_organize)
        except ImportError:
            logger.warning("Could not import triggers from media router")

    return MultipleUploadResponse(
        files=uploaded_files,
        total_size=total_size,
        total_time=round(total_time, 2),
        success_count=len(uploaded_files),
        failed_count=failed_count
    )


@router.get("/progress/{file_id}")
async def get_upload_progress(
    file_id: str,
    user_id: str = Depends(get_current_user_id),
) -> UploadProgress:
    """
    Get current upload progress for a file.
    
    Args:
        file_id: Unique file identifier
        
    Returns:
        UploadProgress with current status
    """
    if file_id not in progress_tracker:
        raise HTTPException(status_code=404, detail="File not found in progress tracker")
    
    return progress_tracker[file_id]


# The download/delete/verify/info endpoints that used to live here have been
# removed. They all looked for data/uploads/<file_id>/<filename>, but no upload
# path has ever written there — _compute_destination() files an upload straight
# into its library category — so every one of them was a permanent 404 that
# advertised capabilities the server does not have. Uploaded files are reached
# through the media API instead: /api/media/browse to list, /api/media/stream
# with download=true to fetch, and /api/media/delete to remove.
