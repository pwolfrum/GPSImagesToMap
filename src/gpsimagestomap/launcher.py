"""GUI launcher for selecting and configuring app modes."""

import os
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .app_config import get_user_env_path, load_app_env, set_user_env_var

TOOLTIPS = {
    "geotag": "Match photos to tracks and display in map.",
    "review": "Show previously generated trip results",
    "browse": "Show photos that already contain GPS tags, no tracks",
}

MODE_HELP = {
    "geotag": (
        "Geotag mode\n"
        "Matches photos to track(s) (via timestamps), writes GPS EXIF tags into photos, and displays everything in map.\n"
        "Photos outside of timespan of any track are ignored.\n\n"
        "Options:\n"
        "- Time offset (minutes): shift photo times before matching (use negative if camera was ahead). This is helpful to correct for camera clock drift.\n"
        "- Port: local web port for the viewer server (default: 5000).\n"
        "- Image mode: Default size for image popups (can always be resized at runtime).\n"
    ),
    "review": (
        "Review mode\n"
        "Opens an already processed trip without re-geotagging. Select the same original input folder and results are autodetected from app storage.\n\n"
        "Options:\n"
        "- Port: local web port for the viewer server (default: 5000).\n"
        "- Image mode: Default size for image popups (can always be resized at runtime).\n"
    ),
    "browse": (
        "Browse mode\n"
        "Displays photos that already contain GPS EXIF, without requiring or using track files.\n\n"
        "Options:\n"
        "- Port: local web port for the viewer server (default: 5000).\n"
        "- Image mode: Default size for image popups (can always be resized at runtime).\n"
        "- Draw temporal sequence line: Draw a thin line connecting photos in temporal order (e.g. to visualize the path of a trip).\n"
    ),
}


