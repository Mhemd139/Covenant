"""Warden — a contract-and-drift firewall in front of an MCP server.

Core pipeline: proxy -> contract snapshot -> schema-diff drift detection -> quarantine.
"""

import asyncio
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from . import capture, db, drift, proxy


async def _list_upstream_tools(url: str, attempts: int = 6, delay: float = 0.5):
    """Connect to the upstream MCP server and list its tools, retrying the connect.

    A drift edit restarts the upstream container, so a refresh fired right after may
    race the restart; retry so Warden-owned detection is reliable on cue."""
    last_err = None
    for _ in range(attempts):
        try:
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return (await session.list_tools()).tools
        except Exception as e:  # connection races during restart
            last_err = e
            await asyncio.sleep(delay)
    raise HTTPException(status_code=503, detail=f"upstream MCP not reachable: {last_err}")


async def refresh_upstream(app: FastAPI) -> dict:
    """Warden itself connects to the upstream MCP server, lists tools, snapshots,
    and runs drift detection — independent of any client re-listing."""
    tools = await _list_upstream_tools(app.state.upstream_url)
    norm = [capture.normalize_tool(t) for t in tools]
    captured = await capture.capture_tools(app.state.pool, norm)
    detected = await app.state.detect(app.state.pool, norm)
    return {"captured": captured, "drift": detected}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db.create_pool()
    app.state.http = httpx.AsyncClient(timeout=30.0)
    app.state.upstream_url = os.environ.get("UPSTREAM_MCP_URL", "http://test-mcp:8000/mcp")
    app.state.detect = drift.detect
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.pool.close()


app = FastAPI(title="Warden", description="MCP contract-and-drift firewall", lifespan=lifespan)
app.include_router(proxy.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "warden"}


@app.post("/warden/refresh")
async def warden_refresh() -> dict:
    """Re-snapshot the upstream contract on demand (Warden-owned detection path)."""
    return await refresh_upstream(app)


@app.get("/warden/status")
async def warden_status() -> dict:
    """Per-tool status + latest drift changes — shared by the CLI and dashboard."""
    pool = app.state.pool
    statuses = await db.get_all_status(pool)
    drift_rows = await db.get_recent_drift(pool, limit=50)
    latest_changes: dict[str, list] = {}
    for r in drift_rows:
        latest_changes.setdefault(r["tool_name"], r["changes"])
    tools = [
        {
            "tool": s["tool_name"],
            "status": s["status"],
            "reason": s["reason"],
            "since": s["since"].isoformat(),
            "changes": latest_changes.get(s["tool_name"], []),
        }
        for s in statuses
    ]
    return {"tools": tools}


@app.get("/warden/calls")
async def warden_calls(limit: int = 20) -> dict:
    rows = await db.get_recent_calls(app.state.pool, limit=limit)
    return {
        "calls": [
            {
                "ts": r["ts"].isoformat(),
                "tool": r["tool_name"],
                "method": r["method"],
                "latency_ms": r["latency_ms"],
                "is_error": r["is_error"],
                "blocked": r["blocked"],
            }
            for r in rows
        ]
    }
