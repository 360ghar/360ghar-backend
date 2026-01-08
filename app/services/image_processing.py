"""
Image Processing Service for 360 Tour panoramas.
Uses Pillow for thumbnail generation, format conversion, and EXIF extraction.
"""
import io
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ExifTags
from PIL.ExifTags import TAGS, GPSTAGS

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
                img = img.convert("RGB")

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
        logger.error(f"Thumbnail generation failed: {str(e)}")
        raise


def convert_to_webp(
    image_bytes: bytes,
    quality: int = WEBP_QUALITY,
    max_dimension: Optional[int] = None,
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
                img = img.convert("RGB")

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
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Save as WebP
            output = io.BytesIO()
            img.save(output, format="WEBP", quality=quality, optimize=True)
            output.seek(0)

            return output.getvalue()

    except Exception as e:
        logger.error(f"WebP conversion failed: {str(e)}")
        raise


def extract_exif(image_bytes: bytes) -> Dict[str, Any]:
    """
    Extract EXIF metadata from image.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Dictionary containing EXIF data (camera info, GPS, etc.)
    """
    exif_data: Dict[str, Any] = {
        "camera": {},
        "gps": {},
        "datetime": None,
        "software": None,
    }

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            raw_exif = img._getexif()

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
        logger.warning(f"EXIF extraction failed (non-critical): {str(e)}")
        return exif_data


def _parse_gps_info(gps_info: Dict) -> Dict[str, Any]:
    """Parse GPS info from EXIF data into latitude/longitude."""
    gps_data: Dict[str, Any] = {}

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
        logger.warning(f"GPS parsing failed (non-critical): {str(e)}")

    return gps_data


def _convert_to_degrees(value) -> float:
    """Convert GPS coordinates to degrees."""
    try:
        d, m, s = value
        return float(d) + float(m) / 60 + float(s) / 3600
    except (TypeError, ValueError):
        return 0.0


def get_image_dimensions(image_bytes: bytes) -> Tuple[int, int]:
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
        logger.error(f"Failed to get image dimensions: {str(e)}")
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
            logger.warning(
                f"Image aspect ratio {actual_ratio:.2f} deviates from expected 2:1 ratio. "
                f"May not be a valid 360 panorama."
            )

        return is_valid

    except Exception as e:
        logger.error(f"360 panorama validation failed: {str(e)}")
        return False


def get_image_info(image_bytes: bytes) -> Dict[str, Any]:
    """
    Get comprehensive image information.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Dictionary with dimensions, format, mode, and EXIF data
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size

            return {
                "width": width,
                "height": height,
                "aspect_ratio": width / height if height > 0 else 0,
                "format": img.format,
                "mode": img.mode,
                "is_360_panorama": validate_360_panorama(image_bytes),
                "exif": extract_exif(image_bytes),
                "file_size": len(image_bytes),
            }
    except Exception as e:
        logger.error(f"Failed to get image info: {str(e)}")
        raise


async def process_scene_image(image_bytes: bytes) -> Dict[str, bytes]:
    """
    Process a 360 scene image to generate all required derivatives.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Dictionary with 'thumbnail', 'web' (WebP optimized), and metadata
    """
    try:
        # Generate thumbnail (512px max)
        thumbnail = generate_thumbnail(image_bytes, max_size=512, format="WEBP")

        # Generate web-optimized version (4096px max for high quality viewing)
        web_optimized = convert_to_webp(image_bytes, quality=WEBP_QUALITY, max_dimension=4096)

        # Extract metadata
        info = get_image_info(image_bytes)

        return {
            "thumbnail": thumbnail,
            "web": web_optimized,
            "info": info,
        }

    except Exception as e:
        logger.error(f"Scene image processing failed: {str(e)}")
        raise
