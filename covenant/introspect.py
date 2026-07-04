"""Connect to an MCP server — list its tools, and call Layer 3 probes.

Supports stdio (a ``command`` launched as a subprocess) and streamable-HTTP (a
``url``). Tools come back in MCP wire shape (``name``/``description``/``inputSchema``/
``outputSchema``) so the differ and the contract model consume them directly. Probe
calls resolve to comparable JSON: ``structuredContent`` when the server provides it,
else the first text block (parsed as JSON when possible).
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from ._types import JsonDict
from .config import Config, Probe
from .errors import ConnectionError, CovenantError


def _split_command(command: str) -> list[str]:
    if os.name == "nt":
        return [p.strip('"') for p in shlex.split(command, posix=False)]
    return shlex.split(command)


@asynccontextmanager
async def _session(config: Config) -> AsyncIterator[ClientSession]:
    """One initialized client session over whichever transport is configured."""
    if config.server_url:
        async with (
            streamablehttp_client(config.server_url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
        return
    parts = _split_command(config.server_command or "")
    # Inherit the full environment: a linter must launch the user's server the way
    # they run it (the SDK default is a minimal safe env that would hide config vars).
    params = StdioServerParameters(command=parts[0], args=parts[1:], env=dict(os.environ))
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _tool_to_dict(tool: Any) -> JsonDict:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.inputSchema,
        "outputSchema": getattr(tool, "outputSchema", None),
    }


def _resolve_result(result: Any) -> tuple[object, bool, str | None]:
    """Resolve a CallToolResult to ``(response, is_error, error_text)``."""
    content = result.content or []
    if result.isError:
        texts = [b.text for b in content if hasattr(b, "text")]
        return None, True, "; ".join(texts) or "tool returned an error"
    if result.structuredContent is not None:
        return result.structuredContent, False, None
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                return json.loads(text), False, None
            except json.JSONDecodeError:
                return text, False, None
    return None, False, None


async def introspect_async(config: Config) -> list[JsonDict]:
    """List the server's tools in MCP wire shape (async; the proxy reuses this)."""
    async with _session(config) as session:
        result = await session.list_tools()
        return [_tool_to_dict(t) for t in result.tools]


async def _run_probes(config: Config, probes: list[Probe]) -> list[JsonDict]:
    records: list[JsonDict] = []
    async with _session(config) as session:
        for probe in probes:
            try:
                result = await session.call_tool(probe.tool, probe.args)
            except Exception as e:  # noqa: BLE001 - name the probe so a config typo isn't a "connection" error
                raise CovenantError(f"probe {probe.tool} failed: {e}") from e
            response, is_error, error = _resolve_result(result)
            records.append({
                "tool": probe.tool,
                "args": probe.args,
                "response": response,
                "is_error": is_error,
                "error": error,
            })
    return records


def introspect(config: Config) -> list[JsonDict]:
    """Introspect the configured server; return wire-shape tool dicts."""
    try:
        return asyncio.run(introspect_async(config))
    except CovenantError:
        raise
    except Exception as e:  # noqa: BLE001 - surface any transport failure as one clean error
        target = config.server_url or config.server_command
        raise ConnectionError(f"could not introspect MCP server ({target}): {e}") from e


def run_probes(config: Config, probes: list[Probe]) -> list[JsonDict]:
    """Call each probe against the live server; return resolved response records."""
    try:
        return asyncio.run(_run_probes(config, probes))
    except CovenantError:
        raise
    except Exception as e:  # noqa: BLE001 - surface any transport failure as one clean error
        target = config.server_url or config.server_command
        raise ConnectionError(f"could not probe MCP server ({target}): {e}") from e
