"""Executable adapter for MCP bridges and other future connectors."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .base import Backend, BackendError, PROTOCOL_VERSION


PREFIX = "scnet-hpc-backend-"


def discover_external_backends() -> dict[str, str]:
    found: dict[str, str] = {}
    search_dirs: list[Path] = []
    for item in os.environ.get("SCNET_HPC_BACKEND_PATH", "").split(os.pathsep):
        if item:
            search_dirs.append(Path(item).expanduser())
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for path in directory.glob(f"{PREFIX}*"):
            if path.is_file() and os.access(path, os.X_OK):
                found[path.name[len(PREFIX) :]] = str(path)
    for name in filter(
        None,
        (item.strip() for item in os.environ.get(
            "SCNET_HPC_EXTERNAL_BACKENDS", ""
        ).split(",")),
    ):
        executable = shutil.which(f"{PREFIX}{name}")
        if executable:
            found[name] = executable
    return found


class ExternalBackend(Backend):
    def __init__(self, context, name: str, executable: str):
        super().__init__(context)
        self.name = name
        self.executable = executable
        self.capabilities = frozenset(self._request("capabilities", {}).get("capabilities", []))

    def _request(self, operation: str, options: Mapping[str, Any]) -> Any:
        request = {
            "protocol": "scnet-hpc.backend",
            "protocol_version": PROTOCOL_VERSION,
            "operation": operation,
            "profile_name": self.context.profile_name,
            "profile": dict(self.context.profile),
            "options": dict(options),
        }
        try:
            completed = subprocess.run(
                [self.executable],
                input=json.dumps(request, ensure_ascii=False),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.context.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(str(exc)) from exc
        if completed.returncode != 0:
            raise BackendError(
                completed.stderr.strip()
                or f"external backend exited with {completed.returncode}"
            )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BackendError("external backend returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise BackendError("external backend response must be a JSON object")
        if response.get("protocol_version") not in (None, PROTOCOL_VERSION):
            raise BackendError("external backend protocol version mismatch")
        if response.get("ok") is False:
            raise BackendError(str(response.get("error") or "external backend failed"))
        return response.get("data", response)

    def execute(self, operation: str, options: Mapping[str, Any]) -> Any:
        if operation not in self.capabilities:
            raise BackendError(
                f"backend {self.name!r} does not support operation {operation!r}"
            )
        return self._request(operation, options)
