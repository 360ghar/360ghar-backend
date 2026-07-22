"""
Splat cleanup & room cuboid constraints.

Targets the failure modes we saw on indoor 360 GS:
  - constellation floaters / spikes outside the room volume
  - residual people / hair blobs
  - mirror-reflected ghost geometry
  - open unbounded splat clouds instead of closed rooms

Methods (practical subset of TIDI-GS + SuperSplat-style cleanup):
  1. Opacity / scale filters
  2. Statistical isolation (kNN distance → remove lonely spikes)
  3. DBSCAN-ish density core (keep largest connected dense component)
  4. Floor-plane RANSAC + gravity align
  5. Percentile axis-aligned cuboid clip (closed room)
  6. Optional soft wall shell: densify near faces of the cuboid so rooms read as closed boxes

Pure numpy — runs locally or inside Modal after export.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

SPLAT_DT = np.dtype(
    [
        ("pos", np.float32, (3,)),
        ("scale", np.float32, (3,)),
        ("color", np.uint8, (4,)),
        ("rot", np.uint8, (4,)),
    ]
)


@dataclass
class CleanupReport:
    input_count: int
    output_count: int
    steps: list[str]
    cuboid_min: Optional[list[float]] = None
    cuboid_max: Optional[list[float]] = None

    def as_dict(self) -> dict:
        return {
            "input_count": self.input_count,
            "output_count": self.output_count,
            "kept_ratio": self.output_count / max(self.input_count, 1),
            "steps": self.steps,
            "cuboid_min": self.cuboid_min,
            "cuboid_max": self.cuboid_max,
        }


def load_splat(path: Path | str) -> np.ndarray:
    path = Path(path)
    buf = path.read_bytes()
    n = len(buf) // 32
    if n == 0:
        raise ValueError(f"Empty splat: {path}")
    return np.frombuffer(buf[: n * 32], dtype=SPLAT_DT).copy()


def save_splat(path: Path | str, data: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.tobytes())


def filter_opacity_scale(
    data: np.ndarray,
    *,
    min_alpha: int = 24,
    max_scale: float = 0.35,
    min_scale: float = 1e-5,
) -> np.ndarray:
    """Drop transparent / huge spike gaussians (classic SuperSplat cleanup)."""
    a = data["color"][:, 3]
    smax = data["scale"].max(axis=1)
    keep = (a >= min_alpha) & (smax <= max_scale) & (smax >= min_scale)
    return data[keep]


def filter_isolation_knn(
    data: np.ndarray,
    *,
    k: int = 12,
    max_median_nn: Optional[float] = None,
    sample_cap: int = 25_000,
) -> np.ndarray:
    """
    Remove constellation spikes via fast voxel-density (O(n)).

    Points in voxels with fewer than `min_count` neighbors are dropped.
    (Name kept for API stability; no longer brute-force kNN.)
    """
    if len(data) < 500:
        return data

    pos = data["pos"].astype(np.float64)
    extent = np.percentile(pos, 95, axis=0) - np.percentile(pos, 5, axis=0)
    scene = float(np.linalg.norm(extent) + 1e-6)
    voxel = max(scene / 55.0, 0.03)

    q = np.floor(pos / voxel).astype(np.int64)
    # pack to 1d key
    q = q - q.min(axis=0)
    keys = q[:, 0] + q[:, 1] * 4096 + q[:, 2] * 4096 * 4096
    _, inv, counts = np.unique(keys, return_inverse=True, return_counts=True)
    # keep points in voxels with at least 2 occupants (kills lone spikes)
    min_count = 2
    keep = counts[inv] >= min_count
    # also drop if in a voxel whose 3x3x3 neighborhood is almost empty
    # (cheap: require voxel count >= 2 already sufficient for constellation)
    _ = k, max_median_nn, sample_cap  # API compat
    return data[keep]


def keep_largest_dense_core(
    data: np.ndarray,
    *,
    voxel: Optional[float] = None,
    min_voxel_count: int = 3,
) -> np.ndarray:
    """
    Voxelize and keep only the largest 6-connected component of occupied voxels.
    Kills satellite clusters (mirror ghosts / outdoor spikes).
    """
    if len(data) < 200:
        return data

    pos = data["pos"].astype(np.float64)
    # adaptive voxel size from scene scale
    extent = np.percentile(pos, 95, axis=0) - np.percentile(pos, 5, axis=0)
    scene = float(np.linalg.norm(extent))
    if voxel is None:
        voxel = max(scene / 40.0, 0.04)
    voxel = float(voxel)

    q = np.floor(pos / voxel).astype(np.int32)
    # shift to positive
    q_min = q.min(axis=0)
    q = q - q_min

    # count per voxel
    # pack keys
    qx, qy, qz = q[:, 0], q[:, 1], q[:, 2]
    # hash
    keys = qx.astype(np.int64) * 73856093 ^ qy.astype(np.int64) * 19349663 ^ qz.astype(np.int64) * 83492791
    uniq, inv, counts = np.unique(keys, return_inverse=True, return_counts=True)
    dense_voxel = counts[inv] >= min_voxel_count

    # Build adjacency of dense voxels via dict
    dense_ids = np.where(counts >= min_voxel_count)[0]
    if len(dense_ids) == 0:
        return data

    # map key -> component via BFS
    key_to_idx = {int(uniq[i]): i for i in dense_ids}
    # reverse coords for each unique dense key
    # reconstruct one coord per unique key
    # pick first occurrence
    first = {}
    for i, k in enumerate(keys):
        ki = int(k)
        if ki in key_to_idx and ki not in first:
            first[ki] = (int(qx[i]), int(qy[i]), int(qz[i]))

    # BFS
    from collections import deque

    visited: dict[int, int] = {}
    comp_sizes: dict[int, int] = {}
    cid = 0
    neighbors = [
        (1, 0, 0),
        (-1, 0, 0),
        (0, 1, 0),
        (0, -1, 0),
        (0, 0, 1),
        (0, 0, -1),
    ]
    # index coords -> key for neighbors
    coord_to_key = {v: k for k, v in first.items()}

    for start_key, start_coord in first.items():
        if start_key in visited:
            continue
        dq = deque([start_key])
        visited[start_key] = cid
        size = 0
        while dq:
            k = dq.popleft()
            size += int(counts[key_to_idx[k]])
            c = first[k]
            for d in neighbors:
                nc = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                nk = coord_to_key.get(nc)
                if nk is not None and nk not in visited:
                    visited[nk] = cid
                    dq.append(nk)
        comp_sizes[cid] = size
        cid += 1

    if not comp_sizes:
        return data
    best = max(comp_sizes, key=comp_sizes.get)
    keep_keys = {k for k, c in visited.items() if c == best}
    keep = np.array([int(k) in keep_keys for k in keys], dtype=bool)
    # also keep non-dense points that fall inside dense voxels of best component? already only dense
    # include borderline: points whose voxel is in best component
    return data[keep]


def fit_floor_plane_ransac(
    pos: np.ndarray,
    *,
    iters: int = 200,
    thresh: float = 0.04,
) -> tuple[np.ndarray, float]:
    """
    Fit plane n·x + d = 0 to lower half of points (floor bias).
    Returns (unit normal pointing "up", d).
    """
    if len(pos) < 50:
        return np.array([0.0, 1.0, 0.0]), 0.0

    # bias toward lower points by Y (nerfstudio often Y-up) and by all axes fallback
    # try assuming largest variance horizontal
    var = pos.var(axis=0)
    up_axis = int(np.argmin(var))  # floor normal often lowest variance for indoor walk
    # take bottom 40% along that axis as floor candidates
    col = pos[:, up_axis]
    thr_y = np.percentile(col, 40)
    cand = pos[col <= thr_y]
    if len(cand) < 30:
        cand = pos

    rng = np.random.default_rng(1)
    best_inliers = 0
    best_n = np.array([0.0, 1.0, 0.0])
    best_d = 0.0

    for _ in range(iters):
        if len(cand) < 3:
            break
        ids = rng.choice(len(cand), 3, replace=False)
        p0, p1, p2 = cand[ids]
        n = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(n)
        if norm < 1e-8:
            continue
        n = n / norm
        d = -float(np.dot(n, p0))
        dist = np.abs(pos @ n + d)
        inl = int((dist < thresh).sum())
        if inl > best_inliers:
            best_inliers = inl
            best_n, best_d = n, d

    # orient normal so majority of points are on the + side (inside room above floor)
    if (pos @ best_n + best_d).mean() < 0:
        best_n = -best_n
        best_d = -best_d
    return best_n.astype(np.float64), float(best_d)


def rotation_align_up(normal: np.ndarray, target_up: np.ndarray = None) -> np.ndarray:
    """3x3 rotation taking `normal` → +Y (viewer/nerfstudio up)."""
    if target_up is None:
        target_up = np.array([0.0, 1.0, 0.0])
    n = normal / (np.linalg.norm(normal) + 1e-12)
    t = target_up / (np.linalg.norm(target_up) + 1e-12)
    v = np.cross(n, t)
    c = float(np.dot(n, t))
    if c < -0.999:
        # 180° — pick orthogonal axis
        axis = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
        axis = axis - n * np.dot(axis, n)
        axis = axis / (np.linalg.norm(axis) + 1e-12)
        K = np.array(
            [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]],
            dtype=np.float64,
        )
        return np.eye(3) + 2 * K @ K
    s = np.linalg.norm(v)
    if s < 1e-12:
        return np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]], dtype=np.float64)
    R = np.eye(3) + K + K @ K * ((1 - c) / (s**2 + 1e-12))
    return R


def align_to_floor(data: np.ndarray) -> np.ndarray:
    """Rotate so floor normal → +Y; shift floor to y≈0.

    Skips alignment when the cloud is nearly planar / degenerate (e.g. short
    hallway clips) — rotating those collapses the room into a pancake.
    """
    data = data.copy()
    pos = data["pos"].astype(np.float64)
    extent = np.percentile(pos, 95, axis=0) - np.percentile(pos, 5, axis=0)
    sorted_ext = np.sort(extent)
    # Need a true 3D volume (short hallway clips are ~planar curtains)
    if sorted_ext[0] < 0.35 or sorted_ext[1] < 0.5 or sorted_ext[2] < 0.8:
        return data

    n, _d = fit_floor_plane_ransac(pos)
    R = rotation_align_up(n)
    pos2 = (pos @ R.T).astype(np.float64)
    ext2 = np.percentile(pos2, 95, axis=0) - np.percentile(pos2, 5, axis=0)
    # Reject if any axis collapsed or volume crushed
    if float(np.min(ext2)) < 0.5 * float(np.min(extent)):
        return data
    if float(np.prod(np.maximum(ext2, 1e-3))) < 0.5 * float(np.prod(np.maximum(extent, 1e-3))):
        return data

    pos2 = pos2.astype(np.float32)
    floor_y = np.percentile(pos2[:, 1], 5)
    pos2[:, 1] -= floor_y
    data["pos"] = pos2
    return data


def cuboid_clip(
    data: np.ndarray,
    *,
    low_pct: float = 3.0,
    high_pct: float = 97.0,
    pad_frac: float = 0.04,
    closed: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Clip to a percentile AABB = closed room cuboid.

    Returns (filtered_data, cuboid_min, cuboid_max).
    """
    pos = data["pos"]
    lo = np.percentile(pos, low_pct, axis=0)
    hi = np.percentile(pos, high_pct, axis=0)
    span = np.maximum(hi - lo, 1e-3)
    pad = span * pad_frac
    lo = lo - pad
    hi = hi + pad

    if closed:
        # tighten slightly on horizontal to kill wall spikes
        lo[0] += span[0] * 0.01
        hi[0] -= span[0] * 0.01
        lo[2] += span[2] * 0.01
        hi[2] -= span[2] * 0.01

    keep = np.all((pos >= lo) & (pos <= hi), axis=1)
    return data[keep], lo.astype(np.float32), hi.astype(np.float32)


