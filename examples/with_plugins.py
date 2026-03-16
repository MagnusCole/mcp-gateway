"""Example: using @tool decorator to add Python tools to the gateway."""
from __future__ import annotations

import asyncio

from mcp_gateway import MCPGateway, tool


@tool(description="Add two numbers")
def add(a: float, b: float) -> float:
    """Add two numbers and return the result."""
    return a + b


@tool(description="Multiply two numbers")
def multiply(a: float, b: float) -> float:
    return a * b


@tool(description="Convert Celsius to Fahrenheit")
async def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9 / 5 + 32


async def main():
    gw = MCPGateway()

    # Register tools programmatically
    gw.register_tool(add)
    gw.register_tool(multiply)
    gw.register_tool(celsius_to_fahrenheit)

    # Or register inline
    gw.register_tool(
        lambda text: len(text.split()),
        name="word_count",
        description="Count words in text",
    )

    print(f"Registered {len(gw._plugin_tools)} plugin tools")
    await gw.serve_stdio()


if __name__ == "__main__":
    asyncio.run(main())
