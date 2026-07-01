"""Warden — a contract-and-drift firewall in front of an MCP server.

Hour 1: minimal FastAPI app with a health check. The proxy, snapshot capture,
drift detection, and quarantine are added in later hours.
"""

from fastapi import FastAPI

app = FastAPI(title="Warden", description="MCP contract-and-drift firewall")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "warden"}
