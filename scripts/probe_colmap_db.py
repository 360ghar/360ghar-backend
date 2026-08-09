"""Probe COLMAP database match counts for official equirect experiment."""
from __future__ import annotations

import json
import sqlite3
import shutil
from pathlib import Path

import modal

app = modal.App("sfm-probe-db")
vol = modal.Volume.from_name("splat-lab-data")


@app.function(volumes={"/data": vol}, timeout=600)
def probe() -> dict:
    db_path = Path("/data/sfm-official-equirect-exp/processed/colmap/database.db")
    if not db_path.exists():
        return {"error": "no database"}
    # copy to /tmp so sqlite can open (volume may be RO-ish)
    local = Path("/tmp/colmap.db")
    shutil.copy2(db_path, local)
    con = sqlite3.connect(str(local))
    cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    out: dict = {"tables": tables}
    for t in ("cameras", "images", "keypoints", "descriptors", "matches", "two_view_geometries"):
        if t in tables:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            out[f"count_{t}"] = n
    if "images" in tables:
        out["image_names_sample"] = [
            r[0] for r in cur.execute("SELECT name FROM images ORDER BY image_id LIMIT 12")
        ]
    if "two_view_geometries" in tables:
        rows = cur.execute(
            "SELECT pair_id, rows FROM two_view_geometries WHERE rows > 0 ORDER BY rows DESC LIMIT 10"
        ).fetchall()
        out["top_two_view_geometries"] = [{"pair_id": r[0], "n_inliers": r[1]} for r in rows]
        out["n_pairs_with_geometry"] = cur.execute(
            "SELECT COUNT(*) FROM two_view_geometries WHERE rows > 0"
        ).fetchone()[0]
        out["median_inliers"] = cur.execute(
            "SELECT rows FROM two_view_geometries WHERE rows > 0 ORDER BY rows"
        ).fetchall()
        if out["median_inliers"]:
            vals = [r[0] for r in out["median_inliers"]]
            out["median_inliers"] = vals[len(vals) // 2]
            out["max_inliers"] = max(vals)
            out["mean_inliers"] = sum(vals) / len(vals)
    # sparse empty confirmation
    sparse = Path("/data/sfm-official-equirect-exp/processed/colmap/sparse")
    out["sparse_children"] = [c.name for c in sparse.iterdir()] if sparse.exists() else []
    con.close()
    return out


@app.local_entrypoint()
def main():
    print(json.dumps(probe.remote(), indent=2))
