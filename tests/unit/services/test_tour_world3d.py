"""
Tests for 3D world (textured skybox mesh) generation.

Covers equirect->cubemap conversion, the GLB builder, and the background
runner (success + failure paths) with mocked download/upload/session.
"""

from __future__ import annotations

import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tours import Tour
from app.services.tour_ai import world3d


def _gradient_equirect() -> np.ndarray:
    """A 2x4 single-channel gradient equirect: row0 = 0..3, row1 = 4..7."""
    return np.arange(8, dtype=np.uint8).reshape(2, 4, 1)


def _fake_faces() -> dict[str, bytes]:
    return {name: f"jpeg-{name}".encode() for name in world3d.FACE_NAMES}


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


class TestEquirectToCubemap:
    def test_face_centers_sample_expected_pixels(self):
        # face_size=1 puts the single face pixel exactly on the forward axis.
        # Values are post longitude-sign-flip (u_px uses -lon).
        faces = world3d.equirect_to_cubemap(_gradient_equirect(), face_size=1)

        assert faces["pz"][0, 0, 0] == 6  # lon 0 -> col 2, lat 0 -> row 1
        assert faces["px"][0, 0, 0] == 5  # lon +90deg -> col 1 (was col 3 pre-fix)
        assert faces["nx"][0, 0, 0] == 7  # lon -90deg -> col 3 (was col 1 pre-fix)
        assert faces["nz"][0, 0, 0] == 4  # lon 180deg -> wraps to col 0
        assert faces["py"][0, 0, 0] == 2  # straight up -> top row
        assert faces["ny"][0, 0, 0] == 6  # straight down -> bottom row

    def test_longitude_fix_is_not_mirrored(self):
        # Viewer at pano center facing +Z (pz). pz's `right` = (1,0,0) = px's
        # forward, so px is "90 deg right". Pre longitude-sign-fix this sampled
        # col 3 val 7; post-fix col 1 val 5 — removes the left/right mirror.
        faces = world3d.equirect_to_cubemap(_gradient_equirect(), face_size=1)
        assert faces["px"][0, 0, 0] == 5

    def test_faces_have_requested_size_and_channels(self):
        rng = np.random.default_rng(42)
        equirect = rng.integers(0, 255, size=(8, 16, 3), dtype=np.uint8)

        faces = world3d.equirect_to_cubemap(equirect, face_size=4)

        assert set(faces) == set(world3d.FACE_NAMES)
        for face in faces.values():
            assert face.shape == (4, 4, 3)


class TestSkyboxWindingIsInward:
    def test_triangle_normals_point_inward_for_all_faces(self):
        # Quad corners BL, BR, TR, TL in (a,b) local coords; position =
        # forward + a*right + b*up. Winding from QUAD_WINDING_INDICES must
        # yield normals with dot(normal, forward) < 0 (inward).
        i0, i1, i2, i3, i4, i5 = world3d.QUAD_WINDING_INDICES
        triangles = ((i0, i1, i2), (i3, i4, i5))
        corners = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]

        for _name, (forward, right, up) in world3d._FACE_BASES.items():
            fwd = np.asarray(forward, dtype=np.float64)
            rgt = np.asarray(right, dtype=np.float64)
            upv = np.asarray(up, dtype=np.float64)
            verts = np.array(
                [fwd + a * rgt + b * upv for a, b in corners],
                dtype=np.float64,
            )
            for t0, t1, t2 in triangles:
                normal = np.cross(verts[t1] - verts[t0], verts[t2] - verts[t0])
                assert np.dot(normal, fwd) < 0, (
                    f"face {_name} triangle {(t0, t1, t2)} normal not inward"
                )


class TestBuildSkyboxGlb:
    def test_single_scene_glb_is_valid(self):
        glb = world3d.build_skybox_glb([_fake_faces()])

        magic, version, total_length = struct.unpack("<4sII", glb[:12])
        assert magic == b"glTF"
        assert version == 2
        assert total_length == len(glb)

        json_length, json_type = struct.unpack("<II", glb[12:20])
        assert json_type == 0x4E4F534A  # b"JSON"
        doc = json.loads(glb[20 : 20 + json_length])
        assert doc["asset"]["version"] == "2.0"
        assert "KHR_materials_unlit" in doc["extensionsUsed"]
        assert len(doc["images"]) == 6
        assert len(doc["meshes"]) == 1
        assert len(doc["meshes"][0]["primitives"]) == 6
        assert len(doc["materials"]) == 6

        bin_offset = 20 + json_length
        bin_length, bin_type = struct.unpack("<II", glb[bin_offset : bin_offset + 8])
        assert bin_type == 0x004E4942  # b"BIN\0"
        assert bin_offset + 8 + bin_length == len(glb)
        assert doc["buffers"][0]["byteLength"] <= bin_length

    def test_multi_scene_cubes_are_offset_in_a_row(self):
        glb = world3d.build_skybox_glb([_fake_faces(), _fake_faces()], spacing=3.0)

        json_length, _ = struct.unpack("<II", glb[12:20])
        doc = json.loads(glb[20 : 20 + json_length])
        assert len(doc["nodes"]) == 2
        assert doc["nodes"][0]["translation"] == [0.0, 0.0, 0.0]
        assert doc["nodes"][1]["translation"] == [3.0, 0.0, 0.0]
        assert len(doc["images"]) == 12
        assert len(doc["meshes"]) == 2

    def test_image_bytes_are_embedded_in_bin_chunk(self):
        faces = _fake_faces()
        glb = world3d.build_skybox_glb([faces])
        for jpeg in faces.values():
            assert jpeg in glb


