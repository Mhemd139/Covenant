"""A real local MCP server (FastMCP over stdio) for Covenant to introspect.

`get_account` is the demo DRIFT LEVER. Normally its output carries `balance_usd`.
With COVENANT_DRIFT=1 that field is renamed to `available_balance` — an
output-field-removed = BREAKING contract change. So:

    covenant snapshot                       # baseline the clean contract
    COVENANT_DRIFT=1 covenant check         # Covenant catches the breaking diff

reproduces a real breaking change end-to-end, nothing simulated.

Layer 3 levers (declared schemas stay identical — only behavior changes):
COVENANT_BEHAVIOR_DRIFT=1 renames `amount_usd`->`amount_cents` inside
`get_transactions` response bodies (probe fingerprints catch it);
COVENANT_SEMANTIC_DRIFT=1 makes `get_account` return the balance in cents —
same schema, same shape, changed meaning (only the LLM judge sees it).
"""

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

# json_response + stateless keep HTTP responses as single JSON bodies (no SSE), so
# the proxy path is deterministic; these are ignored under stdio (Layer 0).
# COVENANT_ALLOWED_HOSTS extends the SDK's DNS-rebinding allowlist beyond localhost —
# needed when a cluster reaches this server via host.docker.internal (K8s demo).
_extra_hosts = [h for h in os.environ.get("COVENANT_ALLOWED_HOSTS", "").split(",") if h]
mcp = FastMCP(
    "covenant-example-bank",
    host="127.0.0.1",
    port=int(os.environ.get("PORT", "8000")),
    json_response=True,
    stateless_http=True,
    # always explicit: mcp 1.10.0 left protection OFF when settings were None
    transport_security=TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*", *_extra_hosts],
    ),
)

DRIFT = os.environ.get("COVENANT_DRIFT") == "1"
BEHAVIOR_DRIFT = os.environ.get("COVENANT_BEHAVIOR_DRIFT") == "1"
SEMANTIC_DRIFT = os.environ.get("COVENANT_SEMANTIC_DRIFT") == "1"

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
    if SEMANTIC_DRIFT:
        balance = balance * 100  # cents: schema and shape identical, meaning changed
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


_TRANSACTIONS = {
    "acct-001": [
        {"txn_id": "t-1001", "amount_usd": -42.5, "merchant": "Grocer & Co"},
        {"txn_id": "t-1002", "amount_usd": 1800.0, "merchant": "Payroll Inc"},
    ],
}


@mcp.tool()
def get_transactions(account_id: str) -> dict:
    """List recent transactions for an account."""
    txns = _TRANSACTIONS.get(account_id, [])
    if BEHAVIOR_DRIFT:  # the response body changes; the declared (loose) schema does not
        txns = [
            {"txn_id": t["txn_id"], "amount_cents": int(t["amount_usd"] * 100),
             "merchant": t["merchant"]}
            for t in txns
        ]
    return {"account_id": account_id, "transactions": txns}


if __name__ == "__main__":
    if os.environ.get("COVENANT_HTTP") == "1":
        mcp.run(transport="streamable-http")  # for the Layer 1 proxy demo
    else:
        mcp.run()  # stdio, the Layer 0 default
