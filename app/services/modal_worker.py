"""
Gaussian Splat Lab – Modal GPU worker.

Pipeline for 360° equirectangular walkthrough video → .splat:

1. Frame extraction (sharpness-filtered)
2. Multi-perspective unwrapping from each equirectangular frame
   (N virtual cameras around the sphere — required for indoor GS)
3. COLMAP SfM via nerfstudio ns-process-data
4. splatfacto training
5. Export PLY → antimatter15 .splat

Why previous runs looked like abstract art:
- Only one rectilinear crop (yaw=0, 120° FOV) was taken from each 360 frame,
  so COLMAP never saw full room coverage and poses were under-constrained.
- Separate room splats were ICP-merged without shared geometry (doors only
  overlap a little) → random orientation soup.
- 16:9 YouTube equirectangular packing needs explicit equirect handling.

Research basis (practical industry + papers):
- Cubemap / multi-yaw virtual cameras from equirect → COLMAP (standard 360→3DGS)
- SphereSfM / panorama rig SfM (zero-baseline virtual rig)
- Joint sequential SfM across connected room clips for doorway continuity
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import modal

app = modal.App("splat-lab-gpu")

image = (
    modal.Image.from_registry("pytorch/pytorch:2.1.2-cuda11.8-cudnn8-devel")
    .env(
        {
            "DEBIAN_FRONTEND": "noninteractive",
            "TZ": "Etc/UTC",
            "QT_QPA_PLATFORM": "offscreen",
        }
    )
    .apt_install(
        "git",
        "build-essential",
        "ninja-build",
        "ffmpeg",
        "libgl1-mesa-glx",
        "libglib2.0-0",
        "libx11-6",
        "colmap",
        "xvfb",
    )
    .pip_install(
        "numpy<2.0.0",
        "nerfstudio==1.1.3",
        "gsplat==1.0.0",
        "plyfile",
        "opencv-python-headless",
        "supabase",
        "httpx",
    )
)

vol = modal.Volume.from_name("splat-lab-data", create_if_missing=True)

# Virtual cameras: yaw × pitch grid.
# Horizon-only yaws leave floor/ceiling empty (user-visible). Add mild pitch
# looks so SfM/GS see tile floors and false ceilings without eating the nadir person.
DEFAULT_YAWS = (0, 60, 120, 180, 240, 300)
DEFAULT_PITCHES = (-35, 0, 28)  # down (floor), horizon, up (ceiling)
DEFAULT_H_FOV = 90
DEFAULT_V_FOV = 70


def _run(cmd: list[str], *, check: bool = True, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=check, cwd=cwd, text=True, capture_output=False)


def _probe_duration(video_path: Path) -> float:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(r.stdout.strip() or "10.0")
    except ValueError:
        return 10.0


def _is_likely_360(video_path: Path) -> bool:
    """Detect equirectangular spherical video via ffprobe side data or 2:1 aspect."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video_path)],
        capture_output=True,
        text=True,
    )
    text = r.stdout or ""
    if "equirectangular" in text.lower() or "Spherical Mapping" in text:
        return True
    # Aspect heuristic
    try:
        import json

        data = json.loads(text)
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                w, h = int(s["width"]), int(s["height"])
                if h > 0 and abs((w / h) - 2.0) < 0.15:
                    return True
    except Exception:
        pass
    return False


