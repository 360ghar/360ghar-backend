"""
AI + geometry multi-view augmentation for sparse 360 room clips.

Problem
-------
Short walkthrough clips lack parallax → COLMAP/GS underfits → unreadable rooms.
Cuboid clip and crude floor disks cannot invent Matterport-level detail.

Idea (industry + research)
--------------------------
1. **Geometry-true free views** from equirectangular: dense yaw×pitch grid
   (correct spherical projection — free extra angles, zero hallucination).
2. **Parallax synthesis via depth**: monocular depth → reproject to slightly
   translated cameras → fill disocclusions (Mode-GS / depth-anchored 3DGS style).
3. **AI multi-angle expansion** (optional): conditioned image models generate
   additional levels/angles from real frames when depth warp is insufficient.
   Used as *extra* observations, not the only source of truth.

This module implements (1) fully, (2) with a lightweight depth proxy + warp
(full Depth-Anything runs on Modal GPU), and (3) as a Gemini/OpenAI-ready hook.

Output: a flat folder of JPGs ready for ns-process-data / COLMAP.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


@dataclass
class AugmentConfig:
    """Controls how many synthetic observations we create."""

    # equirect sample rate
    fps: float = 2.0
    max_keyframes: int = 24
    # spherical free views (math-correct)
    yaws_deg: tuple[int, ...] = (0, 45, 90, 135, 180, 225, 270, 315)
    pitches_deg: tuple[int, ...] = (-40, -20, 0, 20, 35)
    h_fov: int = 85
    v_fov: int = 70
    face_w: int = 768
    face_h: int = 576
    # skip dense pitch×yaw for every keyframe if too many — subsample
    max_total_images: int = 280
    # small virtual baseline (meters, relative) for parallax synthesis
    baseline_frac: float = 0.04  # fraction of image width as parallax shift
    parallax_dirs: tuple[str, ...] = ("left", "right", "forward")
    # AI expansion
    use_ai_views: bool = False
    ai_views_per_keyframe: int = 2
    ai_prompts: tuple[str, ...] = (
        "Same room, camera higher near ceiling looking slightly down, photoreal, no people",
        "Same room, camera lower near floor looking slightly up, photoreal, no people",
        "Same room, camera stepped 1 meter toward the far wall, photoreal, no people",
    )


@dataclass
class AugmentReport:
    keyframes: int = 0
    spherical_views: int = 0
    parallax_views: int = 0
    ai_views: int = 0
    output_dir: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "keyframes": self.keyframes,
            "spherical_views": self.spherical_views,
            "parallax_views": self.parallax_views,
            "ai_views": self.ai_views,
            "total": self.spherical_views + self.parallax_views + self.ai_views,
            "output_dir": self.output_dir,
            "notes": self.notes,
        }


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def extract_equirect_keyframes(
    video_path: Path,
    out_dir: Path,
    *,
    fps: float = 2.0,
    max_frames: int = 24,
) -> list[Path]:
    """Sample equirect frames; force 2:1 for proper sphere math."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "eq_%04d.jpg")
    # scale to 2:1 (YouTube 360 often 16:9)
    vf = f"fps={fps:.4f},scale=1920:960:flags=lanczos"
    r = _run(["ffmpeg", "-y", "-i", str(video_path), "-vf", vf, "-qscale:v", "2", pattern])
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg extract failed: {r.stderr[-500:]}")
    frames = sorted(out_dir.glob("eq_*.jpg"))
    if not frames:
        raise RuntimeError("No frames extracted")

    # sharpness keep
    if cv2 is not None and len(frames) > max_frames:
        scored = []
        for fp in frames:
            g = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
            if g is None:
                continue
            scored.append((float(cv2.Laplacian(g, cv2.CV_64F).var()), fp))
        scored.sort(key=lambda x: -x[0])
        frames = sorted([p for _, p in scored[:max_frames]], key=lambda p: p.name)
    else:
        # uniform subsample
        if len(frames) > max_frames:
            idx = np.linspace(0, len(frames) - 1, max_frames).astype(int)
            frames = [frames[i] for i in idx]

    return frames


