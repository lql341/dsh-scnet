"""User-local, non-secret configuration for the SCNet CLI."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / "scnet-hpc" / "config.json"
    return Path.home() / ".config" / "scnet-hpc" / "config.json"


def load_user_config() -> dict[str, Any]:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_user_config(data: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    clean = json.loads(json.dumps(data, ensure_ascii=False))
    fd, temporary = tempfile.mkstemp(
        prefix=".config.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(clean, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def redacted_config(data: dict[str, Any]) -> dict[str, Any]:
    """Return a safe-to-display copy; this config should contain no secrets anyway."""
    result = json.loads(json.dumps(data, ensure_ascii=False))
    for section in ("openapi", "ssh"):
        if isinstance(result.get(section), dict):
            for key in list(result[section]):
                lowered = key.lower()
                if any(marker in lowered for marker in ("key", "token", "secret", "password")):
                    result[section][key] = "<not displayed>"
    return result
