# AGENTS.md

## Purpose
GPSImagesToMap geotags photos from GPS tracks (IGC/GPX) and visualizes them in a Cesium 3D viewer. It also supports view-only and static export workflows.

## Runtime Overview
- Entry point: `src/gpsimagestomap/main.py` (installed script: `gpsimagestomap`)
- Run via: `uv run gpsimagestomap [args]` or `uv run python -m gpsimagestomap [args]`
- Core flow in default mode:
  1. Discover tracks in selected input folder (`discover_tracks`)
  2. Discover images in the same folder (`discover_images`)
  3. Resolve timestamp issues (missing timestamps, timezone uncertainty, optional manual offset)
  4. Match images to tracks by time (`match_images_to_tracks`)
  5. Interpolate coordinates and write GPS EXIF (`interpolate_position`, `write_gps_exif`)
  6. Launch Flask Cesium viewer (`server.serve`)

## CLI Modes
- `gpsimagestomap [INPUT_DIR]`:
  Geotag images, write output to `INPUT_DIR/geotagged/`, launch viewer.
- `gpsimagestomap serve [INPUT_DIR] [--port N] [--fullscreen]`:
  View-only mode using track files from `INPUT_DIR` and geotagged images from `INPUT_DIR/geotagged/`.
- `gpsimagestomap show [INPUT_DIR] [--port N] [--fullscreen]`:
  Display images that already contain GPS EXIF; no tracks required.
- `gpsimagestomap export [INPUT_DIR] [--output DIR] [--preview]`:
  Export static site with inline track/image metadata and copied image assets.

## Data Model
- `track_parser.TrackPoint`: `time`, `lat`, `lon`, `alt`
- `track_parser.Track`: `name`, `source_path`, `points`
- `image_discovery.ImageInfo`: `path`, `timestamp`, `has_gps`, `tz_certain`

## Module Responsibilities
- `track_parser.py`:
  Parses IGC and GPX into normalized tracks.
- `image_discovery.py`:
  Finds supported image files and extracts EXIF timestamp/GPS metadata.
- `geotagger.py`:
  Interpolates positions and writes GPS EXIF (converts non-JPEG input to JPEG before EXIF write).
- `server.py`:
  Flask app serving map UI, APIs, images, and generated thumbnails.
- `exporter.py`:
  Static-site export (`index.html`, `images/`, `thumbnails/`) and optional local preview server.

## Input/Output Conventions
- Input scanning is non-recursive by default in main flows.
- Track files and photos must be directly in the selected folder.
- Geotagging output is always written to `geotagged/`.
- Existing files in `geotagged/` are cleaned before writing new output.

## Time Handling Notes
- Track timestamps are generally timezone-aware (UTC for IGC, from GPX parser for GPX).
- Image timestamps may be naive when EXIF timezone offset is missing.
- Matching/interpolation falls back to treating naive image time as UTC when compared to aware track times.
- Optional `--time-offset` adjusts only images without original GPS tags.

## Environment and Dependencies
- Python requirement in project config: `>=3.14`
- Source layout: `src/gpsimagestomap/` (hatchling build backend)
- Runtime dependencies: Flask, gpxpy, piexif, Pillow, pillow-heif
- Cesium terrain requires `CESIUM_ION_TOKEN` in `.env` at project root

## Development Workflow
- Install deps: `uv sync`
- Run app: `uv run gpsimagestomap <input-dir>` or `uv run python -m gpsimagestomap <input-dir>`
- Run tests: `uv run --group dev pytest`

## Testing Strategy
- Unit tests should focus on deterministic pure logic:
  - Track parsing (`parse_igc`, `parse_track_file` behavior)
  - Time interpolation (`interpolate_position`)
  - Matching and timezone correction helpers where practical
- Integration tests should exercise real file IO for one end-to-end geotag scenario:
  - Synthetic track + synthetic JPEG with EXIF timestamp
  - Run `main.geotag(...)`
  - Assert geotagged output exists and has GPS EXIF

## Known Behavior and Constraints
- No recursive directory scan for the primary workflows.
- Duplicate image filenames across tracks may overwrite each other in `geotagged/`.
- `server._kill_port` uses Windows-specific commands (`netstat`, `taskkill`).
- Static export requires HTTP hosting for Cesium resources (opening via `file://` is insufficient).

## Suggested Extension Points
- Add deduplication/renaming strategy for colliding output filenames.
- Add richer CLI parsing (argparse/typer) and stronger validation.
- Expand tests for Flask routes and export artifact content.