def filter_skin_like_outliers(data: np.ndarray) -> np.ndarray:
    """
    Heuristic: transient people leave mid-opacity flesh-tone floaters.
    Drop skin-colored gaussians that sit in low-density voxels.
    """
    if len(data) < 100:
        return data
    c = data["color"][:, :3].astype(np.float32)
    a = data["color"][:, 3]
    r, g, b = c[:, 0], c[:, 1], c[:, 2]
    skin = (r > 80) & (g > 40) & (b > 30) & (r > g) & (g > b) & ((r - b) > 20) & (a < 200)
    if not skin.any():
        return data
    pos = data["pos"].astype(np.float64)
    extent = np.percentile(pos, 95, axis=0) - np.percentile(pos, 5, axis=0)
    voxel = max(float(np.linalg.norm(extent)) / 50.0, 0.04)
    q = np.floor(pos / voxel).astype(np.int64)
    q = q - q.min(axis=0)
    keys = q[:, 0] + q[:, 1] * 4096 + q[:, 2] * 4096 * 4096
    _, inv, counts = np.unique(keys, return_inverse=True, return_counts=True)
    # drop skin in sparse voxels only (preserve skin-toned walls/furniture in dense areas)
    drop = skin & (counts[inv] <= 4)
    return data[~drop]


