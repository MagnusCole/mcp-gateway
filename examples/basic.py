"""Basic programmatic usage of mcp-gateway."""
from __future__ import annotations

import asyncio

from mcp_gateway import MCPGateway
from mcp_gateway._types import ServerConfig


async def main():
    gw = MCPGateway()

    # Add a server programmatically
    gw._server_configs["filesystem"] = ServerConfig(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    )
    gw._rebuild_tool_defs()

    # Run in stdio mode
    await gw.serve_stdio()


if __name__ == "__main__":
    asyncio.run(main())
