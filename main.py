"""GPSImagesToMap — Geotag images using GPS track files, then visualize on a 3D map."""

import shutil
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox

from geotagger import interpolate_position, write_gps_exif
from image_discovery import ImageInfo, discover_images
from track_parser import TRACK_EXTENSIONS, Track, parse_track_file


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
    """Find and parse all track files in a directory (recursively)."""
    tracks: list[Track] = []
    for p in sorted(directory.rglob("*")):
        if p.is_file() and p.suffix.lower() in TRACK_EXTENSIONS:
            try:
                tracks.extend(parse_track_file(p))
            except ValueError as e:
                print(f"  Warning: skipping {p.name}: {e}")
    return tracks


def match_images_to_tracks(
    tracks: list[Track],
    images: list[ImageInfo],
    tolerance: timedelta = timedelta(hours=1),
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

            # Make both timezone-aware or both naive for comparison
            if t_start.tzinfo is not None and img_time.tzinfo is None:
                # Track is UTC-aware, image is naive — assume local time = UTC
                # (This is a fallback; proper timezone handling should convert first)
                img_time = img_time.replace(tzinfo=timezone.utc)
            elif t_start.tzinfo is None and img_time.tzinfo is not None:
                img_time = img_time.replace(tzinfo=None)

            if t_start <= img_time <= t_end:
                matched.append(img)
        if matched:
            result.append((track, matched))
    return result


def handle_no_timestamp_images(images: list[ImageInfo]) -> None:
    """Notify user about images without timestamps and let them decide."""
    no_ts = [img for img in images if img.timestamp is None]
    if not no_ts:
        return

    print(f"\n{'='*60}")
    print(f"WARNING: {len(no_ts)} image(s) have NO timestamp in EXIF:")
    for img in no_ts:
        print(f"  - {img.path.name}")
    print(f"\nThese images cannot be placed on any track without a timestamp.")
    print(f"Common causes: sent via messaging apps (Signal, WhatsApp),")
    print(f"screenshots, or manually edited photos.")
    print(f"{'='*60}\n")

    while True:
        choice = (
            input("Options: [s]kip them and continue, [q]uit to provide originals: ")
            .strip()
            .lower()
        )
        if choice == "s":
            print("Skipping images without timestamps.\n")
            return
        elif choice == "q":
            print(
                "Exiting. Please replace these images with originals that have EXIF timestamps."
            )
            raise SystemExit(0)
        else:
            print("Please enter 's' or 'q'.")


def detect_timezone_correction(
    tracks: list[Track],
    images: list[ImageInfo],
) -> timedelta | None:
    """Detect if images with uncertain timezones need an hourly correction.

    For images whose timezone is uncertain (no EXIF offset), check whether
    they fall outside all track time ranges. If so, try integer-hour shifts
    from -12 to +12 and suggest whichever shift places the most images
    within a track.

    Returns the suggested timedelta correction, or None if no correction needed.
    """
    uncertain = [
        img for img in images if img.timestamp is not None and not img.tz_certain
    ]
    if not uncertain:
        return None

    # Check how many uncertain images already match a track (with 0 offset)
    def count_matching(imgs: list[ImageInfo], offset: timedelta) -> int:
        count = 0
        for img in imgs:
            shifted = img.timestamp + offset
            # Make timezone-aware if tracks are aware
            for track in tracks:
                t_start = track.start_time
                t_end = track.end_time
                shifted_cmp = shifted
                if t_start.tzinfo is not None and shifted_cmp.tzinfo is None:
                    shifted_cmp = shifted_cmp.replace(tzinfo=timezone.utc)
                elif t_start.tzinfo is None and shifted_cmp.tzinfo is not None:
                    shifted_cmp = shifted_cmp.replace(tzinfo=None)
                if t_start <= shifted_cmp <= t_end:
                    count += 1
                    break
        return count

    zero_matches = count_matching(uncertain, timedelta(0))

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
        count = count_matching(uncertain, offset)
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
    skip_prompt: bool = False,
) -> list[ImageInfo]:
    """Check for timezone issues and let the user correct them.

    Returns the (potentially corrected) image list.
    """
    uncertain = [
        img for img in images if img.timestamp is not None and not img.tz_certain
    ]
    if not uncertain:
        return images

    correction = detect_timezone_correction(tracks, images)
    if correction is None:
        return images

    hours = int(correction.total_seconds() / 3600)
    sign = "+" if hours > 0 else ""

    # Count how many images would match with vs without correction
    def count_in_tracks(imgs: list[ImageInfo], offset: timedelta) -> int:
        count = 0
        for img in imgs:
            shifted = img.timestamp + offset
            for track in tracks:
                t_start = track.start_time
                t_end = track.end_time
                shifted_cmp = shifted
                if t_start.tzinfo is not None and shifted_cmp.tzinfo is None:
                    shifted_cmp = shifted_cmp.replace(tzinfo=timezone.utc)
                elif t_start.tzinfo is None and shifted_cmp.tzinfo is not None:
                    shifted_cmp = shifted_cmp.replace(tzinfo=None)
                if t_start <= shifted_cmp <= t_end:
                    count += 1
                    break
        return count

    current = count_in_tracks(uncertain, timedelta(0))
    corrected = count_in_tracks(uncertain, correction)

    print(f"\n{'='*60}")
    print(f"TIMEZONE UNCERTAINTY DETECTED")
    print(f"  {len(uncertain)} image(s) have no timezone info in EXIF.")
    print(f"  Currently {current} of them fall within a track's time range.")
    print(
        f"  Applying a {sign}{hours}h correction would place {corrected} within a track."
    )
    print()
    print(f"  This likely means the camera clock was set to a timezone")
    print(f"  that is {sign}{hours}h relative to UTC.")
    print(f"{'='*60}\n")

    if skip_prompt:
        print(
            f"  Auto-applying {sign}{hours}h correction (--skip-no-timestamp mode).\n"
        )
        apply = True
    else:
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

    # Apply correction to uncertain images
    corrected_images = []
    for img in images:
        if img.timestamp is not None and not img.tz_certain:
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


