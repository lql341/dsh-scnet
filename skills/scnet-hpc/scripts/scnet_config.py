"""User-local, non-secret configuration for the SCNet CLI."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


def config_root() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / "scnet-hpc"
    return Path.home() / ".config" / "scnet-hpc"


def config_path() -> Path:
    return config_root() / "config.json"


def ssh_profile_path(cluster: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", cluster):
        raise ValueError("unsafe cluster profile name")
    return config_root() / "ssh" / f"{cluster}.json"


def openapi_cache_path() -> Path:
    return config_root() / "openapi.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_user_config() -> dict[str, Any]:
    data = _read_json(config_path())
    ssh = data.setdefault("ssh", {})
    if isinstance(ssh, dict):
        clusters = ssh.setdefault("clusters", {})
        if isinstance(clusters, dict):
            ssh_dir = config_root() / "ssh"
            for path in sorted(ssh_dir.glob("*.json")):
                profile = _read_json(path)
                if profile:
                    clusters[path.stem] = profile
    openapi_cache = _read_json(openapi_cache_path())
    if openapi_cache:
        current = data.setdefault("openapi", {})
        if isinstance(current, dict):
            current.update(openapi_cache)
    return data


def save_user_config(data: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    clean = json.loads(json.dumps(data, ensure_ascii=False))
    cluster = str(clean.get("cluster") or "")
    ssh = clean.get("ssh")
    if isinstance(ssh, dict):
        clusters = ssh.get("clusters")
        if isinstance(clusters, dict):
            for name, profile in clusters.items():
                if isinstance(profile, dict):
                    save_ssh_profile(str(name), profile)
        elif cluster and isinstance(ssh.get("username"), str):
            save_ssh_profile(
                cluster,
                {
                    key: value
                    for key, value in ssh.items()
                    if key != "clusters"
                },
            )
    openapi = clean.get("openapi")
    if isinstance(openapi, dict):
        _save_json_sidecar(openapi_cache_path(), openapi)
    clean.pop("ssh", None)
    clean.pop("openapi", None)
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


def _save_json_sidecar(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    clean = json.loads(json.dumps(data, ensure_ascii=False))
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent)
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


def save_ssh_profile(cluster: str, data: dict[str, Any]) -> Path:
    return _save_json_sidecar(ssh_profile_path(cluster), data)


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