def filter_strokes(
    data: np.ndarray,
    *,
    max_aspect: float = 6.0,
    max_scale: float = 0.12,
) -> np.ndarray:
    """
    Kill "endless stroke" Gaussians: highly anisotropic scales that look like
    random brush marks through the room (common 3DGS floater mode).

    Room1 analysis showed ~40% of gaussians with aspect > 8 — those are the strokes.
    """
    if len(data) == 0:
        return data
    s = data["scale"].astype(np.float64)
    smax = s.max(axis=1)
    smin = s.min(axis=1) + 1e-8
    aspect = smax / smin
    keep = (aspect <= max_aspect) & (smax <= max_scale)
    # always keep a minimum fraction so we never empty the room
    if keep.sum() < max(500, int(0.15 * len(data))):
        # fall back to milder aspect cut
        keep = (aspect <= max_aspect * 2.5) & (smax <= max_scale * 2.0)
    return data[keep]


def densify_cuboid_shell(
    data: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    *,
    n_per_face: int = 800,
    shell_alpha: int = 40,
    include_floor_ceiling: bool = True,
) -> np.ndarray:
    """
    Add a sparse low-alpha shell on cuboid faces so rooms read as closed boxes.
    Floor (Y min) and ceiling (Y max) get denser sampling — empty poles are the
    #1 complaint after strokes.
    """
    if len(data) == 0:
        return data
    rng = np.random.default_rng(3)
    faces = []
    # axis 0=X walls, 1=Y floor/ceil, 2=Z walls
    for axis in range(3):
        for is_hi in (False, True):
            n = n_per_face
            if axis == 1:
                if not include_floor_ceiling:
                    continue
                n = n_per_face * 3  # denser floor/ceiling
            pts = rng.random((n, 3))
            for a in range(3):
                if a == axis:
                    pts[:, a] = hi[a] if is_hi else lo[a]
                else:
                    pts[:, a] = lo[a] + pts[:, a] * (hi[a] - lo[a])
            faces.append((pts, axis, is_hi))

    shell_pos = np.concatenate([f[0] for f in faces], axis=0).astype(np.float32)
    shell = np.zeros(len(shell_pos), dtype=SPLAT_DT)
    shell["pos"] = shell_pos

    # Color: sample from nearest height band (floor colors from lower third, etc.)
    pos = data["pos"]
    y = pos[:, 1]
    y_lo, y_hi = np.percentile(y, [15, 85])
    low_idx = np.where(y <= y_lo)[0]
    mid_idx = np.where((y > y_lo) & (y < y_hi))[0]
    high_idx = np.where(y >= y_hi)[0]
    if len(low_idx) == 0:
        low_idx = np.arange(len(data))
    if len(mid_idx) == 0:
        mid_idx = np.arange(len(data))
    if len(high_idx) == 0:
        high_idx = np.arange(len(data))

    colors = np.zeros((len(shell_pos), 4), dtype=np.uint8)
    offset = 0
    for pts, axis, is_hi in faces:
        n = len(pts)
        if axis == 1 and not is_hi:
            pool = low_idx  # floor
        elif axis == 1 and is_hi:
            pool = high_idx  # ceiling
        else:
            pool = mid_idx
        pick = rng.choice(pool, size=n, replace=True)
        colors[offset : offset + n] = data["color"][pick]
        # floor/ceiling more opaque; side walls ghost
        if axis == 1:
            colors[offset : offset + n, 3] = np.uint8(min(220, shell_alpha + 120))
        else:
            colors[offset : offset + n, 3] = np.uint8(shell_alpha)
        offset += n

    shell["color"] = colors
    # Flatten scales on the plane normal direction for each face
    base_s = float(np.median(data["scale"].max(axis=1))) * 0.6
    base_s = float(np.clip(base_s, 0.008, 0.05))
    scales = np.full((len(shell_pos), 3), base_s, dtype=np.float32)
    offset = 0
    for pts, axis, is_hi in faces:
        n = len(pts)
        scales[offset : offset + n, axis] = base_s * 0.15  # thin along face normal
        offset += n
    shell["scale"] = scales
    shell["rot"] = np.uint8([128, 128, 128, 255])
    return np.concatenate([data, shell])


