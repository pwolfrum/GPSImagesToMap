"""Configuration helpers for app-level environment variables."""

import os
from pathlib import Path


def get_user_config_dir() -> Path:
    """Return the per-user configuration directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "GPSImagesToMap" / "config"

    return Path.home() / ".gpsimagestomap" / "config"


def get_user_env_path() -> Path:
    """Return the .env path used for launcher-managed settings."""
    return get_user_config_dir() / ".env"


def load_dotenv_file(env_file: Path) -> None:
    """Load variables from a .env file into os.environ (if the file exists)."""
    if not env_file.is_file():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]

        os.environ.setdefault(key, value)


def load_app_env(cwd: Path | None = None) -> None:
    """Load environment values from supported app config locations.

    Precedence:
      1) Existing process environment variables
      2) Per-user config env file
      3) Current working directory env file (developer convenience)
    """
    load_dotenv_file(get_user_env_path())

    if cwd is None:
        cwd = Path.cwd()
    load_dotenv_file(cwd / ".env")


def set_user_env_var(key: str, value: str) -> Path:
    """Set or update an env variable in the per-user .env file."""
    env_path = get_user_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    prefix = f"{key}="
    new_line = f"{key}={value}"
    replaced = False
    updated: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            updated.append(new_line)
            replaced = True
        else:
            updated.append(line)

    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(new_line)

    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    return env_path
