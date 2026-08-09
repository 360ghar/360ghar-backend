# v3 Diagnosis — Why only room1 “works”

## Honest post-mortem

| Asset | Verdict | Why |
|-------|---------|-----|
| **room1** | Shape + cuboid + artifacts OK; **strokes** ruin presentability | Enough parallax in bathroom; strokes = anisotropic Gaussians (~40% aspect>8) |
| **hallway** | Unrecognizable | ~5s clip, almost no translation; curtains + mirror; COLMAP sees a plane |
| **room2** | Unrecognizable | Short walk, low baseline, floaters dominate |
| **“connection”** | **User was right to walk this back** | Not true multi-room SfM — room1 bleed into doorway looked like a hall |

Cuboid confinement **does not invent geometry**. It only clips garbage. If the reconstruct is a curtain plane, the cuboid is a flat box of curtain.

## Math that is still wrong for short clips

COLMAP + 3DGS needs **parallax** (camera translation). Multi-yaw faces from the *same* pose share a **zero baseline** — they help angular coverage, not depth.

```
Good depth ⇔ motion between frames
room1: person/camera moves enough → structure
hallway/room2: too little motion → underconstrained depth → noise soup
```

## Empty floor / ceiling

1. Equirect **nadir** = operator (we dim/mask it) → no floor features for SfM  
2. Virtual cameras were **pitch=0 only** → never look at floor/ceiling hard  
3. GS cannot densify what it never saw  

**v3 capture fix:** pitch grid `(-35°, 0°, +28°)` + soft person mask (not floor wipe).  
**v3 presentability fix:** post densify floor/ceiling disks colored from nearby real splats.

## Strokes (room1)

Highly elongated Gaussians (`scale_max / scale_min ≫ 1`) look like random brush strokes.  
**Fix:** drop aspect > ~5.5 and max_scale cap before show.

## Path forward (redo for hall/room2)

### A. Capture / selection (required)
- Longer clips with deliberate **slow orbit or walk** (≥15–20s, continuous translation)
- Frame scorer: sharpness × parallax (optical flow) — reject static bursts

### B. Depth-prior pipeline (for low-parallax video)
Research: Mode-GS / MoDGS / monocular-depth-anchored 3DGS  
1. Monocular depth per frame (Depth Anything)  
2. Scale-align depths across frames  
3. Unproject → init Gaussians  
4. Short splatfacto refine  
This is the correct math when COLMAP has no baseline.

### C. AI gap-fill (presentability, not metrology)
- Floor/ceiling plane fill (implemented offline now)  
- Later: generative inpaint of missing wall regions, or layout-conditioned room boxes with photoreal materials seeded from keyframes  

### D. Multi-room connection (real)
Do **not** ICP whole rooms.  
1. Reconstruct each room only when quality gate passes (min points, min volume, max stroke ratio)  
2. Joint frames only across **doorway transition** windows  
3. Layout graph: cuboid rooms + portal transforms from door detections  

## Quality gate (reject bad rooms)

A clip is “presentable” only if after train+cleanup:
- Gaussian count ≥ 40k  
- Cuboid volume ≥ threshold  
- Stroke ratio (aspect>8) ≤ 15%  
- At least 2 axes of extent ≥ 0.8  

Hallway/room2 currently **fail** this gate → should not be shown as rooms.

## What to open today

1. `room1_presentable.splat` — strokes cut + floor/ceiling fill (best single room)  
2. Do **not** present hallway/room2 until depth-prior redo  
