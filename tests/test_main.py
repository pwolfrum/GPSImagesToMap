from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gpsimagestomap.image_discovery import ImageInfo
from gpsimagestomap.main import (
    _ask_timezone_correction_gui,
    _run_gui_request,
    handle_timezone_uncertainty,
)


def _uncertain_image() -> ImageInfo:
    return ImageInfo(
        path=Path("IMG_0001.jpg"),
        timestamp=datetime(2025, 5, 1, 12, 0, tzinfo=timezone.utc),
        has_gps=False,
        tz_certain=False,
    )


def test_handle_timezone_uncertainty_no_stdin_uses_gui_choice_no(monkeypatch):
    images = [_uncertain_image()]

    monkeypatch.setattr("gpsimagestomap.main._stdin_available", lambda: False)
    monkeypatch.setattr(
        "gpsimagestomap.main.detect_timezone_correction",
        lambda tracks, imgs: timedelta(hours=1),
    )
    monkeypatch.setattr("gpsimagestomap.main._count_images_in_tracks", lambda *args: 1)
    monkeypatch.setattr(
        "gpsimagestomap.main._ask_timezone_correction_gui",
        lambda hours, current, corrected: False,
    )

    result = handle_timezone_uncertainty([], images)
    assert result == images


def test_handle_timezone_uncertainty_no_stdin_gui_cancel_exits(monkeypatch):
    images = [_uncertain_image()]

    monkeypatch.setattr("gpsimagestomap.main._stdin_available", lambda: False)
    monkeypatch.setattr(
        "gpsimagestomap.main.detect_timezone_correction",
        lambda tracks, imgs: timedelta(hours=1),
    )
    monkeypatch.setattr("gpsimagestomap.main._count_images_in_tracks", lambda *args: 1)
    monkeypatch.setattr(
        "gpsimagestomap.main._ask_timezone_correction_gui",
        lambda hours, current, corrected: None,
    )

    with pytest.raises(SystemExit):
        handle_timezone_uncertainty([], images)


def test_handle_timezone_uncertainty_force_gui_ignores_stdin(monkeypatch):
    images = [_uncertain_image()]
    called: dict = {"gui": False}

    monkeypatch.setattr("gpsimagestomap.main._stdin_available", lambda: True)
    monkeypatch.setattr(
        "gpsimagestomap.main.detect_timezone_correction",
        lambda tracks, imgs: timedelta(hours=1),
    )
    monkeypatch.setattr("gpsimagestomap.main._count_images_in_tracks", lambda *args: 1)

    def fail_input(*args, **kwargs):
        raise AssertionError("input() should not be used when GUI prompts are forced")

    monkeypatch.setattr("builtins.input", fail_input)

    def fake_ask_timezone(hours, current, corrected):
        called["gui"] = True
        return False

    monkeypatch.setattr(
        "gpsimagestomap.main._ask_timezone_correction_gui",
        fake_ask_timezone,
    )

    result = handle_timezone_uncertainty([], images, force_gui_prompt=True)

    assert called["gui"] is True
    assert result == images


def test_ask_timezone_correction_gui_reuses_existing_root(monkeypatch):
    class ExistingRoot:
        def __init__(self):
            self.updated = False

        def winfo_exists(self):
            return True

        def update_idletasks(self):
            self.updated = True

    existing_root = ExistingRoot()
    called: dict = {}

    monkeypatch.setattr(
        "gpsimagestomap.main.tk._default_root", existing_root, raising=False
    )

    def fail_if_called():
        raise AssertionError("tk.Tk() should not be called when a root already exists")

    monkeypatch.setattr("gpsimagestomap.main.tk.Tk", fail_if_called)

    def fake_askyesnocancel(title, message, parent=None):
        called["title"] = title
        called["message"] = message
        called["parent"] = parent
        return True

    monkeypatch.setattr(
        "gpsimagestomap.main.messagebox.askyesnocancel",
        fake_askyesnocancel,
    )

    assert _ask_timezone_correction_gui(1, 2, 3) is True
    assert called["parent"] is existing_root
    assert existing_root.updated is True


def test_run_gui_request_geotag_passes_session_log_to_viewer(monkeypatch, tmp_path):
    captured: dict = {}

    monkeypatch.setattr("gpsimagestomap.main._is_valid_directory", lambda path: True)

    def fake_geotag(input_dir, time_offset_minutes=0, force_gui_prompts=False):
        print("IGNORED: 2 image(s) without EXIF timestamp")
        print("  - foo.jpg")
        captured["force_gui_prompts"] = force_gui_prompts
        return True

    monkeypatch.setattr("gpsimagestomap.main.geotag", fake_geotag)

    import gpsimagestomap.server as server

    def fake_stream_log(input_dir, processing_func, **kwargs):
        captured["input_dir"] = input_dir
        captured["processing_func"] = processing_func
        captured.update(kwargs)

    monkeypatch.setattr(server, "serve_with_streaming_log", fake_stream_log)

    _run_gui_request(
        {
            "mode": "geotag",
            "input_dir": tmp_path,
            "port": 5000,
            "image_mode": "panel",
            "time_offset_minutes": 0.0,
            "include_sequence_line": True,
            "output_dir": None,
            "do_preview": False,
        }
    )

    assert captured["input_dir"] == tmp_path
    assert captured["port"] == 5000
    assert captured["image_mode"] == "panel"
    assert captured["processing_kwargs"]["force_gui_prompts"] is True


def test_run_gui_request_browse_disables_sequence_line(monkeypatch, tmp_path):
    captured: dict = {}

    monkeypatch.setattr("gpsimagestomap.main._is_valid_directory", lambda path: True)

    def fake_prepare(input_dir):
        print("Ready - 3 image(s)")
        return True

    monkeypatch.setattr("gpsimagestomap.main._prepare_gps_images", fake_prepare)

    import gpsimagestomap.server as server

    def fake_stream_log(input_dir, processing_func, **kwargs):
        captured["input_dir"] = input_dir
        captured["processing_func"] = processing_func
        captured.update(kwargs)

    monkeypatch.setattr(server, "serve_with_streaming_log", fake_stream_log)

    _run_gui_request(
        {
            "mode": "browse",
            "input_dir": tmp_path,
            "port": 5001,
            "image_mode": "panel",
            "time_offset_minutes": 0.0,
            "include_sequence_line": False,
            "output_dir": None,
            "do_preview": False,
        }
    )

    assert captured["input_dir"] == tmp_path
    assert captured["include_tracks"] is False
    assert captured["include_image_sequence_track"] is False