def _mask_transient_and_mirrors(im):
    """
    Light-touch suppression of people + mirror-like strips on equirect frames.

    IMPORTANT: never paint large black regions — that starves COLMAP of features
    (v2 retrain collapsed to ~13k gaussians when masks were too aggressive).
    Prefer soft darken / small lower-band only.
    """
    import cv2
    import numpy as np

    out = im.copy()
    h, w = out.shape[:2]

    # --- People: HOG only, soft darken (not hard black), mid band only ---
    try:
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        y0, y1 = int(h * 0.30), int(h * 0.80)
        band = out[y0:y1]
        scale = 640.0 / max(band.shape[1], 1)
        small = cv2.resize(band, (640, max(1, int(band.shape[0] * scale))))
        rects, weights = hog.detectMultiScale(
            small, winStride=(8, 8), padding=(16, 16), scale=1.08
        )
        for i, (x, y, bw, bh) in enumerate(rects):
            # only high-confidence detections
            conf = float(weights[i]) if weights is not None and i < len(weights) else 1.0
            if conf < 0.4:
                continue
            x1 = int(x / scale)
            y1b = int(y / scale) + y0
            x2 = int((x + bw) / scale)
            y2 = int((y + bh) / scale) + y0
            # shrink box — avoid eating furniture
            mx = int(0.15 * (x2 - x1))
            my = int(0.10 * (y2 - y1b))
            x1, x2 = max(0, x1 + mx), min(w, x2 - mx)
            y1b, y2 = max(0, y1b + my), min(h, y2 - my)
            roi = out[y1b:y2, x1:x2]
            if roi.size:
                out[y1b:y2, x1:x2] = (roi.astype(np.float32) * 0.25).astype(np.uint8)
    except Exception:
        pass

    # Skin: only lower 25% (operator hands/arms), soft darken large blobs only
    try:
        y0, y1 = int(h * 0.72), int(h * 0.95)
        roi = out[y0:y1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        m1 = cv2.inRange(hsv, (0, 40, 70), (20, 160, 255))
        m2 = cv2.inRange(hsv, (165, 40, 70), (180, 160, 255))
        skin = cv2.morphologyEx(m1 | m2, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        cnts, _ = cv2.findContours(skin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mask = np.zeros(skin.shape, np.uint8)
        min_area = skin.shape[0] * skin.shape[1] * 0.01  # larger threshold
        for c in cnts:
            if cv2.contourArea(c) >= min_area:
                cv2.drawContours(mask, [c], -1, 255, -1)
        if mask.any():
            blended = roi.astype(np.float32)
            blended[mask > 0] *= 0.2
            out[y0:y1] = blended.astype(np.uint8)
    except Exception:
        pass

    # Mirrors: very conservative — only extreme specular vertical strips, dim not kill
    try:
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        bright = (hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 40)
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 160)
        col_e = edges.sum(axis=0).astype(np.float32)
        col_e = col_e / (col_e.max() + 1e-6)
        for x in range(0, w, 2):
            if col_e[x] > 0.75:
                x0, x1 = max(0, x - 3), min(w, x + 4)
                strip = bright[:, x0:x1]
                if strip.size and strip.mean() > 0.4:
                    out[:, x0:x1] = (out[:, x0:x1].astype(np.float32) * 0.45).astype(np.uint8)
    except Exception:
        pass

    return out


def extract_multiview_frames(
    video_path: Path,
    images_dir: Path,
    *,
    target_frames: int,
    is_360: bool,
    yaws: tuple[int, ...] = DEFAULT_YAWS,
    pitches: tuple[int, ...] = DEFAULT_PITCHES,
    h_fov: int = DEFAULT_H_FOV,
    v_fov: int = DEFAULT_V_FOV,
    frame_prefix: str = "f",
    start_index: int = 0,
    apply_masks: bool = True,
    face_w: int = 768,
    face_h: int = 576,
    equi_max_w: int = 1920,
) -> int:
    """
    Extract frames and, for 360 video, unwrap multiple perspective faces per frame.

    For non-360: plain fps sampling into perspective images.
    Returns the number of image files written.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    duration = max(_probe_duration(video_path), 0.5)
    # Cap fps so we don't explode image count with many yaws
    base_fps = min(4.0, max(0.25, target_frames / duration))

    tmp_equi = images_dir.parent / f"_equi_{frame_prefix}"
    if tmp_equi.exists():
        shutil.rmtree(tmp_equi)
    tmp_equi.mkdir(parents=True, exist_ok=True)

    # 1) Sample equirectangular (or plain) frames. Normalize non-2:1 equirect
    # to proper 2:1 so v360 / COLMAP treat vertical FOV as full sphere.
    if is_360:
        # scale height to width/2 (2:1). YouTube 360 often ships 16:9 containers
        # with spherical metadata still covering full sphere → stretch vertical.
        eh = max(equi_max_w // 2, 512)
        vf = f"fps={base_fps:.4f},scale={equi_max_w}:{eh}:flags=lanczos"
    else:
        vf = f"fps={base_fps:.4f}"

    equi_pattern = str(tmp_equi / "eq_%05d.jpg")
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            vf,
            "-qscale:v",
            "2",
            equi_pattern,
        ]
    )

    equi_frames = sorted(tmp_equi.glob("eq_*.jpg"))
    if not equi_frames:
        raise RuntimeError(f"No frames extracted from {video_path}")

    # Drop blurry + high-shake frames (Laplacian + optical-flow magnitude)
    try:
        import cv2
        import numpy as np

        scored = []
        prev_gray = None
        for fp in equi_frames:
            img = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            sharp = float(cv2.Laplacian(img, cv2.CV_64F).var())
            shake = 0.0
            if prev_gray is not None:
                # Farneback flow → mean magnitude (hand-shake / fast spin)
                small_a = cv2.resize(prev_gray, (320, 160))
                small_b = cv2.resize(img, (320, 160))
                flow = cv2.calcOpticalFlowFarneback(
                    small_a, small_b, None, 0.5, 3, 15, 3, 5, 1.2, 0
                )
                mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
                shake = float(np.median(mag))
            prev_gray = img
            # High sharp, low shake wins
            score = sharp / (1.0 + 8.0 * shake)
            scored.append((score, sharp, shake, fp))

        if scored:
            # Reject worst shake quartile among candidates, then keep sharpest
            shakes = np.array([s[2] for s in scored], dtype=np.float64)
            shake_cut = float(np.percentile(shakes, 75)) if len(shakes) > 4 else 1e9
            filtered = [s for s in scored if s[2] <= shake_cut or s[1] > np.median([x[1] for x in scored])]
            if len(filtered) < max(target_frames // 2, 6):
                filtered = scored
            filtered.sort(key=lambda x: -x[0])
            keep_n = min(len(filtered), max(target_frames, 8))
            equi_frames = sorted([p for *_, p in filtered[:keep_n]], key=lambda p: p.name)
            print(
                f"Sharp+shake filter: kept {len(equi_frames)}/{len(scored)} "
                f"(shake_cut={shake_cut:.3f})",
                flush=True,
            )
    except Exception as e:
        print(f"Sharpness/shake filter skipped: {e}", flush=True)

    written = 0
    idx = start_index

    if not is_360:
        for fp in equi_frames:
            dest = images_dir / f"{frame_prefix}_{idx:05d}.jpg"
            shutil.copy2(fp, dest)
            idx += 1
            written += 1
        shutil.rmtree(tmp_equi, ignore_errors=True)
        return written

    # 2) Multi-yaw (/ optional pitch) perspective unwrap
    for fp in equi_frames:
        if apply_masks:
            try:
                import cv2
                import numpy as np

                im = cv2.imread(str(fp))
                if im is not None:
                    im = _mask_transient_and_mirrors(im)
                    h = im.shape[0]
                    # light nadir dim only (simple recipe skips this entire block)
                    cut = int(h * 0.08)
                    im[h - cut :, :] = (im[h - cut :, :].astype(np.float32) * 0.35).astype(np.uint8)
                    cv2.imwrite(str(fp), im, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            except Exception as e:
                print(f"mask skip {fp.name}: {e}", flush=True)

        for pitch in pitches:
            for yaw in yaws:
                # Fewer yaws when looking hard at floor/ceiling (overlap less needed)
                if pitch != 0 and yaw % 120 != 0:
                    continue
                out = images_dir / f"{frame_prefix}_{idx:05d}_y{yaw:03d}_p{pitch:+03d}.jpg"
                vf_face = (
                    f"v360=input=e:output=rectilinear:"
                    f"yaw={yaw}:pitch={pitch}:roll=0:"
                    f"h_fov={h_fov}:v_fov={v_fov}:"
                    f"w={face_w}:h={face_h}"
                )
                r = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(fp),
                        "-vf",
                        vf_face,
                        "-qscale:v",
                        "2",
                        str(out),
                    ],
                    capture_output=True,
                    text=True,
                )
                if r.returncode != 0 or not out.exists():
                    print(
                        f"WARN face extract failed yaw={yaw} pitch={pitch}: {r.stderr[-200:]}",
                        flush=True,
                    )
                    continue
                written += 1
        idx += 1

    shutil.rmtree(tmp_equi, ignore_errors=True)
    print(f"Wrote {written} perspective images from {video_path.name}", flush=True)
    return written


def run_colmap_ns(images_dir: Path, workspace: Path) -> None:
    """Structure-from-Motion via nerfstudio (COLMAP under the hood)."""
    cmd = [
        "xvfb-run",
        "-a",
        "ns-process-data",
        "images",
        "--data",
        str(images_dir),
        "--output-dir",
        str(workspace),
        "--matching-method",
        "sequential",
        "--num-downscales",
        "0",
    ]
    # Prefer GPU SIFT when available
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    last: list[str] = []
    for line in process.stdout:
        print(line, end="", flush=True)
        last.append(line)
        if len(last) > 80:
            last.pop(0)
    process.wait()
    if process.returncode != 0:
        # Fallback: exhaustive matching (more robust for sparse multi-yaw sets)
        print("Sequential matching failed/weak — retrying exhaustive...", flush=True)
        cmd_ex = [
            "xvfb-run",
            "-a",
            "ns-process-data",
            "images",
            "--data",
            str(images_dir),
            "--output-dir",
            str(workspace),
            "--matching-method",
            "exhaustive",
            "--num-downscales",
            "0",
        ]
        process2 = subprocess.Popen(cmd_ex, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert process2.stdout is not None
        for line in process2.stdout:
            print(line, end="", flush=True)
        process2.wait()
        if process2.returncode != 0:
            raise RuntimeError(
                f"ns-process-data failed (code {process2.returncode}): {''.join(last)[-1500:]}"
            )


def train_splatfacto(workspace: Path, output_dir: Path, max_steps: int) -> Path:
    """Train splatfacto; return path to config.yml."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ns-train",
        "splatfacto",
        "--data",
        str(workspace),
        "--output-dir",
        str(output_dir),
        "--max-num-iterations",
        str(max_steps),
        "--vis",
        "tensorboard",
        "--viewer.quit-on-train-completion",
        "True",
        "nerfstudio-data",
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"ns-train failed with code {process.returncode}")

    configs = list(output_dir.glob("**/config.yml"))
    if not configs:
        raise RuntimeError(f"No config.yml under {output_dir}")
    configs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return configs[0]


def export_ply_to_splat(config_yml: Path, workspace: Path, *, raw_only: bool = False) -> Path:
    """Export nerfstudio gaussian-splat PLY and convert to .splat binary.

    raw_only=True: light opacity filter only — no cuboid/shell/floor polish.
    """
    import numpy as np
    from plyfile import PlyData

    export_dir = workspace / "export"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    r = subprocess.run(
        [
            "ns-export",
            "gaussian-splat",
            "--load-config",
            str(config_yml),
            "--output-dir",
            str(export_dir),
        ],
        capture_output=True,
        text=True,
    )
    print(r.stdout, flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"ns-export failed: {r.stderr[-800:]}")

    ply_path = None
    for p in export_dir.rglob("*.ply"):
        ply_path = p
        break
    if ply_path is None:
        raise FileNotFoundError(f"No PLY in {export_dir}")

    plydata = PlyData.read(str(ply_path))
    v = plydata["vertex"]
    n = len(v)
    print(f"Converting {n} gaussians → .splat", flush=True)

    dt = np.dtype(
        [
            ("pos", "f4", 3),
            ("scale", "f4", 3),
            ("color", "u1", 4),
            ("rot", "u1", 4),
        ]
    )
    data = np.zeros(n, dtype=dt)
    data["pos"][:, 0] = np.asarray(v["x"], dtype=np.float32)
    data["pos"][:, 1] = np.asarray(v["y"], dtype=np.float32)
    data["pos"][:, 2] = np.asarray(v["z"], dtype=np.float32)

    # nerfstudio stores log-scale
    data["scale"][:, 0] = np.exp(np.asarray(v["scale_0"], dtype=np.float32))
    data["scale"][:, 1] = np.exp(np.asarray(v["scale_1"], dtype=np.float32))
    data["scale"][:, 2] = np.exp(np.asarray(v["scale_2"], dtype=np.float32))

    # DC spherical harmonics → RGB; opacity → alpha (sigmoid)
    SH_C0 = 0.28209479177387814
    data["color"][:, 0] = np.clip((0.5 + SH_C0 * np.asarray(v["f_dc_0"])) * 255, 0, 255)
    data["color"][:, 1] = np.clip((0.5 + SH_C0 * np.asarray(v["f_dc_1"])) * 255, 0, 255)
    data["color"][:, 2] = np.clip((0.5 + SH_C0 * np.asarray(v["f_dc_2"])) * 255, 0, 255)
    data["color"][:, 3] = np.clip((1.0 / (1.0 + np.exp(-np.asarray(v["opacity"])))) * 255, 0, 255)

    rots = np.stack(
        [
            np.asarray(v["rot_0"], dtype=np.float32),
            np.asarray(v["rot_1"], dtype=np.float32),
            np.asarray(v["rot_2"], dtype=np.float32),
            np.asarray(v["rot_3"], dtype=np.float32),
        ],
        axis=1,
    )
    norms = np.linalg.norm(rots, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-8)
    rots = rots / norms
    data["rot"] = np.clip(rots * 128.0 + 128.0, 0, 255).astype(np.uint8)

    # Light opacity / scale gate only
    alpha = data["color"][:, 3]
    scales = data["scale"]
    keep = (alpha > 8) & (np.max(scales, axis=1) > 1e-6) & (np.max(scales, axis=1) < 1.5)
    data = data[keep]
    print(f"After alpha/scale: {len(data)}/{n}", flush=True)

    raw_path = workspace / "splat_raw.splat"
    raw_path.write_bytes(data.tobytes())
    print(f"Wrote raw {raw_path} ({len(data)} gaussians)", flush=True)

    if raw_only:
        print("raw_only=True — skipping cuboid/shell/floor polish", flush=True)
        splat_path = workspace / "splat.splat"
        splat_path.write_bytes(data.tobytes())
        return splat_path

    # Optional closed-room cleanup (off for simple/raw recipe)
    try:
        if len(data) >= 40_000:
            try:
                from app.services.splat_cleanup import clean_room_splat

                data, report = clean_room_splat(
                    data, aggressive=False, add_shell=False, align_floor=True
                )
                print(f"Room cleanup: {report.as_dict()}", flush=True)
            except Exception as e1:
                print(f"Package cleanup unavailable ({e1}); inline mild cuboid", flush=True)
                data = _inline_cuboid_cleanup(data, aggressive=False)
        else:
            print(f"Sparse model ({len(data)}) — mild cuboid only", flush=True)
            data = _inline_cuboid_cleanup(data, aggressive=False)
    except Exception as e:
        print(f"Cleanup failed, exporting raw: {e}", flush=True)

    splat_path = workspace / "splat.splat"
    splat_path.write_bytes(data.tobytes())
    return splat_path


def _inline_cuboid_cleanup(data, aggressive: bool = False):
    """Fallback closed-room filter when splat_cleanup module is not on the worker."""
    import numpy as np

    if len(data) < 50:
        return data
    pos = data["pos"]
    a = data["color"][:, 3]
    smax = data["scale"].max(axis=1)
    min_a = 18 if aggressive else 8
    max_s = 0.28 if aggressive else 0.55
    keep = (a >= min_a) & (smax <= max_s)
    data = data[keep]
    pos = data["pos"]
    lo_p, hi_p = (3, 97) if aggressive else (1, 99)
    lo = np.percentile(pos, lo_p, axis=0)
    hi = np.percentile(pos, hi_p, axis=0)
    span = np.maximum(hi - lo, 1e-3)
    pad = 0.03 if aggressive else 0.08
    lo = lo - pad * span
    hi = hi + pad * span
    keep = np.all((pos >= lo) & (pos <= hi), axis=1)
    data = data[keep]
    center = (lo + hi) * 0.5
    data = data.copy()
    data["pos"] = data["pos"] - center.astype(np.float32)
    print(f"Inline cuboid(agg={aggressive}): kept {len(data)}, extent={(hi-lo)}", flush=True)
    return data


def _update_job(sb, job_id: str, **fields) -> None:
    if not job_id or job_id.startswith("local-"):
        return
    try:
        sb.table("splat_jobs").update(fields).eq("id", job_id).execute()
    except Exception as e:
        print(f"job update skipped: {e}", flush=True)


@app.function(
    gpu="A10G",
    memory=32768,
    image=image,
    timeout=14400,  # whole-house pro 360 can need long COLMAP + train
    secrets=[modal.Secret.from_name("supabase-secret")],
    volumes={"/data": vol},
)
def train_splat(
    job_id: str,
    storage_path: str,
    quality_preset: str = "balanced",
    local_vol_path: Optional[str] = None,
    force_360: Optional[bool] = None,
    recipe: str = "default",
):
    """
    Main entry: download video(s), multi-view extract, COLMAP, train, export .splat.

    recipe:
      - "simple": short-clip raw path — horizon yaws, few frames, no polish.
      - "housetour": full pro 360 tour — denser equirect sampling, horizon yaws
        only (no multi-pitch overload), high face res, raw export. For smooth
        real-estate 360 masters (e.g. HouseTour-class capture).
      - "default": multi-pitch + light masks + optional cuboid polish.
    """
    from supabase import create_client
    import httpx

    recipe_l = (recipe or "default").lower()
    simple = recipe_l in ("simple", "raw", "old")
    housetour = recipe_l in ("housetour", "pro", "full", "whole")

    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_SECRET_KEY", "")
    bucket = os.environ.get("SPLAT_BUCKET_NAME", "splat-jobs")
    sb = create_client(sb_url, sb_key) if sb_url and sb_key else None

    _update_job(
        sb,
        job_id,
        status="extracting",
        progress=5,
        stage_message=f"Preparing workspace (recipe={recipe})...",
    )

    persistent = Path(f"/data/{job_id}")
    # Always fresh workspace for simple retrain (never reuse broken perfect jobs)
    if persistent.exists():
        print(f"Wiping workspace {persistent}", flush=True)
        shutil.rmtree(persistent, ignore_errors=True)
    persistent.mkdir(parents=True, exist_ok=True)

    workspace = Path("/workspace/data")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    # ---- Acquire videos ----
    video_paths: list[Path] = []
    if local_vol_path:
        vol_paths = [p.strip() for p in local_vol_path.split(",") if p.strip()]
        for i, vp in enumerate(vol_paths):
            src = Path(vp)
            if not src.is_absolute():
                src = Path("/data") / vp
            if not src.exists():
                # try under /data/clips
                alt = Path("/data/clips") / Path(vp).name
                if alt.exists():
                    src = alt
            if not src.exists():
                err = f"Local volume video not found: {vp}"
                _update_job(sb, job_id, status="failed", error_message=err)
                return {"success": False, "error": err}
            # Preserve real extension (webm/mp4) — do not force .mp4 on VP9
            dest = workspace / f"video_{i}{src.suffix or '.mp4'}"
            shutil.copy2(src, dest)
            video_paths.append(dest)
            print(f"Using volume video: {src} -> {dest}", flush=True)
    else:
        storage_paths = [p.strip() for p in storage_path.split(",") if p.strip()]
        for i, spath in enumerate(storage_paths):
            dest = workspace / f"video_{i}.mp4"
            print(f"Downloading {spath}...", flush=True)
            try:
                # Prefer authenticated download (private buckets)
                url = f"{sb_url}/storage/v1/object/{bucket}/{spath}"
                with httpx.stream(
                    "GET",
                    url,
                    headers={
                        "apikey": sb_key,
                        "Authorization": f"Bearer {sb_key}",
                    },
                    timeout=600.0,
                    follow_redirects=True,
                ) as r:
                    if r.status_code == 404:
                        # public fallback
                        url = f"{sb_url}/storage/v1/object/public/{bucket}/{spath}"
                        with httpx.stream("GET", url, timeout=600.0, follow_redirects=True) as r2:
                            r2.raise_for_status()
                            with open(dest, "wb") as f:
                                for chunk in r2.iter_bytes(8192):
                                    f.write(chunk)
                    else:
                        r.raise_for_status()
                        with open(dest, "wb") as f:
                            for chunk in r.iter_bytes(8192):
                                f.write(chunk)
                video_paths.append(dest)
            except Exception as e:
                err = f"Failed to download video {spath}: {e}"
                _update_job(sb, job_id, status="failed", error_message=err)
                return {"success": False, "error": err}

    if not video_paths:
        err = "No videos provided"
        _update_job(sb, job_id, status="failed", error_message=err)
        return {"success": False, "error": err}

    # Quality → frame / iteration budgets
    # Face output size (higher for pro 4K equi masters)
    face_w, face_h = 768, 576
    equi_max_w = 1920

    if housetour:
        # Whole pro tour: denser path sampling, horizon-only multi-yaw
        # 214s tour → ~55 eq frames × 6 yaws ≈ 330 views (COLMAP-friendly)
        target_frames_total = 55
        max_steps = 15000 if quality_preset != "fast" else 8000
        pitches = (0,)  # proven safer than multi-pitch overload
        yaws = DEFAULT_YAWS  # 6 × 60°
        apply_masks = False  # pro tours rarely need person wipe
        raw_only = True
        face_w, face_h = 1024, 768
        equi_max_w = 2560
    elif simple:
        target_frames_total = 22
        max_steps = 7000 if quality_preset != "quality" else 12000
        pitches = (0,)
        yaws = DEFAULT_YAWS
        apply_masks = False
        raw_only = True
    elif quality_preset == "fast":
        target_frames_total = 40
        max_steps = 5000
        pitches = DEFAULT_PITCHES
        yaws = DEFAULT_YAWS
        apply_masks = True
        raw_only = False
    elif quality_preset == "quality":
        target_frames_total = 90
        max_steps = 20000
        pitches = DEFAULT_PITCHES
        yaws = DEFAULT_YAWS
        apply_masks = True
        raw_only = False
    else:
        target_frames_total = 72
        max_steps = 12000
        pitches = DEFAULT_PITCHES
        yaws = DEFAULT_YAWS
        apply_masks = True
        raw_only = False

    # Detect 360
    if force_360 is None:
        is_360 = any(_is_likely_360(v) for v in video_paths)
    else:
        is_360 = force_360
    print(
        f"is_360={is_360}, videos={len(video_paths)}, preset={quality_preset}, "
        f"recipe={recipe_l}, pitches={pitches}, yaws={yaws}, "
        f"target_eq_frames={target_frames_total}, face={face_w}x{face_h}",
        flush=True,
    )

    images_dir = workspace / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    _update_job(
        sb,
        job_id,
        status="extracting",
        progress=15,
        stage_message=f"Extracting frames (recipe={'simple' if simple else 'default'})...",
    )

    # Apportion frames across clips by duration (joint reconstruction for multi-clip)
    durations = [_probe_duration(v) for v in video_paths]
    total_dur = sum(durations) or 1.0
    start_index = 0
    total_images = 0
    for i, (vpath, dur) in enumerate(zip(video_paths, durations)):
        share = max(8 if simple else 10, int(target_frames_total * (dur / total_dur)))
        n = extract_multiview_frames(
            vpath,
            images_dir,
            target_frames=share,
            is_360=is_360,
            yaws=yaws,
            pitches=pitches,
            h_fov=DEFAULT_H_FOV,
            v_fov=DEFAULT_V_FOV,
            frame_prefix=f"c{i}",
            start_index=start_index,
            apply_masks=apply_masks,
            face_w=face_w,
            face_h=face_h,
            equi_max_w=equi_max_w,
        )
        total_images += n
        start_index += share + 1

    print(f"Total perspective images: {total_images}", flush=True)
    if total_images < 8:
        err = f"Too few images extracted ({total_images})"
        _update_job(sb, job_id, status="failed", error_message=err)
        return {"success": False, "error": err}

    # Checkpoint images to volume
    img_ckpt = persistent / "images"
    if img_ckpt.exists():
        shutil.rmtree(img_ckpt)
    shutil.copytree(images_dir, img_ckpt)
    vol.commit()

    _update_job(
        sb,
        job_id,
        status="sfm",
        progress=35,
        stage_message=f"COLMAP SfM on {total_images} views...",
    )

    try:
        run_colmap_ns(images_dir, workspace)
    except Exception as e:
        err = f"SfM failed: {e}"
        print(err, flush=True)
        _update_job(sb, job_id, status="failed", error_message=err[:1000])
        return {"success": False, "error": err}

    # Checkpoint colmap
    for name in ("colmap", "images", "transforms.json", "sparse"):
        src = workspace / name
        if src.exists():
            dst = persistent / name
            if dst.exists():
                shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    # transforms.json often at workspace root after ns-process-data
    for p in workspace.glob("*.json"):
        shutil.copy2(p, persistent / p.name)
    vol.commit()

    _update_job(
        sb,
        job_id,
        status="training",
        progress=55,
        stage_message=f"Training splatfacto ({max_steps} iters)...",
    )

    output_dir = Path("/workspace/outputs")
    try:
        config_yml = train_splatfacto(workspace, output_dir, max_steps)
    except Exception as e:
        err = f"Training failed: {e}"
        print(err, flush=True)
        _update_job(sb, job_id, status="failed", error_message=err[:1000])
        return {"success": False, "error": err}

    # Checkpoint outputs
    out_ckpt = persistent / "outputs"
    if out_ckpt.exists():
        shutil.rmtree(out_ckpt)
    shutil.copytree(output_dir, out_ckpt)
    vol.commit()

    _update_job(
        sb,
        job_id,
        status="compressing",
        progress=85,
        stage_message="Exporting .splat...",
    )

    try:
        splat_path = export_ply_to_splat(config_yml, workspace, raw_only=raw_only)
    except Exception as e:
        err = f"Export failed: {e}"
        print(err, flush=True)
        _update_job(sb, job_id, status="failed", error_message=err[:1000])
        return {"success": False, "error": err}

    # Persist splat on volume
    splat_vol = persistent / "splat.splat"
    shutil.copy2(splat_path, splat_vol)
    vol.commit()
    print(f"Saved {splat_vol} ({splat_vol.stat().st_size / 1e6:.2f} MB)", flush=True)

    # Upload to Supabase when this is a real job
    ply_url = "local"
    if sb and not job_id.startswith("local-") and storage_path and storage_path != "none":
        try:
            base = storage_path.split(",")[0].rsplit("/", 1)[0]
            key = f"{base}/splat.splat"
            with open(splat_path, "rb") as f:
                sb.storage.from_(bucket).upload(
                    key,
                    f,
                    file_options={"content-type": "application/octet-stream", "upsert": "true"},
                )
            ply_url = sb.storage.from_(bucket).get_public_url(key)
        except Exception as e:
            print(f"Supabase upload failed (splat still on volume): {e}", flush=True)

    supersplat_url = (
        f"https://playcanvas.com/supersplat/editor?load={ply_url}" if ply_url != "local" else ""
    )
    _update_job(
        sb,
        job_id,
        status="ready",
        progress=100,
        splat_url=ply_url,
        viewer_url=supersplat_url,
        stage_message="Complete! (cleaned cuboid room)",
    )

    return {
        "success": True,
        "splat_url": ply_url,
        "viewer_url": supersplat_url,
        "volume_path": str(splat_vol),
        "bytes": splat_vol.stat().st_size,
        "images": total_images,
        "is_360": is_360,
    }


@app.function(
    gpu="A10G",
    memory=32768,
    image=image,
    timeout=7200,
    volumes={"/data": vol},
)
def train_splat_images(
    job_id: str,
    dataset_vol_path: str,
    max_steps: int = 12000,
    raw_only: bool = True,
):
    """
    Train splatfacto from an official-style *image* dataset (images/ + transforms.json).

    Skips video extract and COLMAP — poses are already in transforms.json.
    dataset_vol_path: path under /data to either a zip or a folder with
      images/ + transforms.json
    """
    import zipfile

    persistent = Path(f"/data/{job_id}")
    if persistent.exists():
        shutil.rmtree(persistent, ignore_errors=True)
    persistent.mkdir(parents=True, exist_ok=True)

    workspace = Path("/workspace/data")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    src = Path(dataset_vol_path)
    if not src.is_absolute():
        src = Path("/data") / dataset_vol_path
    if not src.exists():
        return {"success": False, "error": f"Dataset not found on volume: {dataset_vol_path}"}

    print(f"Loading image dataset from {src}", flush=True)
    if src.is_file() and src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src, "r") as zf:
            zf.extractall(workspace)
        # If zip has a single top folder, use it
        children = [p for p in workspace.iterdir() if not p.name.startswith(".")]
        if len(children) == 1 and children[0].is_dir():
            # move contents up
            inner = children[0]
            for item in inner.iterdir():
                shutil.move(str(item), str(workspace / item.name))
            inner.rmdir()
    elif src.is_dir():
        for item in src.iterdir():
            dest = workspace / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    else:
        return {"success": False, "error": f"Unsupported dataset path: {src}"}

    tj = workspace / "transforms.json"
    images = workspace / "images"
    if not tj.exists() or not images.is_dir():
        return {
            "success": False,
            "error": f"Need images/ + transforms.json under dataset (got: {list(workspace.iterdir())})",
        }

    n_img = sum(1 for p in images.iterdir() if p.is_file())
    print(f"Dataset OK: {n_img} images, transforms.json present", flush=True)
    if n_img < 8:
        return {"success": False, "error": f"Too few images ({n_img})"}

    # Checkpoint source on volume
    src_ckpt = persistent / "dataset"
    if src_ckpt.exists():
        shutil.rmtree(src_ckpt)
    shutil.copytree(workspace, src_ckpt)
    vol.commit()

    output_dir = Path("/workspace/outputs")
    try:
        config_yml = train_splatfacto(workspace, output_dir, max_steps)
    except Exception as e:
        err = f"Training failed: {e}"
        print(err, flush=True)
        return {"success": False, "error": err}

    out_ckpt = persistent / "outputs"
    if out_ckpt.exists():
        shutil.rmtree(out_ckpt)
    shutil.copytree(output_dir, out_ckpt)
    vol.commit()

    try:
        splat_path = export_ply_to_splat(config_yml, workspace, raw_only=raw_only)
    except Exception as e:
        err = f"Export failed: {e}"
        print(err, flush=True)
        return {"success": False, "error": err}

    splat_vol = persistent / "splat.splat"
    shutil.copy2(splat_path, splat_vol)
    # also keep raw if present
    raw = workspace / "splat_raw.splat"
    if raw.exists():
        shutil.copy2(raw, persistent / "splat_raw.splat")
    vol.commit()
    print(f"Saved {splat_vol} ({splat_vol.stat().st_size / 1e6:.2f} MB)", flush=True)

    return {
        "success": True,
        "volume_path": str(splat_vol),
        "bytes": splat_vol.stat().st_size,
        "images": n_img,
        "max_steps": max_steps,
        "gaussians_est": splat_vol.stat().st_size // 32,
    }


@app.function(image=image, volumes={"/data": vol}, timeout=600)
def upload_to_volume(remote_path: str, data: bytes) -> str:
    path = Path("/data") / remote_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    vol.commit()
    return str(path)


@app.function(image=image, volumes={"/data": vol}, timeout=600)
def download_from_volume(remote_path: str) -> bytes:
    path = Path("/data") / remote_path
    if not path.exists():
        # try job_id/splat.splat convenience
        alt = Path("/data") / remote_path / "splat.splat"
        if alt.exists():
            return alt.read_bytes()
        return b""
    return path.read_bytes()


@app.function(image=image, volumes={"/data": vol}, timeout=120)
def list_volume(prefix: str = "") -> list[str]:
    root = Path("/data") / prefix if prefix else Path("/data")
    if not root.exists():
        return []
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.stat().st_size > 0:
            # skip image dumps
            if "/images/" in str(p):
                continue
            out.append(f"{p.relative_to('/data')} ({p.stat().st_size})")
    return sorted(out)[:200]
