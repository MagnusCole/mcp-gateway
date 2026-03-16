"""MCPGateway — the core class that unifies N MCP servers into one endpoint."""
from __future__ import annotations

import asyncio
import fnmatch
import importlib
import inspect
import json
import logging
import os
import time
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from ._types import (
    GatewayConfig,
    PluginConfig,
    ServerConfig,
    get_tool_meta,
    is_tool,
    signature_to_json_schema,
)
from .session import ExternalMCPSession, connect, disconnect, proxy_call

_logger = logging.getLogger("mcp_gateway")


class MCPGateway:
    """Unifies multiple MCP servers and Python plugins behind a single MCP endpoint.

    Servers are spawned lazily on first tool call and killed after idle timeout.
    Python ``@tool``-decorated functions run in-process with zero overhead.
    """

    def __init__(
        self,
        config: GatewayConfig | None = None,
        *,
        name: str = "mcp-gateway",
    ) -> None:
        self._config = config or GatewayConfig()
        self._server = Server(name)
        self._start_time = time.time()

        # Tool registries
        self._plugin_tools: dict[str, dict] = {}  # name → {fn, description, inputSchema}
        self._external_sessions: dict[str, ExternalMCPSession] = {}
        self._server_configs: dict[str, ServerConfig] = {}
        self._tool_route: dict[str, tuple[str, str]] = {}  # name → (source, "plugin"|"external"|"connect"|"meta")
        self._tool_defs: list[types.Tool] = []

        # Registry (optional)
        self._registry = None

        # Setup
        self._apply_config()
        self._register_handlers()

    # ── Class Methods ────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, path: str | Path) -> MCPGateway:
        """Create a gateway from a YAML config file."""
        import yaml

        path = Path(path)
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        servers: dict[str, ServerConfig] = {}
        for sname, sconf in raw.get("servers", {}).items():
            env = sconf.get("env")
            if env:
                env = {k: os.path.expandvars(str(v)) for k, v in env.items()}
            servers[sname] = ServerConfig(
                command=sconf.get("command", ""),
                args=sconf.get("args", []),
                env=env,
                enabled=sconf.get("enabled", True),
                lazy=sconf.get("lazy", True),
            )

        plugins = [
            PluginConfig(module=p if isinstance(p, str) else p.get("module", ""))
            for p in raw.get("plugins", [])
        ]

        roles: dict[str, list[str] | None] = {}
        for rname, rtools in raw.get("roles", {}).items():
            roles[rname] = rtools  # None = all tools

        config = GatewayConfig(
            servers=servers,
            plugins=plugins,
            idle_timeout=raw.get("idle_timeout", 300),
            roles=roles,
            registry=raw.get("registry"),
        )

        return cls(config, name=raw.get("name", "mcp-gateway"))

    # ── Public API ───────────────────────────────────────────────────────

    def register_tool(
        self,
        fn,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Register a Python function as an MCP tool programmatically."""
        tool_name = name or fn.__name__
        tool_desc = description or fn.__doc__ or tool_name
        schema = signature_to_json_schema(fn)

        self._plugin_tools[tool_name] = {
            "fn": fn,
            "description": tool_desc,
            "inputSchema": schema,
        }
        self._tool_route[tool_name] = (tool_name, "plugin")
        self._rebuild_tool_defs()

    async def serve_sse(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        """Run the gateway as an SSE server."""
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse, Response
        from starlette.routing import Route
        from mcp.server.sse import SseServerTransport
        import uvicorn

        sse_transport = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as (r, w):
                await self._server.run(r, w, self._server.create_initialization_options())
            return Response()

        async def handle_messages(request):
            await sse_transport.handle_post_message(
                request.scope, request.receive, request._send
            )
            return Response()

        async def handle_health(_request):
            return JSONResponse(self._status_dict())

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Route("/messages/", endpoint=handle_messages, methods=["POST"]),
                Route("/health", endpoint=handle_health),
            ],
            on_startup=[lambda: asyncio.create_task(self._cleanup_idle_loop())],
        )

        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        uv_server = uvicorn.Server(config)
        await uv_server.serve()

    async def serve_stdio(self) -> None:
        """Run the gateway in stdio mode (for Claude Code settings.json)."""
        cleanup_task = asyncio.create_task(self._cleanup_idle_loop())
        try:
            async with stdio_server() as (read, write):
                await self._server.run(
                    read, write, self._server.create_initialization_options()
                )
        finally:
            cleanup_task.cancel()
            for name in list(self._external_sessions):
                await self._disconnect(name)

    # ── Context Manager ──────────────────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        for name in list(self._external_sessions):
            await self._disconnect(name)

    # ── Internals ────────────────────────────────────────────────────────

    def _apply_config(self) -> None:
        cfg = self._config

        # Store server configs
        for sname, sconf in cfg.servers.items():
            if sconf.enabled:
                self._server_configs[sname] = sconf

        # Load plugins
        for plugin in cfg.plugins:
            self._load_plugin(plugin.module)

        # Optional registry
        if cfg.registry:
            from .registry import Registry
            self._registry = Registry(cfg.registry)
            for sname, sconf in cfg.servers.items():
                self._registry.upsert(sname, sconf)

        self._rebuild_tool_defs()

    def _load_plugin(self, module_path: str) -> None:
        """Import a module and register any @tool-decorated functions."""
        try:
            mod = importlib.import_module(module_path)
        except Exception as e:
            _logger.error("Failed to import plugin '%s': %s", module_path, e)
            return

        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if is_tool(obj):
                meta = get_tool_meta(obj)
                schema = signature_to_json_schema(obj)
                tool_name = meta["name"]
                self._plugin_tools[tool_name] = {
                    "fn": obj,
                    "description": meta["description"],
                    "inputSchema": schema,
                }
                self._tool_route[tool_name] = (tool_name, "plugin")
                _logger.info("Loaded plugin tool: %s", tool_name)

    def _rebuild_tool_defs(self) -> None:
        """Rebuild the unified tool definition list."""
        defs: list[types.Tool] = []

        # Plugin tools
        for tname, tinfo in self._plugin_tools.items():
            defs.append(types.Tool(
                name=tname,
                description=tinfo["description"],
                inputSchema=tinfo["inputSchema"],
            ))

        # External servers
        for sname, sconf in self._server_configs.items():
            if sname in self._external_sessions and self._external_sessions[sname].connected:
                # Real schemas from connected session
                for t in self._external_sessions[sname].tools:
                    defs.append(t)
                    self._tool_route[t.name] = (sname, "external")
            else:
                # Placeholder — connect to discover
                placeholder_name = f"_{sname.replace('-', '_')}_connect"
                defs.append(types.Tool(
                    name=placeholder_name,
                    description=(
                        f"[{sname}] Connect and discover tools. "
                        f"Call this to activate {sname} and see its real tools."
                    ),
                    inputSchema={"type": "object", "properties": {}},
                ))
                self._tool_route[placeholder_name] = (sname, "connect")

        # Meta tools
        meta_tools = [
            types.Tool(
                name="gateway_status",
                description="Gateway status: servers, plugins, tool count, uptime.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]
        for mt in meta_tools:
            defs.append(mt)
            self._tool_route[mt.name] = ("_meta", "meta")

        self._tool_defs = defs

    def _register_handlers(self) -> None:
        """Wire up MCP server handlers."""

        @self._server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            role = os.environ.get("MCP_GATEWAY_ROLE", "")
            if not role or role not in self._config.roles:
                return self._tool_defs

            allowed = self._config.roles[role]
            if allowed is None:
                return self._tool_defs

            return [
                t for t in self._tool_defs
                if any(fnmatch.fnmatch(t.name, pat) for pat in allowed)
            ]

        @self._server.call_tool()
        async def handle_call_tool(name: str, args: dict) -> list[types.TextContent]:
            t0 = time.perf_counter()
            try:
                result = await self._dispatch(name, args)
                text = json.dumps(result, ensure_ascii=False, indent=2)
                ms = round((time.perf_counter() - t0) * 1000)
                return [
                    types.TextContent(type="text", text=json.dumps(
                        {"_tool": name, "_ms": ms})),
                    types.TextContent(type="text", text=text),
                ]
            except Exception as e:
                ms = round((time.perf_counter() - t0) * 1000)
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(e), "tool": name, "ms": ms}),
                )]

    async def _dispatch(self, name: str, args: dict) -> dict:
        """Route a tool call to the right handler."""
        route = self._tool_route.get(name)
        if not route:
            return {"error": f"Tool '{name}' not found"}

        source, kind = route

        # Meta tools
        if kind == "meta":
            return self._dispatch_meta(name, args)

        # Connect placeholder
        if kind == "connect":
            return await self._handle_connect(source)

        # Plugin tool (in-process)
        if kind == "plugin":
            return await self._dispatch_plugin(name, args)

        # External proxy
        if kind == "external":
            return await self._dispatch_external(source, name, args)

        return {"error": f"Unknown route kind '{kind}' for tool '{name}'"}

    async def _dispatch_plugin(self, name: str, args: dict) -> dict:
        """Call a plugin tool function."""
        info = self._plugin_tools.get(name)
        if not info:
            return {"error": f"Plugin tool '{name}' not found"}

        fn = info["fn"]
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                result = await asyncio.to_thread(fn, **args)

            if isinstance(result, dict):
                return result
            return {"result": result}
        except Exception as e:
            return {"error": f"Plugin '{name}' error: {e}"}

    async def _dispatch_external(self, server_name: str, tool_name: str, args: dict) -> dict:
        """Proxy a call to an external MCP session."""
        es = self._external_sessions.get(server_name)
        if not es or not es.connected:
            # Auto-reconnect
            es_new = await self._connect_server(server_name)
            if not es_new:
                return {"error": f"Server '{server_name}' not connected"}
            es = es_new

        config = self._server_configs.get(server_name)
        return await proxy_call(es, tool_name, args, reconnect_config=config)

    async def _handle_connect(self, server_name: str) -> dict:
        """Handle a _<server>_connect placeholder call."""
        es = await self._connect_server(server_name)
        if es:
            return {
                "connected": server_name,
                "tools_discovered": len(es.tools),
                "tool_names": sorted(es.tool_names),
                "hint": "Tools are now available. Call them directly by name.",
            }
        return {"error": f"Failed to connect to {server_name}"}

    async def _connect_server(self, server_name: str) -> ExternalMCPSession | None:
        """Connect to a server, cache the session, rebuild tool defs."""
        if server_name in self._external_sessions and self._external_sessions[server_name].connected:
            es = self._external_sessions[server_name]
            es.last_used = time.time()
            return es

        config = self._server_configs.get(server_name)
        if not config:
            _logger.error("No config for server '%s'", server_name)
            return None

        try:
            es = await connect(server_name, config)
            self._external_sessions[server_name] = es
            self._rebuild_tool_defs()
            return es
        except Exception as e:
            _logger.error("Failed to connect '%s': %s", server_name, e)
            return None

    async def _disconnect(self, server_name: str) -> None:
        es = self._external_sessions.pop(server_name, None)
        if es:
            await disconnect(es)

    def _dispatch_meta(self, name: str, args: dict) -> dict:
        if name == "gateway_status":
            return self._status_dict()
        return {"error": f"Unknown meta tool: {name}"}

    def _status_dict(self) -> dict:
        ext_connected = [n for n, es in self._external_sessions.items() if es.connected]
        return {
            "uptime_s": round(time.time() - self._start_time),
            "plugins": len(self._plugin_tools),
            "servers_configured": len(self._server_configs),
            "servers_connected": ext_connected,
            "tools_total": len(self._tool_defs),
            "idle_timeout": self._config.idle_timeout,
        }

    async def _cleanup_idle_loop(self) -> None:
        """Background task: kill sessions idle longer than timeout."""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            to_disconnect = [
                name for name, es in self._external_sessions.items()
                if es.connected and (now - es.last_used) > self._config.idle_timeout
            ]
            for name in to_disconnect:
                await self._disconnect(name)
            if to_disconnect:
                self._rebuild_tool_defs()
