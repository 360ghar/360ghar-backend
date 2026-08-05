import uuid
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.api.api_v1.dependencies.auth import get_current_user
from app.core.auth import get_supabase_service_client
from app.core.config import settings
from app.core.utils import is_valid_uuid
from app.models.users import User
from app.services.modal_worker import train_splat
from app.services.storage_paths import sanitize_filename

router = APIRouter()

# Jobs in these statuses may be (re)started; anything else is already running or terminal.
_STARTABLE_STATUSES = frozenset({"pending", "failed"})


class JobCreate(BaseModel):
    title: str
    is_360_video: bool = False
    quality_preset: Literal["fast", "balanced", "quality"] = "balanced"
    filenames: list[str] = ["video.mp4"]

    @field_validator("filenames")
    @classmethod
    def _reject_commas(cls, v: list[str]) -> list[str]:
        """Filenames are joined with commas for storage_path — commas in names break splitting."""
        for f in v:
            if "," in f:
                raise ValueError(f"Filename must not contain commas: {f!r}")
        return v


def _require_uuid_user_id(user: User) -> str:
    """splat_jobs.user_id is UUID REFERENCES auth.users — reject non-UUID seed ids."""
    uid = str(getattr(user, "supabase_user_id", "") or "")
    if not is_valid_uuid(uid):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_SUPABASE_USER_ID",
                "message": "Account is not linked to a valid auth identity",
            },
        )
    return uid

@router.post("/jobs", response_model=Any)
async def create_job(
    *,
    job_in: JobCreate,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Start a new Gaussian Splat job.
    """
    user_id = _require_uuid_user_id(current_user)
    job_id = str(uuid.uuid4())

    # Generate an upload path for the video
    storage_path = f"{user_id}/{job_id}"

    # Create the record in Supabase.
    # Sanitize identically to get_upload_url so the stored video_path always
    # matches the path the client uploaded to. This also strips path
    # separators / '..' segments, so a crafted filename can never make the
    # worker download outside this job's {user_id}/{job_id}/ storage folder.
    video_paths = ",".join(
        [f"{storage_path}/{sanitize_filename(f)}" for f in job_in.filenames]
    )
    job_data: dict[str, Any] = {
        "id": job_id,
        "user_id": user_id,
        "title": job_in.title,
        "status": "pending",
        "progress": 0,
        "stage_message": "Waiting for video upload...",
        "is_360_video": job_in.is_360_video,
        "quality_preset": job_in.quality_preset,
        "video_path": video_paths
    }

    # We assume you have a splat_jobs table in supabase
    try:
        res = get_supabase_service_client().table("splat_jobs").insert(job_data).execute()
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}") from None

@router.post("/jobs/{job_id}/start", response_model=Any)
async def start_job(
    *,
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Trigger the modal pipeline after video is uploaded to Supabase.
    """
    user_id = _require_uuid_user_id(current_user)
    # Verify job belongs to user
    job_res = get_supabase_service_client().table("splat_jobs").select("*").eq("id", job_id).eq("user_id", user_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job not found")

    job = cast("dict[str, Any]", job_res.data[0])

    # Prevent concurrent GPU launches — claim the job with an atomic
    # conditional update BEFORE spawning, so two concurrent start requests
    # cannot both pass the status check and double-spawn a training run.
    claim_res = (
        get_supabase_service_client()
        .table("splat_jobs")
        .update(
            {
                "status": "extracting",
                "stage_message": "Starting cloud GPU pipeline (multi-view 360 SfM)...",
                "progress": 5,
            }
        )
        .eq("id", job_id)
        .eq("user_id", user_id)
        .in_("status", _STARTABLE_STATUSES)
        .execute()
    )
    if not claim_res.data:
        raise HTTPException(
            status_code=409,
            detail=f"Job is already running or terminal (status={job.get('status')})",
        )

    # Spawn the Modal function asynchronously so we don't block the API.
    # force_360 from job flag — multi-yaw unwrap is required for indoor GS quality.
    # Default to False to match JobCreate default (not True, which would run 360
    # unwrapping on non-360 video and produce garbage).
    force_360 = bool(job.get("is_360_video", False))
    try:
        train_splat.spawn(job_id, job["video_path"], job["quality_preset"], None, force_360)
    except Exception:
        # Roll the claim back so the job is retryable instead of stuck in
        # 'extracting' forever with no worker ever running.
        get_supabase_service_client().table("splat_jobs").update(
            {
                "status": "failed",
                "stage_message": "Failed to start cloud GPU pipeline",
                "progress": 0,
            }
        ).eq("id", job_id).execute()
        raise HTTPException(status_code=500, detail="Failed to start the GPU pipeline") from None

    return job

@router.post("/jobs/{job_id}/upload-video", response_model=Any)
async def get_upload_url(
    job_id: str,
    filename: str,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get a presigned URL to upload a video clip.
    """
    user_id = _require_uuid_user_id(current_user)
    job_res = get_supabase_service_client().table("splat_jobs").select("*").eq("id", job_id).eq("user_id", user_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job not found")

    # Sanitize to prevent path traversal (strips path separators, replaces special chars)
    safe_filename = sanitize_filename(filename)
    storage_path = f"{user_id}/{job_id}/{safe_filename}"

    # Generate signed upload URL from Supabase
    res = get_supabase_service_client().storage.from_(settings.SPLAT_BUCKET_NAME).create_signed_upload_url(storage_path)

    # supabase-py returns an object with a signed_url attribute (named tuple in
    # older versions, dataclass in newer). Handle both attribute and dict shapes.
    if hasattr(res, "signed_url"):
        upload_url = getattr(res, "signed_url", None)
    elif isinstance(res, dict):
        upload_url = res.get("signedUrl") or res.get("signed_url")
    else:
        upload_url = str(res) if res else None

    if not upload_url:
        raise HTTPException(status_code=500, detail="Failed to generate upload URL")

    return {
        "upload_url": upload_url,
        "storage_path": storage_path
    }

@router.get("/jobs", response_model=Any)
async def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List user's splat jobs (paginated, newest first).
    """
    user_id = _require_uuid_user_id(current_user)
    sb = get_supabase_service_client()
    # Count total first, then fetch the page
    count_res = sb.table("splat_jobs").select("id", count="exact").eq("user_id", user_id).execute()  # type: ignore[arg-type]
    total = count_res.count or 0
    res = (
        sb.table("splat_jobs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"jobs": res.data, "total": total, "limit": limit, "offset": offset}

@router.get("/jobs/{job_id}", response_model=Any)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get job status.
    """
    user_id = _require_uuid_user_id(current_user)
    res = get_supabase_service_client().table("splat_jobs").select("*").eq("id", job_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job not found")
    return res.data[0]

@router.delete("/jobs/{job_id}", response_model=Any)
async def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Delete job.
    """
    user_id = _require_uuid_user_id(current_user)
    get_supabase_service_client().table("splat_jobs").delete().eq("id", job_id).eq("user_id", user_id).execute()
    return {"status": "deleted"}
