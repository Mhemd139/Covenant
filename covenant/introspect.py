"""Connect to an MCP server and list its tools — transport-agnostic.

Supports stdio (a ``command`` launched as a subprocess) and streamable-HTTP (a
``url``). Returns tools in MCP wire shape (``name``/``description``/``inputSchema``/
``outputSchema``) so the differ and the contract model consume them directly.
"""

from __future__ import annotations

import asyncio
import os
import shlex
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from ._types import JsonDict
from .config import Config
from .errors import ConnectionError, CovenantError


def _split_command(command: str) -> list[str]:
    if os.name == "nt":
        return [p.strip('"') for p in shlex.split(command, posix=False)]
    return shlex.split(command)


def _tool_to_dict(tool: Any) -> JsonDict:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.inputSchema,
        "outputSchema": getattr(tool, "outputSchema", None),
    }


async def _list_tools(session: ClientSession) -> list[JsonDict]:
    await session.initialize()
    result = await session.list_tools()
    return [_tool_to_dict(t) for t in result.tools]


async def _introspect_stdio(command: str) -> list[JsonDict]:
    parts = _split_command(command)
    # Inherit the full environment: a linter must launch the user's server the way
    # they run it (the SDK default is a minimal safe env that would hide config vars).
    params = StdioServerParameters(command=parts[0], args=parts[1:], env=dict(os.environ))
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        return await _list_tools(session)


async def _introspect_http(url: str) -> list[JsonDict]:
    async with (
        streamablehttp_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        return await _list_tools(session)


async def _introspect(config: Config) -> list[JsonDict]:
    if config.server_url:
        return await _introspect_http(config.server_url)
    return await _introspect_stdio(config.server_command or "")


def introspect(config: Config) -> list[JsonDict]:
    """Introspect the configured server; return wire-shape tool dicts."""
    try:
        return asyncio.run(_introspect(config))
    except CovenantError:
        raise
    except Exception as e:  # noqa: BLE001 - surface any transport failure as one clean error
        target = config.server_url or config.server_command
        raise ConnectionError(f"could not introspect MCP server ({target}): {e}") from e
