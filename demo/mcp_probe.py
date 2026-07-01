"""Tiny real MCP client used to verify a target speaks MCP over Streamable HTTP.

Usage: python demo/mcp_probe.py http://test-mcp:8000/mcp
Points at either the test server directly or at Warden (the proxy is transparent).
"""

import sys

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"=== tools/list ({len(tools.tools)} tools) ===")
            for t in tools.tools:
                out = getattr(t, "outputSchema", None)
                out_props = list((out or {}).get("properties", {}).keys())
                in_props = list((t.inputSchema or {}).get("properties", {}).keys())
                print(f"- {t.name}: input={in_props} output={out_props}")

            print("\n=== tools/call get_account(acct-001) ===")
            res = await session.call_tool("get_account", {"account_id": "acct-001"})
            print("structured:", res.structuredContent)
            print("isError:", res.isError)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp"
    anyio.run(main, target)
