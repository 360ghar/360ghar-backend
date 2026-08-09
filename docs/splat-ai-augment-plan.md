# Innovation plan: AI multi-view augmentation → Matterport-class rooms

## Why we are stuck

| Level | What we have | Gap vs SuperSplat / Matterport |
|-------|----------------|--------------------------------|
| Capture | 5–10s 360 clips | Need dense multi-view with **translation** |
| SfM | COLMAP on few frames | Fails without parallax (hallway/room2) |
| GS train | splatfacto | Garbage in → strokes/floaters out |
| Post | Cuboid + floor dots | Polish only — **cannot invent missing surfaces** |

Cuboid confinement is correct for *clipping*. It will never produce PlayCanvas-demo quality from a failed reconstruct.

## Your idea (correct direction)

> Generate more images from collected frames at different levels/angles so math has enough data.

That is **novel-view expansion**. Industry/research paths:

1. **Spherical free views** (free, exact): more yaw×pitch from equirect — we under-used this.
2. **Depth warp + inpaint** (geometry-aware): monocular depth → reproject to new camera → fill holes (Mode-GS / depth-anchored 3DGS family).
3. **Video generative multi-view** (ViewCrafter, CameraCtrl, CAT3D): AI invents angles with weak 3D consistency — use as *supplement*, not sole truth.
4. **Layout + generative fill** (last resort): empty poles get material from AI texture, not freeform geometry.

## What we implemented

| Module | Role |
|--------|------|
| `app/services/splat_view_augment.py` | Keyframes → dense yaw×pitch + parallax warps + AI hook |
| `estimate_clip_parallax_score()` | Gate: static → depth-prior path; ok → COLMAP |
| Floor fill v2 | Auto up-axis + **dense lattice** (not random dots) + color NN + blur |
| `modal_worker` pitch grid | Floor/ceiling looking cameras in train |

## Recommended production pipeline (v3)

```
clip
  → parallax score
  → if weak: depth-anything (Modal GPU) + warp novel baselines
  → always: spherical yaw×pitch grid (8×5)
  → optional: 2–4 AI elevated/lowered views (texture only)
  → COLMAP / ns-process-data
  → splatfacto (balanced+)
  → stroke filter + lattice floor/ceiling on detected up-axis
  → quality gate (else reject room, don't ship)
```

## Quality gate (do not show bad rooms)

- ≥ 40k gaussians after train  
- stroke ratio (aspect>8 among non-flat) < 12%  
- extent ≥ 0.8 on ≥ 2 axes  
- user-facing only if gate passes  

Hallway/room2 currently fail → hide until depth-prior retrain.

## Next implementation steps

1. Modal job: Depth-Anything-V2 + warp ±0.15m baselines on room1  
2. Wire `augment_video_to_images` into `train_splat` before COLMAP  
3. Gemini/Imagen multi-angle only after depth warps exist  
4. Per-room cuboids (hallway shorter) — don't force one mega-box  

## Honest Matterport bar

Matterport uses **structured capture** (tripod stations, depth sensors / multi-cam).  
We are reverse-engineering that from a casual 360 walk. Closing the gap requires **data volume + geometric multi-view**, not more post-FX. AI image expansion is the right innovation **if** paired with depth/spherical constraints so COLMAP still gets consistent rays.