def detect_up_axis(pos: np.ndarray) -> int:
    """
    Guess gravity / floor normal axis (0=X, 1=Y, 2=Z).

    Heuristic used by many indoor GS cleaners:
    - After a decent reconstruct, the *height* axis often has the largest span
      OR is the PCA component with most variance in wall colors...
    - Better: the axis along which the two extreme *slabs* are the most planar
      (floor/ceiling) vs the other faces (walls with furniture clutter).

    User feedback: hardcoding Y put poles on the wrong faces ("third option" = Z).
    So we score each axis and pick the best floor-pair.
    """
    if len(pos) < 100:
        return 1  # nerfstudio default Y-up fallback

    best_ax = 1
    best_score = -1e9
    for ax in range(3):
        c = pos[:, ax]
        lo_p, hi_p = np.percentile(c, [8, 92])
        span = float(hi_p - lo_p) + 1e-6
        # slabs near extremes
        thr = 0.08 * span
        low = pos[c <= lo_p + thr]
        high = pos[c >= hi_p - thr]
        if len(low) < 30 or len(high) < 30:
            continue
        # planarity of each slab: variance on the other two axes should dominate;
        # variance on `ax` inside slab should be tiny
        def slab_planarity(slab: np.ndarray) -> float:
            v = slab.var(axis=0)
            return float(v.sum() - v[ax]) / (float(v[ax]) + 1e-6)

        # also prefer axes where extremes are relatively empty of "volume"
        # (true floors often under-sampled → lower count at extremes vs mid)
        mid = pos[(c > lo_p + 0.3 * span) & (c < hi_p - 0.3 * span)]
        empty_poles = 1.0 - (len(low) + len(high)) / (len(pos) + 1e-6)

        score = slab_planarity(low) + slab_planarity(high) + 2.0 * empty_poles + 0.1 * span
        if score > best_score:
            best_score = score
            best_ax = ax
    return int(best_ax)


