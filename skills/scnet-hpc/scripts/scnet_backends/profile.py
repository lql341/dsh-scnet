"""Read the repository's simple shell-style cluster profiles safely."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

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
                "default_backend": profile.get("DEFAULT_BACKEND", "ssh"),
            }
        )
    return result


def load_profile(repo_root: Path, name: str | None) -> tuple[str | None, dict[str, str]]:
    profiles = list_profiles(repo_root)
    if name:
        path = repo_root / "clusters" / f"{name}.conf"
        if not path.is_file():
            available = ", ".join(item["name"] for item in profiles) or "(none)"
            raise BackendError(f"unknown cluster profile {name!r}; available: {available}")
        return name, parse_profile(path)
    if len(profiles) == 1:
        selected = profiles[0]["name"]
        return selected, parse_profile(repo_root / "clusters" / f"{selected}.conf")
    return None, {}
