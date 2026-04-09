# GPSImagesToMap

Geotag photos using GPS track files (IGC/GPX), then view the results on a 3D Cesium map. In default mode, only photos taken during the track recording will be shown.
A 'show' can be used to view photos which already have GPS tags without accompanying track files.

## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
```

This installs the package in editable mode and registers the `gpsimagestomap` command.

For 3D terrain in the viewer, configure a free [Cesium ion](https://ion.cesium.com/tokens) token:

- Launcher users: click Setup in the GUI; the token is saved to `%LOCALAPPDATA%/GPSImagesToMap/config/.env`
- Developer/manual workflow: you can still create a project `.env` file

```
CESIUM_ION_TOKEN="your_token_here"
```

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

- Default on Windows: `%LOCALAPPDATA%/GPSImagesToMap/work/`
- Optional override: set `GPSIMAGES_WORK_DIR` to a custom location

Within that work root, each input folder gets its own stable dataset subfolder.

## Usage

### Launcher (recommended)

Run without arguments to open the launcher GUI:

```
uv run gpsimagestomap
```

Modes in the launcher:

- Geotag: Match photos to tracks and display in map.
- Review: Show previously generated trip results (simply select original input folder for autodetection)
- Browse: Show photos that already contain GPS tags (no tracks, but connected by temporal order).
- Export: Build a static website package for sharing or hosting.

All existing CLI commands remain available and are documented below.

### Geotag + View (default)

Place track files and photos in a folder, then run:

```
uv run gpsimagestomap path/to/my-trip
```

This will:
1. Parse all track files in the folder
2. Read EXIF timestamps from images (JPEG, HEIC, TIFF)
3. Match images to tracks by time
4. Write GPS coordinates into image EXIF → saved to the app-managed work directory
5. Launch a 3D viewer in your browser

Omit the path to get a folder picker dialog:

```
uv run gpsimagestomap
```

#### Geotag behavior notes

- Images without EXIF timestamps are always ignored.
- The console prints a clear list of ignored files without timestamps.
- Timestamped images outside all track time ranges are also ignored.
- The console prints a clear list of those outside-range files, including timestamps.

### View only (skip geotagging)

To view results from a previous run without re-geotagging, pass the same source folder you used for geotagging:

```
uv run gpsimagestomap serve path/to/my-trip
uv run gpsimagestomap serve path/to/my-trip --port 8080
```

Or omit the path for a folder picker:

```
uv run gpsimagestomap serve
```

### Options

| Option | Description |
|---|---|
| `--time-offset N` | Shift image timestamps by N minutes before matching (decimal allowed, e.g. `-13` or `7.5`). Only available in geotagging mode. |
| `serve` | View-only mode (no geotagging). Will reuse the processed images from a previous run |
| `serve --port N` | Set the server port (default: 5000) |
| `serve --fullscreen` | Open images in fullscreen mode by default |
| `show` | Display all GPS-tagged images on the map (no tracks needed). Does image format conversion if needed |
| `show --no-sequence-line` | In show mode, hide the thin gray line that connects images in timestamp order |
| `export` | Export a self-contained static site, which can be hosted on the web |
| `export --output DIR` | Set the export output directory (default: `<input>/export/`) |
| `export --preview` | Start a local static preview server after export (default port: 8000) |

### Correcting camera clock drift

If photos appear at the wrong position along the track, the camera clock was likely off by a few minutes. Use `--time-offset` to correct this:

```
uv run gpsimagestomap path/to/my-trip --time-offset -13
```

A **negative** value shifts images earlier (camera was ahead), **positive** shifts later (camera was behind). Each run overwrites the previous generated output for that dataset, so you can quickly iterate to find the right value.

### Show GPS-tagged images (no tracks)

Display images that already have GPS coordinates in their EXIF on the 3D map — no track files needed:

```
uv run gpsimagestomap show path/to/photos
uv run gpsimagestomap show
```

Disable the temporal connecting line in show mode:

```
uv run gpsimagestomap show path/to/photos --no-sequence-line
```

Images without GPS tags are listed but skipped. HEIC/HEIF files are automatically converted to JPEG for browser compatibility.

### Export static site

Generate a self-contained HTML site that can be hosted anywhere (GitHub Pages, Netlify, etc.):

```
uv run gpsimagestomap export path/to/my-trip
uv run gpsimagestomap export path/to/my-trip --output path/to/output
```

This creates an output folder (defaults to `path/to/my-trip/export/`) with:

```
export/
  index.html       ← standalone Cesium viewer with inline data
  images/          ← full-size generated images
  thumbnails/      ← 200×200 JPEG thumbnails
```

To preview the export locally:

```
uv run gpsimagestomap export path/to/my-trip --preview
```

### Hosting on GitHub Pages

1. Export the static site:
   ```
   uv run gpsimagestomap export path/to/my-trip --output docs
   ```

2. Push the `docs/` folder to your repository.

3. In your repo settings → **Pages** → set source to "Deploy from a branch", branch `main`, folder `/docs`.

4. Your flight viewer will be live at `https://<user>.github.io/<repo>/`.

> **Note:** The Cesium ion token is embedded in the exported HTML. Free-tier tokens have no usage limits, but avoid sharing tokens tied to paid plans.

## Supported formats

- **Tracks:** IGC, GPX
- **Images:** JPEG, HEIC/HEIF, TIFF, PNG (all non-JPEG inputs are saved as JPEG in the app-managed work directory)