def fill_floor_ceiling_disks(
    data: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    *,
    n_floor: int = 12000,
    n_ceil: int = 8000,
    up_axis: Optional[int] = None,
    grid_res: int = 96,
) -> np.ndarray:
    """
    Refined floor + ceiling as a *dense regular grid* of flat Gaussians.

    Not random dots: overlapping soft disks on a lattice, colors bilinearly
    sampled from nearest real points projected onto the plane.
    Auto-detects which axis is up (X/Y/Z) so poles land on floor/ceiling.
    """
    import math

    if len(data) < 50:
        return data

    pos = data["pos"].astype(np.float64)
    if up_axis is None:
        up_axis = detect_up_axis(pos)
    print(f"  floor/ceiling up_axis={up_axis} ({'XYZ'[up_axis]})", flush=True)

    # horizontal axes
    h_axes = [a for a in range(3) if a != up_axis]
    a0, a1 = h_axes

    floor_u = float(lo[up_axis] + 0.015 * (hi[up_axis] - lo[up_axis]))
    ceil_u = float(hi[up_axis] - 0.015 * (hi[up_axis] - lo[up_axis]))

    # color pools from points near each pole of the up axis
    c = pos[:, up_axis]
    lo_p, hi_p = np.percentile(c, [20, 80])
    floor_pool = data["color"][c <= lo_p] if np.any(c <= lo_p) else data["color"]
    ceil_pool = data["color"][c >= hi_p] if np.any(c >= hi_p) else data["color"]
    # ceiling bias to brighter
    if len(ceil_pool):
        bright = ceil_pool[:, :3].astype(np.float32).mean(1) > 70
        if bright.any():
            ceil_pool = ceil_pool[bright]

    def _grid_plane(u0: float, color_pool: np.ndarray, n_target: int) -> np.ndarray:
        # lattice resolution
        res = max(16, int(math.sqrt(n_target)))
        u = np.linspace(lo[a0], hi[a0], res)
        v = np.linspace(lo[a1], hi[a1], res)
        uu, vv = np.meshgrid(u, v, indexing="xy")
        pts = np.zeros((res * res, 3), dtype=np.float64)
        pts[:, a0] = uu.ravel()
        pts[:, a1] = vv.ravel()
        pts[:, up_axis] = u0

        # Nearest-neighbor color from real cloud projected (ignore up axis)
        ref = pos.copy()
        ref[:, up_axis] = 0
        query = pts.copy()
        query[:, up_axis] = 0
        # subsample ref for speed
        rng = np.random.default_rng(11)
        if len(ref) > 8000:
            idx = rng.choice(len(ref), 8000, replace=False)
            ref_s = ref[idx]
            col_s = data["color"][idx]
        else:
            ref_s = ref
            col_s = data["color"]

        # chunked NN
        colors = np.zeros((len(pts), 4), dtype=np.uint8)
        batch = 2000
        for i in range(0, len(pts), batch):
            q = query[i : i + batch]
            d2 = ((q[:, None, :] - ref_s[None, :, :]) ** 2).sum(axis=2)
            nn = d2.argmin(axis=1)
            colors[i : i + batch] = col_s[nn]
            # blend toward pool median for empty regions far from any point
            med = np.median(color_pool[:, :3].astype(np.float32), axis=0)
            far = np.sqrt(d2.min(axis=1)) > 0.25 * float(np.linalg.norm(hi - lo))
            for j, is_far in enumerate(far):
                if is_far:
                    colors[i + j, :3] = (
                        0.4 * colors[i + j, :3].astype(np.float32) + 0.6 * med
                    ).astype(np.uint8)
            colors[i : i + batch, 3] = 230

        # gentle spatial blur of colors on the grid (refine "not dots")
        grid_c = colors[:, :3].reshape(res, res, 3).astype(np.float32)
        # 3x3 box blur
        for _ in range(2):
            pad = np.pad(grid_c, ((1, 1), (1, 1), (0, 0)), mode="edge")
            acc = np.zeros_like(grid_c)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    acc += pad[1 + dy : 1 + dy + res, 1 + dx : 1 + dx + res]
            grid_c = acc / 9.0
        colors[:, :3] = grid_c.reshape(-1, 3).astype(np.uint8)

        out = np.zeros(len(pts), dtype=SPLAT_DT)
        out["pos"] = pts.astype(np.float32)
        # scale: spacing so disks *overlap* (smooth surface, not sparkle)
        spacing = float(max(hi[a0] - lo[a0], hi[a1] - lo[a1]) / max(res - 1, 1))
        s_h = spacing * 0.75
        s_n = spacing * 0.08  # thin along normal
        scale = np.array([s_h, s_h, s_h], dtype=np.float32)
        scale[up_axis] = s_n
        out["scale"] = np.tile(scale, (len(pts), 1))
        out["color"] = colors
        out["rot"] = np.tile(np.array([[128, 128, 128, 255]], dtype=np.uint8), (len(pts), 1))
        return out

    floor = _grid_plane(floor_u, floor_pool, n_floor)
    ceil = _grid_plane(ceil_u, ceil_pool, n_ceil)
    return np.concatenate([data, floor, ceil])


