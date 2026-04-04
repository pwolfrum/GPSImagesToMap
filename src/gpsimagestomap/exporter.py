"""Export geotagged flight data as a self-contained static site."""

import http.server
import json
import os
import shutil
import webbrowser
from functools import partial
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

from .image_discovery import IMAGE_EXTENSIONS
from .server import _load_dotenv, _read_gps_from_exif
from .track_parser import TRACK_EXTENSIONS, parse_track_file

THUMBNAIL_SIZE = (200, 200)


def export(input_dir: Path, output_dir: Path) -> None:
    """Export tracks + geotagged images to a static site folder.

    Creates:
        output_dir/
            index.html      – standalone Cesium viewer
            images/          – full-size geotagged images
            thumbnails/      – 200×200 JPEG thumbnails
    """
    _load_dotenv(Path.cwd())

    geotagged_dir = input_dir / "geotagged"
    if not geotagged_dir.is_dir():
        print(f"  No geotagged/ folder found in {input_dir}")
        print("  Run the geotagging pipeline first.")
        return

    # Collect track data
    tracks_data = []
    for p in sorted(input_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in TRACK_EXTENSIONS:
            try:
                for track in parse_track_file(p):
                    tracks_data.append(
                        {
                            "name": track.name,
                            "points": [
                                {
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

    # Collect geotagged image metadata
    images_data = []
    image_files: list[Path] = []
    for p in sorted(geotagged_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            coords = _read_gps_from_exif(p)
            if coords:
                images_data.append(
                    {
                        "filename": p.name,
                        "lat": coords[0],
                        "lon": coords[1],
                        "alt": coords[2],
                    }
                )
                image_files.append(p)

    print(f"  {len(tracks_data)} track(s), {len(images_data)} geotagged image(s)")

    if not tracks_data and not images_data:
        print("  Nothing to export.")
        return

    # Create output directories
    out_images = output_dir / "images"
    out_thumbs = output_dir / "thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_images.mkdir(exist_ok=True)
    out_thumbs.mkdir(exist_ok=True)

    # Copy full-size images
    print("  Copying images...")
    for p in image_files:
        shutil.copy2(p, out_images / p.name)

    # Generate thumbnails
    print("  Generating thumbnails...")
    for p in image_files:
        try:
            img = Image.open(p)
            img = ImageOps.exif_transpose(img)
            img.thumbnail(THUMBNAIL_SIZE)
            img.convert("RGB").save(out_thumbs / p.name, "JPEG", quality=80)
        except Exception as e:
            print(f"    Warning: thumbnail failed for {p.name}: {e}")

    # Render HTML
    token = os.environ.get("CESIUM_ION_TOKEN", "")
    template_path = Path(__file__).parent / "templates" / "export.html"
    html = template_path.read_text(encoding="utf-8")

    title = input_dir.name
    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{CESIUM_TOKEN}}", token)
    html = html.replace("{{TRACKS_JSON}}", json.dumps(tracks_data))
    html = html.replace("{{IMAGES_JSON}}", json.dumps(images_data))

    (output_dir / "index.html").write_text(html, encoding="utf-8")

    print(f"\n  Export complete → {output_dir}")
    print(
        "  NOTE: Opening index.html from file:// won't work (browser blocks Cesium tile requests)."
    )
    print(
        "  Use 'python main.py export --preview' or host on a web server / GitHub Pages."
    )


def preview(output_dir: Path, port: int = 8000) -> None:
    """Serve the export folder with a simple HTTP server for local preview."""
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(output_dir))
    url = f"http://localhost:{port}"
    print(f"  Serving export at {url}")
    print("  Press Ctrl+C to stop.\n")
    webbrowser.open(url)
    with http.server.HTTPServer(("127.0.0.1", port), handler) as httpd:
        httpd.serve_forever()
