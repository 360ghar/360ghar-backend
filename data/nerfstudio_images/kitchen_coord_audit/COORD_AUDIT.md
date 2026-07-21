# Kitchen coordinate audit (no retrain)

## Verdict (preliminary, from local .splat + downloaded transforms)

**The reconstruction is complete and in a coherent coordinate frame.**
The “dense blob” is the **outside view of a hollow indoor shell**, not empty geometry and not a double-normalized collapse.

Screenshots match this: exterior = sparkling ball; interior zoom = floor / piano / chairs / walls.

---

## 1. Nerfstudio scene scale

From `config.yml` (job `local-kitchen-8e06a2aa`):

- `auto_scale_poses: true`
- `center_method: poses`
- `orientation_method: up`
- `scale_factor: 1.0` (extra manual scale; auto still applied)
- `scene_scale: 1.0`

## 2–4. Dataparser transform (`dataparser_transforms.json`)

```json
{
  "transform": [
    [
      1.0,
      0.0,
      0.0,
      0.2282285988330841
    ],
    [
      0.0,
      1.0,
      0.0,
      0.503483235836029
    ],
    [
      0.0,
      0.0,
      1.0,
      -0.05465497449040413
    ]
  ],
  "scale": 0.4542773327816838
}
```

- Rotation: **identity** (no axis flip beyond orientation step already baked into poses during train)
- Translation: centers poses near origin ≈ `[-mean_cam]`
- **scale = 0.454277**  (auto_scale_poses so cameras fit training box)

### Camera centers

| space | mean | p1–p99 diameter | extent (xyz) |
|-------|------|-----------------|--------------|
| original `transforms.json` | [-0.228228592749676, -0.503483188745654, 0.05465497178039883] | 4.7946 | [2.868947744369507, 4.290739417076111, 1.823592483997345] |
| after dataparser (s·(Rp+t)) | [2.7635544161017086e-09, 2.1392089969409967e-08, -1.231093977705923e-09] | 2.1781 | [1.3032979292022076, 1.9491856580505722, 0.8284167297110393] |

Original cameras already ~O(1) ARKit/Polycam units (diameter ≈ 4.79), not meters-large.

## 5. scale_factor

- Config `scale_factor: 1.0` — no second manual scale in config.
- Effective scale is **only** dataparser `scale ≈ 0.454` from auto_scale_poses.

## 6. scene_box

Not stored as a separate file; with auto_scale_poses, training uses a **normalized pose box** (~unit scale). Gaussians may extend beyond the camera path (walls outside walk path).

## 7–9. Export path vs .splat

Export pipeline (`export_ply_to_splat`):

1. `ns-export gaussian-splat` → PLY in **training / dataparser coordinates**
2. Read x,y,z as float32 → antimatter15 `.splat` **without further pose transform**
3. `exp(log_scale)` for scales; SH→RGB; sigmoid opacity
4. Light filter: alpha>8, scale in (1e-6, 1.5) — **positions unchanged**
5. `raw_only=True` — **no cuboid recenter** (important: older polish path *did* subtract AABB center)

### .splat measured locally

| metric | value |
|--------|------|
| n gaussians | 1,279,857 |
| mean | [0.27092664071322914, 0.06027848475279618, -0.2837349584087163] |
| std | [1.0997002385528698, 0.9703372590913509, 0.4649169190342133] |
| full extent | [12.252830028533936, 11.491857528686523, 11.792978763580322] |
| p1–p99 diameter | 9.4322 |
| median max-axis scale | 0.006143 |
| extent / median scale | 1535.5 |

## 10. Normalization twice?

| hypothesis | expected diameter | observed | result |
|------------|-------------------|----------|--------|
| Correct once (dataparser only) | ~ few units, ≥ cam path | splat p1–p99 ≈ **9.43**, cam_norm ≈ **2.18** | **MATCH** |
| Scale applied twice | ~ 4.28 | — | **REJECTED** (too large vs double-shrink) |
| Unnormalized meters | tens–hundreds | — | **REJECTED** |

Splat diameter **>** normalized camera diameter (9.43 > 2.18) → room shell correctly larger than walk path.

Exporter does **not** re-apply dataparser scale; PLY→splat is a layout conversion only (pending PLY re-export confirmation from Modal audit script).

---

## Why SuperSplat shows a blob

1. **Indoor GS is a hollow shell.** Outside views look through / at translucent backsides → foggy ball.
2. **Gaussian means are fine** (~diameter 9); **primitive scales are tiny** (~0.006). From far away the shell reads as a dense point cloud ball.
3. **Default viewer camera** sits outside the shell. Zooming **into** the cluster places you inside the kitchen (as in your 1:17 screenshots).
4. This is **viewer framing / interior scene nature**, not failed SfM.

## What NOT to do

- Do not retrain for this symptom.
- Do not re-run COLMAP.
- Do not “fix empty reconstruction.”

## Optional next (viewer-only, no retrain)

- Start SuperSplat camera **inside** the mean of gaussians (or load with a saved camera).
- Or write a post-export that **does not change geometry**, only embeds a better default camera if the format supports it.
- If a product needs “dollhouse exterior,” that is a different render mode (floorplan / cutaway), not a scale bug.

## Artifacts

- `data/nerfstudio_images/kitchen_coord_audit/dataparser_transforms.json`
- `data/nerfstudio_images/kitchen_coord_audit/config.yml`
- `data/nerfstudio_images/SPLAT_COORD_AUDIT.json`
- Modal re-export audit: run `scripts/audit_kitchen_coords.py` (PLY vs splat)
