"""
"Generate 3D World" — textured skybox-mesh generation for tours.

Converts each scene's equirectangular panorama into a 6-face cubemap
(numpy sampling), builds a GLB (glTF binary) of inward-facing textured
cubes — one cube per scene, laid out in a row — and uploads the mesh to
Cloudinary. The result is stored in ``tour.settings["world_3d"]``.
"""
from __future__ import annotations

import asyncio
import json
import struct
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_bg_session_factory
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.logging import get_logger
from app.models.enums import AIJobType
from app.models.tours import AIJob, Tour
from app.schemas.tour import ALLOWED_FRAME_HOSTS

from .helpers import _download_image_bytes, _run_with_semaphore, _track_background_task
from .jobs import create_ai_job, update_job_status

if TYPE_CHECKING:
    import numpy as np

logger = get_logger(__name__)

FACE_SIZE = 1024
MAX_PANO_WIDTH = 4096  # downscale source panoramas to bound memory
CUBE_SPACING = 3.0  # x-offset between per-scene cubes
JPEG_QUALITY = 90
# ponytail: cap decoded pixel count to bound memory from decompression-bomb
# frames; 40M px is ~5.5x a 12MP photo, comfortably above any real capture.
MAX_DECODED_PIXELS = 40_000_000
# Bound per-job memory/CPU: 32 scenes * 6 faces * ~1MP is a practical ceiling.
MAX_SCENES_PER_3D_JOB = 32
# Inward-facing winding (both triangles): BL->TR->BR and BL->TL->TR.
# right × up == forward for every face, so this winding yields normals
# ∝ -forward (inward, visible from cube center).
QUAD_WINDING_INDICES: tuple[int, int, int, int, int, int] = (0, 2, 1, 0, 3, 2)

# Cubemap face bases: name -> (forward, right, up) unit vectors.
# For each face pixel, the view ray is forward + a*right + b*up with
# a (right) and b (up) in [-1, 1].
_FACE_BASES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "px": ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
    "nx": ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    "py": ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
    "ny": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    "pz": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    "nz": ((0, 0, -1), (-1, 0, 0), (0, 1, 0)),
}
FACE_NAMES = tuple(_FACE_BASES)

_GLB_JSON_CHUNK = 0x4E4F534A  # b"JSON"
_GLB_BIN_CHUNK = 0x004E4942  # b"BIN\0"


# ====================
# Equirect -> cubemap
# ====================

def equirect_to_cubemap(equirect: np.ndarray, face_size: int = FACE_SIZE) -> dict[str, np.ndarray]:
    """Convert an equirectangular image (H x W x C) into 6 cubemap faces.

    Longitude 0 is the horizontal centre of the panorama (the +Z face).
    """
    # ponytail: nearest-neighbour sampling — switch to bilinear if face seams
    # ever look blocky on low-res panoramas.
    import numpy as np

    height, width = equirect.shape[:2]
    coords = (np.arange(face_size) + 0.5) / face_size * 2.0 - 1.0  # [-1, 1]
    a_grid, b_grid = np.meshgrid(coords, -coords)  # a: right, b: up (+1 at top row)

    faces: dict[str, np.ndarray] = {}
    for name, (forward, right, up) in _FACE_BASES.items():
        fwd = np.asarray(forward, dtype=np.float64)
        rgt = np.asarray(right, dtype=np.float64)
        upv = np.asarray(up, dtype=np.float64)

        directions = (
            fwd[None, None, :]
            + a_grid[..., None] * rgt[None, None, :]
            + b_grid[..., None] * upv[None, None, :]
        )
        directions /= np.linalg.norm(directions, axis=-1, keepdims=True)

        lon = np.arctan2(directions[..., 0], directions[..., 2])
        lat = np.arcsin(np.clip(directions[..., 1], -1.0, 1.0))

        # Negate lon so +X (right of +Z) samples eastward columns without
        # left/right mirroring the panorama onto the cubemap.
        u_px = ((-lon / (2.0 * np.pi) + 0.5) * width).astype(np.int64) % width
        v_px = np.clip(((0.5 - lat / np.pi) * height).astype(np.int64), 0, height - 1)
        faces[name] = equirect[v_px, u_px]
    return faces


