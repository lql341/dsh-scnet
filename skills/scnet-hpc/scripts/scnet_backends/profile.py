"""Read the repository's simple shell-style cluster profiles safely."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from scnet_config import config_root, ssh_alias_path
from .base import BackendError


_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def parse_profile(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    logical_lines: list[tuple[int, str]] = []
    pending = ""
    pending_line = 0
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not pending:
            pending_line = line_number
        if raw_line.endswith("\\"):
            pending += raw_line[:-1]
            continue
        logical_lines.append((pending_line, pending + raw_line))
        pending = ""
    if pending:
        raise BackendError(f"{path}:{pending_line}: unfinished line continuation")

    for line_number, raw_line in logical_lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if not match:
            raise BackendError(f"{path}:{line_number}: unsupported profile syntax")
        key, raw_value = match.groups()
        lexer = shlex.shlex(raw_value, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        parts = list(lexer)
        if len(parts) > 1:
            raise BackendError(f"{path}:{line_number}: profile value must be scalar")
        values[key] = parts[0] if parts else ""
    return values


def _alias_base(repo_root: Path, name: str) -> str | None:
    try:
        data = json.loads(ssh_alias_path(name).read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError):
        # No home directory (empty environment) or an unreadable alias file must
        # not break listing the repository's own profiles.
        return None
    base = data.get("base_profile") if isinstance(data, dict) else None
    if not isinstance(base, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", base):
        return None
    if not (repo_root / "clusters" / f"{base}.conf").is_file() or base.startswith("_"):
        return None
    return base


def list_profiles(repo_root: Path) -> list[dict[str, str]]:
    cluster_dir = repo_root / "clusters"
    result: list[dict[str, str]] = []
    for path in sorted(cluster_dir.glob("*.conf")):
        if path.name.startswith("_"):
            continue
        profile = parse_profile(path)
        result.append(
            {
                "name": path.stem,
                "cluster_id": profile.get("CLUSTER_ID", path.stem),
                "description": profile.get("CLUSTER_DESC", ""),
                "default_backend": profile.get("DEFAULT_BACKEND", "openapi"),
            }
        )
    for path in _local_alias_files():
        if (cluster_dir / f"{path.stem}.conf").exists():
            continue
        base = _alias_base(repo_root, path.stem)
        if base:
            result.append({
                "name": path.stem, "cluster_id": path.stem,
                "description": f"SSH alias of {base}", "default_backend": "openapi",
            })
    return result


def _local_alias_files() -> list[Path]:
    """Local SSH aliases are optional; an unresolvable home must not raise."""
    try:
        return sorted((config_root() / "ssh" / "aliases").glob("*.json"))
    except (OSError, RuntimeError):
        return []


def load_profile(repo_root: Path, name: str | None) -> tuple[str | None, dict[str, str]]:
    profiles = list_profiles(repo_root)
    if name:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise BackendError("unsafe cluster profile name")
        path = repo_root / "clusters" / f"{name}.conf"
        if path.is_file():
            return name, parse_profile(path)
        base = _alias_base(repo_root, name)
        if base:
            profile = parse_profile(repo_root / "clusters" / f"{base}.conf")
            profile["CLUSTER_ID"] = name
            profile["CLUSTER_DESC"] = f"{profile.get('CLUSTER_DESC', base)} (SSH alias {name})"
            return name, profile
        available = ", ".join(item["name"] for item in profiles) or "(none)"
        raise BackendError(f"unknown cluster profile {name!r}; available: {available}")
    if len(profiles) == 1:
        return load_profile(repo_root, profiles[0]["name"])
    return None, {}
