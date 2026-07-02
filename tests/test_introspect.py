"""Integration test: introspect the real example MCP server over stdio."""

import sys

from covenant.config import Config
from covenant.introspect import introspect


def _example_config():
    cmd = f'"{sys.executable}" examples/mcp_server.py'
    return Config(server_command=cmd, server_url=None, baseline_path="covenant.lock.json")


def test_introspect_lists_example_tools():
    tools = introspect(_example_config())
    names = {t["name"] for t in tools}
    assert {"get_account", "get_weather", "convert_currency"} <= names


def test_get_account_output_schema_has_balance_usd():
    tools = introspect(_example_config())
    acct = next(t for t in tools if t["name"] == "get_account")
    assert acct["outputSchema"] is not None
    assert "balance_usd" in acct["outputSchema"]["properties"]
