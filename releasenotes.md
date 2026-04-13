# FlightPhotoMapper Release Notes

## v1.0.0

Windows standalone release for geotagging photos from IGC/GPX tracks and viewing results in a Cesium 3D map.

### Download and Run (Windows)
1. Download `flightphotomapper-windows-v1.0.0.zip` from GitHub Release assets.
2. Right-click the zip and select **Extract All...**.
3. Extract to any folder you own, for example:
   - `C:\Users\<your-name>\Desktop\FlightPhotoMapper\`
   - `C:\Users\<your-name>\Downloads\FlightPhotoMapper\`
4. Open the extracted `flightphotomapper` folder.
5. Run `flightphotomapper.exe`.

Important:
- Keep `flightphotomapper.exe` and `_internal` in the same folder.
- Do not move only the `.exe` out of the extracted folder.

If Windows SmartScreen appears:
- Click **More info** -> **Run anyway**.

### First-Time Setup
- In the launcher, click **Setup** and paste your free Cesium ion token:
  https://ion.cesium.com/tokens

### Main Modes
- **Geotag**: Match photos to tracks and write GPS EXIF.
- **Review**: Re-open previously processed trip results.
- **Browse**: Show already GPS-tagged photos (no track needed).

### Input Folder Requirements
Put track files and photos directly in one folder (non-recursive scan), for example:
- `*.igc` / `*.gpx`
- `*.jpg`, `*.heic`, `*.tiff`, `*.png`

### Documentation
For further documentation, see
- the Help section in the app
- `README.md` for complete CLI options and advanced usage.

---
## Publishing Checklist
1. Build with `scripts\build_exe.bat`.
2. Zip the full `dist\flightphotomapper\` folder.
3. Create GitHub release tag `v1.0.0` (or next version).
4. Title: `FlightPhotoMapper v1.0.0`.
5. Attach the zip in release assets.
6. Paste the `v1.0.0` section above into the GitHub release description.
