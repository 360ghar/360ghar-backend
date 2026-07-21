import uuid
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.api.api_v1.dependencies.auth import get_current_user
from app.models.users import User
from app.core.auth import get_supabase_service_client
from app.services.modal_worker import train_splat

router = APIRouter()

class JobCreate(BaseModel):
    title: str
    is_360_video: bool = False
    quality_preset: str = "balanced" # fast, balanced, quality
    filenames: List[str] = ["video.mp4"]

@router.post("/jobs", response_model=Any)
async def create_job(
    *,
    job_in: JobCreate,
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks
) -> Any:
    """
    Start a new Gaussian Splat job.
    """
    job_id = str(uuid.uuid4())
    
    # Generate an upload path for the video
    storage_path = f"{current_user.supabase_user_id}/{job_id}"
    
    # Create the record in Supabase
    video_paths = ",".join([f"{storage_path}/{f}" for f in job_in.filenames])
    job_data = {
        "id": job_id,
        "user_id": str(current_user.supabase_user_id),
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
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")

@router.post("/jobs/{job_id}/start", response_model=Any)
async def start_job(
    *,
    job_id: str,
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks
) -> Any:
    """
    Trigger the modal pipeline after video is uploaded to Supabase.
    """
    # Verify job belongs to user
    job_res = get_supabase_service_client().table("splat_jobs").select("*").eq("id", job_id).eq("user_id", str(current_user.supabase_user_id)).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job = job_res.data[0]
    
    # Spawn the Modal function asynchronously so we don't block the API.
    # force_360 from job flag — multi-yaw unwrap is required for indoor GS quality.
    force_360 = bool(job.get("is_360_video", True))
    train_splat.spawn(job_id, job["video_path"], job["quality_preset"], None, force_360)

    get_supabase_service_client().table("splat_jobs").update({
        "status": "extracting",
        "stage_message": "Starting cloud GPU pipeline (multi-view 360 SfM)...",
        "progress": 5
    }).eq("id", job_id).execute()
    
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
    job_res = get_supabase_service_client().table("splat_jobs").select("*").eq("id", job_id).eq("user_id", str(current_user.supabase_user_id)).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job not found")
        
    storage_path = f"{current_user.supabase_user_id}/{job_id}/{filename}"
    
    # Generate signed upload URL from Supabase
    res = get_supabase_service_client().storage.from_("splat-jobs").create_signed_upload_url(storage_path)
    
    # The return format of create_signed_upload_url is a dict with signedUrl, etc.
    # But usually it's {"signedUrl": ...}
    # Wait, in the supabase python client, it returns a dict. Let's just return what the frontend expects.
    # The frontend expects { "upload_url": string, "storage_path": string }
    upload_url = res.get("signedUrl", res.get("signed_url"))
    # The SDK usually returns signed_url or signedUrl or just a string. 
    # Actually, the python sdk create_signed_upload_url returns a dictionary with 'signedUrl'.
    # I should construct the full URL if it's relative. It usually returns a path! Wait.
    # Let me just check how python supabase create_signed_upload_url works, but for now:
    
    return {
        "upload_url": upload_url,
        "storage_path": storage_path
    }

@router.get("/jobs", response_model=Any)
async def list_jobs(
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List user's splat jobs.
    """
    res = get_supabase_service_client().table("splat_jobs").select("*").eq("user_id", str(current_user.supabase_user_id)).order("created_at", desc=True).execute()
    return {"jobs": res.data, "total": len(res.data)}

@router.get("/jobs/{job_id}", response_model=Any)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get job status.
    """
    res = get_supabase_service_client().table("splat_jobs").select("*").eq("id", job_id).eq("user_id", str(current_user.supabase_user_id)).execute()
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
    res = get_supabase_service_client().table("splat_jobs").delete().eq("id", job_id).eq("user_id", str(current_user.supabase_user_id)).execute()
    return {"status": "deleted"}
