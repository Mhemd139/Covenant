"""The transparent MCP reverse-proxy that enforces quarantine.

Forwards every JSON-RPC exchange to the upstream MCP server byte-for-byte (SSE
passed through unbuffered), but short-circuits a ``tools/call`` to a quarantined
tool with a clean MCP ``isError`` result — so the agent fails safe instead of
receiving a silently-wrong response. Detection reuses Layer 0 and runs on the
Covenant-owned ``POST /covenant/refresh`` path (reliable, client-independent) and
best-effort in-band on JSON ``tools/list`` responses.

Every forwarded ``tools/call`` response is additionally verified per-call against
its compiled reference (``covenant.verify``): a deterministic output-contract
violation is blocked and response-quarantined (unless ``--observe``); on SSE, only
the frame carrying the matching JSON-RPC result is held — one frame's latency.

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
from ..config import Config
from ..contract import read_baseline
from ..errors import CovenantError
from ..introspect import introspect_async
from ..store.base import Store
from ..store.memory import InMemoryStore
from ..verify import compile_references, verify
from .detect import detect
from .metrics import Metrics
from .quarantine import Quarantine

log = logging.getLogger("covenant.proxy")

_STORE_WRITE_TIMEOUT = 2.0  # telemetry must never delay traffic
_UPSTREAM_LIST_TIMEOUT = 10.0  # bound the Covenant-owned re-list
_VERIFY_MAX_BYTES = 1 << 20  # verification cost cap: over it, forward unverified

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
    cfg = Config(server_command=None, server_url=app.state.upstream, baseline_path="")
    return await introspect_async(cfg)


def _label(app: FastAPI, tool: str) -> str:
    """Metric label for a tool name, clamped to the baseline set (cardinality guard)."""
    return tool if tool in app.state.baseline_names else "unknown"


def _is_error(resp_json: object) -> bool:
    if not isinstance(resp_json, dict):
        return False
    result = resp_json.get("result")
    return bool(resp_json.get("error") or (isinstance(result, dict) and result.get("isError")))


async def _verify_call(
    app: FastAPI, tool: str, rpc_id: object, result: object, args: object, size: int
) -> JsonDict | None:
    """Verify one resolved tools/call result; record the outcome; return the blocked
    replacement body when enforce mode must not forward the response."""
    metrics: Metrics = app.state.metrics
    label = _label(app, tool)
    if size > _VERIFY_MAX_BYTES:
        metrics.record_verification(label, "skipped_large")
        return None
    if not isinstance(result, dict):
        metrics.record_verification(label, "unverified")
        return None
    try:
        verdict = verify(app.state.refs.get(tool), result, args if isinstance(args, dict) else None)
    except Exception as e:  # noqa: BLE001 - the firewall never drops traffic because inspection broke
        log.warning("covenant verifier error on %s: %s", tool, e)
        metrics.record_verification(label, "error")
        return None
    metrics.record_verification(label, verdict.outcome)
    if verdict.outcome == "degraded":
        metrics.drift.labels(severity="degraded").inc()
        await _safe(app.state.store.record_drift(
            tool, "degraded", [{"message": m} for m in verdict.reasons]))
        return None
    if verdict.outcome != "violation":
        return None
    metrics.drift.labels(severity="breaking").inc()
    await _safe(app.state.store.record_drift(
        tool, "breaking", [{"message": m} for m in verdict.reasons]))
    if app.state.observe:
        return None
    first = verdict.reasons[0]
    q: Quarantine = app.state.q
    q.mark_response(tool, f"live response violated the output contract ({first})")
    metrics.quarantined.set(len(q.all()))
    metrics.record_call(label, "blocked")
    await _safe(app.state.store.record_call(tool, "tools/call", 0, True, True))
    return _error_result(
        rpc_id, f"quarantined by Covenant: live response violated the output contract ({first})"
    )


def _next_frame(buf: bytes) -> tuple[bytes, bytes] | None:
    """Split off one complete SSE frame (terminator included), or None if incomplete."""
    best: tuple[int, bytes] | None = None
    for delim in (b"\n\n", b"\r\n\r\n"):
        i = buf.find(delim)
        if i != -1 and (best is None or i < best[0]):
            best = (i, delim)
    if best is None:
        return None
    i, delim = best
    return buf[: i + len(delim)], buf[i + len(delim):]


def _sse_data(frame: bytes) -> object:
    """Parse a frame's data lines as JSON; None when absent or unparseable."""
    lines = frame.replace(b"\r\n", b"\n").split(b"\n")
    data = b"\n".join(ln[5:].lstrip() for ln in lines if ln.startswith(b"data:"))
    if not data:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def _replace_data(frame: bytes, payload: JsonDict) -> bytes:
    """Swap a frame's data lines for the blocked result, keeping the event shape."""
    sep = b"\r\n" if b"\r\n" in frame else b"\n"
    body = b"data: " + json.dumps(payload).encode()
    out: list[bytes] = []
    replaced = False
    for line in frame.split(sep):
        if line.startswith(b"data:"):
            if not replaced:  # collapse multi-line data to one replacement line
                out.append(body)
                replaced = True
        else:
            out.append(line)
    return sep.join(out)


