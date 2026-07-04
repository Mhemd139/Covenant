"""Proxy behaviour, driven through FastAPI TestClient against a mocked upstream.

No real MCP server here — httpx.MockTransport stands in for the upstream so we can
assert forwarding, quarantine short-circuiting, refresh, and status precisely.
"""

import json

import httpx
from fastapi.testclient import TestClient

from covenant.proxy.quarantine import Quarantine
from covenant.proxy.server import create_app


def tool(name, out=None, inp=None, description="d"):
    return {"name": name, "description": description, "inputSchema": inp, "outputSchema": out}


def obj(props):
    return {"type": "object", "properties": props}


BASE = [tool("get_account", out=obj({"balance_usd": {"type": "number"}}))]


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def rpc_call(name, rpc_id=1):
    return {"jsonrpc": "2.0", "id": rpc_id, "method": "tools/call",
            "params": {"name": name, "arguments": {}}}


def test_healthy_call_is_forwarded_unchanged():
    seen = {"hit": False}

    def handler(request):
        seen["hit"] = True
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1,
                  "result": {"content": [{"type": "text", "text": "$4210.00"}]}},
            headers={"content-type": "application/json"},
        )

    app = create_app("http://up/mcp", BASE, http_client=mock_client(handler))
    r = TestClient(app).post("/mcp", json=rpc_call("get_account"))
    assert r.status_code == 200
    assert seen["hit"]
    assert "4210.00" in r.text


def test_quarantined_call_is_blocked_and_never_forwarded():
    q = Quarantine()
    q.mark("get_account", "output field 'balance_usd' removed")
    hits = {"n": 0}

    def handler(request):
        hits["n"] += 1
        return httpx.Response(200, json={}, headers={"content-type": "application/json"})

    app = create_app("http://up/mcp", BASE, quarantine=q, http_client=mock_client(handler))
    r = TestClient(app).post("/mcp", json=rpc_call("get_account"))
    body = r.json()
    assert body["result"]["isError"] is True
    assert "quarantined" in body["result"]["content"][0]["text"].lower()
    assert hits["n"] == 0  # upstream never touched


def test_status_reports_quarantine():
    q = Quarantine()
    q.mark("get_account", "reason x")
    app = create_app("http://up/mcp", BASE, quarantine=q,
                     http_client=mock_client(lambda req: httpx.Response(200)))
    data = TestClient(app).get("/covenant/status").json()
    assert data["quarantined"]["get_account"] == "reason x"


def test_refresh_detects_drift_then_call_is_blocked():
    drifted = [tool("get_account", out=obj({"available_balance": {"type": "number"}}))]

    async def lister():
        return drifted

    app = create_app("http://up/mcp", BASE, lister=lister,
                     http_client=mock_client(lambda req: httpx.Response(200)))
    client = TestClient(app)

    refreshed = client.post("/covenant/refresh").json()
    assert "get_account" in refreshed["quarantined"]

    blocked = client.post("/mcp", json=rpc_call("get_account")).json()
    assert blocked["result"]["isError"] is True


def test_refresh_releases_a_restored_tool():
    calls = {"n": 0}

    async def lister():
        calls["n"] += 1
        # first refresh: drifted; second refresh: restored
        if calls["n"] == 1:
            return [tool("get_account", out=obj({"available_balance": {"type": "number"}}))]
        return [tool("get_account", out=obj({"balance_usd": {"type": "number"}}))]

    app = create_app("http://up/mcp", BASE, lister=lister,
                     http_client=mock_client(lambda req: httpx.Response(200)))
    client = TestClient(app)

    assert client.post("/covenant/refresh").json()["quarantined"]
    assert client.post("/covenant/refresh").json()["quarantined"] == {}


def lock_text(props):
    return json.dumps({
        "covenant_version": "0.1.0", "server": "http://up/mcp",
        "tools": {"get_account": {"description": "d", "inputSchema": None,
                                  "outputSchema": obj(props), "schema_hash": "sha256:x"}},
    })


def test_refresh_reloads_baseline_from_disk(tmp_path):
    # An intentional contract update: server changes AND the lock is re-snapshotted.
    # Refresh must diff against the lock on disk, not the copy parsed at startup —
    # otherwise the updated tool reads as drift and a healthy tool is quarantined.
    lock = tmp_path / "covenant.lock.json"
    lock.write_text(lock_text({"balance_usd": {"type": "number"}}), encoding="utf-8")

    async def lister():
        return [tool("get_account", out=obj({"balance_cents": {"type": "integer"}}))]

    app = create_app("http://up/mcp", BASE, lister=lister, baseline_path=str(lock),
                     http_client=mock_client(lambda req: httpx.Response(200)))
    client = TestClient(app)

    lock.write_text(lock_text({"balance_cents": {"type": "integer"}}), encoding="utf-8")
    assert client.post("/covenant/refresh").json()["quarantined"] == {}
