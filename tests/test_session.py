"""Tests for session.py — ExternalMCPSession dataclass and helpers."""
from __future__ import annotations

from mcp_gateway.session import ExternalMCPSession


def test_session_defaults():
    es = ExternalMCPSession(name="test")
    assert es.name == "test"
    assert es.session is None
    assert es.exit_stack is None
    assert es.tools == []
    assert es.tool_names == set()
    assert es.last_used == 0.0
    assert es.connected is False


def test_session_fields():
    es = ExternalMCPSession(
        name="github",
        connected=True,
        last_used=1000.0,
    )
    assert es.connected is True
    assert es.last_used == 1000.0
