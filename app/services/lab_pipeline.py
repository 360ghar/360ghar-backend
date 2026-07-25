"""
3D Splat Lab – Gaussian Splatting Pipeline Service.

Orchestrates Daytona CPU/GPU sandboxes via the Daytona REST API (httpx async).
No GPU is required for stages 1-3 (frame extraction, 360->cubemap, COLMAP CPU
mode).  Stage 4 (Nerfstudio splatfacto training) requires CUDA and is currently
gated: the sandbox self-reports GPU availability and returns GPU_REQUIRED when
none is found, so the job lands in `failed` with a clear operator message.

Structure is intentionally GPU-ready: swap `use_gpu=False` -> `use_gpu=True` in
`_run_pipeline_in_sandbox` once Daytona GPU access is enabled.

Daytona REST base: https://app.daytona.io/api/
Auth:              Authorization: Bearer {DAYTONA_API_KEY}

Sandbox exec via:  POST /toolbox/{sandboxId}/toolbox/process/execute
    Body: {"command": "..."}
    Response: {"exitCode": N, "result": "stdout+stderr"}
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config.settings import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Daytona API client helpers
# ---------------------------------------------------------------------------

DAYTONA_BASE_URL = "https://app.daytona.io/api"
_REQUEST_TIMEOUT = 30  # seconds for control-plane calls


def _daytona_headers() -> dict[str, str]:
    """Return auth headers for Daytona REST API."""
    api_key = settings.DAYTONA_API_KEY
    if not api_key:
        raise RuntimeError("DAYTONA_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _daytona_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = _REQUEST_TIMEOUT,
) -> dict[str, Any]:
    """Make an authenticated request to the Daytona REST API."""
    url = f"{DAYTONA_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method,
            url,
            headers=_daytona_headers(),
            json=json_body,
        )
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}


# ---------------------------------------------------------------------------
# Inline Python pipeline script injected into Daytona sandbox
# ---------------------------------------------------------------------------

PIPELINE_SCRIPT = r'''
import subprocess
import os
import json
import sys
import shutil
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Stage 1 - Extract frames from video
# ---------------------------------------------------------------------------

def extract_frames(video_path: str, output_dir: str, fps: float = 2.0) -> dict:
    """Extract frames at given fps, keeping only sharp ones (Laplacian variance)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Extract raw frames
    raw_dir = out / "_raw"
    raw_dir.mkdir(exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps}",
        str(raw_dir / "frame_%06d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"success": False, "error": f"FFmpeg failed: {result.stderr[-500:]}"}

    raw_frames = sorted(raw_dir.glob("frame_*.jpg"))
    if not raw_frames:
        return {"success": False, "error": "No frames extracted from video"}

    # Quality filter using Laplacian variance (sharpness check)
    SHARPNESS_THRESHOLD = 100
    kept = 0
    try:
        import cv2
        for frame_path in raw_frames:
            img = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            variance = cv2.Laplacian(img, cv2.CV_64F).var()
            if variance >= SHARPNESS_THRESHOLD:
                dest = out / frame_path.name
                shutil.copy2(frame_path, dest)
                kept += 1
        shutil.rmtree(raw_dir)
        if kept == 0:
            # All frames were blurry - keep all of them anyway
            for frame_path in raw_frames:
                shutil.copy2(frame_path, out / frame_path.name)
            kept = len(raw_frames)
    except ImportError:
        # cv2 not available - copy all frames without filtering
        for frame_path in raw_frames:
            shutil.copy2(frame_path, out / frame_path.name)
        kept = len(raw_frames)
        shutil.rmtree(raw_dir, ignore_errors=True)

    return {"success": True, "frame_count": kept}


# ---------------------------------------------------------------------------
# Stage 2 - Convert equirectangular -> 4 cubemap perspective faces
# ---------------------------------------------------------------------------

def convert_360_to_cubemap(frames_dir: str, output_dir: str) -> dict:
    """Convert 360° equirectangular frames to multi-yaw perspective faces.

    Uses 6 yaw directions (every 60°) at 90° HFOV so COLMAP gets full-room
    coverage. Previous 4-face-only path under-constrained indoor SfM.
    Also normalizes non-2:1 YouTube equirect containers to 2:1.
    """
    try:
        import py360convert
        import numpy as np
        from PIL import Image
    except ImportError:
        # Install on-the-fly if missing
        subprocess.run([sys.executable, "-m", "pip", "install", "py360convert", "Pillow"], check=True)
        import py360convert
        import numpy as np
        from PIL import Image

    frames_path = Path(frames_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 6 virtual cameras — better overlap for sequential matching than 4 faces
    YAWS = [0, 60, 120, 180, 240, 300]
    converted = 0

    for frame_file in sorted(frames_path.glob("frame_*.jpg")):
        stem = frame_file.stem
        pil_img = Image.open(frame_file).convert("RGB")
        # Force 2:1 equirect aspect (YouTube 360 often ships 16:9)
        if abs((pil_img.width / max(pil_img.height, 1)) - 2.0) > 0.1:
            target_h = max(pil_img.width // 2, 1)
            pil_img = pil_img.resize((pil_img.width, target_h), Image.Resampling.LANCZOS)
        if pil_img.width > 2048:
            pil_img = pil_img.resize((2048, 1024), Image.Resampling.LANCZOS)
        img = np.array(pil_img)
        # Mask nadir (camera operator) ~12%
        cut = int(img.shape[0] * 0.12)
        if cut > 0:
            img[-cut:, :] = 0
        h, w = img.shape[:2]
        face_size = max(min(w // 3, 768), 256)

        for yaw in YAWS:
            face_img = py360convert.e2p(
                img,
                fov_deg=(90, 75),
                u_deg=float(yaw),
                v_deg=0.0,
                out_hw=(face_size, int(face_size * 0.75)),
                in_rot_deg=0,
                mode="bilinear",
            )
            out_file = out_path / f"{stem}_y{yaw:03d}.jpg"
            Image.fromarray(face_img.astype(np.uint8)).save(out_file, quality=95)
        converted += 1

    return {"success": True, "frames_converted": converted, "faces_per_frame": len(YAWS)}


# ---------------------------------------------------------------------------
# Stage 3 - COLMAP SfM (CPU mode - slow but functional)
# ---------------------------------------------------------------------------

def run_colmap(images_dir: str, output_dir: str, use_gpu: bool = False) -> dict:
    """Run COLMAP feature extraction + exhaustive matching + sparse reconstruction."""
    out = Path(output_dir)
    sparse = out / "sparse"
    sparse.mkdir(parents=True, exist_ok=True)
    db = out / "colmap.db"

    gpu_flag = "1" if use_gpu else "0"

    # Feature extraction
    cmd_extract = [
        "colmap", "feature_extractor",
        "--database_path", str(db),
        "--image_path", images_dir,
        "--SiftExtraction.use_gpu", gpu_flag,
        # Prefer high-res features for 2K–4K equirect faces (old 800px cap hurt quality)
        "--SiftExtraction.max_image_size", "1600",
        "--SiftExtraction.max_num_features", "4096",
        "--SiftExtraction.num_threads", "4",
    ]
    r = subprocess.run(cmd_extract, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        return {"success": False, "error": f"COLMAP feature extraction failed: {r.stderr[-500:]}"}

    # Sequential matching (much faster for video/linear captures than exhaustive)
    cmd_match = [
        "colmap", "sequential_matcher",
        "--database_path", str(db),
        "--SiftMatching.use_gpu", gpu_flag,
        "--SequentialMatching.overlap", "15",
    ]
    r = subprocess.run(cmd_match, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        return {"success": False, "error": f"COLMAP matching failed: {r.stderr[-500:]}"}

    # Sparse reconstruction
    cmd_mapper = [
        "colmap", "mapper",
        "--database_path", str(db),
        "--image_path", images_dir,
        "--output_path", str(sparse),
        "--Mapper.ba_global_images_ratio", "1.4",  # Reduce bundle adjustment memory
        "--Mapper.ba_global_points_ratio", "1.4",
    ]
    r = subprocess.run(cmd_mapper, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        return {"success": False, "error": f"COLMAP mapping failed: {r.stderr[-500:]}"}

    return {"success": True}


# ---------------------------------------------------------------------------
# Stage 4 - GPU-gated Gaussian Splatting training
# ---------------------------------------------------------------------------

def check_gpu_and_train(
    colmap_dir: str,
    images_dir: str,
    output_dir: str,
    quality_preset: str = "balanced",
) -> dict:
    """
    Check for an NVIDIA GPU and train a Gaussian Splatting model.
    If no GPU found, return a GPU_REQUIRED error code.
    """
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        has_gpu = result.returncode == 0
    except FileNotFoundError:
        has_gpu = False

    if not has_gpu:
        return {
            "success": False,
            "error": "GPU_REQUIRED",
            "message": "NVIDIA GPU not available in this sandbox. Enable GPU access in Daytona dashboard.",
        }

    iters_map = {"fast": 5000, "balanced": 15000, "quality": 30000}
    max_iters = iters_map.get(quality_preset, 15000)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ns-train", "splatfacto",
        "--data", colmap_dir,
        "--output-dir", str(out),
        "--max-num-iterations", str(max_iters),
        "--pipeline.datamanager.images-on-gpu", "True",
        "--viewer.quit-on-train-completion", "True",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        return {"success": False, "error": f"Nerfstudio training failed: {r.stderr[-500:]}"}

    return {"success": True, "iterations": max_iters}


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def main():
    config_str = os.environ.get("SPLAT_CONFIG", "{}")
    config = json.loads(config_str)

    video_path = config.get("video_path", "/workspace/video.mp4")
    work_dir = config.get("work_dir", "/workspace/splat")
    is_360 = config.get("is_360_video", True)
    quality = config.get("quality_preset", "balanced")

    results = {}

    # Stage 1: Extract frames
    frames_dir = f"{work_dir}/frames"
    print(json.dumps({"stage": "extracting", "progress": 15}), flush=True)
    r1 = extract_frames(video_path, frames_dir, fps=2.0)
    results["extract"] = r1
    if not r1.get("success"):
        print(json.dumps({"stage": "failed", "progress": 15, "results": results}), flush=True)
        sys.exit(1)
    print(json.dumps({"stage": "extracting_done", "progress": 25, "frame_count": r1.get("frame_count", 0)}), flush=True)

    # Stage 2: Convert 360 -> cubemap (if applicable)
    images_for_colmap = frames_dir
    if is_360:
        cubemap_dir = f"{work_dir}/cubemap"
        print(json.dumps({"stage": "converting", "progress": 30}), flush=True)
        r2 = convert_360_to_cubemap(frames_dir, cubemap_dir)
        results["convert"] = r2
        if not r2.get("success"):
            print(json.dumps({"stage": "failed", "progress": 30, "results": results}), flush=True)
            sys.exit(1)
        images_for_colmap = cubemap_dir
        print(json.dumps({"stage": "converting_done", "progress": 40}), flush=True)

    # Stage 3: COLMAP SfM
    colmap_dir = f"{work_dir}/colmap"
    print(json.dumps({"stage": "sfm", "progress": 45}), flush=True)
    r3 = run_colmap(images_for_colmap, colmap_dir, use_gpu=False)
    results["colmap"] = r3
    if not r3.get("success"):
        print(json.dumps({"stage": "failed", "progress": 55, "results": results}), flush=True)
        sys.exit(1)
    print(json.dumps({"stage": "sfm_done", "progress": 60}), flush=True)

    # Stage 4: Zip data for Modal GPU processing
    print(json.dumps({"stage": "training", "progress": 65, "stage_message": "Preparing data for GPU..."}), flush=True)
    zip_path = f"{work_dir}/colmap_data.zip"
    try:
        import zipfile
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Zip images
            for root, dirs, files in os.walk(images_for_colmap):
                for f in files:
                    file_path = os.path.join(root, f)
                    arcname = os.path.relpath(file_path, work_dir)
                    zf.write(file_path, arcname)
            # Zip colmap output
            for root, dirs, files in os.walk(colmap_dir):
                for f in files:
                    file_path = os.path.join(root, f)
                    arcname = os.path.relpath(file_path, work_dir)
                    zf.write(file_path, arcname)
        results["zip"] = {"success": True, "path": zip_path}
    except Exception as e:
        results["zip"] = {"success": False, "error": str(e)}
        print(json.dumps({"stage": "failed", "progress": 65, "results": results}), flush=True)
        sys.exit(1)

    print(json.dumps({"stage": "ready_for_modal", "progress": 70, "zip_path": zip_path}), flush=True)


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Daytona sandbox lifecycle
# ---------------------------------------------------------------------------

async def create_sandbox(job_id: str) -> str:
    """
    Spin up a new Daytona sandbox and return its sandbox_id.

    The sandbox is provisioned with daytonaio/sandbox:0.6.0 which includes
    Python 3 and FFmpeg pre-installed.
    """
    body: dict[str, Any] = {
        "snapshot": "daytonaio/sandbox:0.6.0",
        "labels": {
            "job_id": job_id,
            "service": "splat-lab",
        },
        "env": {},
        # NOTE: Cannot specify cpu/memory/disk when using a snapshot.
        # Daytona uses the snapshot's defaults. To scale up, use a
        # vm-class sandbox (e.g. "daytona-large") without a snapshot.
    }
    try:
        resp = await _daytona_request("POST", "/sandbox", json_body=body)
        sandbox_id: str = resp.get("id", "")
        if not sandbox_id:
            raise RuntimeError(f"No sandbox ID in response: {resp}")
        logger.info("Daytona sandbox created", extra={"sandbox_id": sandbox_id, "job_id": job_id})
        return sandbox_id
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Failed to create Daytona sandbox: %s %s",
            exc.response.status_code,
            exc.response.text,
            extra={"job_id": job_id},
        )
        raise


async def exec_in_sandbox(sandbox_id: str, command: str, *, timeout: float = 600) -> dict[str, Any]:
    """Execute a shell command inside the sandbox via the Toolbox API.

    Daytona exec endpoint:
        POST /toolbox/{sandboxId}/toolbox/process/execute
        Body: {"command": "..."}
        Response: {"exitCode": N, "result": "stdout+stderr"}
    """
    body: dict[str, Any] = {"command": command}
    url = f"{DAYTONA_BASE_URL}/toolbox/{sandbox_id}/toolbox/process/execute"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=_daytona_headers(), json=body)
            resp.raise_for_status()
            return resp.json() if resp.content else {}
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Daytona exec failed in sandbox %s: %s",
            sandbox_id,
            exc.response.text,
        )
        raise


async def get_sandbox_status(sandbox_id: str) -> dict[str, Any]:
    """Fetch current status of a Daytona sandbox."""
    return await _daytona_request("GET", f"/sandbox/{sandbox_id}")


async def destroy_sandbox(sandbox_id: str) -> None:
    """Delete/destroy a Daytona sandbox."""
    try:
        await _daytona_request("DELETE", f"/sandbox/{sandbox_id}")
        logger.info("Daytona sandbox destroyed", extra={"sandbox_id": sandbox_id})
    except httpx.HTTPStatusError as exc:
        # 404 means it's already gone; log but don't raise
        if exc.response.status_code != 404:
            logger.warning(
                "Failed to destroy sandbox %s: %s",
                sandbox_id,
                exc.response.text,
            )


# ---------------------------------------------------------------------------
# Supabase job record helpers
# ---------------------------------------------------------------------------

def _supabase_client():
    """Return a synchronous supabase-py client."""
    from supabase import create_client  # type: ignore[import]

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)


async def _update_job(job_id: str, updates: dict[str, Any]) -> None:
    """Persist job field updates to the splat_jobs Supabase table (run in thread)."""
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _supabase_client().table("splat_jobs").update(updates).eq("id", job_id).execute(),
    )


# ---------------------------------------------------------------------------
# Main pipeline orchestrator
# ---------------------------------------------------------------------------

async def run_pipeline(job_id: str, job_config: dict[str, Any]) -> None:
    """
    Async orchestrator that:
    1. Provisions a Daytona sandbox.
    2. Installs dependencies.
    3. Downloads video from Supabase Storage into the sandbox.
    4. Uploads the pipeline script.
    5. Runs stages 1-3 (and stage 4 with GPU-gating).
    6. Updates the splat_jobs record at each stage transition.

    CPU-only path: stages 1-3 complete; stage 4 sets status='failed' with
    GPU_REQUIRED message.  Once GPU is available, stage 4 will succeed.
    """
    sandbox_id: str | None = None

    try:
        # -- Create sandbox ---------------------------------------------------
        await _update_job(job_id, {"status": "pending", "progress": 5, "stage_message": "Provisioning sandbox..."})
        sandbox_id = await create_sandbox(job_id)
        await _update_job(job_id, {"daytona_sandbox_id": sandbox_id, "progress": 8, "stage_message": "Sandbox ready, installing deps..."})

        # -- Wait for sandbox to be fully ready --------------------------------
        for _ in range(10):
            status_resp = await get_sandbox_status(sandbox_id)
            if status_resp.get("state") == "started":
                break
            await asyncio.sleep(2)

        # -- Install extra deps (cv2, py360convert, colmap) ---------------------
        install_cmd = (
            "sudo apt-get update -qq && "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq colmap && "
            "pip install -q py360convert Pillow opencv-python-headless 2>&1 | tail -3"
        )
        await exec_in_sandbox(sandbox_id, install_cmd, timeout=120)
        await _update_job(job_id, {"progress": 10, "stage_message": "Dependencies installed"})

        # -- Download video from Supabase Storage into sandbox -----------------
        storage_path = job_config.get("video_path", "")
        bucket = settings.SPLAT_BUCKET_NAME or "splat-jobs"
        supabase_url = settings.SUPABASE_URL
        supabase_key = settings.SUPABASE_SECRET_KEY

        # Generate a download URL and use curl inside the sandbox
        download_url = f"{supabase_url}/storage/v1/object/{bucket}/{storage_path}"
        download_cmd = (
            f'mkdir -p /home/daytona/workspace && '
            f'curl -sL -o /home/daytona/workspace/video.mp4 '
            f'-H "apikey: {supabase_key}" '
            f'-H "Authorization: Bearer {supabase_key}" '
            f'"{download_url}"'
        )
        dl_result = await exec_in_sandbox(sandbox_id, download_cmd, timeout=120)
        dl_exit = dl_result.get("exitCode", 1)
        if dl_exit != 0:
            raise RuntimeError(f"Failed to download video into sandbox: {dl_result.get('result', '')[:300]}")

        # Verify file exists
        verify_result = await exec_in_sandbox(sandbox_id, "ls -la /home/daytona/workspace/video.mp4")
        logger.info("Video download verified: %s", verify_result.get("result", ""))

        await _update_job(job_id, {"status": "extracting", "progress": 12, "stage_message": "Video downloaded, starting extraction..."})

        # -- Upload pipeline script into sandbox --------------------------------
        write_cmd = f"cat > /home/daytona/workspace/pipeline.py << 'ENDOFSCRIPT'\n{PIPELINE_SCRIPT}\nENDOFSCRIPT"
        await exec_in_sandbox(sandbox_id, write_cmd)

        # -- Run pipeline -------------------------------------------------------
        await _update_job(job_id, {"status": "extracting", "progress": 15, "stage_message": "Extracting frames..."})

        splat_config = json.dumps({
            "video_path": "/home/daytona/workspace/video.mp4",
            "work_dir": "/home/daytona/workspace/splat",
            "is_360_video": job_config.get("is_360_video", True),
            "quality_preset": job_config.get("quality_preset", "balanced"),
        })

        # Run pipeline in background to avoid Cloudflare 504 Gateway Timeout (100s)
        run_cmd = f'nohup env SPLAT_CONFIG=\'{splat_config}\' python3 /home/daytona/workspace/pipeline.py > /home/daytona/workspace/pipeline.log 2>&1 &'
        await exec_in_sandbox(sandbox_id, run_cmd)
        
        # Poll for completion
        output = ""
        exit_code = 0
        # Wait up to 1 hour
        for _ in range(720):
            await asyncio.sleep(5)
            # Check if process is still running
            ps_res = await exec_in_sandbox(sandbox_id, "pgrep -f 'python3 /home/daytona/workspace/pipeline.py'")
            # Fetch latest logs
            log_res = await exec_in_sandbox(sandbox_id, "cat /home/daytona/workspace/pipeline.log")
            output = log_res.get("result", "")
            
            if not ps_res.get("result", "").strip():
                # Process finished
                break
                
        # Parse the last JSON line from stdout for final stage/progress info
        logger.info(
            "Pipeline exec finished: output_len=%d",
            len(output),
            extra={"job_id": job_id},
        )

        final_stage_info = _parse_pipeline_output(output)
        stage = final_stage_info.get("stage", "failed")
        progress = final_stage_info.get("progress", 70)

        if stage == "failed":
            results = final_stage_info.get("results", {})
            err_msg = _extract_error(final_stage_info) or output[-500:]
            await _update_job(
                job_id,
                {
                    "status": "failed",
                    "progress": progress,
                    "stage_message": f"Pipeline failed at stage: {stage}",
                    "error_message": err_msg or f"Unknown pipeline error. Exit code: {exit_code}",
                },
            )
        elif stage == "ready_for_modal":
            zip_path = final_stage_info.get("zip_path", "/home/daytona/workspace/splat/colmap_data.zip")
            await _update_job(job_id, {"status": "compressing", "progress": 70, "stage_message": "Uploading data to GPU cluster..."})
            
            # Upload the zip using curl inside the sandbox
            upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{storage_path}/colmap_data.zip"
            upload_cmd = (
                f'curl -sL -X POST '
                f'-H "apikey: {supabase_key}" '
                f'-H "Authorization: Bearer {supabase_key}" '
                f'-H "Content-Type: application/zip" '
                f'--data-binary "@{zip_path}" '
                f'"{upload_url}"'
            )
            up_result = await exec_in_sandbox(sandbox_id, upload_cmd, timeout=300)
            
            if up_result.get("exitCode", 1) != 0:
                await _update_job(job_id, {"status": "failed", "error_message": f"Failed to upload zip to Supabase: {up_result.get('result', '')[-500:]}"})
            else:
                # Spawn Modal GPU worker
                try:
                    from app.services.modal_worker import train_splat
                    train_splat.spawn(job_id, storage_path, job_config.get("quality_preset", "balanced"))
                    logger.info("Spawned modal worker for job %s", job_id)
                except Exception as e:
                    logger.error("Failed to spawn modal worker: %s", e)
                    await _update_job(job_id, {"status": "failed", "error_message": f"Failed to spawn GPU worker: {e}"})
        else:
            # Intermediate stage reported but exec returned
            await _update_job(
                job_id,
                {
                    "status": "failed",
                    "progress": progress,
                    "stage_message": f"Pipeline stopped unexpectedly at stage: {stage}",
                    "error_message": f"Exit code: {exit_code}. Output: {output[-500:]}",
                },
            )

    except Exception as exc:
        logger.error("Pipeline orchestration failed for job %s: %s", job_id, exc, exc_info=True)
        await _update_job(
            job_id,
            {
                "status": "failed",
                "progress": 0,
                "stage_message": "Orchestration error",
                "error_message": str(exc)[:1000],
            },
        )
    finally:
        if sandbox_id:
            try:
                await destroy_sandbox(sandbox_id)
            except Exception as cleanup_exc:
                logger.warning("Sandbox cleanup failed: %s", cleanup_exc)


def _parse_pipeline_output(output: str) -> dict[str, Any]:
    """Extract the last valid JSON line from pipeline stdout."""
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"stage": "failed", "progress": 0}


def _extract_error(stage_info: dict[str, Any]) -> str | None:
    results = stage_info.get("results", {})
    for key in ("train", "colmap", "convert", "extract"):
        r = results.get(key, {})
        if isinstance(r, dict) and not r.get("success"):
            return r.get("error") or r.get("message")
    return None
