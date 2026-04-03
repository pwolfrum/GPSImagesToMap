# GPSImagesToMap

Geotag photos using GPS track files (IGC/GPX), then view the results on a 3D Cesium map.

## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
```

For 3D terrain in the viewer, create a `.env` file with a free [Cesium ion](https://ion.cesium.com/tokens) token:

```
CESIUM_ION_TOKEN="your_token_here"
```

## Folder structure

Both commands expect the same input folder — one that contains your track files and photos:

```
my-trip/
  flight.igc           ← track files (IGC, GPX)
  route.gpx
  IMG_001.jpg          ← photos with EXIF timestamps
  IMG_002.heic
  geotagged/           ← created automatically by geotagging
    IMG_001.jpg
    IMG_002.jpg
```

The viewer reads tracks from the input folder and geotagged images from the `geotagged/` subfolder. If you accidentally select the `geotagged/` folder in the dialog, it will auto-correct to its parent.

## Usage

### Geotag + View (default)

Place track files and photos in a folder, then run:

```
uv run python main.py path/to/my-trip
```

This will:
1. Parse all track files in the folder
2. Read EXIF timestamps from images (JPEG, HEIC, TIFF)
3. Match images to tracks by time
4. Write GPS coordinates into image EXIF → saved to `path/to/my-trip/geotagged/`
5. Launch a 3D viewer in your browser

Omit the path to get a folder picker dialog:

```
uv run python main.py
```

### View only (skip geotagging)

To view results from a previous run without re-geotagging, pass the **same folder** you used for geotagging (not the `geotagged/` subfolder):

```
uv run python main.py serve path/to/my-trip
uv run python main.py serve path/to/my-trip --port 8080
```

Or omit the path for a folder picker:

```
uv run python main.py serve
```

### Options

| Option | Description |
|---|---|
| `--skip-no-timestamp` | Skip images without EXIF timestamps without prompting |
| `--time-offset N` | Shift image timestamps by N minutes before matching (decimal allowed, e.g. `-13` or `7.5`) | Only possible in geotagging mode.
| `serve` | View-only mode (no geotagging) |
| `serve --port N` | Set the server port (default: 5000) |
| `serve --fullscreen` | Open images in fullscreen mode by default |
| `export` | Export a self-contained static site |
| `export --output DIR` | Set the export output directory (default: `<input>/export/`) |

### Correcting camera clock drift

If photos appear at the wrong position along the track, the camera clock was likely off by a few minutes. Use `--time-offset` to correct this:

```
uv run python main.py path/to/my-trip --time-offset -13
```

A **negative** value shifts images earlier (camera was ahead), **positive** shifts later (camera was behind). Each run overwrites the previous `geotagged/` output, so you can quickly iterate to find the right value.

### Export static site

Generate a self-contained HTML site that can be hosted anywhere (GitHub Pages, Netlify, etc.):

```
uv run python main.py export path/to/my-trip
uv run python main.py export path/to/my-trip --output path/to/output
```

This creates an output folder (defaults to `path/to/my-trip/export/`) with:

```
export/
  index.html       ← standalone Cesium viewer with inline data
  images/          ← full-size geotagged images
  thumbnails/      ← 200×200 JPEG thumbnails
```

### Hosting on GitHub Pages

1. Export the static site:
   ```
   uv run python main.py export path/to/my-trip --output docs
   ```

2. Push the `docs/` folder to your repository.

3. In your repo settings → **Pages** → set source to "Deploy from a branch", branch `main`, folder `/docs`.

4. Your flight viewer will be live at `https://<user>.github.io/<repo>/`.

> **Note:** The Cesium ion token is embedded in the exported HTML. Free-tier tokens have no usage limits, but avoid sharing tokens tied to paid plans.

## Supported formats

- **Tracks:** IGC, GPX
- **Images:** JPEG, HEIC/HEIF, TIFF, PNG (HEIC files are converted to JPEG during geotagging)
