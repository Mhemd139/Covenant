"""The downstream 'agent': a real MCP client that reads and reports an account balance.

Deterministic (no LLM), so the demo never touches the public network. It calls
get_account and reports the balance with ONE code path:

    balance = float(data.get("balance_usd") or 0.0)

That single line is the whole point. After the tool renames `balance_usd`, this
naive-but-typical defensive code silently reads 0.0 and confidently reports the
WRONG number — a silent lie about money. Point the agent at Warden instead and the
call is quarantined, so the agent aborts and never lies.

    WARDEN_MCP_URL=http://warden:8080/mcp   python demo/agent_task.py   # guarded
    WARDEN_MCP_URL=http://test-mcp:8000/mcp python demo/agent_task.py   # unguarded
"""

import os

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TARGET = os.environ.get("WARDEN_MCP_URL", "http://warden:8080/mcp")
ACCOUNT = "acct-001"


async def main() -> None:
    guarded = ":8080" in TARGET
    print(f"[agent] task: report the balance for {ACCOUNT}")
    print(f"[agent] via {'Warden (guarded)' if guarded else 'the MCP server directly (unguarded)'}")

    async with streamablehttp_client(TARGET) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("get_account", {"account_id": ACCOUNT})

            if res.isError:
                text = res.content[0].text if res.content else "tool error"
                print(f"[agent] ABORTED — {text}")
                print("[agent] refusing to report a balance from a broken contract. Failing safe. ✅")
                return

            data = res.structuredContent or {}
            balance = float(data.get("balance_usd") or 0.0)  # the silent-lie line
            print(f"[agent] Your balance is ${balance:,.2f}")
            if "balance_usd" not in data:
                print("[agent] ⚠️  (that number is a LIE — balance_usd was gone and nothing stopped me)")


if __name__ == "__main__":
    anyio.run(main)
