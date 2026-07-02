"""A real local MCP server (FastMCP over stdio) for Covenant to introspect.

`get_account` is the demo DRIFT LEVER. Normally its output carries `balance_usd`.
With COVENANT_DRIFT=1 that field is renamed to `available_balance` — an
output-field-removed = BREAKING contract change. So:

    covenant snapshot                       # baseline the clean contract
    COVENANT_DRIFT=1 covenant check         # Covenant catches the breaking diff

reproduces a real breaking change end-to-end, nothing simulated.
"""

import os

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

# json_response + stateless keep HTTP responses as single JSON bodies (no SSE), so
# the proxy path is deterministic; these are ignored under stdio (Layer 0).
mcp = FastMCP(
    "covenant-example-bank",
    host="127.0.0.1",
    port=int(os.environ.get("PORT", "8000")),
    json_response=True,
    stateless_http=True,
)

DRIFT = os.environ.get("COVENANT_DRIFT") == "1"

_ACCOUNTS = {
    "acct-001": ("Ada Lovelace", 4210.00, "USD"),
    "acct-002": ("Alan Turing", 15999.42, "USD"),
}


if DRIFT:
    class Account(BaseModel):
        account_id: str
        holder: str
        available_balance: float  # drifted: renamed from balance_usd
        currency: str
else:
    class Account(BaseModel):
        account_id: str
        holder: str
        balance_usd: float
        currency: str


@mcp.tool()
def get_account(account_id: str) -> Account:
    """Look up a bank account and its current balance."""
    holder, balance, currency = _ACCOUNTS.get(account_id, ("Unknown", 0.0, "USD"))
    fields = {"account_id": account_id, "holder": holder, "currency": currency}
    fields["available_balance" if DRIFT else "balance_usd"] = balance
    return Account(**fields)


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
    if os.environ.get("COVENANT_HTTP") == "1":
        mcp.run(transport="streamable-http")  # for the Layer 1 proxy demo
    else:
        mcp.run()  # stdio, the Layer 0 default
