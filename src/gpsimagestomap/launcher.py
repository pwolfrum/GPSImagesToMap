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
    "export": "Build a static website package for sharing or hosting.",
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
    "export": (
        "Export mode\n"
        "Builds a static site package (index.html + images + thumbnails) for sharing or hosting.\n\n"
        "Options:\n"
        "- Output folder (optional): custom destination; leave empty to use <input>/export.\n"
        "- Preview after export: start local static preview server automatically.\n"
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
    root.title("GPSImagesToMap Launcher")
    root.geometry("640x520")
    root.minsize(640, 520)

    request: dict | None = None
    load_app_env(Path.cwd())

    mode_var = tk.StringVar(value="geotag")
    input_dir_var = tk.StringVar(value="")
    port_var = tk.StringVar(value="5000")
    image_mode_var = tk.StringVar(value="panel")
    time_offset_var = tk.StringVar(value="0")
    include_sequence_line_var = tk.BooleanVar(value=True)
    output_dir_var = tk.StringVar(value="")
    do_preview_var = tk.BooleanVar(value=False)

    container = ttk.Frame(root, padding=12)
    container.pack(fill="both", expand=True)

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

    ttk.Button(header_row, text="Setup", command=open_setup_dialog).pack(side="right")

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
        ("Export", "export"),
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

    def browse_output():
        chosen = filedialog.askdirectory(title="Select export output folder")
        if chosen:
            output_dir_var.set(chosen)

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

        elif mode == "export":
            _row(options_frame, row_index, "Output folder (optional)")
            output_row = ttk.Frame(options_frame)
            output_row.grid(row=row_index, column=1, sticky="ew", pady=4)
            out_entry = ttk.Entry(output_row, textvariable=output_dir_var, width=34)
            out_entry.pack(side="left", fill="x", expand=True)
            ttk.Button(output_row, text="Browse...", command=browse_output).pack(
                side="left", padx=(6, 0)
            )
            row_index += 1

            ttk.Checkbutton(
                options_frame,
                text="Preview after export",
                variable=do_preview_var,
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

    button_row = ttk.Frame(container)
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

        parsed_output_dir: Path | None = None
        if mode == "export":
            out_value = output_dir_var.get().strip()
            if out_value:
                parsed_output_dir = Path(out_value)

        request = {
            "mode": mode,
            "input_dir": input_dir,
            "port": parsed_port,
            "image_mode": parsed_image_mode,
            "time_offset_minutes": parsed_time_offset,
            "include_sequence_line": bool(include_sequence_line_var.get()),
            "output_dir": parsed_output_dir,
            "do_preview": bool(do_preview_var.get()),
        }

        root.destroy()

    ttk.Button(button_row, text="Cancel", command=cancel).pack(side="right")
    ttk.Button(button_row, text="Run", command=run).pack(side="right", padx=(0, 8))

    root.mainloop()
    return request
