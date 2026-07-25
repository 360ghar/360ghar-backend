"""Unit tests for capture schemas (no DB required)."""

from app.models.enums import CaptureMode, CaptureSessionStatus, CaptureTrackingBackend
from app.schemas.capture import (
    CaptureFrameCreate,
    CaptureFrameMetadata,
    CapturePlan,
    CapturePose,
    CaptureRoomPlan,
    CaptureSessionCreate,
    CaptureSessionUpdate,
    CaptureWaypointPlan,
)


def test_session_create_with_plan():
    data = CaptureSessionCreate(
        title="Walkthrough",
        plan=CapturePlan(
            template="1bhk",
            rooms=[
                CaptureRoomPlan(
                    id="r1",
                    label="Living",
                    size="medium",
                    waypoints=[
                        CaptureWaypointPlan(id="w0", index=0, kind="center"),
                    ],
                )
            ],
        ),
    )
    dumped = data.model_dump()
    assert dumped["title"] == "Walkthrough"
    assert dumped["plan"]["rooms"][0]["waypoints"][0]["kind"] == "center"


def test_frame_metadata_pose():
    meta = CaptureFrameMetadata(
        capture_mode=CaptureMode.multi_yaw,
        pose=CapturePose(
            yaw_deg=45.0,
            tracking_backend=CaptureTrackingBackend.imu_pdr,
            tracking_quality="good",
        ),
    )
    assert meta.pose is not None
    assert meta.pose.yaw_deg == 45.0
    assert meta.capture_mode == CaptureMode.multi_yaw


def test_frame_create_requires_fields():
    frame = CaptureFrameCreate(
        room_id="r1",
        waypoint_id="w1",
        image_url="https://cdn.example.com/x.jpg",
    )
    assert frame.frame_index == 0


def test_session_update_status_enum():
    update = CaptureSessionUpdate(status=CaptureSessionStatus.capturing, progress=25)
    assert update.status == CaptureSessionStatus.capturing
    assert update.progress == 25


def test_capture_session_status_lifecycle_values():
    expected = {
        "draft",
        "capturing",
        "review",
        "uploading",
        "processing",
        "ready",
        "failed",
        "cancelled",
    }
    assert {s.value for s in CaptureSessionStatus} == expected
