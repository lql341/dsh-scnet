"""Version helpers shared by the CLI and OpenAPI client."""

from __future__ import annotations

from pathlib import Path


def version_file() -> Path:
    return Path(__file__).resolve().parent.parent / "VERSION"


def get_version() -> str:
    try:
        value = version_file().read_text(encoding="utf-8").strip()
    except OSError:
        return "0+unknown"
    return value or "0+unknown"


VERSION = get_version()
