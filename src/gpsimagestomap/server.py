"""Flask server for the Cesium.js 3D flight viewer."""

import json
import os
import webbrowser
from datetime import timezone
from io import BytesIO
from pathlib import Path

from flask import Flask, Response, abort, send_file
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

from .app_config import load_app_env
from .image_discovery import IMAGE_EXTENSIONS, read_image_info
from .storage import get_dataset_images_dir
from .track_parser import TRACK_EXTENSIONS, parse_track_file

THUMBNAIL_SIZE = (200, 200)


def _build_image_sequence_track(
    sequence_points: list[dict[str, str | float]],
) -> dict | None:
    """Create a virtual track connecting images by timestamp order."""
    if len(sequence_points) < 2:
        return None

    ordered_points = sorted(sequence_points, key=lambda p: str(p["time"]))
    return {
        "name": "Image sequence",
        "points": ordered_points,
        "style": {
            "color": "#9aa0a6",
            "width": 1.5,
        },
    }


def _read_gps_from_exif(path: Path) -> tuple[float, float, float] | None:
    """Read GPS lat/lon/alt from a generated image's EXIF."""
    try:
        import piexif

        exif_dict = piexif.load(str(path))
    except Exception:
        return None

    gps = exif_dict.get("GPS", {})
    if not gps:
        return None

    try:
        lat_dms = gps[piexif.GPSIFD.GPSLatitude]
        lat_ref = gps[piexif.GPSIFD.GPSLatitudeRef]
        lon_dms = gps[piexif.GPSIFD.GPSLongitude]
        lon_ref = gps[piexif.GPSIFD.GPSLongitudeRef]

        def dms_to_decimal(dms: list, ref: bytes) -> float:
            d = dms[0][0] / dms[0][1]
            m = dms[1][0] / dms[1][1]
            s = dms[2][0] / dms[2][1]
            decimal = d + m / 60 + s / 3600
            if ref in (b"S", b"W"):
                decimal = -decimal
            return decimal

        lat = dms_to_decimal(lat_dms, lat_ref)
        lon = dms_to_decimal(lon_dms, lon_ref)

        alt = 0.0
        if piexif.GPSIFD.GPSAltitude in gps:
            alt_rational = gps[piexif.GPSIFD.GPSAltitude]
            alt = alt_rational[0] / alt_rational[1]
            if gps.get(piexif.GPSIFD.GPSAltitudeRef, 0) == 1:
                alt = -alt

        return (lat, lon, alt)
    except KeyError, IndexError, ZeroDivisionError:
        return None


