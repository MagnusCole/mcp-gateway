"""Tests for _types.py — @tool decorator and schema generation."""
from __future__ import annotations

from mcp_gateway._types import (
    is_tool,
    get_tool_meta,
    signature_to_json_schema,
    tool,
    ServerConfig,
    GatewayConfig,
)


def test_tool_decorator_marks_function():
    @tool(description="test tool")
    def my_fn(x: int) -> int:
        return x

    assert is_tool(my_fn)
    meta = get_tool_meta(my_fn)
    assert meta["name"] == "my_fn"
    assert meta["description"] == "test tool"


def test_tool_decorator_custom_name():
    @tool(description="custom", name="custom_name")
    def fn():
        pass

    assert get_tool_meta(fn)["name"] == "custom_name"


def test_is_tool_false_for_plain_function():
    def plain():
        pass

    assert not is_tool(plain)
    assert not is_tool(42)
    assert not is_tool("string")


def test_signature_to_json_schema_basic():
    def add(a: float, b: float) -> float:
        return a + b

    schema = signature_to_json_schema(add)
    assert schema["type"] == "object"
    assert "a" in schema["properties"]
    assert schema["properties"]["a"]["type"] == "number"
    assert schema["required"] == ["a", "b"]


def test_signature_to_json_schema_defaults():
    def greet(name: str, greeting: str = "hello"):
        pass

    schema = signature_to_json_schema(greet)
    assert schema["required"] == ["name"]
    assert schema["properties"]["greeting"]["default"] == "hello"


def test_signature_to_json_schema_no_hints():
    def no_hints(x):
        pass

    schema = signature_to_json_schema(no_hints)
    assert schema["properties"]["x"]["type"] == "string"  # default


def test_server_config_defaults():
    sc = ServerConfig()
    assert sc.command == ""
    assert sc.args == []
    assert sc.env is None
    assert sc.enabled is True
    assert sc.lazy is True


def test_gateway_config_defaults():
    gc = GatewayConfig()
    assert gc.servers == {}
    assert gc.plugins == []
    assert gc.idle_timeout == 300
    assert gc.roles == {}
    assert gc.registry is None