def geotag(
    input_dir: Path, skip_no_timestamp: bool = False, time_offset_minutes: float = 0
) -> bool:
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

    # 3. Handle images without timestamps
    if skip_no_timestamp:
        if without_ts:
            print(
                f"  Skipping {len(without_ts)} image(s) without timestamps (--skip-no-timestamp)"
            )
    else:
        handle_no_timestamp_images(images)

    if not with_ts:
        print("No images with timestamps available. Nothing to geotag.")
        return False

    # 4. Detect and correct timezone issues for images without explicit timezone
    with_ts = handle_timezone_uncertainty(
        tracks, with_ts, skip_prompt=skip_no_timestamp
    )
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

    # 6. Geotag
    print("\nGeotagging...")
    output_dir = input_dir / "geotagged"
    output_dir.mkdir(exist_ok=True)

    # Remove stale files from previous run to avoid Windows file-lock issues
    for old in output_dir.iterdir():
        if old.is_file():
            try:
                old.unlink()
            except PermissionError:
                import time

                time.sleep(0.5)
                old.unlink()

    total_tagged = 0
    for track, imgs in matches:
        for img in imgs:
            point = interpolate_position(track, img.timestamp)
            out_path = output_dir / img.path.name
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


def main():
    import sys

    args = sys.argv[1:]

    # Check for 'serve' subcommand
    if args and args[0] == "serve":
        from server import serve

        serve_args = args[1:]
        port = 5000
        fullscreen = "--fullscreen" in serve_args
        serve_args = [a for a in serve_args if a != "--fullscreen"]
        # Parse --port option
        remaining = []
        i = 0
        while i < len(serve_args):
            if serve_args[i] == "--port" and i + 1 < len(serve_args):
                port = int(serve_args[i + 1])
                i += 2
            elif serve_args[i].startswith("--"):
                i += 1
            else:
                remaining.append(serve_args[i])
                i += 1

        if remaining:
            input_dir = Path(remaining[0])
        else:
            input_dir = select_directory(
                title="Select folder containing tracks and geotagged/ subfolder"
            )

        if input_dir is None:
            print("No directory selected. Exiting.")
            return
        if not input_dir.is_dir():
            print(f"Not a directory: {input_dir}")
            return

        # If user selected the geotagged folder itself, use its parent
        if input_dir.name == "geotagged":
            input_dir = input_dir.parent
            print(f"  (Using parent directory: {input_dir})")

        # Ask image display mode if not set via flag
        if not fullscreen:
            choice = (
                input("Image display: [p]anel (resizable, default) or [f]ullscreen? ")
                .strip()
                .lower()
            )
            if choice == "f":
                fullscreen = True

        serve(input_dir, port=port, image_mode="fullscreen" if fullscreen else "panel")
        return

    # Check for 'export' subcommand
    if args and args[0] == "export":
        from exporter import export, preview

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
                title="Select folder containing tracks and geotagged/ subfolder"
            )

        if input_dir is None:
            print("No directory selected. Exiting.")
            return
        if not input_dir.is_dir():
            print(f"Not a directory: {input_dir}")
            return
        if input_dir.name == "geotagged":
            input_dir = input_dir.parent
            print(f"  (Using parent directory: {input_dir})")

        if out_dir is None:
            out_dir = input_dir / "export"

        print(f"\nExporting static site from: {input_dir}")
        export(input_dir, out_dir)

        if do_preview:
            preview(out_dir)
        return

    # Default: geotag command
    skip_no_ts = "--skip-no-timestamp" in args

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

    if input_dir is None:
        print("No directory selected. Exiting.")
        return

    if not input_dir.is_dir():
        print(f"Not a directory: {input_dir}")
        return

    if geotag(input_dir, skip_no_timestamp=skip_no_ts, time_offset_minutes=time_offset):
        from server import serve

        print("\nLaunching 3D viewer...")
        choice = (
            input("Image display: [p]anel (resizable, default) or [f]ullscreen? ")
            .strip()
            .lower()
        )
        image_mode = "fullscreen" if choice == "f" else "panel"
        serve(input_dir, image_mode=image_mode)


if __name__ == "__main__":
    main()
