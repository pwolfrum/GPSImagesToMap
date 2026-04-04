from pathlib import Path

import pytest

from gpsimagestomap.track_parser import parse_igc, parse_track_file


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


def test_parse_igc_parses_expected_points(tmp_path: Path) -> None:
    igc_path = tmp_path / "flight.igc"
    _write_sample_igc(igc_path)

    track = parse_igc(igc_path)

    assert track.name == "flight"
    assert track.source_path == igc_path
    assert len(track.points) == 2

    first = track.points[0]
    second = track.points[1]

    assert first.lat == pytest.approx(48.1166667, rel=1e-6)
    assert first.lon == pytest.approx(11.5, rel=1e-6)
    assert first.alt == 10000

    assert second.lat == pytest.approx(48.1333333, rel=1e-6)
    assert second.lon == pytest.approx(11.6666667, rel=1e-6)
    assert second.alt == 11000


def test_parse_track_file_rejects_unsupported_extension(tmp_path: Path) -> None:
    unsupported = tmp_path / "track.txt"
    unsupported.write_text("ignored", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported track format"):
        parse_track_file(unsupported)
