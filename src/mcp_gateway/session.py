"""External MCP session management — connect, disconnect, proxy calls via SDK."""
from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass, field

import mcp.types as types
from mcp import ClientSession, StdioServerParameters, stdio_client

from ._types import ServerConfig

_logger = logging.getLogger("mcp_gateway.session")


@dataclass
class ExternalMCPSession:
    """Wraps an MCP ClientSession to an external server subprocess."""
    name: str
    session: ClientSession | None = None
    exit_stack: contextlib.AsyncExitStack | None = None
    tools: list[types.Tool] = field(default_factory=list)
    tool_names: set[str] = field(default_factory=set)
    last_used: float = 0.0
    connected: bool = False


async def connect(name: str, config: ServerConfig) -> ExternalMCPSession:
    """Spawn an external MCP server subprocess and discover its tools.

    Returns an ``ExternalMCPSession`` with real tool schemas populated.
    Raises on failure (caller decides how to handle).
    """
    server_params = StdioServerParameters(
        command=config.command,
        args=config.args,
        env=config.env,
    )

    exit_stack = contextlib.AsyncExitStack()
    read_stream, write_stream = await exit_stack.enter_async_context(
        stdio_client(server_params)
    )
    session = await exit_stack.enter_async_context(
        ClientSession(read_stream, write_stream)
    )
    await session.initialize()

    # Discover real tool schemas
    tools_result = await session.list_tools()
    real_tools = list(tools_result.tools)
    tool_names = {t.name for t in real_tools}

    _logger.info(
        "Connected %s: %d tools (%s)",
        name,
        len(real_tools),
        ", ".join(sorted(tool_names)[:5]) + ("..." if len(tool_names) > 5 else ""),
    )

    return ExternalMCPSession(
        name=name,
        session=session,
        exit_stack=exit_stack,
        tools=real_tools,
        tool_names=tool_names,
        last_used=time.time(),
        connected=True,
    )


async def disconnect(es: ExternalMCPSession) -> None:
    """Gracefully shut down an external MCP session."""
    if es.exit_stack:
        _logger.info("Disconnecting external MCP: %s", es.name)
        try:
            await es.exit_stack.aclose()
        except Exception as e:
            _logger.warning("Error closing %s: %s", es.name, e)
    es.connected = False
    es.session = None
    es.exit_stack = None


async def proxy_call(
    es: ExternalMCPSession,
    tool_name: str,
    args: dict,
    *,
    reconnect_config: ServerConfig | None = None,
) -> dict:
    """Route a tool call through an external MCP session.

    If the call fails and *reconnect_config* is provided, reconnects once and
    retries.  Returns a dict with ``content`` list and ``isError`` flag.
    """
    for attempt in range(2):
        if not es.session or not es.connected:
            if reconnect_config is None or attempt > 0:
                return {"error": f"Not connected to '{es.name}'"}
            # Attempt reconnect
            _logger.info("Reconnecting %s (attempt %d)...", es.name, attempt + 1)
            try:
                new = await connect(es.name, reconnect_config)
                es.session = new.session
                es.exit_stack = new.exit_stack
                es.tools = new.tools
                es.tool_names = new.tool_names
                es.connected = True
            except Exception as exc:
                return {"error": f"Reconnect failed for '{es.name}': {exc}"}

        try:
            result = await es.session.call_tool(tool_name, args)  # type: ignore[union-attr]
            es.last_used = time.time()

            content_parts: list[dict] = []
            for part in result.content:
                if hasattr(part, "text"):
                    content_parts.append({"type": "text", "text": part.text})
                elif hasattr(part, "data"):
                    content_parts.append({
                        "type": "image",
                        "mimeType": getattr(part, "mimeType", ""),
                    })
                else:
                    content_parts.append({"type": type(part).__name__})

            return {
                "content": content_parts,
                "isError": getattr(result, "isError", False),
            }
        except Exception as e:
            _logger.error("Proxy call failed %s.%s: %s", es.name, tool_name, e)
            es.connected = False
            if reconnect_config is None:
                return {"error": f"Tool call failed: {e}"}
            # Loop will retry

    return {"error": f"Tool call failed after retry for {es.name}.{tool_name}"}
