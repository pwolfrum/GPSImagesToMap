"""Discover images and read their EXIF timestamps."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS
from pillow_heif import register_heif_opener

register_heif_opener()

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif"}


@dataclass
class ImageInfo:
    path: Path
    timestamp: datetime | None  # UTC if timezone info available, naive otherwise
    has_gps: bool
    tz_certain: bool = False  # True if EXIF contained an explicit timezone offset


def _parse_exif_datetime(
    dt_str: str, tz_offset_str: str | None = None
) -> datetime | None:
    """Parse EXIF datetime string like '2025:08:15 18:11:06' into datetime.

    If tz_offset_str is provided (e.g., '+02:00'), the datetime is made timezone-aware
    and then converted to UTC. Otherwise returns naive datetime.
    """
    dt = None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(dt_str, fmt)
            break
        except ValueError:
            continue

    if dt is None:
        return None

    if tz_offset_str:
        try:
            # Parse offset like '+02:00' or '-05:00'
            sign = 1 if tz_offset_str[0] == "+" else -1
            parts = tz_offset_str[1:].split(":")
            offset_hours = int(parts[0])
            offset_minutes = int(parts[1]) if len(parts) > 1 else 0
            from datetime import timedelta

            tz = timezone(
                timedelta(hours=sign * offset_hours, minutes=sign * offset_minutes)
            )
            dt = dt.replace(tzinfo=tz).astimezone(timezone.utc)
        except (ValueError, IndexError):
            pass

    return dt


def read_image_info(path: Path) -> ImageInfo:
    """Read EXIF timestamp and GPS presence from an image file."""
    try:
        img = Image.open(path)
        exif_data = img.getexif()
    except Exception:
        return ImageInfo(path=path, timestamp=None, has_gps=False)

    if not exif_data:
        return ImageInfo(path=path, timestamp=None, has_gps=False)

    timestamp = None
    has_gps = False

    # Check GPS IFD for actual coordinate data (not just a version tag)
    gps_ifd = exif_data.get_ifd(0x8825)  # GPS IFD pointer
    if gps_ifd:
        # GPSLatitude = 2, GPSLongitude = 4 — require actual coordinates
        has_gps = 2 in gps_ifd and 4 in gps_ifd

    # Check EXIF sub-IFD for DateTimeOriginal / DateTimeDigitized
    exif_ifd = exif_data.get_ifd(0x8769)  # EXIF IFD pointer
    tz_offset = None
    if exif_ifd:
        # 0x9011 = OffsetTimeOriginal, 0x9012 = OffsetTimeDigitized, 0x9010 = OffsetTime
        tz_offset = exif_ifd.get(0x9011) or exif_ifd.get(0x9012) or exif_ifd.get(0x9010)

        for tag_id, value in exif_ifd.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "DateTimeOriginal" and timestamp is None:
                timestamp = _parse_exif_datetime(str(value), tz_offset)
            elif tag == "DateTimeDigitized" and timestamp is None:
                timestamp = _parse_exif_datetime(str(value), tz_offset)

    # Fallback: check main IFD for DateTime
    if timestamp is None:
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "DateTime":
                timestamp = _parse_exif_datetime(str(value), tz_offset)
                break

    tz_certain = tz_offset is not None and timestamp is not None
    return ImageInfo(
        path=path, timestamp=timestamp, has_gps=has_gps, tz_certain=tz_certain
    )


def discover_images(
    directory: Path, recursive: bool = False, exclude_dirs: set[str] | None = None
) -> list[ImageInfo]:
    """Find image files in a directory and read their metadata.

    By default, only files directly inside the selected directory are considered.
    """
    if exclude_dirs is None:
        exclude_dirs = {"geotagged"}
    images: list[ImageInfo] = []
    pattern = "**/*" if recursive else "*"
    for p in sorted(directory.glob(pattern)):
        if any(part in exclude_dirs for part in p.relative_to(directory).parts):
            continue
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(read_image_info(p))
    return images