def create_app(
    input_dir: Path,
    image_mode: str = "panel",
    include_tracks: bool = True,
    include_image_sequence_track: bool = True,
) -> Flask:
    """Create and configure the Flask app for serving the map viewer."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=None,
    )

    generated_images_dir = get_dataset_images_dir(input_dir)
    thumbnail_cache: dict[str, bytes] = {}

    # Pre-load track data
    tracks_data = []
    if include_tracks:
        for p in sorted(input_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in TRACK_EXTENSIONS:
                try:
                    for track in parse_track_file(p):
                        tracks_data.append(
                            {
                                "name": track.name,
                                "points": [
                                    {
                                        "time": pt.time.isoformat(),
                                        "lat": pt.lat,
                                        "lon": pt.lon,
                                        "alt": pt.alt,
                                    }
                                    for pt in track.points
                                ],
                            }
                        )
                except ValueError:
                    pass

    # Pre-load generated image metadata
    images_data = []
    image_sequence_points: list[dict[str, str | float]] = []
    if generated_images_dir.is_dir():
        for p in sorted(generated_images_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                coords = _read_gps_from_exif(p)
                if coords:
                    img_info = read_image_info(p)
                    images_data.append(
                        {
                            "filename": p.name,
                            "lat": coords[0],
                            "lon": coords[1],
                            "alt": coords[2],
                        }
                    )
                    if img_info.timestamp is not None:
                        timestamp = img_info.timestamp
                        if timestamp.tzinfo is None:
                            timestamp = timestamp.replace(tzinfo=timezone.utc)
                        image_sequence_points.append(
                            {
                                "time": timestamp.isoformat(),
                                "lat": coords[0],
                                "lon": coords[1],
                                "alt": coords[2],
                            }
                        )

    if not include_tracks and include_image_sequence_track:
        image_sequence_track = _build_image_sequence_track(image_sequence_points)
        if image_sequence_track is not None:
            tracks_data.append(image_sequence_track)

    print(
        f"  Loaded {len(tracks_data)} track(s), {len(images_data)} geotagged image(s)"
    )
    print(f"  Input dir: {input_dir}")
    print(
        "  Generated images dir: "
        f"{generated_images_dir} ({'exists' if generated_images_dir.is_dir() else 'NOT FOUND'})"
    )

    @app.route("/")
    def index():
        token = os.environ.get("CESIUM_ION_TOKEN", "")
        html_path = Path(__file__).parent / "templates" / "map.html"
        html = html_path.read_text(encoding="utf-8")
        html = html.replace("{{CESIUM_TOKEN}}", token)
        html = html.replace("{{IMAGE_MODE}}", image_mode)
        return Response(html, mimetype="text/html")

    @app.route("/api/tracks")
    def api_tracks():
        resp = Response(json.dumps(tracks_data), mimetype="application/json")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/api/images")
    def api_images():
        resp = Response(json.dumps(images_data), mimetype="application/json")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/images/<filename>")
    def serve_image(filename: str):
        # Sanitize filename to prevent path traversal
        safe_name = Path(filename).name
        if safe_name != filename:
            abort(400)
        file_path = generated_images_dir / safe_name
        if not file_path.is_file():
            abort(404)
        return send_file(file_path)

    @app.route("/thumbnails/<filename>")
    def serve_thumbnail(filename: str):
        safe_name = Path(filename).name
        if safe_name != filename:
            abort(400)

        if safe_name in thumbnail_cache:
            return Response(thumbnail_cache[safe_name], mimetype="image/jpeg")

        file_path = generated_images_dir / safe_name
        if not file_path.is_file():
            abort(404)

        try:
            img = Image.open(file_path)
            img = ImageOps.exif_transpose(img)
            img.thumbnail(THUMBNAIL_SIZE)
            buf = BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=80)
            thumbnail_cache[safe_name] = buf.getvalue()
            return Response(thumbnail_cache[safe_name], mimetype="image/jpeg")
        except Exception:
            abort(500)

    return app


def _kill_port(port: int) -> None:
    """Kill any process currently listening on the given port (Windows)."""
    import subprocess

    try:
        # Use netstat but match on port + PID column regardless of locale
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            check=False,
            text=True,
        )
        killed = set()
        for line in result.stdout.splitlines():
            # Match lines with our port in a local address column
            if f":{port} " not in line and f":{port}\t" not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            # Local address is parts[1], state is parts[3], PID is parts[4]
            local_addr = parts[1]
            if not local_addr.endswith(f":{port}"):
                continue
            try:
                pid = int(parts[4])
            except ValueError, IndexError:
                continue
            if pid == 0 or pid in killed:
                continue
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
            killed.add(pid)
            print(f"  Killed previous server (PID {pid}) on port {port}")
    except Exception:
        pass


def serve(
    input_dir: Path,
    port: int = 5000,
    image_mode: str = "panel",
    include_tracks: bool = True,
    include_image_sequence_track: bool = True,
) -> None:
    """Start the Flask server and open the browser."""
    load_app_env(Path.cwd())
    _kill_port(port)
    app = create_app(
        input_dir,
        image_mode=image_mode,
        include_tracks=include_tracks,
        include_image_sequence_track=include_image_sequence_track,
    )
    token = os.environ.get("CESIUM_ION_TOKEN", "")
    if not token:
        print("\n  NOTE: Set CESIUM_ION_TOKEN for 3D terrain.")
        print("  Get a free token at https://ion.cesium.com/tokens")
        print("  Launcher setup saves token to per-user config .env automatically.")
        print("  Without it, the viewer will use a flat globe.\n")

    url = f"http://localhost:{port}"
    print(f"  Starting viewer at {url}")
    print("  Press Ctrl+C to stop.\n")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=port, debug=False)
