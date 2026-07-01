"""Transparent MCP reverse proxy.

Warden forwards every JSON-RPC exchange between the client and the upstream MCP
server byte-for-byte, while observing it: it captures a contract snapshot on every
tools/list and logs every tools/call. Quarantine enforcement short-circuits calls
to tools Warden has flagged (the status is set by drift detection, Hour 3).
"""

import json
import time

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from . import capture, db

router = APIRouter()

_HOP_BY_HOP = {
    "host", "content-length", "connection", "keep-alive",
    "transfer-encoding", "upgrade", "proxy-connection",
}


def _request_headers(headers) -> dict:
    fwd = {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}
    fwd["accept-encoding"] = "identity"  # never let upstream compress; we inspect the body
    return fwd


def _response_headers(headers) -> dict:
    drop = _HOP_BY_HOP | {"content-encoding", "content-length"}
    return {k: v for k, v in headers.items() if k.lower() not in drop}


def _quarantine_result(rpc_id, tool_name: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "content": [{
                "type": "text",
                "text": f"tool unavailable — '{tool_name}' quarantined by Warden (contract drift)",
            }],
            "isError": True,
        },
    }


@router.api_route("/mcp", methods=["GET", "POST", "DELETE"])
async def mcp_proxy(request: Request):
    app = request.app
    client: httpx.AsyncClient = app.state.http
    pool = app.state.pool
    upstream = app.state.upstream_url

    body = await request.body()
    rpc = None
    if body:
        try:
            rpc = json.loads(body)
        except Exception:
            rpc = None

    rpc_method = rpc.get("method") if isinstance(rpc, dict) else None
    rpc_id = rpc.get("id") if isinstance(rpc, dict) else None
    params = rpc.get("params") if isinstance(rpc, dict) else None
    tool_name = params.get("name") if isinstance(params, dict) else None

    # --- Quarantine enforcement: block calls to flagged tools, never forward ---
    if rpc_method == "tools/call":
        if await db.get_status(pool, tool_name) == "quarantined":
            blocked = _quarantine_result(rpc_id, tool_name)
            await db.log_call(pool, tool_name, rpc_method, rpc, blocked, 0, True, True)
            return Response(content=json.dumps(blocked), media_type="application/json")

    # --- Forward upstream, transparently ---
    t0 = time.perf_counter()
    upstream_req = client.build_request(
        request.method, upstream,
        headers=_request_headers(request.headers),
        content=body,
        params=request.query_params,
    )
    upstream_resp = await client.send(upstream_req, stream=True)
    ctype = upstream_resp.headers.get("content-type", "")
    resp_headers = _response_headers(upstream_resp.headers)

    # SSE / streaming responses: pass through without buffering.
    if "text/event-stream" in ctype:
        async def _passthrough():
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
            await upstream_resp.aclose()

        return StreamingResponse(
            _passthrough(), status_code=upstream_resp.status_code,
            headers=resp_headers, media_type=ctype,
        )

    # Buffered JSON response: observe, then return unchanged.
    raw = await upstream_resp.aread()
    await upstream_resp.aclose()
    latency_ms = int((time.perf_counter() - t0) * 1000)

    resp_json = None
    try:
        resp_json = json.loads(raw)
    except Exception:
        resp_json = None

    if rpc_method == "tools/list" and isinstance(resp_json, dict):
        tools = ((resp_json.get("result") or {}).get("tools")) or []
        norm = [capture.normalize_tool(t) for t in tools]
        await capture.capture_tools(pool, norm)
        await app.state.detect(pool, norm)  # drift detection + quarantine (Hour 3)

    if rpc_method == "tools/call":
        result = resp_json.get("result") if isinstance(resp_json, dict) else None
        is_error = bool(
            isinstance(resp_json, dict)
            and (resp_json.get("error") or (isinstance(result, dict) and result.get("isError")))
        )
        await db.log_call(pool, tool_name, rpc_method, rpc, resp_json, latency_ms, is_error, False)

    return Response(
        content=raw, status_code=upstream_resp.status_code,
        headers=resp_headers, media_type=ctype or "application/json",
    )
