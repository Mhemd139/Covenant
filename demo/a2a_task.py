"""Kick off an A2A-style recursive delegation chain through Warden.

Calls delegate(0); the tool recurses one level deeper per hop THROUGH Warden.
Warden's depth breaker trips past the limit and quarantines the tool, so the
runaway loop is cut instead of melting the fleet.
"""

import os

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TARGET = os.environ.get("WARDEN_MCP_URL", "http://warden:8080/mcp")


async def main() -> None:
    print("[a2a] starting recursive delegation via Warden (depth 0)...")
    async with streamablehttp_client(TARGET, headers={"X-Covenant-Depth": "0"}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("delegate", {"depth": 0})
            data = res.structuredContent or {}
            print(f"[a2a] top-level returned: {data}")
            print("[a2a] Warden cut the recursion — see the dashboard: delegate is QUARANTINED.")


if __name__ == "__main__":
    anyio.run(main)
