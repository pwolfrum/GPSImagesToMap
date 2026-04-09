import json
from pathlib import Path

import piexif
from PIL import Image

from gpsimagestomap.server import create_app
from gpsimagestomap.storage import get_dataset_images_dir


def _decimal_to_dms(decimal: float):
    decimal = abs(decimal)
    degrees = int(decimal)
    minutes_float = (decimal - degrees) * 60
    minutes = int(minutes_float)
    seconds_float = (minutes_float - minutes) * 60
    seconds = int(round(seconds_float * 10000))
    return (degrees, 1), (minutes, 1), (seconds, 10000)


def _write_jpeg_with_timestamp_and_gps(
    path: Path,
    dt: str,
    lat: float,
    lon: float,
    alt: float,
) -> None:
    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude: _decimal_to_dms(lat),
        piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude: _decimal_to_dms(lon),
        piexif.GPSIFD.GPSAltitudeRef: 0 if alt >= 0 else 1,
        piexif.GPSIFD.GPSAltitude: (int(abs(alt) * 100), 100),
    }

    exif_dict = {
        "0th": {},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: dt},
        "GPS": gps_ifd,
        "1st": {},
        "thumbnail": None,
    }

    img = Image.new("RGB", (8, 8), (0, 255, 0))
    img.save(path, "JPEG", exif=piexif.dump(exif_dict))


def test_show_mode_exposes_virtual_image_sequence_track(tmp_path: Path) -> None:
    trip_dir = tmp_path / "trip"
    trip_dir.mkdir(parents=True)
    geotagged_dir = get_dataset_images_dir(trip_dir)
    geotagged_dir.mkdir(parents=True)

    # Filenames are intentionally out-of-order to verify timestamp ordering.
    _write_jpeg_with_timestamp_and_gps(
        geotagged_dir / "b.jpg",
        "2024:01:01 12:10:00",
        lat=48.2,
        lon=11.2,
        alt=1200,
    )
    _write_jpeg_with_timestamp_and_gps(
        geotagged_dir / "a.jpg",
        "2024:01:01 12:00:00",
        lat=48.1,
        lon=11.1,
        alt=1100,
    )

    app = create_app(trip_dir, include_tracks=False)
    client = app.test_client()

    resp = client.get("/api/tracks")
    assert resp.status_code == 200

    tracks = json.loads(resp.data)
    assert len(tracks) == 1

    sequence = tracks[0]
    assert sequence["name"] == "Image sequence"
    assert sequence["style"]["color"] == "#9aa0a6"
    assert sequence["style"]["width"] == 1.5

    points = sequence["points"]
    assert len(points) == 2
    assert points[0]["time"] < points[1]["time"]
    assert points[0]["lat"] == 48.1
    assert points[1]["lat"] == 48.2


def test_show_mode_can_disable_virtual_image_sequence_track(tmp_path: Path) -> None:
    trip_dir = tmp_path / "trip"
    trip_dir.mkdir(parents=True)
    geotagged_dir = get_dataset_images_dir(trip_dir)
    geotagged_dir.mkdir(parents=True)

    _write_jpeg_with_timestamp_and_gps(
        geotagged_dir / "a.jpg",
        "2024:01:01 12:00:00",
        lat=48.1,
        lon=11.1,
        alt=1100,
    )
    _write_jpeg_with_timestamp_and_gps(
        geotagged_dir / "b.jpg",
        "2024:01:01 12:10:00",
        lat=48.2,
        lon=11.2,
        alt=1200,
    )

    app = create_app(
        trip_dir,
        include_tracks=False,
        include_image_sequence_track=False,
    )
    client = app.test_client()

    resp = client.get("/api/tracks")
    assert resp.status_code == 200

    tracks = json.loads(resp.data)
    assert tracks == []
