"""GPSImagesToMap — Geotag images using GPS track files, then visualize on a 3D map."""

import shutil
import tkinter as tk
from datetime import timedelta, timezone
from pathlib import Path
from tkinter import filedialog

from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

from .geotagger import interpolate_position, write_gps_exif
from .image_discovery import ImageInfo, discover_images
from .storage import get_dataset_images_dir
from .track_parser import TRACK_EXTENSIONS, Track, parse_track_file


def _align_time_for_comparison(reference_time, candidate_time):
    """Align timezone-awareness between datetimes for safe comparison."""
    if reference_time.tzinfo is not None and candidate_time.tzinfo is None:
        return candidate_time.replace(tzinfo=timezone.utc)
    if reference_time.tzinfo is None and candidate_time.tzinfo is not None:
        return candidate_time.replace(tzinfo=None)
    return candidate_time


def _count_images_in_tracks(
    tracks: list[Track], imgs: list[ImageInfo], offset: timedelta
) -> int:
    """Count how many images fall into any track range after time offset."""
    count = 0
    for img in imgs:
        if img.timestamp is None:
            continue
        shifted = img.timestamp + offset
        for track in tracks:
            t_start = track.start_time
            t_end = track.end_time
            shifted_cmp = _align_time_for_comparison(t_start, shifted)
            if t_start <= shifted_cmp <= t_end:
                count += 1
                break
    return count


def _clean_output_dir(output_dir: Path) -> None:
    """Delete stale files from a generated-output directory."""
    for old in output_dir.iterdir():
        if old.is_file():
            try:
                old.unlink()
            except PermissionError:
                import time

                time.sleep(0.5)
                old.unlink()


def _copy_or_convert_for_browser(src: Path, dst: Path) -> Path:
    """Copy image to destination, converting HEIC/HEIF to JPEG if needed."""
    if src.suffix.lower() in (".heic", ".heif"):
        jpg_path = dst.with_suffix(".jpg")
        pil_img = Image.open(src)
        exif_data = pil_img.info.get("exif", b"")
        pil_img.convert("RGB").save(jpg_path, "JPEG", quality=95, exif=exif_data)
        return jpg_path

    shutil.copy2(src, dst)
    return dst


def _parse_subcommand_port_and_flags(
    raw_args: list[str],
    *,
    default_port: int = 5000,
    fullscreen_flag: str = "--fullscreen",
    extra_flags: tuple[str, ...] = (),
) -> tuple[int, bool, dict[str, bool], list[str]]:
    """Parse a command's common flags and return remaining positional args."""
    port = default_port
    fullscreen = fullscreen_flag in raw_args
    parsed_extras = {flag: flag in raw_args for flag in extra_flags}

    stripped_args = [
        a for a in raw_args if a != fullscreen_flag and a not in parsed_extras
    ]

    remaining = []
    i = 0
    while i < len(stripped_args):
        if stripped_args[i] == "--port" and i + 1 < len(stripped_args):
            port = int(stripped_args[i + 1])
            i += 2
        elif stripped_args[i].startswith("--"):
            i += 1
        else:
            remaining.append(stripped_args[i])
            i += 1

    return port, fullscreen, parsed_extras, remaining


def _choose_image_mode(fullscreen: bool) -> str:
    """Return chosen image mode, asking interactively when needed."""
    if fullscreen:
        return "fullscreen"

    choice = (
        input("Image display: [p]anel (resizable, default) or [f]ullscreen? ")
        .strip()
        .lower()
    )
    return "fullscreen" if choice == "f" else "panel"


def select_directory(
    title: str = "Select directory containing tracks and images",
) -> Path | None:
    """Open a file dialog to select the input directory."""
    root = tk.Tk()
    root.withdraw()
    directory = filedialog.askdirectory(title=title)
    root.destroy()
    if not directory:
        return None
    return Path(directory)


def discover_tracks(directory: Path) -> list[Track]:
    """Find and parse all track files directly inside a directory."""
    tracks: list[Track] = []
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in TRACK_EXTENSIONS:
            try:
                tracks.extend(parse_track_file(p))
            except ValueError as e:
                print(f"  Warning: skipping {p.name}: {e}")
    return tracks