def render_spherical_views(
    equi_path: Path,
    out_dir: Path,
    *,
    stem: str,
    yaws: tuple[int, ...],
    pitches: tuple[int, ...],
    h_fov: int,
    v_fov: int,
    w: int,
    h: int,
) -> list[Path]:
    """Math-correct free views via ffmpeg v360 (no AI hallucination)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for pitch in pitches:
        for yaw in yaws:
            # fewer yaws at extreme pitch
            if pitch != 0 and (yaw % 90) != 0:
                continue
            out = out_dir / f"{stem}_y{yaw:03d}_p{pitch:+03d}.jpg"
            vf = (
                f"v360=input=e:output=rectilinear:"
                f"yaw={yaw}:pitch={pitch}:roll=0:"
                f"h_fov={h_fov}:v_fov={v_fov}:w={w}:h={h}"
            )
            r = _run(["ffmpeg", "-y", "-i", str(equi_path), "-vf", vf, "-qscale:v", "2", str(out)])
            if r.returncode == 0 and out.exists():
                written.append(out)
    return written


def _depth_proxy_gray(gray: np.ndarray) -> np.ndarray:
    """
    Lightweight depth surrogate when Depth-Anything is unavailable.

    Indoor prior: darker + lower image regions often closer for handheld walks,
    center slightly farther. This is NOT metric — only used to invent *small*
    parallax shifts for multi-view density. Real training should swap in
    monocular foundation depth on GPU.
    """
    g = gray.astype(np.float32) / 255.0
    h, w = g.shape
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    # lower = closer, upper = farther; invert brightness a bit
    depth = 0.55 + 0.35 * (1.0 - g) + 0.25 * yy
    # edge-aware: high gradient → closer detail (furniture edges)
    if cv2 is not None:
        edges = cv2.Laplacian(g, cv2.CV_32F)
        depth = depth - 0.08 * np.clip(np.abs(edges), 0, 1)
    depth = np.clip(depth, 0.25, 1.5)
    return depth


def synthesize_parallax_views(
    rgb_path: Path,
    out_dir: Path,
    *,
    stem: str,
    baseline_frac: float = 0.04,
    dirs: tuple[str, ...] = ("left", "right", "forward"),
) -> list[Path]:
    """
    Warp a perspective image with a depth proxy to simulate small camera moves.
    Fills holes with inpaint when OpenCV is available.
    """
    if cv2 is None:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(str(rgb_path))
    if img is None:
        return []
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    depth = _depth_proxy_gray(gray)
    # map depth to disparity scale in pixels
    max_shift = baseline_frac * w

    written: list[Path] = []
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    for dname in dirs:
        # inverse depth disparity
        disp = (max_shift * (1.0 / depth)).astype(np.float32)
        if dname == "left":
            map_x = xx + disp
            map_y = yy
        elif dname == "right":
            map_x = xx - disp
            map_y = yy
        elif dname == "forward":
            # slight zoom from center (forward motion approx)
            cx, cy = w / 2.0, h / 2.0
            scale = 1.0 + 0.08 * (1.0 / depth)
            map_x = cx + (xx - cx) * scale
            map_y = cy + (yy - cy) * scale
        else:
            continue

        warped = cv2.remap(
            img, map_x, map_y, interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
        )
        # hole mask
        holes = (warped.sum(axis=2) == 0).astype(np.uint8) * 255
        if holes.any():
            warped = cv2.inpaint(warped, holes, 5, cv2.INPAINT_TELEA)
        out = out_dir / f"{stem}_par_{dname}.jpg"
        cv2.imwrite(str(out), warped, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        written.append(out)
    return written


def generate_ai_angle_views(
    reference_image: Path,
    out_dir: Path,
    *,
    stem: str,
    prompts: tuple[str, ...],
    max_views: int = 2,
) -> list[Path]:
    """
    Optional AI multi-angle expansion using configured vision/image APIs.

    These are *not* multi-view consistent by construction — use sparingly as
    extra texture hypotheses. Prefer spherical + parallax views for geometry.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Prefer Gemini if available
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return written

    try:
        import google.generativeai as genai
        from dotenv import load_dotenv

        load_dotenv()
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY", api_key))
    except Exception:
        return written

    # Many Gemini stacks only do vision understanding, not image out.
    # If image generation isn't available, we skip silently.
    try:
        # Try imagen-style if present in SDK; otherwise no-op
        model_name = os.environ.get("GEMINI_IMAGE_MODEL", "")
        if not model_name:
            return written  # no image model configured
        # Placeholder for when Imagen is wired:
        # response = genai.ImageGenerationModel(model_name).generate_images(...)
        _ = (reference_image, prompts, max_views, stem)
        return written
    except Exception:
        return written


