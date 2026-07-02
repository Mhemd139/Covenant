"""The proxy records calls through its Store (default in-memory), via TestClient."""

import asyncio

import httpx
from fastapi.testclient import TestClient

from covenant.proxy.quarantine import Quarantine
from covenant.proxy.server import create_app
from covenant.store.memory import InMemoryStore


def tool(name, out=None):
    return {"name": name, "description": "d", "inputSchema": None, "outputSchema": out}


def obj(props):
    return {"type": "object", "properties": props}


BASE = [tool("get_account", obj({"balance_usd": {"type": "number"}}))]


def rpc_call(name):
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {}}}


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(req):
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": 1,
              "result": {"content": [{"type": "text", "text": "$4210"}]}},
        headers={"content-type": "application/json"},
    )


def test_healthy_call_is_recorded():
    store = InMemoryStore()
    app = create_app("http://up/mcp", BASE, http_client=mock_client(_ok), store=store)
    TestClient(app).post("/mcp", json=rpc_call("get_account"))
    calls = asyncio.run(store.recent_calls(10))
    assert len(calls) == 1
    assert calls[0]["tool"] == "get_account"
    assert calls[0]["blocked"] is False


def test_blocked_call_is_recorded_as_blocked_and_not_forwarded():
    q = Quarantine()
    q.mark("get_account", "output field 'balance_usd' removed")
    store = InMemoryStore()
    hits = {"n": 0}

    def handler(req):
        hits["n"] += 1
        return _ok(req)

    app = create_app("http://up/mcp", BASE, quarantine=q,
                     http_client=mock_client(handler), store=store)
    TestClient(app).post("/mcp", json=rpc_call("get_account"))
    calls = asyncio.run(store.recent_calls(10))
    assert calls[0]["blocked"] is True
    assert hits["n"] == 0


def test_calls_endpoint_returns_the_log():
    store = InMemoryStore()
    app = create_app("http://up/mcp", BASE, http_client=mock_client(_ok), store=store)
    client = TestClient(app)
    client.post("/mcp", json=rpc_call("get_account"))
    data = client.get("/covenant/calls").json()
    assert data["calls"][0]["tool"] == "get_account"