def _pano_to_jpeg_faces(pano_bytes: bytes, face_size: int = FACE_SIZE) -> dict[str, bytes]:
    """Decode a panorama and return its 6 cubemap faces as JPEG bytes."""
    import cv2
    import numpy as np

    array = np.frombuffer(pano_bytes, dtype=np.uint8)
    pano = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if pano is None:
        raise ValueError("Panorama could not be decoded as an image")

    height, width = pano.shape[:2]
    if width * height > MAX_DECODED_PIXELS:
        raise ValueError(
            f"Frame too large ({width}x{height} = {width * height} px, "
            f"max {MAX_DECODED_PIXELS})"
        )
    if width > MAX_PANO_WIDTH:
        scale = MAX_PANO_WIDTH / width
        pano = cv2.resize(
            pano,
            (MAX_PANO_WIDTH, max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )

    jpeg_faces: dict[str, bytes] = {}
    for name, face in equirect_to_cubemap(pano, face_size).items():
        ok, encoded = cv2.imencode(".jpg", face, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise ValueError(f"Failed to encode cubemap face '{name}' as JPEG")
        jpeg_faces[name] = encoded.tobytes()
    return jpeg_faces


# ====================
# GLB (glTF binary) builder
# ====================

def _append_buffer(buffer: bytearray, data: bytes) -> tuple[int, int]:
    """Append data to the binary buffer 4-byte aligned; return (offset, length)."""
    while len(buffer) % 4:
        buffer.append(0)
    offset = len(buffer)
    buffer.extend(data)
    return offset, len(data)


def build_skybox_glb(scene_faces: list[dict[str, bytes]], spacing: float = CUBE_SPACING) -> bytes:
    """Build a GLB of inward-facing textured cubes, one per scene, in a row.

    ``scene_faces`` is a list (one entry per scene) of face-name -> JPEG bytes.
    Cube n is offset by ``n * spacing`` on the x axis via its node translation.
    """
    binary = bytearray()
    accessors: list[dict[str, Any]] = []
    buffer_views: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    textures: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    meshes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []

    quad_indices = struct.pack("<6H", *QUAD_WINDING_INDICES)

    for cube_index, faces in enumerate(scene_faces):
        primitives: list[dict[str, Any]] = []
        for name in FACE_NAMES:
            forward, right, up = (list(v) for v in _FACE_BASES[name])
            # Quad corners as seen from inside: BL, BR, TR, TL (a right, b up).
            corners = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
            positions: list[float] = []
            uvs: list[float] = []
            for a, b in corners:
                positions.extend(
                    forward[axis] + a * right[axis] + b * up[axis] for axis in range(3)
                )
                uvs.extend(((a + 1.0) / 2.0, (1.0 - b) / 2.0))

            pos_bytes = struct.pack(f"<{len(positions)}f", *positions)
            uv_bytes = struct.pack(f"<{len(uvs)}f", *uvs)

            pos_offset, pos_len = _append_buffer(binary, pos_bytes)
            buffer_views.append(
                {"buffer": 0, "byteOffset": pos_offset, "byteLength": pos_len, "target": 34962}
            )
            xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
            accessors.append(
                {
                    "bufferView": len(buffer_views) - 1,
                    "componentType": 5126,  # FLOAT
                    "count": 4,
                    "type": "VEC3",
                    "min": [min(xs), min(ys), min(zs)],
                    "max": [max(xs), max(ys), max(zs)],
                }
            )
            position_accessor = len(accessors) - 1

            uv_offset, uv_len = _append_buffer(binary, uv_bytes)
            buffer_views.append(
                {"buffer": 0, "byteOffset": uv_offset, "byteLength": uv_len, "target": 34962}
            )
            accessors.append(
                {
                    "bufferView": len(buffer_views) - 1,
                    "componentType": 5126,
                    "count": 4,
                    "type": "VEC2",
                }
            )
            uv_accessor = len(accessors) - 1

            idx_offset, idx_len = _append_buffer(binary, quad_indices)
            buffer_views.append(
                {"buffer": 0, "byteOffset": idx_offset, "byteLength": idx_len, "target": 34963}
            )
            accessors.append(
                {
                    "bufferView": len(buffer_views) - 1,
                    "componentType": 5123,  # UNSIGNED_SHORT
                    "count": 6,
                    "type": "SCALAR",
                }
            )
            index_accessor = len(accessors) - 1

            img_offset, img_len = _append_buffer(binary, faces[name])
            buffer_views.append(
                {"buffer": 0, "byteOffset": img_offset, "byteLength": img_len}
            )
            images.append(
                {
                    "bufferView": len(buffer_views) - 1,
                    "mimeType": "image/jpeg",
                    "name": f"cube{cube_index}_{name}",
                }
            )
            textures.append({"sampler": 0, "source": len(images) - 1})
            materials.append(
                {
                    "name": f"cube{cube_index}_{name}",
                    "pbrMetallicRoughness": {
                        "baseColorTexture": {"index": len(textures) - 1},
                        "metallicFactor": 0.0,
                        "roughnessFactor": 1.0,
                    },
                    "extensions": {"KHR_materials_unlit": {}},
                }
            )
            primitives.append(
                {
                    "attributes": {
                        "POSITION": position_accessor,
                        "TEXCOORD_0": uv_accessor,
                    },
                    "indices": index_accessor,
                    "material": len(materials) - 1,
                }
            )

        meshes.append({"name": f"skybox_{cube_index}", "primitives": primitives})
        nodes.append(
            {
                "mesh": len(meshes) - 1,
                "translation": [cube_index * spacing, 0.0, 0.0],
                "name": f"scene_{cube_index}",
            }
        )

    gltf = {
        "asset": {"version": "2.0", "generator": "360ghar-world3d"},
        "extensionsUsed": ["KHR_materials_unlit"],
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "textures": textures,
        "images": images,
        "samplers": [{"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071}],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(binary)}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    bin_bytes = bytes(binary) + b"\x00" * (-len(binary) % 4)

    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    return b"".join(
        (
            struct.pack("<4sII", b"glTF", 2, total_length),
            struct.pack("<II", len(json_bytes), _GLB_JSON_CHUNK),
            json_bytes,
            struct.pack("<II", len(bin_bytes), _GLB_BIN_CHUNK),
            bin_bytes,
        )
    )


# ====================
# Service entry + background runner
# ====================

async def generate_3d_world(
    db: AsyncSession,
    tour_id: str,
    user_id: int,
) -> AIJob:
    """Kick off 3D world (textured skybox mesh) generation for a tour."""
    from app.services.tour import get_tour

    tour = await get_tour(db, tour_id, user_id, include_scenes=True)

    if tour.user_id != user_id:
        raise ForbiddenException(detail="Access denied")

    scenes = sorted(tour.scenes or [], key=lambda s: s.order_index)
    if not scenes:
        raise BadRequestException(detail="Cannot generate a 3D world for a tour without scenes")
    if len(scenes) > MAX_SCENES_PER_3D_JOB:
        raise BadRequestException(
            detail=f"Cannot generate a 3D world for more than {MAX_SCENES_PER_3D_JOB} scenes"
        )

    scene_inputs = [(scene.id, scene.image_url) for scene in scenes]

    job = await create_ai_job(db, user_id, AIJobType.generate_3d_world.value, tour_id=tour_id)

    _track_background_task(
        _run_with_semaphore(_run_generate_3d_world(job.id, tour_id, scene_inputs))
    )
    return job


async def _run_generate_3d_world(
    job_id: str,
    tour_id: str,
    scene_inputs: list[tuple[str, str]],
) -> None:
    """Background runner: cubemap each scene, build the GLB, upload, persist.

    Creates its own database session for the background task.
    """
    # ponytail: v1 layout is one skybox cube per scene in a row (x += 3 units);
    # a real reconstruction (splat/mesh from geometry) can replace this later.
    session_factory = get_bg_session_factory()
    async with session_factory() as db:
        try:
            await update_job_status(db, job_id, "processing", 10)

            scene_faces: list[dict[str, bytes]] = []
            scene_ids: list[str] = []
            total = len(scene_inputs)
            for index, (scene_id, image_url) in enumerate(scene_inputs):
                parsed = urlparse(image_url)
                if parsed.scheme != "https" or parsed.hostname not in ALLOWED_FRAME_HOSTS:
                    raise ValueError(
                        f"Scene image URL is not from an allowed host: {image_url}"
                    )
                pano_bytes = await _download_image_bytes(image_url)
                faces = await asyncio.to_thread(_pano_to_jpeg_faces, pano_bytes)
                del pano_bytes
                scene_faces.append(faces)
                scene_ids.append(scene_id)
                progress = 10 + int(50 * (index + 1) / total)
                await update_job_status(db, job_id, "processing", progress)

            glb_bytes = await asyncio.to_thread(build_skybox_glb, scene_faces)
            del scene_faces
            await update_job_status(db, job_id, "processing", 80)

            from app.services.cloudinary import get_cloudinary_service

            upload_result = await asyncio.to_thread(
                get_cloudinary_service().upload_file,
                file_bytes=glb_bytes,
                public_id=f"{uuid4().hex[:8]}_world.glb",
                folder=f"tours/{tour_id}/world3d",
                content_type="model/gltf-binary",
            )
            mesh_url: str = upload_result["secure_url"]

            result = {
                "mesh_url": mesh_url,
                "kind": "skybox_mesh",
                "scene_id": scene_ids[0],
                "scene_ids": scene_ids,
            }

            tour = (
                await db.execute(select(Tour).where(Tour.id == tour_id))
            ).scalar_one_or_none()
            if tour is None:
                raise ValueError("Tour was deleted while generating the 3D world")
            tour.settings = {**(tour.settings or {}), "world_3d": result}
            await db.commit()

            await update_job_status(db, job_id, "completed", 100, result=result)
            await db.commit()
            logger.info("3D world generated for tour %s (%d scenes)", tour_id, total)
        except Exception as e:
            logger.error("Error generating 3D world for tour %s: %s", tour_id, e, exc_info=True)
            await db.rollback()
            await update_job_status(db, job_id, "failed", error_message=str(e))
            await db.commit()
