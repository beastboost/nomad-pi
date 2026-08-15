"""Small authenticated endpoint for the active household/profile policy."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.auth import get_current_user_id
from app.services.profile_policy import get_profile_policy


router = APIRouter()


@router.get("/profile-policy")
def profile_policy(
    profile_id: int = Query(..., gt=0),
    user_id: int = Depends(get_current_user_id),
):
    policy = get_profile_policy(user_id, profile_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    # Only normalized controls are returned; no account/session secrets.
    return {"policy": policy}
