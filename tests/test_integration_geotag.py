from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image

from gpsimagestomap.main import geotag
from gpsimagestomap.storage import get_dataset_images_dir


def _write_sample_igc(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "AXXX",
                "HFDTEDATE:010124,01",
                "B1200004807000N01130000EA0000010000",
                "B1210004808000N01140000EA0000011000",
            ]
        ),
        encoding="latin-1",
    )


def _write_jpeg_with_timestamp(path: Path, dt: str) -> None:
    img = Image.new("RGB", (8, 8), (255, 0, 0))
    exif_dict = {
        "0th": {},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: dt},
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    img.save(path, "JPEG", exif=piexif.dump(exif_dict))


def test_geotag_writes_output_with_gps_exif(tmp_path: Path) -> None:
    trip = tmp_path / "trip"
    trip.mkdir()

    _write_sample_igc(trip / "flight.igc")
    _write_jpeg_with_timestamp(trip / "IMG_0001.jpg", "2024:01:01 12:05:00")

    ok = geotag(trip, skip_no_timestamp=True)

    assert ok is True

    out = get_dataset_images_dir(trip) / "IMG_0001.jpg"
    assert out.is_file()

    exif = piexif.load(str(out))
    gps = exif.get("GPS", {})

    assert piexif.GPSIFD.GPSLatitude in gps
    assert piexif.GPSIFD.GPSLongitude in gps
    assert piexif.GPSIFD.GPSAltitude in gps


def _write_jpeg_with_timestamp_and_gps(
    path: Path, dt: str, lat: float, lon: float
) -> None:
    """Create JPEG with both DateTimeOriginal and GPS EXIF tags."""
    img = Image.new("RGB", (8, 8), (0, 255, 0))

    def _dms(val: float):
        val = abs(val)
        d = int(val)
        m = int((val - d) * 60)
        s = int(round(((val - d) * 60 - m) * 60 * 10000))
        return ((d, 1), (m, 1), (s, 10000))

    exif_dict = {
        "0th": {},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: dt},
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: _dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: _dms(lon),
            piexif.GPSIFD.GPSAltitudeRef: 0,
            piexif.GPSIFD.GPSAltitude: (4000, 1),
        },
        "1st": {},
        "thumbnail": None,
    }
    img.save(path, "JPEG", exif=piexif.dump(exif_dict))


def test_gps_tagged_image_preserves_original_coordinates(tmp_path: Path) -> None:
    """GPS-tagged images should be copied as-is, not re-geotagged from track."""
    trip = tmp_path / "trip"
    trip.mkdir()

    _write_sample_igc(trip / "flight.igc")
    # Image within track time range, but already has GPS at a different location
    _write_jpeg_with_timestamp_and_gps(
        trip / "PHONE.jpg", "2024:01:01 12:05:00", lat=46.0, lon=7.0
    )

    ok = geotag(trip, skip_no_timestamp=True)
    assert ok is True

    out = get_dataset_images_dir(trip) / "PHONE.jpg"
    assert out.is_file()

    exif = piexif.load(str(out))
    gps = exif.get("GPS", {})

    # Should keep original GPS (lat ~46, lon ~7), not track position (~48, ~11)
    lat_dms = gps[piexif.GPSIFD.GPSLatitude]
    assert lat_dms[0] == (46, 1)  # degrees = 46


def test_out_of_range_image_is_skipped(tmp_path: Path) -> None:
    """Images with timestamps outside track range should not appear in output."""
    trip = tmp_path / "trip"
    trip.mkdir()

    _write_sample_igc(trip / "flight.igc")
    # Track is 12:00-12:10 UTC on 2024-01-01; this image is on a different day
    _write_jpeg_with_timestamp(trip / "LATE.jpg", "2024:01:02 12:05:00")

    ok = geotag(trip, skip_no_timestamp=True)

    # No images matched → returns False
    assert ok is False
    assert not (get_dataset_images_dir(trip) / "LATE.jpg").exists()
