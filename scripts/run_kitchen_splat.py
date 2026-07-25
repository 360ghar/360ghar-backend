#!/usr/bin/env python3
"""
Train Gaussian splat from the official Nerfstudio *kitchen* image dataset.

Uses images/ + transforms.json (poses already known) — no 360 video, no COLMAP.

Data:
  data/nerfstudio_images/kitchen_ready/

Output:
  ../360-tours/public/splats/kitchen.splat
  ../Desktop/nerfstudio-image-datasets/kitchen.splat
"""
from __future__ import annotations

import os
import sys
import uuid
import zipfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
# Modal tokens from .env
for key in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
    if os.getenv(key):
        os.environ[key] = os.environ[key]

sys.path.insert(0, str(ROOT))

from app.services.modal_worker import (  # noqa: E402
    app,
    download_from_volume,
    train_splat_images,
    upload_to_volume,
)

DATA = ROOT / "data" / "nerfstudio_images" / "kitchen_ready"
OUT_DIR = Path("/Users/chiragsingh/Desktop/360-tours/public/splats")
OUT = OUT_DIR / "kitchen.splat"
GALLERY = Path("/Users/chiragsingh/Desktop/nerfstudio-image-datasets")
# Balanced steps: enough for a solid kitchen, not multi-hour
MAX_STEPS = 12000


def _zip_dataset(src: Path, zip_path: Path) -> Path:
    if not (src / "images").is_dir() or not (src / "transforms.json").is_file():
        raise SystemExit(f"Need images/ + transforms.json in {src}")
    n = sum(1 for p in (src / "images").iterdir() if p.is_file())
    print(f"Zipping {n} images + transforms from {src} …")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(src / "transforms.json", "transforms.json")
        for p in sorted((src / "images").iterdir()):
            if p.is_file():
                zf.write(p, f"images/{p.name}")
    print(f"  zip size={zip_path.stat().st_size / 1e6:.1f} MB")
    return zip_path


def main() -> None:
    if not DATA.exists():
        raise SystemExit(f"Missing {DATA}\nDownload kitchen first (see data/nerfstudio_images/README.md)")

    job_id = f"local-kitchen-{uuid.uuid4().hex[:8]}"
    print(f"job_id={job_id}")
    print(f"data={DATA}")
    print(f"max_steps={MAX_STEPS}  (image dataset, poses in transforms.json)")

    zip_path = ROOT / "data" / "nerfstudio_images" / "_kitchen_upload.zip"
    _zip_dataset(DATA, zip_path)

    with app.run():
        remote = f"datasets/kitchen_ready.zip"
        print(f"Uploading to Modal volume as {remote} …")
        upload_to_volume.remote(remote, zip_path.read_bytes())

        print("Training splatfacto on A10G (this can take 20–50 min)…")
        res = train_splat_images.remote(
            job_id,
            remote,
            MAX_STEPS,
            True,  # raw_only
        )
        print("train result:", res)
        if not res.get("success"):
            raise SystemExit(f"FAILED: {res}")

        blob = b""
        for i in range(8):
            blob = download_from_volume.remote(f"{job_id}/splat.splat")
            if blob and len(blob) > 50_000:
                break
            print(f"  download retry {i + 1}")
            import time

            time.sleep(2)
        if not blob or len(blob) < 50_000:
            blob = download_from_volume.remote(f"{job_id}/splat_raw.splat")
        if not blob or len(blob) < 50_000:
            raise SystemExit("Could not download splat from volume")

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(blob)
        GALLERY.mkdir(parents=True, exist_ok=True)
        gallery_out = GALLERY / "kitchen.splat"
        gallery_out.write_bytes(blob)

        # drop upload zip to free space
        try:
            zip_path.unlink()
        except OSError:
            pass

        n_gauss = len(blob) // 32
        print(f"\n✓ Saved {OUT}")
        print(f"  also  {gallery_out}")
        print(f"  size={len(blob)/1e6:.2f} MB  gaussians≈{n_gauss:,}")
        print(f"  images={res.get('images')}  steps={res.get('max_steps')}")
        print("Open in SuperSplat: https://playcanvas.com/supersplat/editor")
        print(f"  or drag {OUT}")


if __name__ == "__main__":
    main()
