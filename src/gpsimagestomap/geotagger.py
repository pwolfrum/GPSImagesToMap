"""Geotag images by interpolating positions from GPS tracks."""

import bisect
import os
from datetime import datetime, timezone
from pathlib import Path

import piexif
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

from .track_parser import Track, TrackPoint

# Formats that piexif can handle natively
_PIEXIF_FORMATS = {".jpg", ".jpeg"}


def interpolate_position(track: Track, time: datetime) -> TrackPoint | None:
    """Interpolate lat/lon/alt on a track for a given timestamp.

    Uses linear interpolation between the two nearest track points.
    If the time falls exactly on a point, returns that point.
    Returns None if the time falls outside the track's time range.
    """
    times = [p.time for p in track.points]

    # Ensure timezone compatibility
    if times[0].tzinfo is not None and time.tzinfo is None:
        time = time.replace(tzinfo=timezone.utc)
    elif times[0].tzinfo is None and time.tzinfo is not None:
        time = time.replace(tzinfo=None)

    # Outside track range → cannot interpolate
    if time < times[0] or time > times[-1]:
        return None

    # Find insertion point
    idx = bisect.bisect_left(times, time)

    # Exact match
    if times[idx] == time:
        p = track.points[idx]
        return TrackPoint(time=time, lat=p.lat, lon=p.lon, alt=p.alt)

    # Interpolate between idx-1 and idx
    p0 = track.points[idx - 1]
    p1 = track.points[idx]
    total = (p1.time - p0.time).total_seconds()
    if total == 0:
        return TrackPoint(time=time, lat=p0.lat, lon=p0.lon, alt=p0.alt)

    frac = (time - p0.time).total_seconds() / total
    lat = p0.lat + frac * (p1.lat - p0.lat)
    lon = p0.lon + frac * (p1.lon - p0.lon)
    alt = p0.alt + frac * (p1.alt - p0.alt)

    return TrackPoint(time=time, lat=lat, lon=lon, alt=alt)


