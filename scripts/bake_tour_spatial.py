#!/usr/bin/env python3
"""
Bake TourSpatialManifest from image-dataset poses + .splat (no retrain / no COLMAP).

Example:
  python scripts/bake_tour_spatial.py \\
    --transforms data/nerfstudio_images/kitchen_ready/transforms.json \\
    --splat /path/to/kitchen.splat \\
    --dataparser data/nerfstudio_images/kitchen_coord_audit/dataparser_transforms.json \\
    --out data/nerfstudio_images/kitchen_ready/tour_spatial_manifest.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


def mat_to_quat(R: np.ndarray) -> list[float]:
    tr = float(R[0, 0] + R[1, 1] + R[2, 2])
    if tr > 0:
        S = math.sqrt(tr + 1.0) * 2
        w, x = 0.25 * S, (R[2, 1] - R[1, 2]) / S
        y, z = (R[0, 2] - R[2, 0]) / S, (R[1, 0] - R[0, 1]) / S
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        S = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w, x = (R[2, 1] - R[1, 2]) / S, 0.25 * S
        y, z = (R[0, 1] + R[1, 0]) / S, (R[0, 2] + R[2, 0]) / S
    elif R[1, 1] > R[2, 2]:
        S = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w, x = (R[0, 2] - R[2, 0]) / S, (R[0, 1] + R[1, 0]) / S
        y, z = 0.25 * S, (R[1, 2] + R[2, 1]) / S
    else:
        S = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w, x = (R[1, 0] - R[0, 1]) / S, (R[0, 2] + R[2, 0]) / S
        y, z = (R[1, 2] + R[2, 1]) / S, 0.25 * S
    q = np.array([x, y, z, w], dtype=float)
    q /= np.linalg.norm(q) + 1e-12
    return q.tolist()


def bake(
    transforms_path: Path,
    splat_path: Path,
    out_path: Path,
    dataparser_path: Path | None,
    splat_url: str,
    room_id: str,
    room_name: str,
) -> dict:
    d = json.loads(transforms_path.read_text())
    frames = d["frames"]
    C = np.stack([np.array(fr["transform_matrix"], dtype=np.float64)[:3, 3] for fr in frames], 0)
    ups = np.stack([np.array(fr["transform_matrix"], dtype=np.float64)[:3, :3][:, 1] for fr in frames], 0)

    dp = None
    if dataparser_path and dataparser_path.exists():
        dp = json.loads(dataparser_path.read_text())
        T = np.array(dp["transform"], dtype=np.float64)
        s = float(dp["scale"])
        Rdp, t = T[:3, :3], T[:3, 3]
        C_v = (s * (Rdp @ C.T + t[:, None])).T
        ups_v = (Rdp @ ups.T).T
    else:
        C_v, ups_v = C.copy(), ups

    raw = splat_path.read_bytes()
    n = len(raw) // 32
    dt = np.dtype([("pos", "f4", 3), ("scale", "f4", 3), ("color", "u1", 4), ("rot", "u1", 4)])
    g = np.frombuffer(raw, dtype=dt)
    idx = np.linspace(0, n - 1, min(80_000, n), dtype=int)
    P = g["pos"][idx].astype(np.float64)
    P = P[g["color"][idx, 3] > 20]

    lo_g, hi_g = np.percentile(P, 2, axis=0), np.percentile(P, 98, axis=0)
    lo_c = np.percentile(C_v, 5, axis=0) - 0.3
    hi_c = np.percentile(C_v, 95, axis=0) + 0.3
    cam_std = C_v.std(0) + 1e-6

    u = ups_v.mean(0)
    u = u / (np.linalg.norm(u) + 1e-9)
    up_axis = int(np.argmax(np.abs(u)))
    sign = 1.0 if u[up_axis] >= 0 else -1.0
    up_vec = np.zeros(3)
    up_vec[up_axis] = sign

    spawn_pos = C_v.mean(0).copy()
    room_height = float(hi_g[up_axis] - lo_g[up_axis])
    eye = 0.15 * room_height if room_height > 1e-3 else 0.15

    room_center = P.mean(0)
    look_dir = room_center - spawn_pos
    look_dir[up_axis] = 0
    if np.linalg.norm(look_dir) < 1e-6:
        look_dir = np.array([0.0, 0.0, -1.0])
    look_dir = look_dir / (np.linalg.norm(look_dir) + 1e-9)
    forward = look_dir
    right = np.cross(forward, up_vec)
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1.0, 0.0, 0.0])
    right = right / np.linalg.norm(right)
    up_o = np.cross(right, forward)
    up_o = up_o / (np.linalg.norm(up_o) + 1e-9)
    Rm = np.stack([right, up_o, -forward], axis=1)
    spawn_quat = mat_to_quat(Rm)

    if up_axis == 1 and sign > 0:
        align_quat = [0.0, 0.0, 0.0, 1.0]
    else:
        target = np.array([0.0, 1.0, 0.0])
        v = up_vec / (np.linalg.norm(up_vec) + 1e-9)
        axis = np.cross(v, target)
        nn = np.linalg.norm(axis)
        if nn < 1e-8:
            align_quat = [0.0, 0.0, 0.0, 1.0] if float(v.dot(target)) > 0 else [1.0, 0.0, 0.0, 0.0]
        else:
            axis = axis / nn
            angle = math.acos(float(np.clip(v.dot(target), -1, 1)))
            hs = math.sin(angle / 2)
            align_quat = [axis[0] * hs, axis[1] * hs, axis[2] * hs, math.cos(angle / 2)]

    stride = max(1, len(C_v) // 40)
    node_indices = list(range(0, len(C_v), stride))
    if node_indices[-1] != len(C_v) - 1:
        node_indices.append(len(C_v) - 1)

    nodes = []
    for i, fi in enumerate(node_indices):
        pos = C_v[fi]
        R_c = np.array(frames[fi]["transform_matrix"], dtype=np.float64)[:3, :3]
        if dp is not None:
            R_c = np.array(dp["transform"], dtype=np.float64)[:3, :3] @ R_c
        nodes.append(
            {
                "id": f"n{i:03d}",
                "position": [float(pos[0]), float(pos[1]), float(pos[2])],
                "rotation_xyzw": mat_to_quat(R_c),
                "room_id": room_id,
                "source": f"frame_{fi + 1:05d}",
            }
        )

    edges = []
    for i in range(len(nodes) - 1):
        pa = np.array(nodes[i]["position"])
        pb = np.array(nodes[i + 1]["position"])
        w = float(np.linalg.norm(pb - pa))
        edges.append({"from": nodes[i]["id"], "to": nodes[i + 1]["id"], "weight": w})
        edges.append({"from": nodes[i + 1]["id"], "to": nodes[i]["id"], "weight": w})
    positions = np.array([n["position"] for n in nodes])
    for i in range(len(nodes)):
        dist = np.linalg.norm(positions - positions[i], axis=1)
        for j in np.argsort(dist)[1:4]:
            if dist[j] < 1.5:
                edges.append({"from": nodes[i]["id"], "to": nodes[int(j)]["id"], "weight": float(dist[j])})
    seen: set[tuple[str, str]] = set()
    edges_u = []
    for e in edges:
        key = (e["from"], e["to"])
        if key not in seen:
            seen.add(key)
            edges_u.append(e)

    path = [n["position"] for n in nodes]
    radius = max(float(np.median(cam_std) * 1.2), 0.25)
    mid = nodes[len(nodes) // 2]["id"]

    manifest = {
        "version": 1,
        "splat_url": splat_url,
        "dataparser": dp,
        "up": [float(up_vec[0]), float(up_vec[1]), float(up_vec[2])],
        "align": {"rotation_xyzw": align_quat},
        "spawn": {
            "position": [float(spawn_pos[0]), float(spawn_pos[1]), float(spawn_pos[2])],
            "rotation_xyzw": spawn_quat,
            "eye_height": float(eye),
            "node_id": mid,
        },
        "bounds": {
            "min": [float(x) for x in lo_g],
            "max": [float(x) for x in hi_g],
            "walkable": {
                "type": "camera_tube",
                "path": path,
                "radius": radius,
                "min": [float(x) for x in lo_c],
                "max": [float(x) for x in hi_c],
            },
        },
        "graph": {"nodes": nodes, "edges": edges_u},
        "rooms": [
            {
                "id": room_id,
                "name": room_name,
                "spawn_node_id": mid,
                "bounds": {"min": [float(x) for x in lo_g], "max": [float(x) for x in hi_g]},
            }
        ],
        "hotspots": [],
        "viewer_defaults": {
            "mode": "STANDPOINT",
            "fov_deg": 70,
            "move_speed": 1.0,
            "lerp_seconds": 1.2,
        },
        "meta": {
            "n_train_cameras": len(C_v),
            "n_graph_nodes": len(nodes),
            "n_gaussians_sampled": int(len(P)),
            "splat_gaussians": n,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--transforms", type=Path, required=True)
    p.add_argument("--splat", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--dataparser", type=Path, default=None)
    p.add_argument("--splat-url", default="/splats/kitchen.splat")
    p.add_argument("--room-id", default="kitchen")
    p.add_argument("--room-name", default="Kitchen")
    args = p.parse_args()
    m = bake(
        args.transforms,
        args.splat,
        args.out,
        args.dataparser,
        args.splat_url,
        args.room_id,
        args.room_name,
    )
    print(f"wrote {args.out} nodes={m['meta']['n_graph_nodes']} gaussians={m['meta']['splat_gaussians']}")


if __name__ == "__main__":
    main()
