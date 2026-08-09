# HouseTour reference data & video policy

## Why this data

Previous walkthrough clips were short, handheld, person-heavy. Results were
path-biased splat fog, not closed rooms.

We now use a **professional 360 house tour** (YouTube `LrcJRLMpYvs`, 2160 equi)
as the primary source. Same class of content as the HouseTour (ICCV 2025) domain:
smooth real-estate trajectories, full property coverage.

## HouseTour paper vs our job

| HouseTour (GradientSpaces) | Our splat lab |
|----------------------------|---------------|
| Needs **already reconstructed** 3D + poses | Must **estimate** poses + train 3DGS from video |
| Residual Diffuser = trajectory planning | COLMAP / depth + splatfacto = geometry |
| Qwen2-VL-3D = language tour | Viewer / free-roam later |
| Renders with 3DGS along planned path | Builds the 3DGS itself |

So: their demos prove **good captures + good 3D** look excellent. They do not
remove the need for a solid SfM/GS pipeline on the RGB video.

Links: https://house-tour.github.io/ · https://github.com/GradientSpaces/HouseTour

## Compress videos?

**No — not for training.**

1. **Keep full 2160 equirect** for GS train (max features, less equi stretch damage).
2. **Remove artificial size limiters** on lab upload (frontend/backend) if any block >50–100 MB.
3. **Do not commit** 200 MB+ files to git.
4. Optional: generate a **small proxy** for UI only.

Supabase / Modal can handle ~250 MB with normal multi-part or single PUT; if a
limit trips, raise the limit — do not CRF the training master to mush.

## Local path

Video lives in the **360-tours** repo (gitignored):

`360-tours/data/housetour/housetour_source.webm`
