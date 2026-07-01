"""A real local MCP server (FastMCP over Streamable HTTP) that Warden guards.

It exposes real tools. `get_account` is the demo DRIFT LEVER: the output field the
downstream agent reads and reports. Renaming it (see demo/drift_patch.md) is a
BREAKING contract change. `delegate` drives the optional A2A recursive-DoS demo.

Comments here are intentionally ASCII-only so the demo's string-replace scripts
cannot corrupt the file on repeated runs.
"""

import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

mcp = FastMCP(
    "test-bank",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    # json_response + stateless keeps responses as single JSON bodies (no SSE),
    # which makes the proxy path deterministic for the demo.
    json_response=True,
    stateless_http=True,
)

# Warden's own MCP endpoint, used by `delegate` to recurse through the proxy.
WARDEN_SELF_URL = os.environ.get("WARDEN_SELF_URL", "http://warden:8080/mcp")


class AccountInfo(BaseModel):
    account_id: str
    holder: str
    balance_usd: float  # the demo drift lever (renamed to break the contract)
    currency: str


_ACCOUNTS = {
    "acct-001": ("Ada Lovelace", 4210.00, "USD"),
    "acct-002": ("Alan Turing", 15999.42, "USD"),
}


@mcp.tool()
def get_account(account_id: str) -> AccountInfo:
    """Look up a bank account and its current balance."""
    holder, balance, currency = _ACCOUNTS.get(account_id, ("Unknown", 0.0, "USD"))
    return AccountInfo(
        account_id=account_id,
        holder=holder,
        balance_usd=balance,  # drift-lever line
        currency=currency,
    )


class Weather(BaseModel):
    city: str
    temp_c: float
    conditions: str


@mcp.tool()
def get_weather(city: str) -> Weather:
    """Return current weather for a city."""
    return Weather(city=city, temp_c=21.5, conditions="clear")


class Conversion(BaseModel):
    amount: float
    rate: float
    converted: float


@mcp.tool()
def convert_currency(amount: float, to_currency: str = "EUR") -> Conversion:
    """Convert a USD amount to another currency."""
    rate = 0.92
    return Conversion(amount=amount, rate=rate, converted=round(amount * rate, 2))


class DelegateResult(BaseModel):
    depth: int
    note: str


@mcp.tool()
async def delegate(depth: int = 0) -> DelegateResult:
    """A2A-style recursive delegation: call one level deeper THROUGH Warden.

    The tool itself has no stopping condition worth trusting; Warden's depth breaker
    is what halts the runaway. Each hop advertises its depth in X-Covenant-Depth.
    """
    if depth >= 25:  # absolute local safety net if the breaker were ever removed
        return DelegateResult(depth=depth, note="local safety net hit")

    child = depth + 1
    async with streamablehttp_client(
        WARDEN_SELF_URL, headers={"X-Covenant-Depth": str(child)}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("delegate", {"depth": child})
            if res.isError:
                text = res.content[0].text if res.content else "blocked"
                return DelegateResult(depth=depth, note=f"child blocked: {text}")
    return DelegateResult(depth=depth, note="chain returned")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
