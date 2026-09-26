"""Shared backend interfaces for the SCNet command-line client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_VERSION = 1


class BackendError(RuntimeError):
    """A bounded, user-facing backend failure."""


@dataclass(frozen=True)
class BackendContext:
    repo_root: Path
    profile_name: str | None
    profile: Mapping[str, str]
    timeout: int = 30


class Backend:
    name = "base"
    capabilities: frozenset[str] = frozenset()

    def __init__(self, context: BackendContext):
        self.context = context

    def execute(self, operation: str, options: Mapping[str, Any]) -> Any:
        if operation not in self.capabilities:
            raise BackendError(
                f"backend {self.name!r} does not support operation {operation!r}"
            )
        handler = getattr(self, f"op_{operation.replace('-', '_')}", None)
        if handler is None:
            raise BackendError(
                f"backend {self.name!r} advertises {operation!r} but has no handler"
            )
        return handler(options)

    def preview(self, operation: str, options: Mapping[str, Any]) -> Any:
        """Describe a mutation without contacting the backend."""
        if operation not in self.capabilities:
            raise BackendError(
                f"backend {self.name!r} does not support operation {operation!r}"
            )
        handler = getattr(self, f"preview_{operation.replace('-', '_')}", None)
        if handler is not None:
            return handler(options)
        return {
            "backend": self.name,
            "operation": operation,
            "options": dict(options),
        }


def require_option(options: Mapping[str, Any], name: str) -> Any:
    value = options.get(name)
    if value is None or value == "":
        raise BackendError(f"missing required option: {name}")
    return value