class TestPanoToJpegFaces:
    def test_rejects_undecodable_panorama(self):
        with pytest.raises(ValueError, match="decoded"):
            world3d._pano_to_jpeg_faces(b"not an image")

    def test_returns_jpeg_bytes_for_all_faces(self):
        import cv2

        pano = np.zeros((8, 16, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", pano)
        assert ok

        faces = world3d._pano_to_jpeg_faces(encoded.tobytes(), face_size=4)

        assert set(faces) == set(world3d.FACE_NAMES)
        for jpeg in faces.values():
            assert jpeg[:2] == b"\xff\xd8"  # JPEG SOI marker


class TestRunGenerate3DWorld:
    @pytest.mark.asyncio
    async def test_success_persists_world_3d_in_tour_settings(self):
        tour = Tour(id="tour-1", user_id=1, title="Test Tour", settings={"auto_rotate": True})
        db, factory = _bg_db(tour)
        fake_cloudinary = MagicMock()
        fake_cloudinary.upload_file.return_value = {
            "secure_url": "https://res.cloudinary.com/demo/world.glb"
        }

        with (
            patch(
                "app.services.tour_ai.world3d.get_bg_session_factory", return_value=factory
            ),
            patch(
                "app.services.tour_ai.world3d._download_image_bytes",
                new_callable=AsyncMock,
                return_value=b"pano-bytes",
            ),
            patch(
                "app.services.tour_ai.world3d._pano_to_jpeg_faces",
                return_value=_fake_faces(),
            ),
            patch(
                "app.services.tour_ai.world3d.update_job_status", new_callable=AsyncMock
            ) as mock_update,
            patch(
                "app.services.cloudinary.get_cloudinary_service",
                return_value=fake_cloudinary,
            ),
        ):
            await world3d._run_generate_3d_world(
                "job-1",
                "tour-1",
                [("scene-1", "https://res.cloudinary.com/demo/pano.jpg")],
            )

        world = tour.settings["world_3d"]
        assert world["mesh_url"] == "https://res.cloudinary.com/demo/world.glb"
        assert world["kind"] == "skybox_mesh"
        assert world["scene_id"] == "scene-1"
        assert world["scene_ids"] == ["scene-1"]
        assert tour.settings["auto_rotate"] is True  # existing settings preserved

        final_call = mock_update.await_args_list[-1]
        assert final_call.args[2] == "completed"
        assert final_call.args[3] == 100
        assert final_call.kwargs["result"]["mesh_url"] == (
            "https://res.cloudinary.com/demo/world.glb"
        )

    @pytest.mark.asyncio
    async def test_download_failure_marks_job_failed(self):
        db, factory = _bg_db(None)

        with (
            patch(
                "app.services.tour_ai.world3d.get_bg_session_factory", return_value=factory
            ),
            patch(
                "app.services.tour_ai.world3d._download_image_bytes",
                new_callable=AsyncMock,
                side_effect=ValueError("download blew up"),
            ),
            patch(
                "app.services.tour_ai.world3d.update_job_status", new_callable=AsyncMock
            ) as mock_update,
        ):
            await world3d._run_generate_3d_world(
                "job-1",
                "tour-1",
                [("scene-1", "https://res.cloudinary.com/demo/pano.jpg")],
            )

        final_call = mock_update.await_args_list[-1]
        assert final_call.args[2] == "failed"
        assert "download blew up" in final_call.kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_failure_rolls_back_before_marking_job_failed(self):
        """Regression: without rollback-first, update_job_status cannot persist.

        Fake session starts clean. The first commit (success-path persist) fails
        and flips the session into pending-rollback. update_job_status then
        refuses to run unless rollback() was called first — exactly the ordering
        bug that left jobs stuck in 'processing'.
        """
        state = {"rolled_back": False, "failed_status_updates": 0}

        db = MagicMock(spec=AsyncSession)

        async def fake_rollback() -> None:
            state["rolled_back"] = True

        async def fake_commit() -> None:
            if not state["rolled_back"]:
                # Simulate SQLAlchemy leaving the session needing rollback.
                raise RuntimeError("simulated commit failure leaving pending rollback")
            # After rollback, commits succeed (status update path).

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

        db.commit = AsyncMock(side_effect=fake_commit)
        db.rollback = AsyncMock(side_effect=fake_rollback)
        db.execute = AsyncMock()

        factory_cm = MagicMock()
        factory_cm.__aenter__ = AsyncMock(return_value=db)
        factory_cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=factory_cm)

        with (
            patch(
                "app.services.tour_ai.world3d.get_bg_session_factory", return_value=factory
            ),
            patch(
                "app.services.tour_ai.world3d._download_image_bytes",
                new_callable=AsyncMock,
                side_effect=ValueError("forced failure after processing started"),
            ),
            patch(
                "app.services.tour_ai.world3d.update_job_status",
                new_callable=AsyncMock,
                side_effect=fake_update_job_status,
            ),
        ):
            await world3d._run_generate_3d_world(
                "job-1",
                "tour-1",
                [("scene-1", "https://res.cloudinary.com/demo/pano.jpg")],
            )

        assert state["rolled_back"] is True
        assert state["failed_status_updates"] == 1
        db.rollback.assert_awaited()
