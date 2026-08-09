#!/usr/bin/env python3
"""
Coordinate / scene-normalization audit for kitchen GS (no retrain, no COLMAP).

Pulls existing Modal job checkpoint, re-exports PLY only, measures:
  - dataparser_transforms.json
  - camera poses original vs after dataparser
  - PLY gaussian means
  - .splat gaussian means
  - double-normalization hypothesis
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from app.services.modal_worker import app, download_from_volume, image, vol  # noqa: E402

JOB = "local-kitchen-8e06a2aa"
CFG = f"/data/{JOB}/outputs/data/splatfacto/2026-07-21_073242/config.yml"
DP = f"/data/{JOB}/outputs/data/splatfacto/2026-07-21_073242/dataparser_transforms.json"
LOCAL_OUT = ROOT / "data" / "nerfstudio_images" / "kitchen_coord_audit"


@app.function(gpu="A10G", memory=32768, image=image, timeout=1800, volumes={"/data": vol})
def audit_kitchen_coords():
    import shutil
    import subprocess

    import numpy as np
    from plyfile import PlyData

    report: dict = {}
    cfg = Path(CFG)
    if not cfg.exists():
        return {"success": False, "error": f"missing config {cfg}"}

    dp_path = Path(DP)
    dp = json.loads(dp_path.read_text()) if dp_path.exists() else None
    report["dataparser_transforms"] = dp

    ds_tj = Path(f"/data/{JOB}/dataset/transforms.json")
    if ds_tj.exists():
        d = json.loads(ds_tj.read_text())
        cams = []
        for fr in d["frames"]:
            M = np.array(fr["transform_matrix"], dtype=np.float64)
            cams.append(M[:3, 3])
        C = np.stack(cams)
        report["cameras_original"] = {
            "n": int(len(C)),
            "min": C.min(0).tolist(),
            "max": C.max(0).tolist(),
            "mean": C.mean(0).tolist(),
            "std": C.std(0).tolist(),
            "extent": (C.max(0) - C.min(0)).tolist(),
            "diameter": float(np.linalg.norm(C.max(0) - C.min(0))),
        }
        if dp:
            T = np.array(dp["transform"], dtype=np.float64)
            s = float(dp["scale"])
            R = T[:3, :3]
            t = T[:3, 3]
            # p' = s * (R @ p + t)  for column p
            C_n = (s * (R @ C.T + t[:, None])).T
            report["cameras_after_dataparser"] = {
                "min": C_n.min(0).tolist(),
                "max": C_n.max(0).tolist(),
                "mean": C_n.mean(0).tolist(),
                "std": C_n.std(0).tolist(),
                "extent": (C_n.max(0) - C_n.min(0)).tolist(),
                "diameter": float(np.linalg.norm(C_n.max(0) - C_n.min(0))),
                "scale": s,
            }

    export_dir = Path(f"/data/{JOB}/export_audit")
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [
            "ns-export",
            "gaussian-splat",
            "--load-config",
            str(cfg),
            "--output-dir",
            str(export_dir),
        ],
        capture_output=True,
        text=True,
    )
    report["export_returncode"] = r.returncode
    report["export_stdout_tail"] = (r.stdout or "")[-2000:]
    report["export_stderr_tail"] = (r.stderr or "")[-1500:]
    if r.returncode != 0:
        return {"success": False, "error": "ns-export failed", **report}

    ply_path = next(export_dir.rglob("*.ply"), None)
    if not ply_path:
        return {"success": False, "error": "no ply", **report}
    report["ply_path"] = str(ply_path)
    report["ply_bytes"] = ply_path.stat().st_size

    ply = PlyData.read(str(ply_path))
    v = ply["vertex"]
    pos = np.stack(
        [np.asarray(v["x"]), np.asarray(v["y"]), np.asarray(v["z"])],
        axis=1,
    ).astype(np.float64)
    sc = np.stack(
        [np.asarray(v["scale_0"]), np.asarray(v["scale_1"]), np.asarray(v["scale_2"])],
        axis=1,
    )
    sc_lin = np.exp(sc)

    def stats(P: np.ndarray) -> dict:
        lo = np.percentile(P, 1, axis=0)
        hi = np.percentile(P, 99, axis=0)
        return {
            "n": int(len(P)),
            "min": P.min(0).tolist(),
            "max": P.max(0).tolist(),
            "mean": P.mean(0).tolist(),
            "std": P.std(0).tolist(),
            "extent": (P.max(0) - P.min(0)).tolist(),
            "diameter": float(np.linalg.norm(P.max(0) - P.min(0))),
            "p1": lo.tolist(),
            "p99": hi.tolist(),
            "p1p99_extent": (hi - lo).tolist(),
            "p1p99_diameter": float(np.linalg.norm(hi - lo)),
        }

    report["ply_positions"] = stats(pos)
    report["ply_scale_linear"] = {
        "min": float(sc_lin.min()),
        "mean": float(sc_lin.mean()),
        "median_max_axis": float(np.median(sc_lin.max(1))),
        "p99_max_axis": float(np.percentile(sc_lin.max(1), 99)),
        "max": float(sc_lin.max()),
    }

    splat_path = Path(f"/data/{JOB}/splat.splat")
    raw = splat_path.read_bytes()
    dt = np.dtype([("pos", "f4", 3), ("scale", "f4", 3), ("color", "u1", 4), ("rot", "u1", 4)])
    sp = np.frombuffer(raw, dtype=dt)
    spos = sp["pos"].astype(np.float64)
    report["splat_positions"] = stats(spos)
    report["splat_n"] = int(len(sp))
    report["splat_vs_ply_mean_delta"] = (spos.mean(0) - pos.mean(0)).tolist()
    report["splat_vs_ply_p1p99_diameter_ratio"] = report["splat_positions"]["p1p99_diameter"] / max(
        report["ply_positions"]["p1p99_diameter"], 1e-12
    )

    if dp:
        s = float(dp["scale"])
        pos2 = pos * s
        report["if_scale_applied_twice_to_ply"] = stats(pos2)
        cam_d = report.get("cameras_after_dataparser", {}).get("diameter") or 1e-12
        report["double_norm_hypothesis"] = {
            "dataparser_scale": s,
            "ply_p1p99_diameter": report["ply_positions"]["p1p99_diameter"],
            "if_double_scaled_diameter": report["if_scale_applied_twice_to_ply"]["p1p99_diameter"],
            "cameras_normalized_diameter": cam_d,
            "ply_over_norm_cam_diameter": report["ply_positions"]["p1p99_diameter"] / max(cam_d, 1e-12),
            "conclusion": (
                "NOT double-normalized: ply diameter is O(1) and larger than normalized camera path "
                "(room shell). Double scale would shrink to ~"
                f"{report['if_scale_applied_twice_to_ply']['p1p99_diameter']:.3f}."
            ),
        }

    # opacity filter effect (same as export path)
    alpha = 1.0 / (1.0 + np.exp(-np.asarray(v["opacity"], dtype=np.float64)))
    scale_max = sc_lin.max(1)
    keep = (alpha > 8 / 255.0) & (scale_max > 1e-6) & (scale_max < 1.5)
    report["export_filter"] = {
        "n_before": int(len(pos)),
        "n_after_alpha_scale_gate": int(keep.sum()),
        "fraction_kept": float(keep.mean()),
        "filtered_positions": stats(pos[keep]),
    }

    sample_idx = np.linspace(0, len(pos) - 1, min(8000, len(pos)), dtype=int)
    sample_path = export_dir / "gaussian_centers_sample.npy"
    np.save(sample_path, pos[sample_idx])
    report["sample_centers_path"] = str(sample_path)

    # scene_box inference from positions
    report["scene_box_from_ply"] = {
        "aabb_min": pos.min(0).tolist(),
        "aabb_max": pos.max(0).tolist(),
        "note": "Nerfstudio scene_box is typically unit cube after pose normalization; gaussians may extend beyond.",
    }

    report["viewer_blob_diagnosis"] = {
        "summary": (
            "From outside, indoor GS looks like a dense blob because geometry is a hollow room shell "
            "of tiny gaussians (median scale ~0.006) with diameter ~O(10). SuperSplat default framing "
            "shows the whole shell as a ball; flying inside reveals the room. This is consistent with "
            "correct reconstruction in dataparser-normalized coordinates, not empty COLMAP."
        ),
        "median_gaussian_scale": report["ply_scale_linear"]["median_max_axis"],
        "extent_over_median_scale": report["ply_positions"]["p1p99_diameter"]
        / max(report["ply_scale_linear"]["median_max_axis"], 1e-12),
    }

    report["success"] = True
    rp = export_dir / "COORD_AUDIT_REPORT.json"
    rp.write_text(json.dumps(report, indent=2))
    vol.commit()
    return report


def main() -> None:
    LOCAL_OUT.mkdir(parents=True, exist_ok=True)
    print(f"Auditing job {JOB} (export PLY only, no train)…")
    with app.run():
        rep = audit_kitchen_coords.remote()
        out = LOCAL_OUT / "COORD_AUDIT_REPORT.json"
        out.write_text(json.dumps(rep, indent=2))
        print(json.dumps(rep, indent=2)[:12000])
        print(f"\nsaved {out}")
        for remote, local_name in [
            (f"{JOB}/export_audit/gaussian_centers_sample.npy", "gaussian_centers_sample.npy"),
            (f"{JOB}/export_audit/COORD_AUDIT_REPORT.json", "COORD_AUDIT_REPORT_remote.json"),
        ]:
            blob = download_from_volume.remote(remote)
            if blob:
                (LOCAL_OUT / local_name).write_bytes(blob)
                print(f"downloaded {local_name} ({len(blob)} bytes)")


if __name__ == "__main__":
    # ensure tokens from env file if not set
    if not os.getenv("MODAL_TOKEN_ID"):
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("MODAL_TOKEN_ID="):
                os.environ["MODAL_TOKEN_ID"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("MODAL_TOKEN_SECRET="):
                os.environ["MODAL_TOKEN_SECRET"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    main()