async def _verify_sse(
    app: FastAPI, up_resp: httpx.Response, tool: str, rpc_id: object, args: object
) -> AsyncIterator[bytes]:
    """Frame-parse a POST tools/call SSE response: forward every frame immediately,
    except the one carrying the matching JSON-RPC result — that one is verified and
    forwarded, or replaced by an error frame of the same event shape."""
    buf = b""
    done = False  # matching frame handled (or cap tripped): pure passthrough from here
    try:
        async for chunk in up_resp.aiter_raw():
            if done:
                yield chunk
                continue
            buf += chunk
            while (split := _next_frame(buf)) is not None:
                frame, buf = split
                payload = _sse_data(frame)
                if (not done and isinstance(payload, dict)
                        and payload.get("id") == rpc_id and "result" in payload):
                    done = True
                    if not _is_error(payload):  # an isError result is already loud
                        blocked = await _verify_call(
                            app, tool, rpc_id, payload.get("result"), args, len(frame))
                        if blocked is not None:
                            yield _replace_data(frame, blocked)
                            continue
                yield frame
            if not done and len(buf) > _VERIFY_MAX_BYTES:
                app.state.metrics.record_verification(_label(app, tool), "skipped_large")
                done = True
            if done and buf:
                yield buf
                buf = b""
        if buf:
            yield buf
        if not done:  # stream closed without the matching frame: no evidence
            app.state.metrics.record_verification(_label(app, tool), "unverified")
    finally:
        await up_resp.aclose()


async def _proxy(app: FastAPI, request: Request) -> Response:
    q: Quarantine = app.state.q
    store: Store = app.state.store
    metrics: Metrics = app.state.metrics
    body = await request.body()

    parsed: object = None
    if body:
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(body)
    rpc: JsonDict = parsed if isinstance(parsed, dict) else {}
    method, rpc_id, params = rpc.get("method"), rpc.get("id"), rpc.get("params")
    tool = params.get("name") if isinstance(params, dict) else None
    args = params.get("arguments") if isinstance(params, dict) else None

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

        # Only POST tools/call responses are frame-parsed; the long-lived GET listen
        # stream (no rpc body) falls through to unbuffered passthrough as always.
        if method == "tools/call" and isinstance(tool, str):
            stream = _verify_sse(app, up_resp, tool, rpc_id, args)
        else:
            stream = _passthrough()
        return StreamingResponse(
            stream, status_code=up_resp.status_code,
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
        if not is_err and isinstance(resp_json, dict):
            replacement = await _verify_call(
                app, tool, rpc_id, resp_json.get("result"), args, len(raw))
            if replacement is not None:  # _verify_call already recorded the blocked call
                return Response(content=json.dumps(replacement), media_type="application/json")
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
    baseline_path: str | None = None,
    baseline_probes: list[JsonDict] | None = None,
    observe: bool = False,
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
    app.state.baseline_path = baseline_path
    app.state.refs = compile_references(baseline_tools, baseline_probes or [])
    app.state.observe = observe

    @app.get("/covenant/status")
    async def status() -> JsonDict:
        return {"quarantined": app.state.q.all(), "sources": app.state.q.sources(),
                "upstream": upstream_url}

    @app.get("/covenant/calls")
    async def calls(limit: int = 20) -> JsonDict:
        return {"calls": await app.state.store.recent_calls(limit)}

    @app.post("/covenant/refresh")
    async def refresh() -> JsonDict:
        # Re-read the baseline first: a re-snapshotted lock (or an updated ConfigMap
        # mount) must not be diffed against the copy parsed at startup, or an
        # intentional contract update reads as drift and quarantines a healthy tool.
        if app.state.baseline_path:
            try:
                _, base_tools, base_probes = read_baseline(app.state.baseline_path)
            except CovenantError as e:
                raise HTTPException(status_code=500, detail=f"baseline reload failed: {e}") from e
            app.state.baseline = base_tools
            app.state.baseline_names = {t["name"] for t in base_tools}
            app.state.refs = compile_references(base_tools, base_probes)
        try:
            tools = await asyncio.wait_for(_list_upstream(app), timeout=_UPSTREAM_LIST_TIMEOUT)
        except TimeoutError as e:
            raise HTTPException(status_code=502, detail="upstream did not respond in time") from e
        except Exception as e:  # noqa: BLE001 - upstream failure is a bad gateway, not a 500
            raise HTTPException(status_code=502, detail=f"upstream list failed: {e}") from e
        app.state.q.clear_responses()  # refresh is the operator's re-check button
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
