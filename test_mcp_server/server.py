"""A real local MCP server (FastMCP over Streamable HTTP) that Warden guards.

It exposes three real tools. `get_account` is the demo DRIFT LEVER: its output
field `balance_usd` is what the downstream agent reads and reports. Renaming that
field (see demo/drift_patch.md) is a BREAKING contract change â€” without Warden the
agent would read a missing field and confabulate a balance.
"""

import os

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


class AccountInfo(BaseModel):
    account_id: str
    holder: str
    balance_usd: float  # DRIFT LEVER â€” demo renames this to `balance_usd`
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
        balance_usd=balance,  # DRIFT LEVER line
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


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