def match_images_to_tracks(
    tracks: list[Track],
    images: list[ImageInfo],
    tolerance: timedelta = timedelta(0),
) -> list[tuple[Track, list[ImageInfo]]]:
    """Match images with timestamps to tracks whose time range covers them.

    An image matches a track if its timestamp falls within
    [track.start_time - tolerance, track.end_time + tolerance].

    Only images WITH timestamps are considered.
    """
    result: list[tuple[Track, list[ImageInfo]]] = []
    for track in tracks:
        t_start = track.start_time - tolerance
        t_end = track.end_time + tolerance
        matched = []
        for img in images:
            if img.timestamp is None:
                continue
            img_time = img.timestamp
            img_time = _align_time_for_comparison(t_start, img_time)

            if t_start <= img_time <= t_end:
                matched.append(img)
        if matched:
            result.append((track, matched))
    return result


def handle_no_timestamp_images(images: list[ImageInfo]) -> None:
    """Report images without timestamps and always ignore them."""
    no_ts = [img for img in images if img.timestamp is None]
    if not no_ts:
        return

    print(f"\n{'=' * 60}")
    print(f"IGNORED: {len(no_ts)} image(s) without EXIF timestamp:")
    for img in no_ts:
        print(f"  - {img.path.name}")
    print("\nThese images cannot be matched to tracks without timestamps.")
    print("Common causes: messaging app exports, screenshots, or edited photos.")
    print("Processing continues with timestamped images only.")
    print(f"{'=' * 60}\n")


def detect_timezone_correction(
    tracks: list[Track],
    images: list[ImageInfo],
) -> timedelta | None:
    """Detect if images with uncertain timezones need an hourly correction.

    For images whose timezone is uncertain (no EXIF offset), check whether
    they fall outside all track time ranges. If so, try integer-hour shifts
    from -12 to +12 and suggest whichever shift places the most images
    within a track.

    Images with GPS tags are excluded — their clocks are NTP-synced and
    should not be corrected.

    Returns the suggested timedelta correction, or None if no correction needed.
    """
    uncertain = [
        img
        for img in images
        if img.timestamp is not None and not img.tz_certain and not img.has_gps
    ]
    if not uncertain:
        return None

    # Check how many uncertain images already match a track (with 0 offset)
    zero_matches = _count_images_in_tracks(tracks, uncertain, timedelta(0))

    # If all uncertain images already match, no correction needed
    if zero_matches == len(uncertain):
        return None

    # Try hourly offsets from -12 to +12
    best_offset = timedelta(0)
    best_count = zero_matches
    for hours in range(-12, 13):
        if hours == 0:
            continue
        offset = timedelta(hours=hours)
        count = _count_images_in_tracks(tracks, uncertain, offset)
        if count > best_count:
            best_count = count
            best_offset = offset

    if best_count <= zero_matches:
        # No improvement found
        return None

    return best_offset


def handle_timezone_uncertainty(
    tracks: list[Track],
    images: list[ImageInfo],
) -> list[ImageInfo]:
    """Check for timezone issues and let the user correct them.

    Returns the (potentially corrected) image list.
    """
    uncertain = [
        img
        for img in images
        if img.timestamp is not None and not img.tz_certain and not img.has_gps
    ]
    if not uncertain:
        return images

    correction = detect_timezone_correction(tracks, images)
    if correction is None:
        return images

    hours = int(correction.total_seconds() / 3600)
    sign = "+" if hours > 0 else ""

    # Count how many images would match with vs without correction
    current = _count_images_in_tracks(tracks, uncertain, timedelta(0))
    corrected = _count_images_in_tracks(tracks, uncertain, correction)

    print(f"\n{'=' * 60}")
    print("TIMEZONE UNCERTAINTY DETECTED")
    print(f"  {len(uncertain)} image(s) have no timezone info in EXIF.")
    print(f"  Currently {current} of them fall within a track's time range.")
    print(
        f"  Applying a {sign}{hours}h correction would place {corrected} within a track."
    )
    print()
    print("  This likely means the camera clock was set to a timezone")
    print(f"  that is {sign}{hours}h relative to UTC.")
    print(f"{'=' * 60}\n")

    while True:
        choice = (
            input(f"Apply {sign}{hours}h correction? [y]es / [n]o / [q]uit: ")
            .strip()
            .lower()
        )
        if choice == "y":
            apply = True
            break
        elif choice == "n":
            apply = False
            break
        elif choice == "q":
            raise SystemExit(0)
        else:
            print("Please enter 'y', 'n', or 'q'.")

    if not apply:
        return images

    # Apply correction to uncertain images (skip GPS-tagged)
    corrected_images = []
    for img in images:
        if img.timestamp is not None and not img.tz_certain and not img.has_gps:
            corrected_images.append(
                ImageInfo(
                    path=img.path,
                    timestamp=img.timestamp + correction,
                    has_gps=img.has_gps,
                    tz_certain=True,  # now corrected, treat as certain
                )
            )
        else:
            corrected_images.append(img)

    print(f"  Applied {sign}{hours}h correction to {len(uncertain)} image(s).\n")
    return corrected_images


