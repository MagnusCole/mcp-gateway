"""CLI entry point: mcp-gateway serve|stdio|list."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .gateway import MCPGateway


def _find_config(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    for name in ("gateway.yaml", "mcp-gateway.yaml"):
        p = Path(name)
        if p.exists():
            return p
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-gateway",
        description="Unify multiple MCP servers behind a single endpoint.",
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    p_serve = sub.add_parser("serve", help="Run as SSE server")
    p_serve.add_argument("--config", "-c", type=str, default=None)
    p_serve.add_argument("--host", type=str, default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8765)

    # stdio
    p_stdio = sub.add_parser("stdio", help="Run in stdio mode (for Claude Code)")
    p_stdio.add_argument("--config", "-c", type=str, default=None)

    # list
    p_list = sub.add_parser("list", help="List configured servers and tools")
    p_list.add_argument("--config", "-c", type=str, default=None)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.command in ("serve", "stdio", "list"):
        config_path = _find_config(args.config)
        if config_path:
            gw = MCPGateway.from_config(config_path)
        else:
            gw = MCPGateway()

        if args.command == "serve":
            asyncio.run(gw.serve_sse(host=args.host, port=args.port))
        elif args.command == "stdio":
            asyncio.run(gw.serve_stdio())
        elif args.command == "list":
            _print_list(gw)
    else:
        parser.print_help()


def _print_list(gw: MCPGateway) -> None:
    print(f"Servers ({len(gw._server_configs)}):")
    for name, cfg in gw._server_configs.items():
        status = "enabled" if cfg.enabled else "disabled"
        print(f"  {name}: {cfg.command} {' '.join(cfg.args)} [{status}]")

    print(f"\nPlugins ({len(gw._plugin_tools)}):")
    for name, info in gw._plugin_tools.items():
        print(f"  {name}: {info['description'][:60]}")

    print(f"\nTotal tools: {len(gw._tool_defs)}")


if __name__ == "__main__":
    main()
