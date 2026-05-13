"""
Image Processing Service for 360 Tour panoramas.
Uses Pillow for thumbnail generation, format conversion, and EXIF extraction.
"""
import io
from typing import Any

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

from app.core.logging import get_logger

logger = get_logger(__name__)


# Standard thumbnail sizes
THUMBNAIL_SIZES = {
    "small": (256, 128),
    "medium": (512, 256),
    "large": (1024, 512),
}

# Default quality settings
WEBP_QUALITY = 85
JPEG_QUALITY = 85


def generate_thumbnail(
    image_bytes: bytes,
    max_size: int = 512,
    format: str = "WEBP",
) -> bytes:
    """
    Generate a thumbnail from image bytes.

    Args:
        image_bytes: Raw image bytes
        max_size: Maximum dimension (width or height)
        format: Output format (WEBP, JPEG, PNG)

    Returns:
        Processed thumbnail as bytes
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # Convert to RGB if necessary (for JPEG/WebP output)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")  # type: ignore[assignment]

            # Calculate thumbnail size maintaining aspect ratio
            # For 360 panoramas, we want to preserve the 2:1 ratio
            width, height = img.size
            aspect_ratio = width / height

            if width > height:
                new_width = min(max_size, width)
                new_height = int(new_width / aspect_ratio)
            else:
                new_height = min(max_size, height)
                new_width = int(new_height * aspect_ratio)

            # Use high-quality resampling
            img.thumbnail((new_width, new_height), Image.Resampling.LANCZOS)

            # Save to bytes
            output = io.BytesIO()
            quality = WEBP_QUALITY if format.upper() == "WEBP" else JPEG_QUALITY
            img.save(output, format=format.upper(), quality=quality, optimize=True)
            output.seek(0)

            return output.getvalue()

    except Exception as e:
        logger.error("Thumbnail generation failed: %s", e, exc_info=True)
        raise


def convert_to_webp(
    image_bytes: bytes,
    quality: int = WEBP_QUALITY,
    max_dimension: int | None = None,
) -> bytes:
    """
    Convert image to WebP format for optimal web delivery.

    Args:
        image_bytes: Raw image bytes
        quality: WebP quality (0-100)
        max_dimension: Optional maximum dimension to resize

    Returns:
        WebP image as bytes
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # Convert to RGB if necessary
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")  # type: ignore[assignment]

            # Resize if max_dimension is specified
            if max_dimension:
                width, height = img.size
                if width > max_dimension or height > max_dimension:
                    aspect_ratio = width / height
                    if width > height:
                        new_width = max_dimension
                        new_height = int(max_dimension / aspect_ratio)
                    else:
                        new_height = max_dimension
                        new_width = int(max_dimension * aspect_ratio)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)  # type: ignore[assignment]

            # Save as WebP
            output = io.BytesIO()
            img.save(output, format="WEBP", quality=quality, optimize=True)
            output.seek(0)

            return output.getvalue()

    except Exception as e:
        logger.error("WebP conversion failed: %s", e, exc_info=True)
        raise


def extract_exif(image_bytes: bytes) -> dict[str, Any]:
    """
    Extract EXIF metadata from image.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Dictionary containing EXIF data (camera info, GPS, etc.)
    """
    exif_data: dict[str, Any] = {
        "camera": {},
        "gps": {},
        "datetime": None,
        "software": None,
    }

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            raw_exif = img.getexif()

            if not raw_exif:
                return exif_data

            # Process standard EXIF tags
            for tag_id, value in raw_exif.items():
                tag_name = TAGS.get(tag_id, str(tag_id))

                # Camera information
                if tag_name == "Make":
                    exif_data["camera"]["make"] = str(value)
                elif tag_name == "Model":
                    exif_data["camera"]["model"] = str(value)
                elif tag_name == "LensModel":
                    exif_data["camera"]["lens"] = str(value)
                elif tag_name == "FocalLength":
                    exif_data["camera"]["focal_length"] = float(value) if value else None
                elif tag_name == "FNumber":
                    exif_data["camera"]["aperture"] = float(value) if value else None
                elif tag_name == "ISOSpeedRatings":
                    exif_data["camera"]["iso"] = int(value) if value else None
                elif tag_name == "ExposureTime":
                    exif_data["camera"]["exposure"] = str(value) if value else None

                # Datetime
                elif tag_name == "DateTimeOriginal":
                    exif_data["datetime"] = str(value)
                elif tag_name == "DateTime" and not exif_data["datetime"]:
                    exif_data["datetime"] = str(value)

                # Software
                elif tag_name == "Software":
                    exif_data["software"] = str(value)

                # GPS data
                elif tag_name == "GPSInfo":
                    exif_data["gps"] = _parse_gps_info(value)

            return exif_data

    except Exception as e:
        logger.warning("EXIF extraction failed (non-critical): %s", e)
        return exif_data


