# Continuous house path — starting from one perfected room

After **room1 is good**, continuous GS is still the hard part. Do **not** jump to
hallway+room2 soup. Grow outward from the seed room.

## Principle

```
seed room (perfected) ──door──► transition clip ──door──► next room
         ▲                              │
         │                              ▼
    quality gate              joint SfM only on overlap
```

1. **Never** train the whole house as one blob until each segment passes the gate.
2. **Transition clips** (doorway + 2–3s each side) carry the only shared geometry.
3. **Layout graph**: cuboid per room; portal at door; hallway is its own short cuboid.

## Seed: room1

Artifact: `public/splats/room1_perfect.splat`  
Gate: `room1_perfect_report.json`

Only when `gate.passed == true` proceed.

## Step 2 — Capture / cut transition

From the full tour video, cut:

| Clip | Content | Min length |
|------|---------|------------|
| `room1_seed` | Full room orbit/walk | 15–25s |
| `t_room1_hall` | Inside room1 → through door → into hall | 8–12s continuous |
| `hall_body` | Hall walk | 10–15s |
| `t_hall_room2` | Hall → curtains → room2 | 8–12s |

If recapturing: slow walk, pause 2s at corners, avoid pointing at mirrors.

## Step 3 — Train policy

| Segment | Method |
|---------|--------|
| Each room body | Same as room1 perfect pipeline |
| Transition | Joint train of (end of room A + transition + start of room B) only |
| Merge | Portal transform from transition poses — **not** full-room ICP |

## Step 4 — Viewer

- Load seed room splat first (free look inside cuboid).
- At door hotspot → load transition or adjacent room.
- Continuous free-roam only after all segments pass gate.

## Why this is the hard part

- Short hall clips lack parallax → COLMAP fails.
- Mirrors/curtains break multi-view consistency.
- Joint whole-house train mixes scales and floaters.

Growing from one good room keeps a **known-good coordinate frame** and forces
each new piece to prove itself at the doorway.

## Commands

```bash
# 1) Perfect room1
python run_room1_perfect.py

# 2) Later: continuous grow (when implemented)
python run_continuous_from_seed.py --seed room1_perfect.splat --transition t_room1_hall.mp4
```
