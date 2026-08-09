"""List artifacts from official equirect SfM experiment on Modal volume."""
from __future__ import annotations

import json
from pathlib import Path

import modal

app = modal.App("sfm-list-official")
vol = modal.Volume.from_name("splat-lab-data")


@app.function(volumes={"/data": vol}, timeout=300)
def list_job() -> dict:
    root = Path("/data/sfm-official-equirect-exp")
    if not root.exists():
        return {"exists": False}
    files = []
    for p in root.rglob("*"):
        if p.is_file():
            files.append(f"{p.relative_to(root)} ({p.stat().st_size})")
    sparse = root / "processed" / "colmap" / "sparse"
    sparse_info: dict = {"sparse_exists": sparse.exists()}
    if sparse.exists():
        sparse_info["children"] = [c.name for c in sparse.iterdir()]
        # any reconstruction under sparse?
        sparse_info["rglob_points"] = [
            str(p.relative_to(root)) for p in sparse.rglob("points3D.bin")
        ]
    db = root / "processed" / "colmap" / "database.db"
    images = root / "processed" / "images"
    equirect = root / "processed" / "equirect_images"  # may vary
    planar = list((root / "processed").rglob("*.jpg"))[:5]
    return {
        "exists": True,
        "n_files": len(files),
        "files_sample": sorted(files)[:120],
        "sparse": sparse_info,
        "db_size": db.stat().st_size if db.exists() else 0,
        "images_dir_exists": images.exists(),
        "images_count": len(list(images.glob("*"))) if images.exists() else 0,
        "jpg_count": len(list((root / "processed").rglob("*.jpg"))),
        "sample_jpgs": [str(p.relative_to(root)) for p in planar],
    }


@app.local_entrypoint()
def main():
    print(json.dumps(list_job.remote(), indent=2))