def _parse_gps_info(gps_info: dict) -> dict[str, Any]:
    """Parse GPS info from EXIF data into latitude/longitude."""
    gps_data: dict[str, Any] = {}

    try:
        # Get GPS tags
        gps_tags = {}
        for tag_id, value in gps_info.items():
            tag_name = GPSTAGS.get(tag_id, str(tag_id))
            gps_tags[tag_name] = value

        # Parse latitude
        if "GPSLatitude" in gps_tags and "GPSLatitudeRef" in gps_tags:
            lat = _convert_to_degrees(gps_tags["GPSLatitude"])
            if gps_tags["GPSLatitudeRef"] == "S":
                lat = -lat
            gps_data["latitude"] = lat

        # Parse longitude
        if "GPSLongitude" in gps_tags and "GPSLongitudeRef" in gps_tags:
            lon = _convert_to_degrees(gps_tags["GPSLongitude"])
            if gps_tags["GPSLongitudeRef"] == "W":
                lon = -lon
            gps_data["longitude"] = lon

        # Parse altitude
        if "GPSAltitude" in gps_tags:
            alt = float(gps_tags["GPSAltitude"])
            if gps_tags.get("GPSAltitudeRef", 0) == 1:
                alt = -alt
            gps_data["altitude"] = alt

    except Exception as e:
        logger.warning("GPS parsing failed (non-critical): %s", e)

    return gps_data


def _convert_to_degrees(value) -> float:
    """Convert GPS coordinates to degrees."""
    try:
        d, m, s = value
        return float(d) + float(m) / 60 + float(s) / 3600
    except (TypeError, ValueError):
        return 0.0


