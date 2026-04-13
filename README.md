# FlightPhotoMapper

## About

FlightPhotoMapper geotags photos to flight/activity tracks (IGC/GPX) and visualizes both in a Cesium 3D map viewer.

Main capabilities:
- Match photo timestamps to recorded track points
- Write interpolated GPS EXIF coordinates into images
- Render tracks and photos in a Cesium 3D map viewer
- Review previously processed trips (to save processing time)
- Browse already geotagged photos without the need for gps tracks (e.g. for vacation pictures)

Author: Philipp Wolfrum


## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
```

This installs the package in editable mode and registers the `flightphotomapper` command.

For 3D terrain in the viewer, configure a free [Cesium ion](https://ion.cesium.com/tokens) token:

- Launcher users: click Setup in the GUI; the token is saved to `%LOCALAPPDATA%/FlightPhotoMapper/config/.env`
- Developer/manual workflow: you can still create a project `.env` file

```
CESIUM_ION_TOKEN="your_token_here"
```

## Windows standalone executable

Build a one-folder Windows executable:

```
scripts\build_exe.bat
```

Successful output is:

```
dist\flightphotomapper\flightphotomapper.exe
```

For distribution to non-technical users:

1. Zip the folder `dist\flightphotomapper\`
2. Upload that zip to a GitHub Release
3. Users download zip, extract, and run `flightphotomapper.exe`

One-folder mode is intentional; startup is faster and more reliable than one-file mode.

## Folder structure

All commands expect the same input folder — one that contains your track files and photos directly in that folder:

```
my-trip/
  flight.igc           ← track files (IGC, GPX)
  route.gpx
  IMG_001.jpg          ← photos with EXIF timestamps
  IMG_002.heic
```

The tool only reads track files and images directly in the folder you select; it does not scan nested subfolders.

Generated images are stored in an app-managed working directory, not inside your trip folder.

- Default on Windows: `%LOCALAPPDATA%/FlightPhotoMapper/work/`
- Optional override: set `GPSIMAGES_WORK_DIR` to a custom location

Within that work root, each input folder gets its own stable dataset subfolder.

## Usage

### Launcher (recommended)

Run without arguments to open the launcher GUI:

```
uv run flightphotomapper
```

Modes in the launcher:

- Geotag: Match photos to tracks and display in map.
- Review: Show previously generated trip results (simply select original input folder for autodetection)
- Browse: Show photos that already contain GPS tags (no tracks, but connected by temporal order).

All existing CLI commands remain available and are documented below.

### Geotag + View (default)

Place track files and photos in a folder, then run:

```
uv run flightphotomapper path/to/my-trip
uv run flightphotomapper geotag path/to/my-trip
```

This will:
1. Parse all track files in the folder
2. Read EXIF timestamps from images (JPEG, HEIC, TIFF)
3. Match images to tracks by time
4. Write GPS coordinates into image EXIF → saved to the app-managed work directory
5. Launch a 3D viewer in your browser

Omit the path to get a folder picker dialog:

```
uv run flightphotomapper
```

#### Geotag behavior notes

- Images without EXIF timestamps are always ignored.
- The console prints a clear list of ignored files without timestamps.
- Timestamped images outside all track time ranges are also ignored.
- The console prints a clear list of those outside-range files, including timestamps.

### Review (skip geotagging)

To view results from a previous run without re-geotagging, pass the same source folder you used for geotagging:

```
uv run flightphotomapper review path/to/my-trip
uv run flightphotomapper review path/to/my-trip --port 8080
```

Or omit the path for a folder picker:

```
uv run flightphotomapper review
```

### Options

| Option | Description |
|---|---|
| `geotag [INPUT_DIR]` | Geotag mode. Match photos to tracks, write GPS EXIF, and open the viewer (also the default when no subcommand is given). |
| `--time-offset N` | Shift image timestamps by N minutes before matching (decimal allowed, e.g. `-13` or `7.5`). Only available in geotagging mode. |
| `review` | View-only mode (no geotagging). Reuses processed images from a previous run (same input folder). |
| `review --port N` | Set the server port (default: 5000) |
| `review --fullscreen` | Open images in fullscreen mode by default |
| `browse` | Display all GPS-tagged images on the map (no tracks needed). Does image format conversion if needed |
| `browse --no-sequence-line` | In browse mode, hide the thin gray line that connects images in timestamp order |

### Correcting camera clock drift

If photos appear at the wrong position along the track, the camera clock was likely off by a few minutes. Use `--time-offset` to correct this:

```
uv run flightphotomapper path/to/my-trip --time-offset -13
```

A **negative** value shifts images earlier (camera was ahead), **positive** shifts later (camera was behind). Each run overwrites the previous generated output for that dataset, so you can quickly iterate to find the right value.

### Browse GPS-tagged images (no tracks)

Display images that already have GPS coordinates in their EXIF on the 3D map — no track files needed:

```
uv run flightphotomapper browse path/to/photos
uv run flightphotomapper browse
```

Disable the temporal connecting line in browse mode:

```
uv run flightphotomapper browse path/to/photos --no-sequence-line
```

Images without GPS tags are listed but skipped. HEIC/HEIF files are automatically converted to JPEG for browser compatibility.

## Supported formats

- **Tracks:** IGC, GPX
- **Images:** JPEG, HEIC/HEIF, TIFF, PNG (all non-JPEG inputs are saved as JPEG in the app-managed work directory)


## Acknowledgements

This project uses and depends on several excellent open-source libraries and services, including:

- Flask (web server)
- Pillow and pillow-heif (image processing and HEIC support)
- piexif (EXIF read/write)
- gpxpy (GPX parsing)
- CesiumJS / Cesium ion (3D globe and terrain)

For redistributed builds, please keep all third-party license notices required by dependencies.

## License

This project is licensed under the MIT License.

See [LICENSE](LICENSE) for the full text.
