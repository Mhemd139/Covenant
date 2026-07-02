"""Layer 4 metrics: counters, latency, quarantine gauge, and the exposition endpoint."""

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


def ok_handler(request):
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "x"}]}},
        headers={"content-type": "application/json"},
    )


def test_forwarded_call_counts_ok_and_observes_latency():
    app = create_app("http://up/mcp", BASE, http_client=mock_client(ok_handler))
    client = TestClient(app)
    client.post("/mcp", json=rpc_call("get_account"))
    text = client.get("/covenant/metrics").text
    assert 'covenant_calls_total{outcome="ok",tool="get_account"} 1.0' in text
    assert 'covenant_call_latency_seconds_count{tool="get_account"} 1.0' in text


def test_blocked_call_counts_blocked():
    q = Quarantine()
    q.mark("get_account", "drift")
    app = create_app("http://up/mcp", BASE, quarantine=q, http_client=mock_client(ok_handler))
    client = TestClient(app)
    client.post("/mcp", json=rpc_call("get_account"))
    text = client.get("/covenant/metrics").text
    assert 'covenant_calls_total{outcome="blocked",tool="get_account"} 1.0' in text


def test_error_response_counts_error():
    def err_handler(request):
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1,
                  "result": {"content": [{"type": "text", "text": "boom"}], "isError": True}},
            headers={"content-type": "application/json"},
        )

    app = create_app("http://up/mcp", BASE, http_client=mock_client(err_handler))
    client = TestClient(app)
    client.post("/mcp", json=rpc_call("get_account"))
    text = client.get("/covenant/metrics").text
    assert 'covenant_calls_total{outcome="error",tool="get_account"} 1.0' in text


def test_refresh_drift_sets_gauge_and_counts_drift():
    drifted = [tool("get_account", out=obj({"renamed": {"type": "number"}}))]

    async def lister():
        return drifted

    app = create_app("http://up/mcp", BASE, http_client=mock_client(ok_handler), lister=lister)
    client = TestClient(app)
    client.post("/covenant/refresh")
    text = client.get("/covenant/metrics").text
    assert "covenant_quarantined_tools 1.0" in text
    assert 'covenant_drift_total{severity="breaking"} 1.0' in text


def test_two_apps_do_not_share_a_registry():
    a = create_app("http://up/mcp", BASE, http_client=mock_client(ok_handler))
    b = create_app("http://up/mcp", BASE, http_client=mock_client(ok_handler))
    TestClient(a).post("/mcp", json=rpc_call("get_account"))
    text_b = TestClient(b).get("/covenant/metrics").text
    assert "covenant_calls_total{" not in text_b  # b never saw a call
