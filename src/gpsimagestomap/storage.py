"""Paths for app-managed generated artifacts."""

import hashlib
import os
import re
from pathlib import Path


def _sanitize_name(name: str) -> str:
    """Keep folder names filesystem-friendly and stable."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return cleaned or "dataset"


def get_work_root() -> Path:
    """Return the root folder for generated app artifacts."""
    override = os.environ.get("GPSIMAGES_WORK_DIR")
    if override:
        return Path(override)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "GPSImagesToMap" / "work"

    # Fallback for non-Windows environments running tests.
    return Path.home() / ".gpsimagestomap" / "work"


def get_dataset_images_dir(input_dir: Path) -> Path:
    """Return the generated-images folder for a specific input directory."""
    resolved = input_dir.resolve()
    dataset_hash = hashlib.sha1(str(resolved).casefold().encode("utf-8")).hexdigest()[
        :12
    ]
    dataset_name = _sanitize_name(input_dir.name)
    return get_work_root() / f"{dataset_name}-{dataset_hash}" / "images"
