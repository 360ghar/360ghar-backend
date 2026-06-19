# 360Ghar Wiki — Overview Video

A silent ~2.5-minute (≈150s) overview video for the 360Ghar backend wiki, built with [Remotion 4.x](https://www.remotion.dev/). Text captions drive the narrative across eight scenes that alternate between navy and sand backgrounds ("Sky & Earth" palette). There is **no audio** — no voiceover, no background music.

## Prerequisites

- **Node.js 18+** (Node 20 LTS recommended)
- **npm** (bundled with Node) or any compatible package manager
- **ffmpeg** is not required — Remotion bundles its own renderer

## Project layout

```
.
├── package.json              # Remotion 4.x project + scripts
├── tsconfig.json             # TypeScript config (jsx: react-jsx, bundler resolution)
├── render.sh                 # One-shot install + render script
├── README.md                 # This file
└── src/
    ├── Root.tsx              # Registers the <Composition id="Video">
    ├── Video.tsx             # Sequences the 8 scenes via <Series>
    ├── theme.ts              # "Sky & Earth" palette + typography constants
    ├── components/
    │   ├── Wordmark.tsx      # Reusable "360 GHAR" wordmark (navy + terracotta dot)
    │   ├── Caption.tsx       # Animated fade-in caption
    │   └── PropertyCard.tsx  # Animated property card (Ghar Core scene)
    └── scenes/
        ├── Intro.tsx              # Scene 1 — wordmark + tagline
        ├── GharCore.tsx           # Scene 2 — property cards + map pin
        ├── Stays.tsx              # Scene 3 — booking calendar grid
        ├── Flatmates.tsx          # Scene 4 — match line + chat bubbles
        ├── PropertyManagement.tsx # Scene 5 — Lease → Rent → Maintenance → Documents pipeline
        ├── VirtualTours.tsx       # Scene 6 — 360 scene with hotspots + AI spark
        ├── DataHub.tsx            # Scene 7 — source grid → dashboard
        └── TechStack.tsx          # Scene 8 — tech badges + outro wordmark
```

## Composition

- **ID**: `Video`
- **Duration**: 4500 frames (150s @ 30fps)
- **FPS**: 30
- **Resolution**: 1920×1080 (Full HD)
- **Codec**: H.264, CRF 18 (high quality)

## Quick start

```bash
# 1. Install dependencies
npm install

# 2. Open Remotion Studio for live preview while editing
npm run studio
# → http://localhost:3000

# 3. Render the final MP4
./render.sh
# → produces ./overview.mp4
```

## Editing scenes

Each scene is a self-contained React component in `src/scenes/`. Inside a scene, `useCurrentFrame()` returns the **local** frame (starting from 0), so animations are relative to the scene's start.

### Timing model

| Scene | Duration | Frames |
|-------|----------|--------|
| 1. Intro | 12s | 360 |
| 2. Ghar Core | 18s | 540 |
| 3. Stays | 18s | 540 |
| 4. Flatmates | 18s | 540 |
| 5. Property Management | 18s | 540 |
| 6. Virtual Tours | 18s | 540 |
| 7. Data Hub | 18s | 540 |
| 8. Tech Stack + Outro | 30s | 900 |

**Total: 4500 frames (150s @ 30fps)** — fills the composition exactly.

Scene durations are defined in `src/Video.tsx`. To change one, update the `durationInFrames` on the corresponding `<Series.Sequence>`.

### Animation primitives

All animation is driven by Remotion's `useCurrentFrame()`, `interpolate()`, and `spring()`. CSS transitions/animations are **not** used (they don't render deterministically).

```tsx
const frame = useCurrentFrame();
const { fps } = useVideoConfig();

const opacity = interpolate(frame, [0, fps], [0, 1], {
  extrapolateLeft: "clamp",
  extrapolateRight: "clamp",
});

const scale = spring({ frame, fps, config: { damping: 200 } });
```

### Palette

The palette lives in `src/theme.ts`. Use it consistently:

```ts
import { palette } from "../theme";

palette.navy       // #0F2C4A — primary, dark backgrounds
palette.sand       // #E8DCC4 — light backgrounds
palette.terracotta // #C75D3B — accent, highlights
palette.ink        // #1A1A1A — text on light
palette.muted      // #5A6B7A — subtext
palette.white      // #FFFFFF — text on dark
```

The wordmark is "360 GHAR" — navy text with a terracotta accent dot after "360". Use the `<Wordmark>` component to keep it consistent.

### Design rules

- Titles: ≥ 72px (we use 96px). Captions: ≥ 36px (we use 44px).
- Alternate navy/sand backgrounds between scenes for visual rhythm.
- Every scene has: a large title, an animated visual element, and a caption.
- Transitions are clean: fade, slide, scale. No flashy effects.
- The wordmark appears in the intro and outro only.
- **No audio components anywhere.**

## Rendering

```bash
# Equivalent to what render.sh does:
npx remotion render src/index.ts Video overview.mp4 --codec=h264 --crf=18 --gl=swiftshader
```

`render.sh` runs `npm install` first, then renders. The output `overview.mp4` lands in this directory.

> **Why `--gl=swiftshader`?** This flag forces software-based WebGL rendering via SwiftShader, which produces consistent results across macOS, Linux, and CI runners without relying on a host GPU. Without it, headless Chrome may fail to bind a GPU context and the render will stall with `Visited "http://localhost:XXXX/index.html" but got no response`.

### Git LFS

The rendered `overview.mp4` is large. This repository uses **Git LFS** to track MP4 files, so committing the render is safe:

```bash
git lfs install            # once per clone
git add overview.mp4
git commit -m "chore(wiki): render overview video"
```

If Git LFS is not yet configured for `*.mp4`, add a `.gitattributes` entry:

```
*.mp4 filter=lfs diff=lfs merge=lfs -text
```

## Re-rendering after edits

1. Edit the relevant scene in `src/scenes/`.
2. Preview in Studio: `npm run studio`.
3. When happy, run `./render.sh` to produce a fresh `overview.mp4`.
4. Commit both the source changes and the new `overview.mp4`.