def get_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """
    Get image dimensions (width, height).

    Args:
        image_bytes: Raw image bytes

    Returns:
        Tuple of (width, height)
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return img.size
    except Exception as e:
        logger.error("Failed to get image dimensions: %s", e, exc_info=True)
        raise


def validate_360_panorama(image_bytes: bytes, tolerance: float = 0.1) -> bool:
    """
    Validate if image is a 360 equirectangular panorama.

    A valid 360 panorama should have a 2:1 aspect ratio.

    Args:
        image_bytes: Raw image bytes
        tolerance: Allowed deviation from 2:1 ratio (default 10%)

    Returns:
        True if image appears to be a valid 360 panorama
    """
    try:
        width, height = get_image_dimensions(image_bytes)

        # Check for 2:1 aspect ratio (equirectangular projection)
        expected_ratio = 2.0
        actual_ratio = width / height

        is_valid = abs(actual_ratio - expected_ratio) <= tolerance

        if not is_valid:
            logger.warning("Image aspect ratio %f deviates from expected 2:1 ratio. May not be a valid 360 panorama.", actual_ratio)

        return is_valid

    except Exception as e:
        logger.error("360 panorama validation failed: %s", e, exc_info=True)
        return False


def get_image_info(
    image_bytes: bytes | None = None,
    *,
    img: Image.Image | None = None,
    file_size: int = 0,
) -> dict[str, Any]:
    """
    Get comprehensive image information.

    Accepts either raw bytes (opens once internally) or an already-opened
    Pillow Image to avoid redundant Image.open calls.

    Args:
        image_bytes: Raw image bytes (mutually exclusive with ``img``)
        img: Already-opened Pillow Image (avoids re-opening)
        file_size: Original file size in bytes (used when ``img`` is provided)

    Returns:
        Dictionary with dimensions, format, mode, and EXIF data
    """
    try:
        if image_bytes is None and img is None:
            raise ValueError("Either image_bytes or img must be provided")

        if img is not None:
            width, height = img.size
            aspect_ratio = width / height if height > 0 else 0
            expected_ratio = 2.0
            is_360 = abs(aspect_ratio - expected_ratio) <= 0.1
            raw_exif = img.getexif()

            exif_data: dict[str, Any] = {"camera": {}, "gps": {}, "datetime": None, "software": None}
            if raw_exif:
                for tag_id, value in raw_exif.items():
                    tag_name = TAGS.get(tag_id, str(tag_id))
                    if tag_name == "Make":
                        exif_data["camera"]["make"] = str(value)
                    elif tag_name == "Model":
                        exif_data["camera"]["model"] = str(value)
                    elif tag_name == "LensModel":
                        exif_data["camera"]["lens"] = str(value)
                    elif tag_name == "FocalLength":
                        exif_data["camera"]["focal_length"] = float(value) if value else None
                    elif tag_name == "FNumber":
                        exif_data["camera"]["aperture"] = float(value) if value else None
                    elif tag_name == "ISOSpeedRatings":
                        exif_data["camera"]["iso"] = int(value) if value else None
                    elif tag_name == "ExposureTime":
                        exif_data["camera"]["exposure"] = str(value) if value else None
                    elif tag_name == "DateTimeOriginal":
                        exif_data["datetime"] = str(value)
                    elif tag_name == "DateTime" and not exif_data["datetime"]:
                        exif_data["datetime"] = str(value)
                    elif tag_name == "Software":
                        exif_data["software"] = str(value)
                    elif tag_name == "GPSInfo":
                        exif_data["gps"] = _parse_gps_info(value)

            return {
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
                "format": img.format,
                "mode": img.mode,
                "is_360_panorama": is_360,
                "exif": exif_data,
                "file_size": file_size,
            }

        # Legacy path: open from bytes (single open)
        with Image.open(io.BytesIO(image_bytes)) as opened:  # type: ignore[arg-type]
            return get_image_info(img=opened, file_size=len(image_bytes))  # type: ignore[arg-type]

    except Exception as e:
        logger.error("Failed to get image info: %s", e, exc_info=True)
        raise


async def process_scene_image(image_bytes: bytes) -> dict[str, Any]:
    """
    Process a 360 scene image to generate all required derivatives.

    Opens the source image **once** and reuses it for thumbnail, web-optimized
    conversion, and metadata extraction to avoid the 3x Pillow open overhead.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Dictionary with 'thumbnail', 'web' (WebP optimized), and metadata
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # Convert to RGB once if needed
            rgb_img = img
            if img.mode in ("RGBA", "P"):
                rgb_img = img.convert("RGB")  # type: ignore[assignment]

            # --- Thumbnail (512px max) ---
            thumb_img = rgb_img.copy()
            width, height = thumb_img.size
            aspect_ratio = width / height
            if width > height:
                new_w = min(512, width)
                new_h = int(new_w / aspect_ratio)
            else:
                new_h = min(512, height)
                new_w = int(new_h * aspect_ratio)
            thumb_img.thumbnail((new_w, new_h), Image.Resampling.LANCZOS)
            thumb_buf = io.BytesIO()
            thumb_img.save(thumb_buf, format="WEBP", quality=WEBP_QUALITY, optimize=True)
            thumbnail = thumb_buf.getvalue()
            thumb_img.close()

            # --- Web-optimized (4096px max) ---
            web_img = rgb_img.copy()
            max_dim = 4096
            w, h = web_img.size
            if w > max_dim or h > max_dim:
                ar = w / h
                if w > h:
                    new_w = max_dim
                    new_h = int(max_dim / ar)
                else:
                    new_h = max_dim
                    new_w = int(new_h * ar)
                web_img = web_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            web_buf = io.BytesIO()
            web_img.save(web_buf, format="WEBP", quality=WEBP_QUALITY, optimize=True)
            web_optimized = web_buf.getvalue()
            web_img.close()

            # --- Metadata (reuse already-open image) ---
            info = get_image_info(img=img, file_size=len(image_bytes))

        return {
            "thumbnail": thumbnail,
            "web": web_optimized,
            "info": info,
        }

    except Exception as e:
        logger.error("Scene image processing failed: %s", e, exc_info=True)
        raise
