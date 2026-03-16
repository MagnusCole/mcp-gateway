"""Tests for registry.py — SQLite server registry."""
from __future__ import annotations

import tempfile
from pathlib import Path

from mcp_gateway.registry import Registry
from mcp_gateway._types import ServerConfig


def test_registry_create_and_list():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        reg = Registry(db)

        reg.upsert("fs", ServerConfig(command="npx", args=["-y", "server-fs"]))
        reg.upsert("gh", ServerConfig(command="npx", args=["-y", "server-gh"], enabled=False))

        servers = reg.list_servers()
        assert len(servers) == 2
        names = {s["name"] for s in servers}
        assert names == {"fs", "gh"}


def test_registry_activate_deactivate():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        reg = Registry(db)

        reg.upsert("myserver", ServerConfig(command="echo"))
        reg.deactivate("myserver")

        cfg = reg.get_config("myserver")
        assert cfg is not None
        assert cfg.enabled is False

        reg.activate("myserver")
        cfg = reg.get_config("myserver")
        assert cfg.enabled is True


def test_registry_get_config_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        reg = Registry(db)
        assert reg.get_config("nonexistent") is None


def test_registry_upsert_updates():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        reg = Registry(db)

        reg.upsert("s", ServerConfig(command="echo", args=["v1"]))
        reg.upsert("s", ServerConfig(command="echo", args=["v2"]))

        servers = reg.list_servers()
        assert len(servers) == 1

        cfg = reg.get_config("s")
        assert cfg.args == ["v2"]


def test_registry_save_tools():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        reg = Registry(db)

        reg.upsert("s", ServerConfig(command="echo"))
        reg.save_tools("s", '["tool1", "tool2"]')

        servers = reg.list_servers()
        assert servers[0]["tools_json"] == '["tool1", "tool2"]'
