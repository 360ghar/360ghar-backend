#!/usr/bin/env python3
"""
SfM-only experiment: official Nerfstudio equirectangular preprocessing.

Does NOT train Gaussian Splatting.
Does NOT use custom multi-yaw extraction.

Pipeline:
  360 video → ns-process-data video --camera-type equirectangular
            → COLMAP sparse model only
            → metrics + sparse PLY viz + trajectory dump
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import modal
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VIDEO_LOCAL = Path("/Users/chiragsingh/Desktop/360-tours/data/housetour/housetour_source.webm")
OUT_LOCAL = Path("/Users/chiragsingh/Desktop/360-tours/data/housetour/sfm_official_equirect")
REMOTE_VIDEO = "clips/housetour_source.webm"
JOB = "sfm-official-equirect-exp"

app = modal.App("sfm-official-equirect")
vol = modal.Volume.from_name("splat-lab-data", create_if_missing=True)

image = (
    modal.Image.from_registry("pytorch/pytorch:2.1.2-cuda11.8-cudnn8-devel")
    .env({"DEBIAN_FRONTEND": "noninteractive", "TZ": "Etc/UTC", "QT_QPA_PLATFORM": "offscreen"})
    .apt_install(
        "git", "build-essential", "ninja-build", "ffmpeg",
        "libgl1-mesa-glx", "libglib2.0-0", "libx11-6", "colmap", "xvfb",
    )
    .pip_install(
        "numpy<2.0.0",
        "nerfstudio==1.1.3",
        "gsplat==1.0.0",
        "plyfile",
        "opencv-python-headless",
        "matplotlib",
    )
)


@app.function(image=image, volumes={"/data": vol}, timeout=600)
def upload_video(remote_path: str, data: bytes) -> str:
    p = Path("/data") / remote_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    vol.commit()
    return str(p)


@app.function(image=image, gpu="A10G", memory=32768, volumes={"/data": vol}, timeout=14400)
def run_official_equirect_sfm(
    video_rel: str,
    job_id: str,
    num_frames_target: int = 40,
    images_per_equirect: int = 8,
) -> dict:
    """Official ns-process-data equirectangular only — stop after COLMAP."""
    import shutil
    from pathlib import Path
    import subprocess

    src = Path("/data") / video_rel
    if not src.exists():
        return {"success": False, "error": f"missing {src}"}

    work = Path(f"/data/{job_id}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # Copy video into work (stable name for ns-process-data)
    video = work / f"input{src.suffix}"
    shutil.copy2(src, video)

    out_dir = work / "processed"
    out_dir.mkdir()

    cmd = [
        "xvfb-run", "-a",
        "ns-process-data", "video",
        "--data", str(video),
        "--output-dir", str(out_dir),
        "--camera-type", "equirectangular",
        "--images-per-equirect", str(images_per_equirect),
        "--matching-method", "sequential",
        "--num-frames-target", str(num_frames_target),
        "--num-downscales", "0",
    ]
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert proc.stdout is not None
    lines = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        lines.append(line)
        if len(lines) > 200:
            lines.pop(0)
    proc.wait()
    if proc.returncode != 0:
        return {
            "success": False,
            "error": f"ns-process-data failed code={proc.returncode}",
            "tail": "".join(lines)[-3000:],
        }

    vol.commit()

    # Locate COLMAP sparse + transforms
    sparse_candidates = list(out_dir.glob("**/sparse/**/points3D.bin")) + list(
        out_dir.glob("**/colmap/sparse/**/points3D.bin")
    )
    # nerfstudio often: processed/colmap/sparse/0/
    if not sparse_candidates:
        sparse_candidates = list(out_dir.rglob("points3D.bin"))
    if not sparse_candidates:
        return {
            "success": False,
            "error": "no points3D.bin found",
            "tree": [str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file()][:80],
        }

    points_path = sorted(sparse_candidates)[0]
    sparse_dir = points_path.parent
    cameras_path = sparse_dir / "cameras.bin"
    images_path = sparse_dir / "images.bin"

    transforms_path = out_dir / "transforms.json"
    if not transforms_path.exists():
        tjs = list(out_dir.rglob("transforms.json"))
        transforms_path = tjs[0] if tjs else None

    metrics = analyze_colmap(sparse_dir, transforms_path)
    metrics["success"] = True
    metrics["sparse_dir"] = str(sparse_dir)
    metrics["job_id"] = job_id
    metrics["cmd"] = cmd

    # Export sparse PLY for viz
    ply_path = work / "sparse_points.ply"
    export_points_ply(points_path, ply_path)
    metrics["sparse_ply"] = str(ply_path.relative_to(Path("/data")))

    # Camera trajectory CSV
    traj_path = work / "camera_trajectory.csv"
    if transforms_path and transforms_path.exists():
        write_trajectory_csv(transforms_path, traj_path)
        metrics["trajectory_csv"] = str(traj_path.relative_to(Path("/data")))

    # Matplotlib trajectory + point cloud scatter
    viz_path = work / "sfm_visualization.png"
    try:
        make_visualization(points_path, transforms_path, viz_path, metrics)
        metrics["visualization"] = str(viz_path.relative_to(Path("/data")))
    except Exception as e:
        metrics["visualization_error"] = str(e)

    # Save metrics JSON
    metrics_path = work / "sfm_metrics.json"
    # strip non-serializable
    serial = {k: v for k, v in metrics.items() if k != "cmd"}
    serial["cmd"] = " ".join(cmd)
    metrics_path.write_text(json.dumps(serial, indent=2, default=str))
    metrics["metrics_json"] = str(metrics_path.relative_to(Path("/data")))

    vol.commit()
    return metrics


def read_points3d_xyz(path: Path) -> np.ndarray:
    xyzs = []
    with open(path, "rb") as fid:
        num = struct.unpack("Q", fid.read(8))[0]
        for _ in range(num):
            data = fid.read(43)
            if len(data) < 43:
                break
            props = struct.unpack("<QdddBBBd", data)
            xyzs.append(props[1:4])
            track_len = struct.unpack("<Q", fid.read(8))[0]
            fid.read(8 * track_len)
    return np.array(xyzs, dtype=np.float64) if xyzs else np.zeros((0, 3))


def read_cameras_bin(path: Path) -> list[dict]:
    cams = []
    with open(path, "rb") as fid:
        num = struct.unpack("Q", fid.read(8))[0]
        for _ in range(num):
            cam_id, model_id, w, h = struct.unpack("iiQQ", fid.read(24))
            nparams = {0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 8}.get(model_id, 8)
            params = struct.unpack("d" * nparams, fid.read(8 * nparams))
            model_name = {
                0: "SIMPLE_PINHOLE",
                1: "PINHOLE",
                2: "SIMPLE_RADIAL",
                3: "RADIAL",
                4: "OPENCV",
            }.get(model_id, str(model_id))
            cams.append(
                {
                    "camera_id": cam_id,
                    "model": model_name,
                    "width": w,
                    "height": h,
                    "params": params,
                }
            )
    return cams


def analyze_colmap(sparse_dir: Path, transforms_path: Path | None) -> dict:
    pts = read_points3d_xyz(sparse_dir / "points3D.bin")
    cams = read_cameras_bin(sparse_dir / "cameras.bin")

    # Focal lengths from COLMAP cameras
    focals = []
    for c in cams:
        p = c["params"]
        if c["model"] in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL"):
            focals.append({"id": c["camera_id"], "model": c["model"], "f": p[0], "cx": p[1], "cy": p[2]})
        elif c["model"] == "PINHOLE":
            focals.append(
                {"id": c["camera_id"], "model": c["model"], "fl_x": p[0], "fl_y": p[1], "cx": p[2], "cy": p[3]}
            )
        elif c["model"] == "OPENCV":
            focals.append(
                {
                    "id": c["camera_id"],
                    "model": c["model"],
                    "fl_x": p[0],
                    "fl_y": p[1],
                    "cx": p[2],
                    "cy": p[3],
                    "k1": p[4],
                    "k2": p[5],
                    "p1": p[6],
                    "p2": p[7],
                    "fl_ratio": float(p[1] / p[0]) if p[0] else None,
                }
            )

    # Camera centers from transforms.json if present
    cam_centers = None
    n_frames = 0
    if transforms_path and transforms_path.exists():
        tj = json.loads(transforms_path.read_text())
        frames = tj.get("frames", [])
        n_frames = len(frames)
        if frames:
            cam_centers = np.array(
                [np.array(f["transform_matrix"], float)[:3, 3] for f in frames],
                dtype=np.float64,
            )
        # Also record transforms-level intrinsics if present
        tf_intr = {
            k: tj[k]
            for k in ("camera_model", "fl_x", "fl_y", "cx", "cy", "w", "h", "k1", "k2")
            if k in tj
        }
    else:
        tf_intr = {}

    def pca_ratios(X: np.ndarray) -> list[float]:
        if len(X) < 3:
            return [0.0, 0.0, 0.0]
        Xc = X - X.mean(0)
        # variance along principal axes
        _, _, vh = np.linalg.svd(Xc, full_matrices=False)
        var = np.var(Xc @ vh.T, axis=0)
        s = var.sum()
        return (var / s).tolist() if s > 0 else [0.0, 0.0, 0.0]

    out: dict = {
        "points3D_count": int(len(pts)),
        "num_cameras_models": len(cams),
        "cameras": focals,
        "transforms_intrinsics": tf_intr,
        "n_frames_transforms": n_frames,
    }

    if len(pts):
        out["points_extent"] = (pts.max(0) - pts.min(0)).tolist()
        out["points_std"] = pts.std(0).tolist()
        out["points_pca_var_ratios"] = pca_ratios(pts)
    else:
        out["points_extent"] = None
        out["points_pca_var_ratios"] = None

    if cam_centers is not None and len(cam_centers):
        out["camera_centers_extent"] = (cam_centers.max(0) - cam_centers.min(0)).tolist()
        out["camera_centers_std"] = cam_centers.std(0).tolist()
        out["camera_path_pca_var_ratios"] = pca_ratios(cam_centers)
        steps = np.linalg.norm(cam_centers[1:] - cam_centers[:-1], axis=1)
        if len(steps):
            out["camera_step_median"] = float(np.median(steps))
            out["camera_step_mean"] = float(steps.mean())
            out["camera_step_p95"] = float(np.percentile(steps, 95))

    # Pass/fail criteria from audit
    fl_ok = None
    if focals:
        f0 = focals[0]
        if "fl_x" in f0 and "fl_y" in f0 and f0["fl_x"]:
            ratio = abs(f0["fl_y"] / f0["fl_x"] - 1.0)
            fl_ok = ratio < 0.25
        elif "f" in f0:
            fl_ok = True
    out["criterion_fl_x_approx_fl_y"] = fl_ok
    out["criterion_points_gt_50k"] = len(pts) > 50_000
    third = (out.get("points_pca_var_ratios") or [0, 0, 0])[2]
    out["criterion_pca_third_not_near_zero"] = third is not None and third > 0.02
    out["sfm_geometry_pass"] = bool(
        out["criterion_points_gt_50k"]
        and out["criterion_pca_third_not_near_zero"]
        and (fl_ok is not False)
    )
    return out


def export_points_ply(points_bin: Path, ply_path: Path) -> None:
    pts = read_points3d_xyz(points_bin)
    with open(ply_path, "w") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {len(pts)}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("end_header\n")
        for p in pts:
            f.write(f"{p[0]} {p[1]} {p[2]}\n")


def write_trajectory_csv(transforms_path: Path, csv_path: Path) -> None:
    tj = json.loads(transforms_path.read_text())
    with open(csv_path, "w") as f:
        f.write("index,file_path,cx,cy,cz\n")
        for i, fr in enumerate(tj.get("frames", [])):
            M = np.array(fr["transform_matrix"], float)
            c = M[:3, 3]
            f.write(f'{i},{fr.get("file_path","")},{c[0]},{c[1]},{c[2]}\n')


def make_visualization(
    points_bin: Path,
    transforms_path: Path | None,
    out_png: Path,
    metrics: dict,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pts = read_points3d_xyz(points_bin)
    # subsample for plot
    if len(pts) > 20000:
        rng = np.random.default_rng(0)
        pts = pts[rng.choice(len(pts), 20000, replace=False)]

    fig = plt.figure(figsize=(14, 6))
    ax1 = fig.add_subplot(121, projection="3d")
    if len(pts):
        ax1.scatter(pts[:, 0], pts[:, 1], pts[:, 2], s=0.3, c="steelblue", alpha=0.5)
    ax1.set_title(f"Sparse points3D (n={metrics.get('points3D_count')})")
    ax1.set_xlabel("X")
    ax1.set_ylabel("Y")
    ax1.set_zlabel("Z")

    ax2 = fig.add_subplot(122, projection="3d")
    if transforms_path and transforms_path.exists():
        tj = json.loads(transforms_path.read_text())
        Cs = np.array(
            [np.array(f["transform_matrix"], float)[:3, 3] for f in tj.get("frames", [])]
        )
        if len(Cs):
            ax2.plot(Cs[:, 0], Cs[:, 1], Cs[:, 2], "r.-", markersize=2, linewidth=0.8)
            ax2.scatter(Cs[0, 0], Cs[0, 1], Cs[0, 2], c="g", s=40, label="start")
            ax2.scatter(Cs[-1, 0], Cs[-1, 1], Cs[-1, 2], c="k", s=40, label="end")
            ax2.legend()
    ax2.set_title("Camera trajectory (transforms.json)")
    ax2.set_xlabel("X")
    ax2.set_ylabel("Y")
    ax2.set_zlabel("Z")

    fig.suptitle(
        f"Official equirect SfM | PCA pts={metrics.get('points_pca_var_ratios')} | "
        f"pass={metrics.get('sfm_geometry_pass')}"
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    plt.close(fig)


@app.function(image=image, volumes={"/data": vol}, timeout=600)
def download_bytes(remote_path: str) -> bytes:
    p = Path("/data") / remote_path
    if not p.exists():
        return b""
    return p.read_bytes()


@app.local_entrypoint()
def main():
    if not VIDEO_LOCAL.exists():
        raise SystemExit(f"Missing {VIDEO_LOCAL}")

    OUT_LOCAL.mkdir(parents=True, exist_ok=True)

    print(f"Uploading {VIDEO_LOCAL} ({VIDEO_LOCAL.stat().st_size/1e6:.1f} MB)…")
    upload_video.remote(REMOTE_VIDEO, VIDEO_LOCAL.read_bytes())

    print("Running official ns-process-data equirectangular (SfM only)…")
    metrics = run_official_equirect_sfm.remote(
        REMOTE_VIDEO,
        JOB,
        num_frames_target=40,
        images_per_equirect=8,
    )
    print(json.dumps({k: v for k, v in metrics.items() if k != "cmd"}, indent=2, default=str))

    # Pull artifacts
    for key in ("metrics_json", "sparse_ply", "trajectory_csv", "visualization"):
        rel = metrics.get(key)
        if not rel:
            continue
        data = download_bytes.remote(rel)
        if not data:
            print("missing remote", rel)
            continue
        dest = OUT_LOCAL / Path(rel).name
        dest.write_bytes(data)
        print(f"saved {dest} ({len(data)} bytes)")

    # Write comparison vs previous custom pipeline
    prev = {
        "label": "custom multi-yaw + ns-process-data images (housetour job)",
        "points3D_count": 4636,
        "fl_x": 534.2132034934124,
        "fl_y": 3107.9832997043454,
        "fl_ratio": 3107.9832997043454 / 534.2132034934124,
        "points_pca_var_ratios": [0.8916, 0.1071, 0.0013],
        "camera_path_pca_var_ratios": [0.6128, 0.3651, 0.0221],
        "n_frames": 206,
    }
    comparison = {
        "previous_custom_pipeline": prev,
        "official_equirect_pipeline": metrics,
        "interpretation": {
            "official_sfm_geometry_pass": metrics.get("sfm_geometry_pass"),
            "if_pass": "Preprocessing was the bottleneck; rewire to official equirect path.",
            "if_fail": "Official SfM also fails criteria → implementation of multi-yaw is not the sole bottleneck; COLMAP/video still insufficient or needs stronger SfM stack.",
        },
    }
    comp_path = OUT_LOCAL / "comparison_vs_custom.json"
    # strip large/nonessential
    clean_metrics = {k: v for k, v in metrics.items() if k not in ("cmd",)}
    comparison["official_equirect_pipeline"] = clean_metrics
    comp_path.write_text(json.dumps(comparison, indent=2, default=str))
    print(f"\nComparison → {comp_path}")
    print("sfm_geometry_pass =", metrics.get("sfm_geometry_pass"))
