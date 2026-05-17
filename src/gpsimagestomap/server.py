"""Flask server for the Cesium.js 3D flight viewer."""

import json
import os
import subprocess
import threading
import tkinter as tk
import webbrowser
from datetime import timezone
from io import BytesIO
from pathlib import Path
from tkinter import scrolledtext, ttk
from typing import Callable

from flask import Flask, Response, abort, send_file
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from werkzeug.serving import make_server

register_heif_opener()

from .app_config import load_app_env
from .image_discovery import IMAGE_EXTENSIONS, read_image_info
from .storage import get_dataset_images_dir
from .track_parser import TRACK_EXTENSIONS, parse_track_file

THUMBNAIL_SIZE = (200, 200)

_ACTIVE_SERVER_LOCK = threading.Lock()
_ACTIVE_HTTPD = None
_ACTIVE_SERVER_THREAD: threading.Thread | None = None
_ACTIVE_SERVER_PORT: int | None = None


def _position_window_shifted_right(
    root: tk.Tk | tk.Toplevel, width: int, height: int
) -> None:
    """Position a window slightly to the right of center to avoid launcher overlap."""
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    base_x = (screen_w - width) // 2
    base_y = (screen_h - height) // 2

    x = min(max(20, base_x + 220), max(20, screen_w - width - 20))
    y = min(max(20, base_y - 30), max(20, screen_h - height - 20))
    root.geometry(f"{width}x{height}+{x}+{y}")


def _create_window(
    owner_root: tk.Tk | None,
    title: str,
    width: int = 760,
    height: int = 500,
) -> tk.Tk | tk.Toplevel:
    """Create a launcher-owned child window when possible, else a root window."""
    if owner_root is not None and owner_root.winfo_exists():
        window = tk.Toplevel(owner_root)
        window.transient(owner_root)
    else:
        window = tk.Tk()
    window.title(title)
    _position_window_shifted_right(window, width, height)
    return window


def _bring_window_to_front(root: tk.Tk | tk.Toplevel) -> None:
    """Best-effort raise/focus for Tk windows."""
    try:
        root.update_idletasks()
        root.lift()
        root.attributes("-topmost", True)
        root.after(200, lambda: root.attributes("-topmost", False))
        root.after(220, root.focus_force)
    except tk.TclError:
        pass


def _open_url(url: str) -> None:
    """Open a URL in the default browser across Windows/Linux/WSL."""

    def _is_wsl() -> bool:
        if "WSL_DISTRO_NAME" in os.environ:
            return True
        try:
            release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
        except OSError:
            return False
        return "microsoft" in release.lower()

    if os.name == "nt":
        try:
            os.startfile(url)
            return
        except OSError:
            pass

    if _is_wsl():
        # Prefer wslview when available; fall back to Windows PowerShell.
        launchers = [
            ["wslview", url],
            ["powershell.exe", "-NoProfile", "-Command", "Start-Process", url],
            ["cmd.exe", "/C", "start", "", url],
        ]
        for command in launchers:
            try:
                result = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if result.returncode == 0:
                    return
            except OSError:
                continue

    try:
        if webbrowser.open(url):
            return
    except webbrowser.Error:
        pass

    print(f"  Could not open browser automatically. Open manually: {url}")


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

    if os.name != "nt":
        return

    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO") and hasattr(
        subprocess, "STARTF_USESHOWWINDOW"
    ):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    def _run_hidden(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            text=True,
            creationflags=create_no_window,
            startupinfo=startupinfo,
        )

    try:
        # Use netstat but match on port + PID column regardless of locale
        result = _run_hidden(["netstat", "-ano", "-p", "TCP"])
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
            _run_hidden(["taskkill", "/F", "/PID", str(pid)])
            killed.add(pid)
            print(f"  Killed previous server (PID {pid}) on port {port}")
    except Exception:
        pass


def _stop_server_instance(httpd, server_thread: threading.Thread | None) -> None:
    """Stop a specific managed server instance."""
    if httpd is None:
        return

    try:
        httpd.shutdown()
    except Exception:
        pass

    try:
        httpd.server_close()
    except Exception:
        pass

    if server_thread is not None:
        try:
            server_thread.join(timeout=2)
        except Exception:
            pass


def stop_active_server() -> None:
    """Stop the currently active in-process viewer server, if any."""
    global _ACTIVE_HTTPD, _ACTIVE_SERVER_THREAD, _ACTIVE_SERVER_PORT

    with _ACTIVE_SERVER_LOCK:
        httpd = _ACTIVE_HTTPD
        server_thread = _ACTIVE_SERVER_THREAD
        _ACTIVE_HTTPD = None
        _ACTIVE_SERVER_THREAD = None
        _ACTIVE_SERVER_PORT = None

    _stop_server_instance(httpd, server_thread)


