# Splat Pipeline v2 — Closed Rooms, Less Constellation

## What went right (v1 multi-view)

- **room1** and **connected_tour** recovered real indoor signal: geyser, mug, curtain, marble palette.
- Multi-yaw equirect unwrap fixed the “abstract soup” from single-forward crops.
- Joint SfM across room1→hallway→room2 preserved **doorway connectivity**.

## What still failed

| Artifact | Cause | v2 fix |
|----------|--------|--------|
| Constellation spikes | Under-constrained GS + no post prune | Voxel density + largest dense core + cuboid clip |
| People / hair ghosts | Transient subjects in every frame | HOG + skin mask on equirect; skin-floater prune |
| Mirror cabinets | Multi-view inconsistency | Specular vertical-strip darkening |
| Camera shake / blur | Bad poses & smeared Gaussians | Optical-flow shake score + Laplacian |
| Open unbounded cloud | No room prior | Floor align + closed cuboid + optional shell |

## Pipeline stages (v2)

```
360 clip(s)
  → fps sample + 2:1 equirect normalize
  → sharp+shake filter
  → mask people / skin / mirrors / nadir
  → 6× yaw perspective faces (90°×75°)
  → COLMAP (sequential → exhaustive fallback)
  → splatfacto train
  → PLY → .splat
  → clean_room_splat():
        opacity/scale → floor RANSAC align
        → skin outliers → voxel isolation
        → largest dense core
        → percentile cuboid clip (closed room)
        → recenter → optional wall shell
  → room1.splat / connected_tour.splat / …
```

## Files

| Path | Role |
|------|------|
| `app/services/modal_worker.py` | GPU train + pre-masks + export |
| `app/services/splat_cleanup.py` | Post cuboid / floater cleanup (CPU) |
| `run_clip_pipeline.py` | End-to-end Modal run for 3 clips |
| `run_clean_existing.py` | Clean already-trained splats (no GPU) |

## Commands

```bash
# Clean current outputs → *_v2.splat (instant)
python run_clean_existing.py

# Retrain with v2 masks (Modal GPU)
SPLAT_QUALITY=balanced python run_clip_pipeline.py
```

## Viewing priority

1. `connected_tour_v2.splat` — joint walk, cleaned cuboid  
2. `room1_v2.splat` — best single-room detail  
3. `connected_rooms_cuboid.splat` — layout-stitched closed rooms  

## Research notes

- Floater prune inspired by **TIDI-GS** (view consistency / importance) — we use spatial density proxies that run offline without retraining.
- Dynamic object removal literature: segment-then-inpaint before SfM; we black-mask (COLMAP ignores black regions poorly — better future: binary masks via nerfstudio).
- Mirrors remain the hardest indoor case; full fix needs semantic mirror detection + reflection ray exclusion (open research).

## Next experiments

1. YOLO/SAM person+mirror masks → true alpha masks in COLMAP  
2. Longer hallway capture (≥15s with forward motion)  
3. `quality` preset (20k iters) on room1 only  
4. Collision mesh from densified COLMAP points inside cuboid  
