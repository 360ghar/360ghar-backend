#!/usr/bin/env python3
"""
Whole-house 360 GS train on the professional HouseTour-class source.

Source (local, gitignored):
  ../360-tours/data/housetour/housetour_source.webm

Recipe: housetour
  - ~55 equirect samples across full ~214s tour
  - 6 horizon yaws only (no multi-pitch overload)
  - higher face res (1024×768)
  - raw export only (no fake floor shell)

Output:
  360-tours/public/splats/housetour_full.splat
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from app.services.modal_worker import app, download_from_volume, train_splat, upload_to_volume

VIDEO = Path("/Users/chiragsingh/Desktop/360-tours/data/housetour/housetour_source.webm")
OUT_DIR = Path("/Users/chiragsingh/Desktop/360-tours/public/splats")
OUT = OUT_DIR / "housetour_full.splat"


def main() -> None:
    if not VIDEO.exists():
        raise SystemExit(
            f"Missing {VIDEO}\n"
            "Download with yt-dlp into data/housetour/ (see data/housetour/README.md)"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    job_id = f"local-housetour-{uuid.uuid4().hex[:8]}"
    print(f"job_id={job_id}")
    print(f"video={VIDEO} ({VIDEO.stat().st_size / 1e6:.1f} MB)")
    print("recipe=housetour  (full tour, horizon multi-yaw, raw export)")

    with app.run():
        print("Uploading to Modal volume (no heavy re-encode)…")
        remote = f"clips/housetour_source{VIDEO.suffix}"
        upload_to_volume.remote(remote, VIDEO.read_bytes())

        print("Training whole tour on GPU (this can take 30–90+ min)…")
        res = train_splat.remote(
            job_id,
            "none",
            "balanced",
            remote,
            True,  # force_360
            "housetour",
        )
        print("train result:", res)
        if not res.get("success"):
            raise SystemExit(f"FAILED: {res}")

        blob = b""
        for i in range(8):
            blob = download_from_volume.remote(f"{job_id}/splat.splat")
            if blob and len(blob) > 100_000:
                break
            print(f"  download retry {i + 1}")
            import time

            time.sleep(3)
        if not blob or len(blob) < 100_000:
            blob = download_from_volume.remote(f"{job_id}/splat_raw.splat")
        if not blob or len(blob) < 100_000:
            raise SystemExit("Could not download splat from volume")

        OUT.write_bytes(blob)
        print(f"\n✓ Saved {OUT}")
        print(f"  size={len(blob)/1e6:.2f} MB  gaussians≈{len(blob)//32:,}")
        print(f"  images={res.get('images')}  recipe=housetour")
        print("Open in SuperSplat / Swyvl. Goal: whole-house free look.")


if __name__ == "__main__":
    main()
