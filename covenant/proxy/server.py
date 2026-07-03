"""The transparent MCP reverse-proxy that enforces quarantine.

Forwards every JSON-RPC exchange to the upstream MCP server byte-for-byte (SSE
passed through unbuffered), but short-circuits a ``tools/call`` to a quarantined
tool with a clean MCP ``isError`` result — so the agent fails safe instead of
receiving a silently-wrong response. Detection reuses Layer 0 and runs on the
Covenant-owned ``POST /covenant/refresh`` path (reliable, client-independent) and
best-effort in-band on JSON ``tools/list`` responses.

An optional Layer 2 ``Store`` persists quarantine, a call log, and drift events.
Recording is best-effort: a store error is logged, never raised into the request
path — a firewall must not drop traffic because its own telemetry hiccuped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .._types import JsonDict
from ..store.base import Store
from ..store.memory import InMemoryStore
from .detect import detect
from .metrics import Metrics
from .quarantine import Quarantine

log = logging.getLogger("covenant.proxy")

_STORE_WRITE_TIMEOUT = 2.0  # telemetry must never delay traffic
_UPSTREAM_LIST_TIMEOUT = 10.0  # bound the Covenant-owned re-list

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


async def _safe(coro: Awaitable[Any]) -> None:
    """Await a store write; log and swallow failures so recording never breaks proxying.

    Bounded by a timeout: a hung store call (Postgres under load) must not block the
    request path — a firewall must not stall traffic because its telemetry is slow.
    """
    try:
        await asyncio.wait_for(coro, timeout=_STORE_WRITE_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - telemetry must not fail the request path
        log.warning("covenant store write failed: %s", e)


async def _list_upstream(app: FastAPI) -> list[JsonDict]:
    lister: Lister | None = app.state.lister
    if lister is not None:
        return await lister()
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


def _label(app: FastAPI, tool: str) -> str:
    """Metric label for a tool name, clamped to the baseline set (cardinality guard)."""
    return tool if tool in app.state.baseline_names else "unknown"


def _is_error(resp_json: object) -> bool:
    if not isinstance(resp_json, dict):
        return False
    result = resp_json.get("result")
    return bool(resp_json.get("error") or (isinstance(result, dict) and result.get("isError")))


async def _proxy(app: FastAPI, request: Request) -> Response:
    q: Quarantine = app.state.q
    store: Store = app.state.store
    metrics: Metrics = app.state.metrics
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
        metrics.record_call(_label(app, tool), "blocked")
        await _safe(store.record_call(tool, method, 0, True, True))
        return Response(content=json.dumps(blocked), media_type="application/json")

    # Forward upstream, transparently.
    client: httpx.AsyncClient = app.state.http
    t0 = time.perf_counter()
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
    latency_ms = int((time.perf_counter() - t0) * 1000)

    resp_json: object = None
    with contextlib.suppress(json.JSONDecodeError):
        resp_json = json.loads(raw)

    # Best-effort in-band detection on JSON tools/list responses.
    if method == "tools/list" and isinstance(resp_json, dict):
        tools = ((resp_json.get("result") or {}).get("tools")) or []
        breaking = detect(app.state.baseline, tools)
        q.sync(breaking)
        metrics.quarantined.set(len(q.all()))
        await _safe(store.sync_quarantine(breaking))

    if method == "tools/call" and isinstance(tool, str):
        is_err = _is_error(resp_json)
        metrics.record_call(_label(app, tool), "error" if is_err else "ok", latency_ms / 1000)
        await _safe(store.record_call(tool, method, latency_ms, is_err, False))

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
    store: Store | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await app.state.store.connect()
            app.state.q.sync(await app.state.store.load_quarantine())  # resume across restart
        except Exception as e:  # noqa: BLE001 - proxy must start even if the store is down
            log.warning("covenant store connect failed, running in-memory: %s", e)
        yield
        with contextlib.suppress(Exception):
            await app.state.store.close()

    app = FastAPI(title="Covenant proxy", description="MCP contract-and-drift firewall",
                  lifespan=lifespan)
    app.state.upstream = upstream_url
    app.state.baseline = baseline_tools
    app.state.q = quarantine or Quarantine()
    app.state.http = http_client or httpx.AsyncClient(timeout=30.0)
    app.state.lister = lister
    app.state.store = store or InMemoryStore()
    app.state.metrics = Metrics()
    # Clamp the metric label to known tools: a client-supplied name must not be able
    # to mint unbounded Prometheus timeseries (label-cardinality DoS).
    app.state.baseline_names = {t["name"] for t in baseline_tools}

    @app.get("/covenant/status")
    async def status() -> JsonDict:
        return {"quarantined": app.state.q.all(), "upstream": upstream_url}

    @app.get("/covenant/calls")
    async def calls(limit: int = 20) -> JsonDict:
        return {"calls": await app.state.store.recent_calls(limit)}

    @app.post("/covenant/refresh")
    async def refresh() -> JsonDict:
        try:
            tools = await asyncio.wait_for(_list_upstream(app), timeout=_UPSTREAM_LIST_TIMEOUT)
        except TimeoutError as e:
            raise HTTPException(status_code=502, detail="upstream did not respond in time") from e
        except Exception as e:  # noqa: BLE001 - upstream failure is a bad gateway, not a 500
            raise HTTPException(status_code=502, detail=f"upstream list failed: {e}") from e
        breaking = detect(app.state.baseline, tools)
        app.state.q.sync(breaking)
        app.state.metrics.quarantined.set(len(app.state.q.all()))
        await _safe(app.state.store.sync_quarantine(breaking))
        for tool, reason in breaking.items():
            app.state.metrics.drift.labels(severity="breaking").inc()
            await _safe(app.state.store.record_drift(tool, "breaking", [{"message": reason}]))
        return {"quarantined": app.state.q.all(), "checked": len(tools)}

    @app.get("/covenant/metrics")
    async def metrics() -> Response:
        payload, content_type = app.state.metrics.render()
        return Response(content=payload, media_type=content_type)

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
    async def mcp(request: Request) -> Response:
        return await _proxy(app, request)

    return app
