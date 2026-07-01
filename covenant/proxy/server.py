"""The transparent MCP reverse-proxy that enforces quarantine.

Forwards every JSON-RPC exchange to the upstream MCP server byte-for-byte (SSE
passed through unbuffered), but short-circuits a ``tools/call`` to a quarantined
tool with a clean MCP ``isError`` result — so the agent fails safe instead of
receiving a silently-wrong response. Detection reuses Layer 0 and runs on the
Covenant-owned ``POST /covenant/refresh`` path (reliable, client-independent) and
best-effort in-band on JSON ``tools/list`` responses.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from .._types import JsonDict
from .detect import detect
from .quarantine import Quarantine

Lister = Callable[[], Awaitable[list[JsonDict]]]

_HOP = {
    "host", "content-length", "connection", "keep-alive",
    "transfer-encoding", "upgrade", "proxy-connection",
}


def _error_result(rpc_id: object, text: str) -> JsonDict:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": True},
    }


def _req_headers(headers: Any) -> dict[str, str]:
    fwd = {k: v for k, v in headers.items() if k.lower() not in _HOP}
    fwd["accept-encoding"] = "identity"  # never let upstream compress; we inspect bodies
    return fwd


def _resp_headers(headers: httpx.Headers) -> dict[str, str]:
    drop = _HOP | {"content-encoding", "content-length"}
    return {k: v for k, v in headers.items() if k.lower() not in drop}


async def _list_upstream(app: FastAPI) -> list[JsonDict]:
    lister: Lister | None = app.state.lister
    if lister is not None:
        return await lister()
    # Default: Covenant connects to the upstream itself and lists tools.
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with (
        streamablehttp_client(app.state.upstream) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
                "outputSchema": getattr(t, "outputSchema", None),
            }
            for t in result.tools
        ]


async def _proxy(app: FastAPI, request: Request) -> Response:
    q: Quarantine = app.state.q
    body = await request.body()

    rpc = None
    if body:
        try:
            rpc = json.loads(body)
        except json.JSONDecodeError:
            rpc = None
    method = rpc.get("method") if isinstance(rpc, dict) else None
    rpc_id = rpc.get("id") if isinstance(rpc, dict) else None
    params = rpc.get("params") if isinstance(rpc, dict) else None
    tool = params.get("name") if isinstance(params, dict) else None

    # Quarantine enforcement: block a call to a flagged tool, never forward it.
    if method == "tools/call" and isinstance(tool, str) and q.is_quarantined(tool):
        blocked = _error_result(
            rpc_id,
            f"tool unavailable - '{tool}' quarantined by Covenant "
            f"(contract drift: {q.reason(tool)})",
        )
        return Response(content=json.dumps(blocked), media_type="application/json")

    # Forward upstream, transparently.
    client: httpx.AsyncClient = app.state.http
    up_req = client.build_request(
        request.method, app.state.upstream, headers=_req_headers(request.headers), content=body
    )
    up_resp = await client.send(up_req, stream=True)
    ctype = up_resp.headers.get("content-type", "")
    resp_headers = _resp_headers(up_resp.headers)

    if "text/event-stream" in ctype:
        async def _passthrough() -> AsyncIterator[bytes]:
            async for chunk in up_resp.aiter_raw():
                yield chunk
            await up_resp.aclose()

        return StreamingResponse(
            _passthrough(), status_code=up_resp.status_code,
            headers=resp_headers, media_type=ctype,
        )

    raw = await up_resp.aread()
    await up_resp.aclose()

    # Best-effort in-band detection on JSON tools/list responses.
    if method == "tools/list":
        try:
            rj = json.loads(raw)
        except json.JSONDecodeError:
            rj = None
        if isinstance(rj, dict):
            tools = ((rj.get("result") or {}).get("tools")) or []
            q.sync(detect(app.state.baseline, tools))

    return Response(
        content=raw, status_code=up_resp.status_code,
        headers=resp_headers, media_type=ctype or "application/json",
    )


def create_app(
    upstream_url: str,
    baseline_tools: list[JsonDict],
    *,
    quarantine: Quarantine | None = None,
    http_client: httpx.AsyncClient | None = None,
    lister: Lister | None = None,
) -> FastAPI:
    app = FastAPI(title="Covenant proxy", description="MCP contract-and-drift firewall")
    app.state.upstream = upstream_url
    app.state.baseline = baseline_tools
    app.state.q = quarantine or Quarantine()
    app.state.http = http_client or httpx.AsyncClient(timeout=30.0)
    app.state.lister = lister

    @app.get("/covenant/status")
    async def status() -> JsonDict:
        return {"quarantined": app.state.q.all(), "upstream": upstream_url}

    @app.post("/covenant/refresh")
    async def refresh() -> JsonDict:
        tools = await _list_upstream(app)
        app.state.q.sync(detect(app.state.baseline, tools))
        return {"quarantined": app.state.q.all(), "checked": len(tools)}

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
    async def mcp(request: Request) -> Response:
        return await _proxy(app, request)

    return app