def _start_managed_server(app: Flask, port: int) -> tuple[object, threading.Thread]:
    """Start a managed in-process server, replacing any previous session."""
    global _ACTIVE_HTTPD, _ACTIVE_SERVER_THREAD, _ACTIVE_SERVER_PORT

    # Replace the previous in-process server first to avoid self-kill via taskkill.
    stop_active_server()

    try:
        httpd = make_server("127.0.0.1", port, app, threaded=True)
    except OSError:
        # Fallback for stale external listeners.
        _kill_port(port)
        httpd = make_server("127.0.0.1", port, app, threaded=True)

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    with _ACTIVE_SERVER_LOCK:
        _ACTIVE_HTTPD = httpd
        _ACTIVE_SERVER_THREAD = server_thread
        _ACTIVE_SERVER_PORT = port

    return httpd, server_thread


def serve_with_streaming_log(
    input_dir: Path,
    processing_func,
    processing_args: tuple = (),
    processing_kwargs: dict | None = None,
    port: int = 5000,
    image_mode: str = "panel",
    include_tracks: bool = True,
    include_image_sequence_track: bool = True,
    on_return_to_launcher: Callable[[], None] | None = None,
    owner_root: tk.Tk | None = None,
) -> None:
    """Show control window immediately and stream processing output in real-time."""
    import sys
    from contextlib import redirect_stdout

    if processing_kwargs is None:
        processing_kwargs = {}

    # Create and show a passive session-log window before any processing starts.
    try:
        root = _create_window(owner_root, "FlightPhotoMapper Session Log")
        root.minsize(520, 320)
        _bring_window_to_front(root)
        root.update()
    except tk.TclError as e:
        print("\nERROR: Could not open the FlightPhotoMapper session window.")
        print("  The app will report status and errors to the terminal instead.")
        print(f"  Tkinter error: {e}\n")
        raise

    container = ttk.Frame(root, padding=12)
    container.pack(fill="both", expand=True)

    status_label = ttk.Label(
        container,
        text="Processing...",
        font=("Segoe UI", 12, "bold"),
    )
    status_label.pack(anchor="w")

    ttk.Label(
        container,
        text="Processing your images. Please wait...",
        justify="left",
        wraplength=700,
    ).pack(anchor="w", pady=(6, 10))

    log_box = scrolledtext.ScrolledText(container, wrap="word", height=18)
    log_box.pack(fill="both", expand=True)

    # Prepare log writer that writes to the text box
    import io

    class LogWriter:
        def __init__(self, text_widget):
            self.text = text_widget
            self.buffer = io.StringIO()

        def write(self, msg: str) -> int:
            if msg:
                try:
                    self.text.configure(state="normal")
                    self.text.insert("end", msg)
                    self.text.see("end")
                    self.text.update_idletasks()
                    root.update()
                except tk.TclError:
                    pass
                self.buffer.write(msg)
            return len(msg)

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return False

        def getvalue(self) -> str:
            return self.buffer.getvalue()

    log_writer = LogWriter(log_box)
    stdout_backup = sys.stdout

    # Run processing with real-time log capture
    processing_result = None
    default_root_backup = getattr(tk, "_default_root", None)
    setattr(tk, "_default_root", root)
    try:
        with redirect_stdout(log_writer):
            processing_result = processing_func(*processing_args, **processing_kwargs)
    except Exception as e:
        log_writer.write(f"\nError during processing: {e}\n")
        root.after(2000, root.destroy)
        return
    finally:
        setattr(tk, "_default_root", default_root_backup)
        sys.stdout = stdout_backup

    if not processing_result:
        log_writer.write("\nProcessing failed. Closing in 2 seconds...\n")
        root.after(2000, root.destroy)
        root.mainloop()
        return

    # Processing complete, now start the server and update window
    load_app_env(Path.cwd())
    app = create_app(
        input_dir,
        image_mode=image_mode,
        include_tracks=include_tracks,
        include_image_sequence_track=include_image_sequence_track,
    )

    # Update UI to show viewer is running; launcher remains the primary control surface.
    status_label.configure(text="Viewer is running")

    url = f"http://localhost:{port}"
    log_writer.write(f"\n\nLaunching viewer at {url}...\n")

    # Start Flask server in background thread, replacing any previous in-process session.
    _start_managed_server(app, port)

    # Brief delay then open browser
    root.after(500, lambda: _open_url(url))

    log_writer.write(
        "\nSession log window will close automatically. Continue via the launcher.\n"
    )

    def close_log_window() -> None:
        root.destroy()
        if on_return_to_launcher is not None:
            on_return_to_launcher()

    root.after(1200, close_log_window)

    # Closing this passive window should not affect server lifecycle.
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


def serve(
    input_dir: Path,
    port: int = 5000,
    image_mode: str = "panel",
    include_tracks: bool = True,
    include_image_sequence_track: bool = True,
    show_control_window: bool = False,
    on_return_to_launcher: Callable[[], None] | None = None,
    owner_root: tk.Tk | None = None,
) -> None:
    """Start the Flask server and open the browser."""
    _ = owner_root
    load_app_env(Path.cwd())
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
    if show_control_window:
        _start_managed_server(app, port)
        _open_url(url)
        if on_return_to_launcher is not None:
            on_return_to_launcher()
        return

    print(f"  Starting viewer at {url}")
    print("  Press Ctrl+C to stop.\n")
    _open_url(url)
    _kill_port(port)
    app.run(host="127.0.0.1", port=port, debug=False)
