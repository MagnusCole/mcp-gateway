"""Tests for gateway.py — MCPGateway core class."""
from __future__ import annotations

import asyncio
import json
import tempfile

import pytest

from mcp_gateway import MCPGateway, tool
from mcp_gateway._types import GatewayConfig, ServerConfig


def test_create_empty_gateway():
    gw = MCPGateway()
    assert len(gw._tool_defs) >= 1  # at least gateway_status


def test_register_tool_sync():
    gw = MCPGateway()
    initial = len(gw._tool_defs)

    def add(a: float, b: float) -> float:
        return a + b

    gw.register_tool(add, description="Add two numbers")
    assert len(gw._tool_defs) == initial + 1
    assert "add" in gw._tool_route


def test_register_tool_with_custom_name():
    gw = MCPGateway()

    def fn(x: int) -> int:
        return x * 2

    gw.register_tool(fn, name="double", description="Double a number")
    assert "double" in gw._tool_route


@pytest.mark.asyncio
async def test_dispatch_plugin_sync():
    gw = MCPGateway()

    def add(a: float, b: float) -> float:
        return a + b

    gw.register_tool(add)
    result = await gw._dispatch("add", {"a": 2.0, "b": 3.0})
    assert result == {"result": 5.0}


@pytest.mark.asyncio
async def test_dispatch_plugin_async():
    gw = MCPGateway()

    async def greet(name: str) -> str:
        return f"Hello, {name}!"

    gw.register_tool(greet)
    result = await gw._dispatch("greet", {"name": "World"})
    assert result == {"result": "Hello, World!"}


@pytest.mark.asyncio
async def test_dispatch_plugin_returns_dict():
    gw = MCPGateway()

    def status() -> dict:
        return {"ok": True, "count": 42}

    gw.register_tool(status)
    result = await gw._dispatch("status", {})
    assert result == {"ok": True, "count": 42}


@pytest.mark.asyncio
async def test_dispatch_unknown_tool():
    gw = MCPGateway()
    result = await gw._dispatch("nonexistent", {})
    assert "error" in result


@pytest.mark.asyncio
async def test_dispatch_meta_status():
    gw = MCPGateway()
    result = await gw._dispatch("gateway_status", {})
    assert "uptime_s" in result
    assert "tools_total" in result


def test_from_config_yaml():
    import yaml

    config = {
        "servers": {
            "test": {
                "command": "echo",
                "args": ["hello"],
                "enabled": True,
            },
        },
        "idle_timeout": 120,
        "roles": {
            "admin": None,
            "viewer": ["gateway_status"],
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        f.flush()

        gw = MCPGateway.from_config(f.name)
        assert "test" in gw._server_configs
        assert gw._config.idle_timeout == 120
        assert gw._config.roles["admin"] is None
        assert gw._config.roles["viewer"] == ["gateway_status"]


def test_server_placeholder_created():
    gw = MCPGateway(GatewayConfig(
        servers={"myserver": ServerConfig(command="echo", args=["hi"])},
    ))
    names = [t.name for t in gw._tool_defs]
    assert "_myserver_connect" in names


def test_status_dict():
    gw = MCPGateway()
    gw.register_tool(lambda: 1, name="t1", description="test")
    status = gw._status_dict()
    assert status["plugins"] == 1
    assert status["servers_configured"] == 0
