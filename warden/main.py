"""Warden — a contract-and-drift firewall in front of an MCP server.

Core pipeline: proxy -> contract snapshot -> schema-diff drift detection -> quarantine.
"""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from . import capture, db, proxy


async def _noop_detect(pool, norm_tools):
    """Placeholder until drift detection is wired (Hour 3)."""
    return None


async def refresh_upstream(app: FastAPI) -> list[dict]:
    """Warden itself connects to the upstream MCP server, lists tools, snapshots,
    and runs drift detection — independent of any client re-listing."""
    url = app.state.upstream_url
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools

    norm = [capture.normalize_tool(t) for t in tools]
    captured = await capture.capture_tools(app.state.pool, norm)
    await app.state.detect(app.state.pool, norm)
    return captured


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await db.create_pool()
    app.state.http = httpx.AsyncClient(timeout=30.0)
    app.state.upstream_url = os.environ.get("UPSTREAM_MCP_URL", "http://test-mcp:8000/mcp")
    app.state.detect = _noop_detect
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
    captured = await refresh_upstream(app)
    return {"refreshed": captured}
