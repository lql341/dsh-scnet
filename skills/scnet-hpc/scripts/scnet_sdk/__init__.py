"""Small internal client used by CLI, plugins, and future MCP adapters."""

from .client import SCNetClient, canonical_signature, service_endpoint
from .notebook import NotebookService

__all__ = [
    "NotebookService",
    "SCNetClient",
    "canonical_signature",
    "service_endpoint",
]
