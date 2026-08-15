"""Small lifecycle controls for Stream + Keep remote playback."""

from fastapi import APIRouter, Depends, HTTPException

from app.routers.auth import get_current_user_id
from app.routers import playback_stream_keep as stream_keep


router = APIRouter()


@router.delete("/stream-keep/{job_id}/playback")
def stop_stream_keep_playback(
    job_id: str,
    user_id: int = Depends(get_current_user_id),
):
    job = stream_keep.store.get(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Stream + Keep job not found")
    # Stop only FFmpeg/proxy playback state. The existing debrid download keeps
    # running until completion and the persistent job remains visible.
    stream_keep.hls_manager.stop(job.id, remove_cache=True)
    return {"status": "playback_stopped", "job": stream_keep._public_job(job)}