def geotag(input_dir: Path, time_offset_minutes: float = 0) -> bool:
    """Main geotagging workflow. Returns True if images were geotagged."""
    print(f"\nScanning: {input_dir}\n")

    # 1. Discover tracks
    print("Discovering tracks...")
    tracks = discover_tracks(input_dir)
    if not tracks:
        print("No track files (IGC, GPX) found. Nothing to do.")
        return False
    for t in tracks:
        print(f"  Track: {t.name} ({t.source_path.name})")
        print(f"         {len(t.points)} points, {t.start_time} → {t.end_time}")

    # 2. Discover images
    print("\nDiscovering images...")
    images = discover_images(input_dir)
    if not images:
        print("No images found. Nothing to do.")
        return False
    with_ts = [img for img in images if img.timestamp is not None]
    without_ts = [img for img in images if img.timestamp is None]
    print(
        f"  Found {len(images)} image(s): {len(with_ts)} with timestamp, {len(without_ts)} without"
    )

    # 3. Always ignore images without timestamps (with clear reporting)
    handle_no_timestamp_images(images)

    if not with_ts:
        print("No images with timestamps available. Nothing to geotag.")
        return False

    # 4. Detect and correct timezone issues for images without explicit timezone
    with_ts = handle_timezone_uncertainty(tracks, with_ts)
    with_ts = [img for img in with_ts if img.timestamp is not None]

    # 4b. Apply manual time offset (camera clock drift correction)
    #     Only applied to images WITHOUT original GPS tags (camera images).
    #     Images with GPS (e.g. from phones) have NTP-synced clocks.
    if time_offset_minutes != 0:
        offset = timedelta(minutes=time_offset_minutes)
        sign = "+" if time_offset_minutes > 0 else ""
        no_gps = [img for img in with_ts if not img.has_gps]
        has_gps = [img for img in with_ts if img.has_gps]
        print(
            f"  Applying {sign}{time_offset_minutes}min offset to {len(no_gps)} image(s) without GPS."
        )
        if has_gps:
            print(
                f"  Skipping {len(has_gps)} image(s) with GPS (timestamps assumed accurate)."
            )
        with_ts = has_gps + [
            ImageInfo(
                path=img.path,
                timestamp=img.timestamp + offset,
                has_gps=img.has_gps,
                tz_certain=img.tz_certain,
            )
            for img in no_gps
        ]

    # 5. Match images to tracks
    print("Matching images to tracks...")
    matches = match_images_to_tracks(tracks, with_ts)
    if not matches:
        print("No images matched any track's time range. Check that image timestamps")
        print("correspond to the same time period as the tracks.")
        return False

    for track, imgs in matches:
        print(f"  Track '{track.name}': {len(imgs)} image(s) matched")

    matched_paths = {img.path for _, imgs in matches for img in imgs}
    outside_track = [img for img in with_ts if img.path not in matched_paths]
    if outside_track:
        print(
            f"\nIGNORED: {len(outside_track)} image(s) outside all track time ranges:"
        )
        for img in outside_track:
            if img.timestamp is None:
                print(f"  - {img.path.name}")
            else:
                print(
                    f"  - {img.path.name} ({img.timestamp.isoformat(sep=' ', timespec='seconds')})"
                )

    # 6. Geotag
    print("\nGeotagging...")
    output_dir = get_dataset_images_dir(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale files from previous run to avoid Windows file-lock issues
    _clean_output_dir(output_dir)

    total_tagged = 0
    for track, imgs in matches:
        for img in imgs:
            out_path = output_dir / img.path.name

            if img.has_gps:
                # GPS-tagged: copy as-is, preserving original coordinates
                saved = _copy_or_convert_for_browser(img.path, out_path)
                total_tagged += 1
                print(f"  {img.path.name} → {saved.name} (GPS preserved)")
                continue

            point = interpolate_position(track, img.timestamp)
            if point is None:
                print(f"  {img.path.name}: timestamp outside track range, skipping")
                continue

            if img.path.suffix.lower() in (".jpg", ".jpeg"):
                # JPEG: copy then write EXIF in-place
                shutil.copy2(img.path, out_path)
                saved = write_gps_exif(out_path, point, out_path)
            else:
                # HEIC/other: write_gps_exif converts to JPEG directly
                saved = write_gps_exif(img.path, point, out_path)
            total_tagged += 1
            print(
                f"  {img.path.name} → {saved.name} ({point.lat:.6f}, {point.lon:.6f}, {point.alt:.0f}m)"
            )

    print(f"\nDone! {total_tagged} image(s) geotagged → {output_dir}")
    return True


def _prepare_gps_images(input_dir: Path) -> bool:
    """Find GPS-tagged images and prepare them for the viewer.

    Copies images with valid GPS coordinates to the app-managed work folder
    (converting HEIC to JPEG as needed). Returns True if any images were found.
    """
    print(f"\nScanning for GPS-tagged images: {input_dir}\n")

    images = discover_images(input_dir)
    if not images:
        print("No images found.")
        return False

    with_gps = [img for img in images if img.has_gps]
    without_gps = [img for img in images if not img.has_gps]

    if with_gps:
        print(f"  {len(with_gps)} image(s) with GPS coordinates (will be displayed):")
        for img in with_gps:
            print(f"    ✓ {img.path.name}")

    if without_gps:
        print(f"\n  {len(without_gps)} image(s) without GPS coordinates (skipped):")
        for img in without_gps:
            print(f"    ✗ {img.path.name}")

    if not with_gps:
        print("\nNo images with GPS coordinates found. Nothing to display.")
        return False

    # Copy GPS-tagged images to the app work directory (converting HEIC→JPEG as needed)
    output_dir = get_dataset_images_dir(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean stale files from previous run
    _clean_output_dir(output_dir)

    print(f"\nPreparing {len(with_gps)} image(s)...")
    for img in with_gps:
        src = img.path
        dst = _copy_or_convert_for_browser(src, output_dir / src.name)
        if dst.suffix.lower() == ".jpg" and src.suffix.lower() in (".heic", ".heif"):
            print(f"  {src.name} → {dst.name} (converted to JPEG)")
        else:
            print(f"  {src.name}")

    print(f"\nReady — {len(with_gps)} image(s) → {output_dir}")
    return True


def _is_valid_directory(input_dir: Path | None) -> bool:
    """Validate selected input directory and print user-facing errors."""
    if input_dir is None:
        print("No directory selected. Exiting.")
        return False
    if not input_dir.is_dir():
        print(f"Not a directory: {input_dir}")
        return False
    return True


def orchestrate_geotag_mode(
    input_dir: Path,
    *,
    time_offset_minutes: float = 0,
    port: int = 5000,
    image_mode: str = "panel",
) -> bool:
    """Run geotag workflow and launch map viewer when successful."""
    if not _is_valid_directory(input_dir):
        return False

    if geotag(
        input_dir,
        time_offset_minutes=time_offset_minutes,
    ):
        from .server import serve

        print("\nLaunching 3D viewer...")
        serve(input_dir, port=port, image_mode=image_mode)
        return True

    return False


def orchestrate_review_mode(
    input_dir: Path,
    *,
    port: int = 5000,
    image_mode: str = "panel",
) -> None:
    """View previously generated trip results without re-geotagging."""
    if not _is_valid_directory(input_dir):
        return

    from .server import serve

    serve(input_dir, port=port, image_mode=image_mode)


def orchestrate_browse_mode(
    input_dir: Path,
    *,
    port: int = 5000,
    image_mode: str = "panel",
    include_sequence_line: bool = True,
) -> None:
    """Display GPS-tagged images without requiring track files."""
    if not _is_valid_directory(input_dir):
        return

    from .server import serve

    if not _prepare_gps_images(input_dir):
        return

    if not include_sequence_line:
        print("  Image sequence line disabled (--no-sequence-line).")

    serve(
        input_dir,
        port=port,
        image_mode=image_mode,
        include_tracks=False,
        include_image_sequence_track=include_sequence_line,
    )


def orchestrate_export_mode(
    input_dir: Path,
    *,
    output_dir: Path | None = None,
    do_preview: bool = False,
) -> None:
    """Export static site artifacts and optionally launch preview server."""
    if not _is_valid_directory(input_dir):
        return

    from .exporter import export, preview

    if output_dir is None:
        output_dir = input_dir / "export"

    print(f"\nExporting static site from: {input_dir}")
    export(input_dir, output_dir)

    if do_preview:
        preview(output_dir)


def main():
    import sys

    args = sys.argv[1:]

    # GUI-first launcher when no explicit CLI arguments were provided.
    if not args:
        try:
            from .launcher import run_launcher
        except ImportError as e:
            print(f"Failed to initialize launcher GUI: {e}")
            return

        try:
            request = run_launcher()
        except tk.TclError as e:
            print(f"Failed to open launcher GUI: {e}")
            return

        if request is None:
            print("No action selected. Exiting.")
            return

        mode = request["mode"]
        input_dir = request["input_dir"]

        if mode == "geotag":
            orchestrate_geotag_mode(
                input_dir,
                time_offset_minutes=request["time_offset_minutes"],
                port=request["port"],
                image_mode=request["image_mode"],
            )
            return

        if mode == "review":
            orchestrate_review_mode(
                input_dir,
                port=request["port"],
                image_mode=request["image_mode"],
            )
            return

        if mode == "browse":
            orchestrate_browse_mode(
                input_dir,
                port=request["port"],
                image_mode=request["image_mode"],
                include_sequence_line=request["include_sequence_line"],
            )
            return

        if mode == "export":
            orchestrate_export_mode(
                input_dir,
                output_dir=request["output_dir"],
                do_preview=request["do_preview"],
            )
            return

    # Check for 'serve' subcommand
    if args and args[0] == "serve":
        port, fullscreen, _, remaining = _parse_subcommand_port_and_flags(args[1:])

        if remaining:
            input_dir = Path(remaining[0])
        else:
            input_dir = select_directory(
                title="Select folder containing tracks and photos"
            )

        if not _is_valid_directory(input_dir):
            return

        orchestrate_review_mode(
            input_dir,
            port=port,
            image_mode=_choose_image_mode(fullscreen),
        )
        return

    # Check for 'show' subcommand — display GPS-tagged images without tracks
    if args and args[0] == "show":
        port, fullscreen, extra_flags, remaining = _parse_subcommand_port_and_flags(
            args[1:], extra_flags=("--no-sequence-line",)
        )
        show_sequence_line = not extra_flags["--no-sequence-line"]

        if remaining:
            input_dir = Path(remaining[0])
        else:
            input_dir = select_directory(
                title="Select folder containing GPS-tagged images"
            )

        if not _is_valid_directory(input_dir):
            return

        orchestrate_browse_mode(
            input_dir,
            port=port,
            image_mode=_choose_image_mode(fullscreen),
            include_sequence_line=show_sequence_line,
        )
        return

    # Check for 'export' subcommand
    if args and args[0] == "export":
        export_args = args[1:]
        do_preview = "--preview" in export_args
        export_args = [a for a in export_args if a != "--preview"]
        # Parse --output option
        out_dir = None
        remaining = []
        i = 0
        while i < len(export_args):
            if export_args[i] == "--output" and i + 1 < len(export_args):
                out_dir = Path(export_args[i + 1])
                i += 2
            elif export_args[i].startswith("--"):
                i += 1
            else:
                remaining.append(export_args[i])
                i += 1

        if remaining:
            input_dir = Path(remaining[0])
        else:
            input_dir = select_directory(
                title="Select folder containing tracks and photos"
            )

        if not _is_valid_directory(input_dir):
            return

        orchestrate_export_mode(
            input_dir,
            output_dir=out_dir,
            do_preview=do_preview,
        )
        return

    # Parse --time-offset N (minutes)
    time_offset = 0.0
    consumed = set()
    for i in range(len(args)):
        if args[i] == "--time-offset" and i + 1 < len(args):
            time_offset = float(args[i + 1])
            consumed.add(i)
            consumed.add(i + 1)

    positional = [
        a for i, a in enumerate(args) if i not in consumed and not a.startswith("--")
    ]

    if positional:
        input_dir = Path(positional[0])
    else:
        input_dir = select_directory()

    if not _is_valid_directory(input_dir):
        return

    orchestrate_geotag_mode(
        input_dir,
        time_offset_minutes=time_offset,
        image_mode=_choose_image_mode(fullscreen=False),
    )


if __name__ == "__main__":
    main()
