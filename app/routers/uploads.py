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
from pathlib import Path
from typing import Optional, AsyncGenerator, Dict, List
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
import aiofiles
import aiofiles.os
from pydantic import BaseModel, Field

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

# Configuration
UPLOAD_DIR = Path("uploads")
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
ALLOWED_EXTENSIONS = {
    "txt", "pdf", "png", "jpg", "jpeg", "gif", "mp3", "mp4",
    "doc", "docx", "xls", "xlsx", "zip", "csv", "json", "xml"
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
    percentage: float = Field(ge=0, le=100)
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


# Global progress tracking (in production, use Redis or similar)
progress_tracker: Dict[str, UploadProgress] = {}


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


async def calculate_file_hash(file_path: Path) -> str:
    """
    Calculate SHA256 hash of a file asynchronously.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Hexadecimal hash string
    """
    hash_sha256 = hashlib.sha256()
    
    async with aiofiles.open(file_path, "rb") as f:
        async for chunk in iter_file_chunks(f):
            hash_sha256.update(chunk)
    
    return hash_sha256.hexdigest()


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
        # Initialize progress tracker
        progress_tracker[file_id] = UploadProgress(
            file_id=file_id,
            filename=upload_file.filename,
            total_size=0,
            uploaded_size=0,
            status="uploading"
        )
        
        # Create parent directories if needed
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file with chunked buffering
        async with aiofiles.open(destination, "wb") as f:
            while True:
                chunk = await upload_file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                
                # Write chunk
                await f.write(chunk)
                hash_sha256.update(chunk)
                total_size += len(chunk)
                
                # Update progress
                if file_id in progress_tracker:
                    progress_tracker[file_id].uploaded_size = total_size
                    progress_tracker[file_id].percentage = (total_size / max(upload_file.size or total_size, 1)) * 100
        
        # Calculate final checksum
        checksum = hash_sha256.hexdigest()
        
        # Update progress to completed
        if file_id in progress_tracker:
            progress_tracker[file_id].status = "completed"
            progress_tracker[file_id].percentage = 100.0
        
        logger.info(f"File uploaded successfully: {upload_file.filename} ({total_size} bytes)")
        return total_size, checksum
        
    except Exception as e:
        logger.error(f"Error uploading file {upload_file.filename}: {str(e)}")
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
    file: UploadFile = File(...),
    file_id: Optional[str] = Query(None),
) -> UploadResponse:
    """
    Upload a single file with progress tracking.
    
    Args:
        file: The file to upload
        file_id: Optional unique identifier for tracking
        
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
    
    # Prepare destination
    destination = UPLOAD_DIR / file_id / file.filename
    
    try:
        # Save file
        file_size, checksum = await save_upload_file(file, file_id, destination)
        
        upload_time = time.time() - start_time
        
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
async def upload_multiple_files(files: List[UploadFile] = File(...)):
    """
    Upload multiple files with individual progress tracking.
    
    Args:
        files: List of files to upload
        
    Returns:
        MultipleUploadResponse with details for all files
    """
    import time
    start_time = time.time()
    
    uploaded_files: List[UploadResponse] = []
    failed_count = 0
    total_size = 0
    
    for file in files:
        file_id = hashlib.md5(f"{file.filename}{datetime.utcnow()}".encode()).hexdigest()
        
        # Validate file
        is_valid, error_msg = await validate_file(file.filename, file.size or 0)
        if not is_valid:
            logger.warning(f"File validation failed for {file.filename}: {error_msg}")
            failed_count += 1
            continue
        
        # Prepare destination
        destination = UPLOAD_DIR / file_id / file.filename
        
        try:
            # Save file
            file_size, checksum = await save_upload_file(file, file_id, destination)
            total_size += file_size
            
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
    
    return MultipleUploadResponse(
        files=uploaded_files,
        total_size=total_size,
        total_time=round(total_time, 2),
        success_count=len(uploaded_files),
        failed_count=failed_count
    )


@router.get("/progress/{file_id}")
async def get_upload_progress(file_id: str) -> UploadProgress:
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


@router.get("/download/{file_id}/{filename}")
async def download_file(file_id: str, filename: str):
    """
    Download a previously uploaded file with streaming.
    
    Args:
        file_id: Unique file identifier
        filename: Name of the file to download
        
    Returns:
        StreamingResponse with file content
    """
    file_path = UPLOAD_DIR / file_id / filename
    
    # Validate file exists and is within upload directory
    try:
        file_path = file_path.resolve()
        upload_dir = UPLOAD_DIR.resolve()
        
        if not file_path.is_relative_to(upload_dir):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not await aiofiles.os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")
    
    except Exception as e:
        logger.error(f"Error accessing file: {str(e)}")
        raise HTTPException(status_code=500, detail="Error accessing file")
    
    # Stream file in chunks
    async def file_iterator():
        async with aiofiles.open(file_path, "rb") as f:
            async for chunk in iter_file_chunks(f):
                yield chunk
    
    return StreamingResponse(
        file_iterator(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.delete("/{file_id}")
async def delete_upload(file_id: str):
    """
    Delete an uploaded file.
    
    Args:
        file_id: Unique file identifier
        
    Returns:
        JSON response with deletion status
    """
    file_dir = UPLOAD_DIR / file_id
    
    try:
        # Validate directory is within upload directory
        file_dir = file_dir.resolve()
        upload_dir = UPLOAD_DIR.resolve()
        
        if not file_dir.is_relative_to(upload_dir):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if await aiofiles.os.path.exists(file_dir):
            # Remove all files in directory
            for file in os.listdir(file_dir):
                file_path = file_dir / file
                if os.path.isfile(file_path):
                    await aiofiles.os.remove(file_path)
            
            # Remove directory
            await aiofiles.os.rmdir(file_dir)
            
            # Clean progress tracker
            if file_id in progress_tracker:
                del progress_tracker[file_id]
            
            return JSONResponse(
                status_code=200,
                content={"message": f"File {file_id} deleted successfully"}
            )
        else:
            raise HTTPException(status_code=404, detail="File not found")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file {file_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error deleting file")


@router.post("/verify/{file_id}/{filename}")
async def verify_file_integrity(file_id: str, filename: str, expected_checksum: str):
    """
    Verify integrity of uploaded file against checksum.
    
    Args:
        file_id: Unique file identifier
        filename: Name of the file
        expected_checksum: Expected SHA256 checksum
        
    Returns:
        JSON response with verification result
    """
    file_path = UPLOAD_DIR / file_id / filename
    
    if not await aiofiles.os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        actual_checksum = await calculate_file_hash(file_path)
        is_valid = actual_checksum == expected_checksum
        
        return JSONResponse(
            status_code=200,
            content={
                "file_id": file_id,
                "filename": filename,
                "expected_checksum": expected_checksum,
                "actual_checksum": actual_checksum,
                "valid": is_valid
            }
        )
    
    except Exception as e:
        logger.error(f"Error verifying file: {str(e)}")
        raise HTTPException(status_code=500, detail="Error verifying file")


@router.get("/info/{file_id}")
async def get_file_info(file_id: str) -> Dict:
    """
    Get information about an uploaded file.
    
    Args:
        file_id: Unique file identifier
        
    Returns:
        Dictionary with file information
    """
    file_dir = UPLOAD_DIR / file_id
    
    if not await aiofiles.os.path.exists(file_dir):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        files_info = []
        for filename in os.listdir(file_dir):
            file_path = file_dir / filename
            if os.path.isfile(file_path):
                stat = os.stat(file_path)
                files_info.append({
                    "filename": filename,
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        return {
            "file_id": file_id,
            "files": files_info,
            "total_size": sum(f["size"] for f in files_info)
        }
    
    except Exception as e:
        logger.error(f"Error getting file info: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting file info")
