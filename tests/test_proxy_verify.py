"""Per-call response verification at the proxy: JSON and SSE paths, both modes.

Same harness as test_proxy: FastAPI TestClient over an httpx.MockTransport upstream.
"""

import json

import httpx
from fastapi.testclient import TestClient

from covenant.proxy.server import create_app


def tool(name, out=None):
    return {"name": name, "description": "d", "inputSchema": None, "outputSchema": out}


def obj(props, required=None):
    schema = {"type": "object", "properties": props}
    if required is not None:
        schema["required"] = required
    return schema


BASE = [tool("get_account", out=obj({"balance_usd": {"type": "number"}},
                                    required=["balance_usd"]))]


def rpc_call(name, rpc_id=1, arguments=None):
    return {"jsonrpc": "2.0", "id": rpc_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


def json_result(payload, rpc_id=1):
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {"structuredContent": payload}}


def upstream_json(payload):
    def handler(request):
        return httpx.Response(200, json=json_result(payload),
                              headers={"content-type": "application/json"})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def make_app(client, observe=False, base=None, probes=None):
    return create_app("http://up/mcp", base or BASE, http_client=client,
                      baseline_probes=probes, observe=observe)


def test_clean_response_forwards():
    app = make_app(upstream_json({"balance_usd": 42.0}))
    r = TestClient(app).post("/mcp", json=rpc_call("get_account"))
    assert r.json()["result"]["structuredContent"] == {"balance_usd": 42.0}


def test_violating_response_is_blocked_and_quarantines():
    app = make_app(upstream_json({"available_balance": 42.0}))  # reference field gone
    client = TestClient(app)
    body = client.post("/mcp", json=rpc_call("get_account")).json()
    assert body["result"]["isError"] is True
    assert "quarantined by Covenant" in body["result"]["content"][0]["text"]

    status = client.get("/covenant/status").json()
    assert status["sources"]["get_account"] == "response"

    # the next call hits the quarantine gate without reaching the upstream
    body2 = client.post("/mcp", json=rpc_call("get_account")).json()
    assert body2["result"]["isError"] is True
    assert "tool unavailable" in body2["result"]["content"][0]["text"]


def test_observe_mode_records_but_forwards():
    app = make_app(upstream_json({"available_balance": 42.0}), observe=True)
    client = TestClient(app)
    body = client.post("/mcp", json=rpc_call("get_account")).json()
    assert body["result"]["structuredContent"] == {"available_balance": 42.0}
    assert client.get("/covenant/status").json()["quarantined"] == {}


def test_scalar_retype_is_degraded_and_forwards():
    app = make_app(upstream_json({"balance_usd": "42.00"}))
    body = TestClient(app).post("/mcp", json=rpc_call("get_account")).json()
    assert body["result"]["structuredContent"] == {"balance_usd": "42.00"}


def test_upstream_error_skips_verification():
    def handler(request):
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "boom"}], "isError": True}},
            headers={"content-type": "application/json"})
    app = make_app(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    body = TestClient(app).post("/mcp", json=rpc_call("get_account")).json()
    assert body["result"]["isError"] is True
    assert "boom" in body["result"]["content"][0]["text"]


def test_unverifiable_tool_forwards_untouched():
    base = [tool("free_tool")]  # no outputSchema, no probes
    app = make_app(upstream_json({"anything": 1}), base=base)
    body = TestClient(app).post("/mcp", json=rpc_call("free_tool")).json()
    assert body["result"]["structuredContent"] == {"anything": 1}


def test_pin_mismatch_blocks():
    base = [tool("get_rate")]
    probes = [{"tool": "get_rate", "args": {"pair": "USDILS"},
               "fingerprint": obj({"rate": {"type": "number"}}),
               "sample": {"rate": 3.7}, "expect": {"rate": 3.7}}]
    app = make_app(upstream_json({"rate": 370}), base=base, probes=probes)
    body = TestClient(app).post(
        "/mcp", json=rpc_call("get_rate", arguments={"pair": "USDILS"})).json()
    assert body["result"]["isError"] is True
    assert "quarantined by Covenant" in body["result"]["content"][0]["text"]


def test_refresh_releases_the_response_bucket():
    async def lister():
        return BASE  # schema is clean; only the response lied

    app = create_app("http://up/mcp", BASE, lister=lister,
                     http_client=upstream_json({"available_balance": 1.0}))
    client = TestClient(app)
    client.post("/mcp", json=rpc_call("get_account"))
    assert client.get("/covenant/status").json()["quarantined"]

    refreshed = client.post("/covenant/refresh").json()
    assert refreshed["quarantined"] == {}


# --- SSE --------------------------------------------------------------------

class _Chunks(httpx.AsyncByteStream):
    """A real async stream — Response(content=...) marks itself consumed and
    aiter_raw() would raise StreamConsumed."""

    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


def sse_stream(*frames):
    def handler(request):
        return httpx.Response(200, stream=_Chunks(list(frames)),
                              headers={"content-type": "text/event-stream"})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def frame(payload):
    return b"event: message\r\ndata: " + json.dumps(payload).encode() + b"\r\n\r\n"


NOTIFICATION = frame({"jsonrpc": "2.0", "method": "notifications/progress",
                      "params": {"progress": 1}})


def test_sse_violating_result_frame_is_replaced():
    frames = sse_stream(NOTIFICATION, frame(json_result({"available_balance": 1.0})))
    app = make_app(frames)
    r = TestClient(app).post("/mcp", json=rpc_call("get_account"))
    text = r.text
    assert "notifications/progress" in text  # notifications stream through
    assert "available_balance" not in text  # the lie never reaches the client
    assert "quarantined by Covenant" in text
    assert text.count("event: message") == 2  # same event shape


def test_sse_clean_result_forwards_and_notifications_pass():
    frames = sse_stream(NOTIFICATION, frame(json_result({"balance_usd": 42.0})))
    app = make_app(frames)
    r = TestClient(app).post("/mcp", json=rpc_call("get_account"))
    assert "balance_usd" in r.text
    assert app.state.q.all() == {}


def test_sse_get_listen_stream_is_never_parsed():
    frames = sse_stream(b"data: not-json\r\n\r\n")
    app = make_app(frames)
    r = TestClient(app).get("/mcp")
    assert r.text == "data: not-json\r\n\r\n"


def test_sse_oversized_frame_forwards_unverified():
    big = json_result({"available_balance": 1.0, "pad": "x" * (2 << 20)})
    frames = sse_stream(frame(big))
    app = make_app(frames)
    r = TestClient(app).post("/mcp", json=rpc_call("get_account"))
    assert "available_balance" in r.text  # forwarded, not blocked
    assert app.state.q.all() == {}