class _ToolTip:
    """Small hover tooltip helper for Tk widgets."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip_window: tk.Toplevel | None = None
        self.widget.bind("<Enter>", self._show)
        self.widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip_window or not self.text:
            return

        x = self.widget.winfo_rootx() + 22
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4

        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            self.tip_window,
            text=self.text,
            justify=tk.LEFT,
            relief=tk.SOLID,
            borderwidth=1,
            background="#ffffe0",
            padx=6,
            pady=4,
            wraplength=360,
        )
        label.pack()

    def _hide(self, _event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


def _row(frame: tk.Widget, row: int, label_text: str) -> ttk.Label:
    label = ttk.Label(frame, text=label_text)
    label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
    return label


def run_launcher() -> dict | None:
    """Show launcher GUI and return a normalized run request or None."""
    root = tk.Tk()
    root.title("FlightPhotoMapper Launcher")
    root.geometry("640x520")
    root.minsize(420, 260)

    request: dict | None = None
    load_app_env(Path.cwd())

    mode_var = tk.StringVar(value="geotag")
    input_dir_var = tk.StringVar(value="")
    port_var = tk.StringVar(value="5000")
    image_mode_var = tk.StringVar(value="panel")
    time_offset_var = tk.StringVar(value="0")
    include_sequence_line_var = tk.BooleanVar(value=True)

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    viewport = ttk.Frame(root, padding=12)
    viewport.grid(row=0, column=0, sticky="nsew")
    viewport.columnconfigure(0, weight=1)
    viewport.rowconfigure(0, weight=1)

    canvas = tk.Canvas(viewport, highlightthickness=0)
    scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")

    container = ttk.Frame(canvas)
    container_id = canvas.create_window((0, 0), window=container, anchor="nw")

    def _sync_scroll_region(_event=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _sync_container_width(event) -> None:
        canvas.itemconfigure(container_id, width=event.width)

    container.bind("<Configure>", _sync_scroll_region)
    canvas.bind("<Configure>", _sync_container_width)

    footer = ttk.Frame(root, padding=(12, 0, 12, 12))
    footer.grid(row=1, column=0, sticky="ew")

    header_row = ttk.Frame(container)
    header_row.pack(fill="x")

    title = ttk.Label(header_row, text="Choose Mode", font=("Segoe UI", 12, "bold"))
    title.pack(side="left", anchor="w")

    token_status_var = tk.StringVar()

    def refresh_token_status() -> None:
        token_present = bool(os.environ.get("CESIUM_ION_TOKEN", "").strip())
        if token_present:
            token_status_var.set("Cesium token: configured")
        else:
            token_status_var.set("Cesium token: missing (terrain disabled)")

    def open_help_dialog() -> None:
        dialog = tk.Toplevel(root)
        dialog.title("FlightPhotoMapper — Help")
        dialog.transient(root)
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.geometry("680x600")
        dialog.minsize(520, 400)

        # Scrollable body
        outer = ttk.Frame(dialog)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        body = ttk.Frame(canvas, padding=14)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def _sync(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _resize(e):
            canvas.itemconfigure(body_id, width=e.width)

        body.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _resize)

        W = 620  # wrap width for labels

        def section(title):
            ttk.Label(body, text=title, font=("Segoe UI", 10, "bold")).pack(
                anchor="w", pady=(14, 2)
            )
            ttk.Separator(body, orient="horizontal").pack(fill="x", pady=(0, 6))

        def para(text):
            ttk.Label(body, text=text, justify="left", wraplength=W).pack(
                anchor="w", pady=(0, 4)
            )

        def link(label, url):
            lbl = tk.Label(body, text=label, fg="#0a58ca", cursor="hand2")
            lbl.pack(anchor="w")
            lbl.bind("<Button-1>", lambda _e: webbrowser.open(url))

        # ── Getting started ──────────────────────────────────────────────
        ttk.Label(body, text="Getting Started", font=("Segoe UI", 12, "bold")).pack(
            anchor="w", pady=(0, 6)
        )

        section("Step 1 — Prepare your input folder")
        para(
            "Put your GPS track file(s) and your photos into the same folder. "
            "The app reads only files directly in that folder — not in subfolders."
        )
        para(
            "Example folder layout:\n"
            "    my-trip/\n"
            "      flight.igc        ← GPS track (IGC or GPX)\n"
            "      IMG_001.jpg       ← photos with EXIF timestamps\n"
            "      IMG_002.heic"
        )
        para("Supported track formats: IGC, GPX")
        para("Supported photo formats: JPEG, HEIC/HEIF, TIFF, PNG")

        section("Step 2 — Cesium terrain token (optional)")
        para(
            "A free Cesium ion token enables 3D terrain in the viewer. "
            "Without it the globe still works but appears flat.\n"
            "Get a free token, then click Setup to save it."
        )
        link(
            "Get a free Cesium token → ion.cesium.com/tokens",
            "https://ion.cesium.com/tokens",
        )

        # ── Modes ────────────────────────────────────────────────────────
        section("Modes")

        para(
            "Geotag\n"
            "Matches your photos to the GPS track by timestamp and writes GPS "
            "coordinates into the images. Opens the 3D map viewer afterwards. "
            "Output is saved automatically — you do not need to manage any output folder."
        )
        para(
            "Review\n"
            "Opens the 3D viewer for a previously geotagged trip without reprocessing. "
            "Select the same folder you originally used for geotagging."
        )
        para(
            "Browse\n"
            "Shows photos that already have GPS coordinates (e.g. taken with a phone). "
            "No track file needed. Images are connected by time order on the map."
        )
        # ── Timing correction ────────────────────────────────────────────
        section("Correcting camera clock drift")
        para(
            "If photos appear at wrong positions on the track, your camera clock "
            "was probably set to a different timezone or was slightly off."
        )
        para(
            "Use the 'Time offset (minutes)' field in the launcher to shift photo "
            "timestamps before matching. Try multiples of 60 for timezone differences.  "
            "Note that typically the app itself will autodetect timezone mismatch and "
            "suggest a correction, so focusing on camera clock drift is usually sufficient.\n"
            " Negative offset values shift photos earlier; positive later.\n"
            "Each run overwrites the previous result, so you can quickly iterate."
        )

        # ── Viewer controls ──────────────────────────────────────────────
        section("Viewer controls (in the browser)")
        para(
            "Left-click + drag to shift  •  Scroll or Right-click + drag to zoom  •  Ctrl + Left-click + drag to tilt/rotate\n"
            "Click a photo thumbnail to open the full image.\n"
            "Close the viewer control window (or click Stop viewer) to exit."
        )

        # ── Footer ───────────────────────────────────────────────────────
        footer = ttk.Frame(dialog, padding=(14, 6, 14, 10))
        footer.pack(fill="x")
        link_lbl = tk.Label(
            footer,
            text="Full documentation: github.com/pwolfrum/FlightPhotoMapper",
            fg="#0a58ca",
            cursor="hand2",
        )
        link_lbl.pack(side="left")
        link_lbl.bind(
            "<Button-1>",
            lambda _e: webbrowser.open("https://github.com/pwolfrum/FlightPhotoMapper"),
        )
        ttk.Button(footer, text="Close", command=dialog.destroy).pack(side="right")

    def open_about_dialog() -> None:
        dialog = tk.Toplevel(root)
        dialog.title("About FlightPhotoMapper")
        dialog.transient(root)
        dialog.grab_set()
        dialog.resizable(False, False)

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="FlightPhotoMapper",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            body,
            text=(
                "Geotag photos to GPS tracks (IGC/GPX), then view them\n"
                "in a Cesium 3D map viewer."
            ),
            justify="left",
        ).pack(anchor="w", pady=(6, 8))

        ttk.Label(
            body,
            text=(
                "Author: Philipp Wolfrum\n"
                "License: MIT (see LICENSE file)\n"
                "Acknowledgements: Flask, Pillow, pillow-heif, piexif, gpxpy, CesiumJS"
            ),
            justify="left",
            foreground="#444444",
        ).pack(anchor="w")

        links = ttk.Frame(body)
        links.pack(fill="x", pady=(10, 0))

        github_link = tk.Label(
            links,
            text="Project page: github.com/pwolfrum/FlightPhotoMapper",
            fg="#0a58ca",
            cursor="hand2",
        )
        github_link.pack(anchor="w")
        github_link.bind(
            "<Button-1>",
            lambda _e: webbrowser.open("https://github.com/pwolfrum/FlightPhotoMapper"),
        )

        token_link = tk.Label(
            links,
            text="Cesium page: ion.cesium.com",
            fg="#0a58ca",
            cursor="hand2",
        )
        token_link.pack(anchor="w", pady=(2, 0))
        token_link.bind(
            "<Button-1>",
            lambda _e: webbrowser.open("https://ion.cesium.com"),
        )

        ttk.Button(body, text="Close", command=dialog.destroy).pack(
            anchor="e", pady=(12, 0)
        )

    def open_setup_dialog() -> None:
        dialog = tk.Toplevel(root)
        dialog.title("Cesium Token Setup")
        dialog.transient(root)
        dialog.grab_set()
        dialog.resizable(False, False)

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, text="Cesium Terrain Setup", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "3D terrain requires your own Cesium ion token.\n"
                "Create a free token, then paste it below.\n"
                "The launcher stores it in your per-user config .env file."
            ),
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(6, 10))

        token_var = tk.StringVar(value=os.environ.get("CESIUM_ION_TOKEN", ""))
        ttk.Label(body, text="Token").pack(anchor="w")
        token_entry = ttk.Entry(body, textvariable=token_var, width=72)
        token_entry.pack(fill="x", pady=(2, 8))
        token_entry.focus_set()

        save_status_var = tk.StringVar(value="")
        env_path = get_user_env_path()
        ttk.Label(
            body,
            text=f"Save location: {env_path}",
            foreground="#555555",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        button_row = ttk.Frame(body)
        button_row.pack(fill="x")

        def open_token_page() -> None:
            webbrowser.open("https://ion.cesium.com/tokens")

        def save_token() -> None:
            token = token_var.get().strip()
            if not token:
                messagebox.showerror(
                    "Missing token", "Please paste a Cesium token before saving."
                )
                return

            saved_path = set_user_env_var("CESIUM_ION_TOKEN", token)
            os.environ["CESIUM_ION_TOKEN"] = token
            save_status_var.set(f"Saved to {saved_path}")
            refresh_token_status()
            # now close the dialog after saving
            dialog.destroy()

        ttk.Button(button_row, text="Cesium token page", command=open_token_page).pack(
            side="left"
        )
        ttk.Button(button_row, text="Close", command=dialog.destroy).pack(side="right")
        ttk.Button(button_row, text="Save", command=save_token).pack(
            side="right", padx=(0, 8)
        )

        ttk.Label(
            body,
            textvariable=save_status_var,
            foreground="#2f6f2f",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

    header_actions = ttk.Frame(header_row)
    header_actions.pack(side="right")
    ttk.Button(header_actions, text="About", command=open_about_dialog).pack(
        side="right"
    )
    ttk.Button(header_actions, text="Help", command=open_help_dialog).pack(
        side="right", padx=(0, 8)
    )
    ttk.Button(header_actions, text="Setup", command=open_setup_dialog).pack(
        side="right", padx=(0, 8)
    )

    ttk.Label(
        container,
        textvariable=token_status_var,
        foreground="#555555",
    ).pack(anchor="w", pady=(4, 0))

    refresh_token_status()

    mode_frame = ttk.Frame(container)
    mode_frame.pack(fill="x", pady=(8, 10))

    modes = [
        ("Geotag", "geotag"),
        ("Review", "review"),
        ("Browse", "browse"),
    ]

    for i, (label, value) in enumerate(modes):
        rb = ttk.Radiobutton(mode_frame, text=label, variable=mode_var, value=value)
        rb.grid(row=0, column=i, sticky="w", padx=(0, 12))
        _ToolTip(rb, TOOLTIPS[value])

    input_group = ttk.LabelFrame(container, text="Input Folder", padding=10)
    input_group.pack(fill="x", pady=(0, 10))

    input_entry = ttk.Entry(input_group, textvariable=input_dir_var)
    input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
    input_group.columnconfigure(0, weight=1)

    def browse_input():
        chosen = filedialog.askdirectory(
            title="Select input folder containing photos and tracks (optional)"
        )
        if chosen:
            input_dir_var.set(chosen)

    ttk.Button(input_group, text="Browse...", command=browse_input).grid(
        row=0, column=1, sticky="e"
    )

    options_group = ttk.LabelFrame(container, text="Options", padding=10)
    options_group.pack(fill="both", expand=True)

    options_frame = ttk.Frame(options_group)
    options_frame.pack(fill="both", expand=True)

    def render_options(*_args):
        for child in options_frame.winfo_children():
            child.destroy()

        mode = mode_var.get()
        row_index = 0

        if mode == "geotag":
            _row(options_frame, row_index, "Time offset (minutes)")
            ttk.Entry(options_frame, textvariable=time_offset_var, width=14).grid(
                row=row_index, column=1, sticky="w", pady=4
            )
            row_index += 1

            _row(options_frame, row_index, "Port")
            ttk.Entry(options_frame, textvariable=port_var, width=14).grid(
                row=row_index, column=1, sticky="w", pady=4
            )
            row_index += 1

            _row(options_frame, row_index, "Image mode")
            ttk.Combobox(
                options_frame,
                textvariable=image_mode_var,
                state="readonly",
                values=("panel", "fullscreen"),
                width=12,
            ).grid(row=row_index, column=1, sticky="w", pady=4)
            row_index += 1

        elif mode == "review":
            _row(options_frame, row_index, "Port")
            ttk.Entry(options_frame, textvariable=port_var, width=14).grid(
                row=row_index, column=1, sticky="w", pady=4
            )
            row_index += 1

            _row(options_frame, row_index, "Image mode")
            ttk.Combobox(
                options_frame,
                textvariable=image_mode_var,
                state="readonly",
                values=("panel", "fullscreen"),
                width=12,
            ).grid(row=row_index, column=1, sticky="w", pady=4)
            row_index += 1

        elif mode == "browse":
            _row(options_frame, row_index, "Port")
            ttk.Entry(options_frame, textvariable=port_var, width=14).grid(
                row=row_index, column=1, sticky="w", pady=4
            )
            row_index += 1

            _row(options_frame, row_index, "Image mode")
            ttk.Combobox(
                options_frame,
                textvariable=image_mode_var,
                state="readonly",
                values=("panel", "fullscreen"),
                width=12,
            ).grid(row=row_index, column=1, sticky="w", pady=4)
            row_index += 1

            ttk.Checkbutton(
                options_frame,
                text="Draw temporal sequence line",
                variable=include_sequence_line_var,
            ).grid(row=row_index, column=0, columnspan=2, sticky="w", pady=4)
            row_index += 1

        ttk.Label(
            options_frame,
            text=MODE_HELP[mode],
            foreground="#555555",
            wraplength=560,
            justify="left",
        ).grid(row=row_index, column=0, columnspan=2, sticky="w", pady=(10, 0))

    mode_var.trace_add("write", render_options)
    render_options()

    button_row = ttk.Frame(footer)
    button_row.pack(fill="x", pady=(10, 0))

    def cancel():
        root.destroy()

    def run():
        nonlocal request

        folder_text = input_dir_var.get().strip()
        if not folder_text:
            messagebox.showerror(
                "Missing input folder", "Please select an input folder."
            )
            return

        input_dir = Path(folder_text)
        if not input_dir.is_dir():
            messagebox.showerror(
                "Invalid input folder", f"Not a directory:\n{input_dir}"
            )
            return

        mode = mode_var.get()

        parsed_port = 5000
        parsed_image_mode = image_mode_var.get()

        if mode in {"geotag", "review", "browse"}:
            try:
                parsed_port = int(port_var.get().strip())
                if parsed_port < 1 or parsed_port > 65535:
                    raise ValueError()
            except ValueError:
                messagebox.showerror(
                    "Invalid port",
                    "Port must be an integer between 1 and 65535.",
                )
                return

        if parsed_image_mode not in {"panel", "fullscreen"}:
            messagebox.showerror(
                "Invalid image mode", "Image mode must be panel or fullscreen."
            )
            return

        parsed_time_offset = 0.0
        if mode == "geotag":
            try:
                parsed_time_offset = float(time_offset_var.get().strip())
            except ValueError:
                messagebox.showerror(
                    "Invalid time offset",
                    "Time offset must be a number in minutes (e.g. -13 or 7.5).",
                )
                return

        request = {
            "mode": mode,
            "input_dir": input_dir,
            "port": parsed_port,
            "image_mode": parsed_image_mode,
            "time_offset_minutes": parsed_time_offset,
            "include_sequence_line": bool(include_sequence_line_var.get()),
        }

        root.destroy()

    ttk.Button(button_row, text="Cancel", command=cancel).pack(side="right")
    ttk.Button(button_row, text="Run", command=run).pack(side="right", padx=(0, 8))

    root.mainloop()
    return request