def clean_room_splat(
    data: np.ndarray,
    *,
    aggressive: bool = True,
    add_shell: bool = True,
    align_floor: bool = True,
    kill_strokes: bool = True,
    fill_poles: bool = True,
) -> tuple[np.ndarray, CleanupReport]:
    """
    Full cleanup pipeline → closed cuboid room, fewer strokes, filled floor/ceiling.
    """
    steps: list[str] = []
    n0 = len(data)
    report = CleanupReport(input_count=n0, output_count=n0, steps=steps)

    data = filter_opacity_scale(
        data,
        min_alpha=22 if aggressive else 12,
        max_scale=0.20 if aggressive else 0.45,
    )
    steps.append(f"opacity_scale→{len(data)}")

    if kill_strokes:
        data = filter_strokes(
            data,
            max_aspect=5.5 if aggressive else 8.0,
            max_scale=0.09 if aggressive else 0.15,
        )
        steps.append(f"strokes→{len(data)}")

    if align_floor and len(data) > 200:
        data = align_to_floor(data)
        steps.append("floor_align")

    data = filter_skin_like_outliers(data)
    steps.append(f"skin_outliers→{len(data)}")

    try:
        data = filter_isolation_knn(data, k=10)
        steps.append(f"isolation_knn→{len(data)}")
    except Exception as e:
        steps.append(f"isolation_knn_skip:{e}")

    try:
        data = keep_largest_dense_core(data, min_voxel_count=2 if aggressive else 1)
        steps.append(f"dense_core→{len(data)}")
    except Exception as e:
        steps.append(f"dense_core_skip:{e}")

    data, lo, hi = cuboid_clip(
        data,
        low_pct=4.0 if aggressive else 2.0,
        high_pct=96.0 if aggressive else 98.0,
        pad_frac=0.03,
        closed=True,
    )
    steps.append(f"cuboid_clip→{len(data)}")

    # recentre cuboid for viewer comfort
    center = (lo + hi) * 0.5
    data = data.copy()
    data["pos"] = data["pos"] - center.astype(np.float32)
    lo = lo - center
    hi = hi - center
    report.cuboid_min = lo.tolist()
    report.cuboid_max = hi.tolist()
    steps.append("recenter")

    if fill_poles and len(data) > 100:
        data = fill_floor_ceiling_disks(
            data, lo, hi,
            n_floor=5000 if aggressive else 3000,
            n_ceil=3000 if aggressive else 2000,
        )
        steps.append(f"floor_ceil_fill→{len(data)}")

    if add_shell and len(data) > 100:
        data = densify_cuboid_shell(
            data, lo, hi,
            n_per_face=500 if aggressive else 350,
            shell_alpha=35,
            include_floor_ceiling=False,  # already filled denser disks
        )
        steps.append(f"wall_shell→{len(data)}")

    report.output_count = len(data)
    report.steps = steps
    return data, report


def clean_splat_file(
    in_path: Path | str,
    out_path: Path | str,
    **kwargs,
) -> CleanupReport:
    data = load_splat(in_path)
    cleaned, report = clean_room_splat(data, **kwargs)
    save_splat(out_path, cleaned)
    return report


if __name__ == "__main__":
    import json
    import sys

    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "/Users/chiragsingh/Desktop/360-tours/public/splats/room1.splat"
    )
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name(src.stem + "_clean.splat")
    rep = clean_splat_file(src, dst, aggressive=True, add_shell=True)
    print(json.dumps(rep.as_dict(), indent=2))
    print(f"Wrote {dst}")
