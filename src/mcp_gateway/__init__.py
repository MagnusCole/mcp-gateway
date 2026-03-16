"""mcp-gateway — Unify multiple MCP servers behind a single endpoint."""
from __future__ import annotations

__version__ = "0.1.0"

from .gateway import MCPGateway
from ._types import tool

__all__ = ["MCPGateway", "tool", "__version__"]
