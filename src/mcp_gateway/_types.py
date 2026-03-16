"""Type definitions, config dataclasses, and the @tool decorator."""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints


# ── @tool decorator ──────────────────────────────────────────────────────────

_TOOL_MARKER = "__mcp_gateway_tool__"


def tool(
    description: str = "",
    name: str | None = None,
) -> Callable:
    """Mark a function as an MCP tool exposed through the gateway.

    Usage::

        @tool(description="Add two numbers")
        def add(a: float, b: float) -> float:
            return a + b
    """

    def decorator(fn: Callable) -> Callable:
        setattr(fn, _TOOL_MARKER, {
            "name": name or fn.__name__,
            "description": description or fn.__doc__ or fn.__name__,
        })
        return fn

    return decorator


def is_tool(fn: Any) -> bool:
    return callable(fn) and hasattr(fn, _TOOL_MARKER)


def get_tool_meta(fn: Callable) -> dict:
    return getattr(fn, _TOOL_MARKER)


# ── Signature → JSON Schema ─────────────────────────────────────────────────

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def signature_to_json_schema(fn: Callable) -> dict:
    """Introspect type hints of *fn* and return a JSON Schema ``inputSchema``."""
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        hint = hints.get(param_name, str)
        origin = getattr(hint, "__origin__", None)
        json_type = _PY_TO_JSON.get(origin or hint, "string")
        prop: dict[str, Any] = {"type": json_type}
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(param_name)
        properties[param_name] = prop

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# ── Config Dataclasses ───────────────────────────────────────────────────────

@dataclass
class ServerConfig:
    """Launch configuration for one external MCP server."""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    enabled: bool = True
    lazy: bool = True


@dataclass
class PluginConfig:
    """A Python module containing @tool-decorated functions."""
    module: str = ""


@dataclass
class GatewayConfig:
    """Top-level gateway configuration (maps to gateway.yaml)."""
    servers: dict[str, ServerConfig] = field(default_factory=dict)
    plugins: list[PluginConfig] = field(default_factory=list)
    idle_timeout: int = 300
    roles: dict[str, list[str] | None] = field(default_factory=dict)
    registry: str | None = None  # path to SQLite registry, optional