def augment_video_to_images(
    video_path: Path | str,
    output_dir: Path | str,
    config: Optional[AugmentConfig] = None,
) -> AugmentReport:
    """
    Full local augmentation: keyframes → spherical grid → parallax warps → optional AI.
    """
    config = config or AugmentConfig()
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    equi_dir = output_dir / "_equi"
    if images_dir.exists():
        import shutil

        shutil.rmtree(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    report = AugmentReport(output_dir=str(output_dir))

    frames = extract_equirect_keyframes(
        video_path, equi_dir, fps=config.fps, max_frames=config.max_keyframes
    )
    report.keyframes = len(frames)
    report.notes.append(f"keyframes={len(frames)}")

    # budget spherical views
    budget = config.max_total_images
    for i, eq in enumerate(frames):
        if report.spherical_views >= budget:
            break
        stem = f"k{i:03d}"
        views = render_spherical_views(
            eq,
            images_dir,
            stem=stem,
            yaws=config.yaws_deg,
            pitches=config.pitches_deg,
            h_fov=config.h_fov,
            v_fov=config.v_fov,
            w=config.face_w,
            h=config.face_h,
        )
        report.spherical_views += len(views)

        # parallax from a few horizon faces only
        horizon = [v for v in views if "_p+00" in v.name or "_p+000" in v.name or "_p+00" in v.stem]
        # naming is p+00 or p+000 — we used {pitch:+03d} so p+00 for 0
        horizon = [v for v in views if "p+00" in v.name or "p+000" in v.name]
        if not horizon:
            horizon = views[:2]
        for hv in horizon[:2]:
            if report.spherical_views + report.parallax_views >= budget:
                break
            pviews = synthesize_parallax_views(
                hv,
                images_dir,
                stem=hv.stem,
                baseline_frac=config.baseline_frac,
                dirs=config.parallax_dirs,
            )
            report.parallax_views += len(pviews)

        if config.use_ai_views and horizon:
            ai = generate_ai_angle_views(
                horizon[0],
                images_dir,
                stem=f"{stem}_ai",
                prompts=config.ai_prompts,
                max_views=config.ai_views_per_keyframe,
            )
            report.ai_views += len(ai)

    # write manifest
    manifest = {
        "video": str(video_path),
        "config": {
            "fps": config.fps,
            "yaws": config.yaws_deg,
            "pitches": config.pitches_deg,
            "max_total_images": config.max_total_images,
        },
        "report": report.as_dict(),
    }
    (output_dir / "augment_manifest.json").write_text(json.dumps(manifest, indent=2))
    report.notes.append(f"total_images={report.as_dict()['total']}")
    return report


def estimate_clip_parallax_score(video_path: Path | str, sample_fps: float = 3.0) -> dict[str, float]:
    """
    Quick gate: is this clip worth COLMAP, or must use depth-prior/AI path?

    Returns mean optical-flow magnitude (higher = more translation/rotation).
    """
    if cv2 is None:
        return {"flow_mean": -1.0, "n_pairs": 0, "verdict": "unknown_no_cv2"}

    video_path = Path(video_path)
    tmp = Path("/tmp/parallax_probe")
    tmp.mkdir(exist_ok=True)
    for p in tmp.glob("*.jpg"):
        p.unlink()
    _run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"fps={sample_fps},scale=480:-1",
        "-qscale:v", "5",
        str(tmp / "f_%03d.jpg"),
    ])
    frames = sorted(tmp.glob("f_*.jpg"))
    if len(frames) < 2:
        return {"flow_mean": 0.0, "n_pairs": 0, "verdict": "too_short"}

    mags = []
    prev = cv2.imread(str(frames[0]), cv2.IMREAD_GRAYSCALE)
    for fp in frames[1:]:
        cur = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
        if prev is None or cur is None:
            continue
        flow = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        mags.append(float(np.median(mag)))
        prev = cur
    mean = float(np.mean(mags)) if mags else 0.0
    # empirical thresholds for 480p
    if mean < 0.8:
        verdict = "static_use_depth_prior"
    elif mean < 2.5:
        verdict = "weak_parallax_augment_heavily"
    else:
        verdict = "ok_for_colmap"
    return {"flow_mean": mean, "n_pairs": len(mags), "verdict": verdict}


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    clip = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "/Users/chiragsingh/Desktop/360ghar-backend/test_clips/room1.mp4"
    )
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/augment_room1")
    print("parallax", estimate_clip_parallax_score(clip))
    rep = augment_video_to_images(clip, out, AugmentConfig(max_keyframes=12, max_total_images=160))
    print(json.dumps(rep.as_dict(), indent=2))
