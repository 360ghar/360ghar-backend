"""Virtual staging: image-to-image "keep the structure, add furniture", with a visible watermark.

The prompt is built from two closed choices (room, style), never from client text. The model's
image is returned only after the "Virtually staged" band is drawn on it.
"""

from __future__ import annotations

import base64
import io
import math

from app.schemas.ai_tools import WATERMARK_TEXT
from app.services.ai.image_gen.schemas import (
    ALLOWED_RATIOS,
    ImageGenMode,
    ImageGenRequest,
    ImageGenResponse,
)
from app.services.ai.photos import Photo

SEND_SIDE = 1600  # longest side sent to the model

INSTRUCTION = (
    "You are a real estate photo editor. Virtually stage the room in the photo. Keep the room exactly "
    "as it is: the walls, floor, ceiling, windows, doors, fixtures, light and camera angle do not change. "
    "Add only furniture and soft decor. Do not add text, logos, signs, people or pets. "
    "The result must look like a real photograph."
)


def prompt_for(room: str, style: str) -> str:
    return (
        f"Stage this {room.replace('_', ' ')} with furniture and decor in a {style.replace('_', ' ')} style. "
        "Keep the structure of the room unchanged."
    )


def nearest_ratio(width: int, height: int) -> str:
    """The Agnes ratio closest to the photo's own."""
    target = math.log(width / height)
    return min(ALLOWED_RATIOS, key=lambda r: abs(math.log(int(r.split(":")[0]) / int(r.split(":")[1])) - target))


def _prepare(photo: Photo) -> bytes:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(photo.data)) as img:
        rgb = ImageOps.exif_transpose(img).convert("RGB")
        rgb.thumbnail((SEND_SIDE, SEND_SIDE))
        out = io.BytesIO()
        rgb.save(out, "JPEG", quality=90)
    return out.getvalue()


def add_watermark(image_bytes: bytes) -> bytes:
    """Draw a dark band across the bottom with the label centred in it. Returns a JPEG."""
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(io.BytesIO(image_bytes)) as src:
        img = src.convert("RGBA")
    width, height = img.size
    band = max(40, height // 12)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([0, height - band, width, height], fill=(0, 0, 0, 170))
    font = ImageFont.load_default(size=max(16, int(band * 0.5)))
    left, top, right, bottom = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    x = (width - (right - left)) / 2 - left
    y = height - band + (band - (bottom - top)) / 2 - top
    draw.text((x, y), WATERMARK_TEXT, font=font, fill=(255, 255, 255, 255))
    out = io.BytesIO()
    Image.alpha_composite(img, overlay).convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


async def stage_photo(photo: Photo, room: str, style: str) -> ImageGenResponse:
    """Success carries a JPEG data URL of the watermarked image. A failure carries the provider code."""
    from app.services.ai.image_gen.service import generate_image

    sent = _prepare(photo)
    request = ImageGenRequest(
        mode=ImageGenMode.IMAGE_TO_IMAGE,
        prompt=prompt_for(room, style),
        image=base64.b64encode(sent).decode("ascii"),
        mime_type="image/jpeg",
        ratio=nearest_ratio(photo.width, photo.height),
    )
    result = await generate_image(request, instruction=INSTRUCTION)
    if not result.success or not result.image:
        return result
    raw = base64.b64decode(result.image.split(",", 1)[1])
    marked = add_watermark(raw)
    return ImageGenResponse(success=True, image="data:image/jpeg;base64," + base64.b64encode(marked).decode("ascii"))
