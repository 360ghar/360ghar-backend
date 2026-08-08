# Guided Capture Sessions API (Phase 0)

Additive API for the mobile capture client. Does **not** replace
`POST /upload` or the existing panorama tour create flow.

## Base path

`/api/v1/capture-sessions`

All endpoints require `Authorization: Bearer <supabase_jwt>`.

## Lifecycle

```text
draft → capturing → review → uploading → processing → ready
                              ↘ failed / cancelled
```

Phase 0 implements session CRUD, frame registration, cancel, and a **stub**
complete endpoint (marks `ready` without creating a tour). Tour generation
is Phase 5.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/capture-sessions` | Create session |
| GET | `/capture-sessions` | List sessions (`?status=&limit=&offset=`) |
| GET | `/capture-sessions/{id}` | Detail + frames |
| PATCH | `/capture-sessions/{id}` | Update title/plan/status/progress |
| GET | `/capture-sessions/{id}/status` | Lightweight poll |
| POST | `/capture-sessions/{id}/frames` | Register uploaded frame + metadata |
| POST | `/capture-sessions/{id}/complete` | Finish (stub processing) |
| POST | `/capture-sessions/{id}/cancel` | Cancel in-progress session |

## Create body

```json
{
  "title": "2BHK Walkthrough",
  "description": "optional",
  "plan": {
    "template": "2bhk",
    "rooms": [
      {
        "id": "room-living",
        "label": "Living Room",
        "size": "medium",
        "order_index": 0,
        "waypoints": [
          { "id": "wp-0", "index": 0, "label": "Center", "kind": "center" }
        ]
      }
    ]
  },
  "device_info": {
    "platform": "ios",
    "model": "iPhone15,2",
    "os_version": "18.0",
    "app_version": "0.1.0"
  }
}
```

## Frame registration

1. Upload binary via `POST /api/v1/upload` or presigned flow.
2. Register:

```json
{
  "room_id": "room-living",
  "room_label": "Living Room",
  "waypoint_id": "wp-0",
  "waypoint_index": 0,
  "frame_index": 2,
  "image_url": "https://…/frame.jpg",
  "media_file_id": "optional-media-uuid",
  "metadata": {
    "capture_mode": "multi_yaw",
    "timestamp_iso": "2026-07-22T12:00:00Z",
    "pose": {
      "yaw_deg": 90.0,
      "pitch_deg": -2.0,
      "roll_deg": 0.0,
      "tracking_backend": "imu_pdr",
      "tracking_quality": "good",
      "position_m": { "x": 0, "y": 0, "z": 0 },
      "position_frame": "session_local"
    },
    "camera": {
      "fov_h_deg": 65,
      "resolution": [4032, 3024]
    },
    "quality": {
      "blur_score": 0.85,
      "exposure_ok": true
    }
  }
}
```

Either `image_url` or `media_file_id` is required.

When `media_file_id` is supplied it must reference a `media_files` row owned by
the current user with `upload_status = 'complete'` (400 otherwise), so a frame
can never point at a file that does not exist or was not uploaded.

## Status transitions

Clients may only move forward through the capture states via PATCH
(`draft → capturing → review → uploading`, with `review ⇄ capturing` and
`uploading → review` allowed for reshoots). `processing`, `ready`, `failed`
and `cancelled` are server-controlled — `ready` is only reachable through
`POST /{id}/complete` (which requires at least one frame), and `cancel`
refuses `ready`/`failed` sessions.

## Row Level Security

Both tables enable RLS with per-owner policies. `capture_sessions.user_id` is
the local `users.id`, so policies resolve ownership through `users` in a
SECURITY DEFINER helper (`capture_session_owned_by` / `capture_frame_owned_by`)
that binds `auth.uid()` from the request JWT — same pattern as the flatmates
realtime authorization fix. Frame ownership is derived through its session.

## Migration

`supabase/migrations/20260722000001_capture_sessions.sql`

## Related code

- Models: `app/models/capture.py`
- Schemas: `app/schemas/capture.py`
- Service: `app/services/capture/sessions.py`
- Routes: `app/api/api_v1/endpoints/capture.py`
