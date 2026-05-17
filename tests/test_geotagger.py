from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image
import piexif

from gpsimagestomap.geotagger import interpolate_position, write_gps_exif
from gpsimagestomap.track_parser import Track, TrackPoint


def _make_track() -> Track:
    return Track(
        name="demo",
        source_path=Path("demo.igc"),
        points=[
            TrackPoint(
                time=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                lat=48.0,
                lon=11.0,
                alt=1000.0,
            ),
            TrackPoint(
                time=datetime(2025, 1, 1, 12, 10, 0, tzinfo=timezone.utc),
                lat=49.0,
                lon=12.0,
                alt=2000.0,
            ),
        ],
    )


def test_interpolate_position_midpoint() -> None:
    track = _make_track()
    at = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    point = interpolate_position(track, at)

    assert point.lat == pytest.approx(48.5)
    assert point.lon == pytest.approx(11.5)
    assert point.alt == pytest.approx(1500.0)


def test_interpolate_position_returns_none_before_start() -> None:
    track = _make_track()
    before = datetime(2025, 1, 1, 11, 55, 0, tzinfo=timezone.utc)

    point = interpolate_position(track, before)

    assert point is None


def test_interpolate_position_returns_none_after_end() -> None:
    track = _make_track()
    after = datetime(2025, 1, 1, 12, 15, 0, tzinfo=timezone.utc)

    point = interpolate_position(track, after)

    assert point is None


def test_interpolate_position_exact_start() -> None:
    track = _make_track()
    at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    point = interpolate_position(track, at)

    assert point is not None
    assert point.lat == pytest.approx(48.0)
    assert point.lon == pytest.approx(11.0)


def test_interpolate_position_exact_end() -> None:
    track = _make_track()
    at = datetime(2025, 1, 1, 12, 10, 0, tzinfo=timezone.utc)

    point = interpolate_position(track, at)

    assert point is not None
    assert point.lat == pytest.approx(49.0)
    assert point.lon == pytest.approx(12.0)


def test_write_gps_exif_handles_missing_exif_tag(tmp_path) -> None:
    image_path = tmp_path / "input.jpg"
    output_path = tmp_path / "output.jpg"

    Image.new("RGB", (10, 10), color="white").save(image_path, format="JPEG")
    output_path.write_bytes(image_path.read_bytes())

    point = TrackPoint(
        time=datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc),
        lat=48.0,
        lon=11.0,
        alt=1000.0,
    )

    result_path = write_gps_exif(output_path, point, output_path=output_path)
    assert result_path == output_path

    exif_data = piexif.load(str(result_path))
    assert piexif.GPSIFD.GPSLatitude in exif_data["GPS"]
    assert piexif.GPSIFD.GPSLongitude in exif_data["GPS"]
    assert piexif.GPSIFD.GPSAltitude in exif_data["GPS"]