def _decimal_to_dms(
    decimal: float,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Convert decimal degrees to (degrees, minutes, seconds) as piexif rational tuples."""
    decimal = abs(decimal)
    degrees = int(decimal)
    minutes_float = (decimal - degrees) * 60
    minutes = int(minutes_float)
    seconds_float = (minutes_float - minutes) * 60
    # Use 10000 denominator for sub-arcsecond precision
    seconds = int(round(seconds_float * 10000))
    return (degrees, 1), (minutes, 1), (seconds, 10000)


def _debug_exif_log(message: str) -> None:
    if os.getenv("GPSIMAGES_DEBUG_EXIF", "0").lower() in {"1", "true", "yes"}:
        print(message)


def sanitize_exif_for_piexif(exif_dict: dict) -> dict:
    """Conservative sanitization of an EXIF dict so piexif.dump() won't fail.

    Mutates and returns the provided `exif_dict`.
    - Ensures IFDs exist
    - Converts ints for `Undefined` (type 7) tags to minimal bytes representing
      the numeric value
    - Encodes strings for ASCII/Undefined tags to bytes
    - Converts floats for rational tags into (num, den) tuples
    - Removes tags with clearly incompatible types when conversion is unsafe
    """
    if exif_dict is None:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

    debug_messages: list[str] = []
    for ifd_name in ("0th", "Exif", "GPS", "1st"):
        ifd = exif_dict.setdefault(ifd_name, {})
        tag_defs = piexif.TAGS.get(ifd_name, {})

        for tag in list(ifd.keys()):
            val = ifd[tag]
            tag_def = tag_defs.get(tag)
            if tag_def is None:
                # Allow common simple types, otherwise drop unknown/complex tags
                if isinstance(val, (bytes, int, tuple, list, str)):
                    continue
                else:
                    debug_messages.append(
                        f"Dropped unknown unsupported tag {tag} from {ifd_name}: {type(val).__name__}"
                    )
                    del ifd[tag]
                    continue

            typ = tag_def.get("type")

            try:
                # ASCII
                if typ == 2:
                    if isinstance(val, str):
                        ifd[tag] = val.encode("ascii", "replace")
                        debug_messages.append(
                            f"Encoded ASCII tag {tag} in {ifd_name} from str to bytes"
                        )

                # Undefined / raw bytes — ensure bytes
                elif typ == 7:
                    if isinstance(val, int):
                        length = max(1, (val.bit_length() + 7) // 8)
                        ifd[tag] = val.to_bytes(length, "big")
                        debug_messages.append(
                            f"Converted Undefined tag {tag} in {ifd_name} from int to bytes"
                        )
                    elif isinstance(val, str):
                        ifd[tag] = val.encode("ascii", "replace")
                        debug_messages.append(
                            f"Encoded Undefined tag {tag} in {ifd_name} from str to bytes"
                        )
                    elif isinstance(val, bytes):
                        pass
                    else:
                        debug_messages.append(
                            f"Dropped Undefined tag {tag} in {ifd_name} with unsupported type {type(val).__name__}"
                        )
                        del ifd[tag]

                # Rational / SRational -> (num, den) or sequence of such tuples
                elif typ in (5, 10):
                    if isinstance(val, float):
                        num = int(round(val * 100000))
                        den = 100000
                        ifd[tag] = (num, den)
                        debug_messages.append(
                            f"Converted rational tag {tag} in {ifd_name} from float to tuple"
                        )
                    elif isinstance(val, int):
                        ifd[tag] = (val, 1)
                        debug_messages.append(
                            f"Converted rational tag {tag} in {ifd_name} from int to tuple"
                        )
                    elif isinstance(val, (list, tuple)):
                        if len(val) == 2 and all(isinstance(elem, int) for elem in val):
                            ifd[tag] = tuple(val)
                        else:
                            ok = True
                            new_seq = []
                            for elem in val:
                                if isinstance(elem, (list, tuple)) and len(elem) == 2 and all(
                                    isinstance(x, int) for x in elem
                                ):
                                    new_seq.append(tuple(elem))
                                elif isinstance(elem, float):
                                    num = int(round(elem * 100000))
                                    new_seq.append((num, 100000))
                                elif isinstance(elem, int):
                                    new_seq.append((elem, 1))
                                else:
                                    ok = False
                                    break
                            if ok:
                                ifd[tag] = tuple(new_seq)
                                if isinstance(val, list):
                                    debug_messages.append(
                                        f"Converted rational sequence tag {tag} in {ifd_name} from list to tuple"
                                    )
                            else:
                                debug_messages.append(
                                    f"Dropped rational tag {tag} in {ifd_name} with unsupported sequence contents"
                                )
                                del ifd[tag]
                    else:
                        debug_messages.append(
                            f"Dropped rational tag {tag} in {ifd_name} with unsupported type {type(val).__name__}"
                        )
                        del ifd[tag]

                # Short / Long / SLong — require ints
                elif typ in (3, 4, 9):
                    if isinstance(val, int):
                        pass
                    elif isinstance(val, bytes):
                        try:
                            ifd[tag] = int.from_bytes(val, "big")
                            debug_messages.append(
                                f"Converted numeric tag {tag} in {ifd_name} from bytes to int"
                            )
                        except Exception:
                            debug_messages.append(
                                f"Dropped numeric tag {tag} in {ifd_name} due to bytes conversion failure"
                            )
                            del ifd[tag]
                    else:
                        debug_messages.append(
                            f"Dropped numeric tag {tag} in {ifd_name} with unsupported type {type(val).__name__}"
                        )
                        del ifd[tag]

                else:
                    pass

            except Exception:
                debug_messages.append(
                    f"Dropped tag {tag} in {ifd_name} due to sanitization exception"
                )
                try:
                    del ifd[tag]
                except Exception:
                    pass

    if debug_messages:
        _debug_exif_log("EXIF sanitization actions:")
        for message in debug_messages:
            _debug_exif_log(f"  {message}")

    return exif_dict


def write_gps_exif(
    image_path: Path, point: TrackPoint, output_path: Path | None = None
) -> Path:
    """Write GPS coordinates into the EXIF of an image.

    For JPEG: writes EXIF directly with piexif.
    For HEIC/other: converts to JPEG first, then writes EXIF.

    Args:
        image_path: Source image path.
        point: TrackPoint with lat/lon/alt to write.
        output_path: Where to save. If None, overwrites the original.

    Returns:
        The path the image was saved to (may have .jpg extension for converted files).
    """
    # For non-JPEG formats, convert to JPEG first
    if image_path.suffix.lower() not in _PIEXIF_FORMATS:
        jpg_path = (output_path or image_path).with_suffix(".jpg")
        img = Image.open(image_path)
        exif_data = img.info.get("exif", b"")
        img.convert("RGB").save(jpg_path, "JPEG", quality=95, exif=exif_data)
        save_to = jpg_path
    else:
        save_to = output_path or image_path

    try:
        exif_dict = piexif.load(str(save_to))
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

    # Latitude
    lat_ref = b"N" if point.lat >= 0 else b"S"
    lat_dms = _decimal_to_dms(point.lat)

    # Longitude
    lon_ref = b"E" if point.lon >= 0 else b"W"
    lon_dms = _decimal_to_dms(point.lon)

    # Altitude
    alt_ref = 0 if point.alt >= 0 else 1  # 0 = above sea level
    alt_rational = (int(abs(point.alt) * 100), 100)

    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: lat_ref,
        piexif.GPSIFD.GPSLatitude: lat_dms,
        piexif.GPSIFD.GPSLongitudeRef: lon_ref,
        piexif.GPSIFD.GPSLongitude: lon_dms,
        piexif.GPSIFD.GPSAltitudeRef: alt_ref,
        piexif.GPSIFD.GPSAltitude: alt_rational,
    }

    exif_dict["GPS"] = gps_ifd
    # Sanitize before dumping to avoid piexif type errors from weird EXIF data
    sanitize_exif_for_piexif(exif_dict)
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, str(save_to), str(save_to))

    return save_to
