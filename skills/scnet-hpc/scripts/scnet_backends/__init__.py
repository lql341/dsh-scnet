"""Backend registry."""

from __future__ import annotations

from .base import BackendContext, BackendError
from .external import ExternalBackend, discover_external_backends
from .openapi import OpenAPIBackend
from .ssh import SSHBackend


BUILTINS = {
    "ssh": SSHBackend,
    "openapi": OpenAPIBackend,
}


def backend_catalog() -> list[dict[str, object]]:
    result = [
        {
            "name": name,
            "kind": "builtin",
            "capabilities": sorted(backend.capabilities),
        }
        for name, backend in BUILTINS.items()
    ]
    for name, executable in sorted(discover_external_backends().items()):
        result.append(
            {
                "name": name,
                "kind": "external",
                "executable": executable,
                "capabilities": "queried when selected",
            }
        )
    return result


def create_backend(name: str, context: BackendContext):
    if name in BUILTINS:
        return BUILTINS[name](context)
    external = discover_external_backends()
    if name in external:
        return ExternalBackend(context, name, external[name])
    available = ", ".join(item["name"] for item in backend_catalog())
    raise BackendError(f"unknown backend {name!r}; available: {available}")


__all__ = [
    "BackendContext",
    "BackendError",
    "backend_catalog",
    "create_backend",
]
