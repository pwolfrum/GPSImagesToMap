from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image

from gpsimagestomap.main import geotag


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

    out = trip / "geotagged" / "IMG_0001.jpg"
    assert out.is_file()

    exif = piexif.load(str(out))
    gps = exif.get("GPS", {})

    assert piexif.GPSIFD.GPSLatitude in gps
    assert piexif.GPSIFD.GPSLongitude in gps
    assert piexif.GPSIFD.GPSAltitude in gps
