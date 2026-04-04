"""Parse GPS track files (IGC, GPX) into a common format."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import gpxpy


@dataclass
class TrackPoint:
    time: datetime
    lat: float
    lon: float
    alt: float  # meters, GPS altitude


@dataclass
class Track:
    name: str
    source_path: Path
    points: list[TrackPoint]

    @property
    def start_time(self) -> datetime:
        return self.points[0].time

    @property
    def end_time(self) -> datetime:
        return self.points[-1].time


def parse_igc(path: Path) -> Track:
    """Parse an IGC file into a Track."""
    points: list[TrackPoint] = []
    flight_date = None

    with open(path, encoding="latin-1") as f:
        for line in f:
            line = line.strip()

            # Date header: HFDTEDATE:DDMMYY,NN or HFDTE:DDMMYY or HFDTEDDMMYY
            if line.startswith("HFDTE"):
                date_str = line.split(":")[-1].split(",")[0]
                # Could also be HFDTEDDMMYY without colon
                if not date_str:
                    date_str = line[5:11]
                date_str = date_str.strip()
                if len(date_str) >= 6:
                    day = int(date_str[0:2])
                    month = int(date_str[2:4])
                    year = int(date_str[4:6])
                    year += 2000 if year < 80 else 1900
                    flight_date = (year, month, day)

            # B-record: BHHMMSSDDMMmmmNDDDMMmmmEVPPPPPGGGGG
            if line.startswith("B") and len(line) >= 35 and flight_date:
                try:
                    hour = int(line[1:3])
                    minute = int(line[3:5])
                    second = int(line[5:7])

                    lat_deg = int(line[7:9])
                    lat_min = int(line[9:11])
                    lat_min_frac = int(line[11:14])
                    lat = lat_deg + (lat_min + lat_min_frac / 1000) / 60
                    if line[14] == "S":
                        lat = -lat

                    lon_deg = int(line[15:18])
                    lon_min = int(line[18:20])
                    lon_min_frac = int(line[20:23])
                    lon = lon_deg + (lon_min + lon_min_frac / 1000) / 60
                    if line[23] == "W":
                        lon = -lon

                    # GPS altitude (field after pressure altitude)
                    gps_alt = int(line[30:35])

                    time = datetime(
                        flight_date[0],
                        flight_date[1],
                        flight_date[2],
                        hour,
                        minute,
                        second,
                        tzinfo=timezone.utc,
                    )
                    points.append(TrackPoint(time=time, lat=lat, lon=lon, alt=gps_alt))
                except (ValueError, IndexError):
                    continue

    if not points:
        raise ValueError(f"No valid B-records found in {path}")

    name = path.stem
    return Track(name=name, source_path=path, points=points)


def parse_gpx(path: Path) -> list[Track]:
    """Parse a GPX file into one or more Tracks."""
    with open(path, encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    tracks: list[Track] = []
    for gpx_track in gpx.tracks:
        points: list[TrackPoint] = []
        for segment in gpx_track.segments:
            for pt in segment.points:
                if pt.time is None:
                    continue
                points.append(
                    TrackPoint(
                        time=pt.time,
                        lat=pt.latitude,
                        lon=pt.longitude,
                        alt=pt.elevation or 0.0,
                    )
                )
        if points:
            track_name = gpx_track.name or path.stem
            tracks.append(Track(name=track_name, source_path=path, points=points))

    if not tracks:
        raise ValueError(f"No tracks with timestamps found in {path}")

    return tracks


TRACK_EXTENSIONS = {".igc", ".gpx"}


def parse_track_file(path: Path) -> list[Track]:
    """Parse any supported track file, returning a list of Tracks."""
    ext = path.suffix.lower()
    if ext == ".igc":
        return [parse_igc(path)]
    elif ext == ".gpx":
        return parse_gpx(path)
    else:
        raise ValueError(f"Unsupported track format: {ext}")
