"""MCP servers are launched with the parent's full environment."""

from __future__ import annotations

import pytest

from agents import _base


def test_server_subprocess_inherits_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("LLM_RATE_LIMITER_DB", "/app/var/ledger.db")
    params = _base.server_params("mcp_servers/research_mcp/server.py")
    assert params.env["TAVILY_API_KEY"] == "test-key"
    assert params.env["LLM_RATE_LIMITER_DB"] == "/app/var/ledger.db"
