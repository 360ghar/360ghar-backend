"""
Tests for cloud panorama stitching.

Covers frame decoding/downscaling, the OpenCV stitch wrapper (mocked
Stitcher for deterministic success/failure), and the background runner.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tours import Scene
from app.services.tour_ai import stitch


def _jpeg(width: int, height: int, seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def _bg_db(scalar) -> tuple[MagicMock, MagicMock]:
    """Mock bg session factory returning a session whose execute() yields scalar."""
    db = MagicMock(spec=AsyncSession)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    db.execute = AsyncMock(return_value=result)
    factory_cm = MagicMock()
    factory_cm.__aenter__ = AsyncMock(return_value=db)
    factory_cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=factory_cm)
    return db, factory


class TestDecodeAndDownscale:
    def test_downscales_frames_above_long_side_cap(self):
        image = stitch._decode_and_downscale(_jpeg(3200, 400))
        assert max(image.shape[:2]) <= stitch.MAX_FRAME_LONG_SIDE

    def test_keeps_small_frames_unscaled(self):
        image = stitch._decode_and_downscale(_jpeg(640, 480))
        assert image.shape[:2] == (480, 640)

    def test_rejects_undecodable_frame(self):
        with pytest.raises(ValueError, match="decoded"):
            stitch._decode_and_downscale(b"not an image")


class TestStitchFrames:
    def test_stitcher_failure_status_raises_value_error(self):
        fake_stitcher = MagicMock()
        fake_stitcher.stitch.return_value = (cv2.Stitcher_ERR_NEED_MORE_IMGS, None)

        with patch("cv2.Stitcher.create", return_value=fake_stitcher):
            with pytest.raises(ValueError, match="stitching failed"):
                stitch._stitch_frames([_jpeg(64, 48, 1), _jpeg(64, 48, 2)])

    def test_stitcher_cv2_error_raises_value_error(self):
        fake_stitcher = MagicMock()
        fake_stitcher.stitch.side_effect = cv2.error("knn assertion failed")

        with patch("cv2.Stitcher.create", return_value=fake_stitcher):
            with pytest.raises(ValueError, match="stitching failed"):
                stitch._stitch_frames([_jpeg(64, 48, 1), _jpeg(64, 48, 2)])

    def test_success_pads_panorama_to_two_to_one_canvas(self):
        panorama = np.full((100, 300, 3), 128, dtype=np.uint8)
        fake_stitcher = MagicMock()
        fake_stitcher.stitch.return_value = (cv2.Stitcher_OK, panorama)

        with patch("cv2.Stitcher.create", return_value=fake_stitcher):
            jpeg_bytes, width, height = stitch._stitch_frames(
                [_jpeg(64, 48, 1), _jpeg(64, 48, 2)]
            )

        assert width == 2 * height
        assert width >= 300
        decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape[:2] == (height, width)


class TestRunSceneStitch:
    @pytest.mark.asyncio
    async def test_success_updates_scene_and_completes_job(self):
        scene = Scene(id="scene-1", tour_id="tour-1", image_url="https://old.example.com/p.jpg")
        db, factory = _bg_db(scene)
        fake_cloudinary = MagicMock()
        fake_cloudinary.upload_file.return_value = {
            "secure_url": "https://cdn.example.com/stitched.jpg"
        }

        with (
            patch("app.services.tour_ai.stitch.get_bg_session_factory", return_value=factory),
            patch(
                "app.services.tour_ai.stitch._download_image_bytes",
                new_callable=AsyncMock,
                return_value=b"frame-bytes",
            ),
            patch(
                "app.services.tour_ai.stitch._stitch_frames",
                return_value=(b"jpeg-bytes", 800, 400),
            ),
            patch(
                "app.services.tour_ai.stitch.update_job_status", new_callable=AsyncMock
            ) as mock_update,
            patch(
                "app.services.cloudinary.get_cloudinary_service",
                return_value=fake_cloudinary,
            ),
            patch("app.services.tour.schedule_scene_processing") as mock_schedule,
        ):
            await stitch._run_scene_stitch(
                "job-1",
                "tour-1",
                "scene-1",
                1,
                ["https://cdn.example.com/f1.jpg", "https://cdn.example.com/f2.jpg"],
            )

        assert scene.image_url == "https://cdn.example.com/stitched.jpg"
        mock_schedule.assert_called_once()
        final_call = mock_update.await_args_list[-1]
        assert final_call.args[2] == "completed"
        assert final_call.args[3] == 100
        assert final_call.kwargs["result"] == {
            "image_url": "https://cdn.example.com/stitched.jpg",
            "width": 800,
            "height": 400,
        }

    @pytest.mark.asyncio
    async def test_stitch_failure_marks_job_failed(self):
        db, factory = _bg_db(None)

        with (
            patch("app.services.tour_ai.stitch.get_bg_session_factory", return_value=factory),
            patch(
                "app.services.tour_ai.stitch._download_image_bytes",
                new_callable=AsyncMock,
                return_value=b"frame-bytes",
            ),
            patch(
                "app.services.tour_ai.stitch._stitch_frames",
                side_effect=ValueError("OpenCV stitching failed (status 1)"),
            ),
            patch(
                "app.services.tour_ai.stitch.update_job_status", new_callable=AsyncMock
            ) as mock_update,
        ):
            await stitch._run_scene_stitch(
                "job-1",
                "tour-1",
                "scene-1",
                1,
                ["https://cdn.example.com/f1.jpg", "https://cdn.example.com/f2.jpg"],
            )

        final_call = mock_update.await_args_list[-1]
        assert final_call.args[2] == "failed"
        assert "stitching failed" in final_call.kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_failure_rolls_back_before_marking_job_failed(self):
        """Regression: without rollback-first, update_job_status cannot persist.

        Fake session starts clean. After a failure, update_job_status refuses
        to run unless rollback() was called first — discriminating the ordering
        bug that left jobs stuck in 'processing'.
        """
        state = {"rolled_back": False, "failed_status_updates": 0}

        db = MagicMock(spec=AsyncSession)

        async def fake_rollback() -> None:
            state["rolled_back"] = True

        async def fake_update_job_status(
            _db: AsyncSession,
            _job_id: str,
            status: str,
            *args: object,
            **kwargs: object,
        ) -> None:
            if status == "failed" and not state["rolled_back"]:
                raise RuntimeError(
                    "PendingRollbackError: session requires rollback before execute"
                )
            if status == "failed":
                state["failed_status_updates"] += 1

        db.commit = AsyncMock()
        db.rollback = AsyncMock(side_effect=fake_rollback)
        db.execute = AsyncMock()

        factory_cm = MagicMock()
        factory_cm.__aenter__ = AsyncMock(return_value=db)
        factory_cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=factory_cm)

        with (
            patch("app.services.tour_ai.stitch.get_bg_session_factory", return_value=factory),
            patch(
                "app.services.tour_ai.stitch._download_image_bytes",
                new_callable=AsyncMock,
                return_value=b"frame-bytes",
            ),
            patch(
                "app.services.tour_ai.stitch._stitch_frames",
                side_effect=ValueError("OpenCV stitching failed (status 1)"),
            ),
            patch(
                "app.services.tour_ai.stitch.update_job_status",
                new_callable=AsyncMock,
                side_effect=fake_update_job_status,
            ),
        ):
            await stitch._run_scene_stitch(
                "job-1",
                "tour-1",
                "scene-1",
                1,
                ["https://cdn.example.com/f1.jpg", "https://cdn.example.com/f2.jpg"],
            )

        assert state["rolled_back"] is True
        assert state["failed_status_updates"] == 1
        db.rollback.assert_awaited()
