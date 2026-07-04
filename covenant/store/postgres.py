"""PostgresStore — durable Store backed by asyncpg + JSONB.

Applies the idempotent schema on connect. Used when the proxy is given a
``--database-url``; otherwise the proxy uses ``InMemoryStore``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncpg

from .._types import JsonDict

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    @property
    def _p(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresStore.connect() was not called")
        return self._pool

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        async with self._p.acquire() as c:
            await c.execute(_SCHEMA)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def sync_quarantine(self, breaking: dict[str, str]) -> None:
        async with self._p.acquire() as c, c.transaction():
            await c.execute("DELETE FROM tool_status WHERE status = 'quarantined'")
            for tool, reason in breaking.items():
                await c.execute(
                    """INSERT INTO tool_status (tool, status, reason)
                       VALUES ($1, 'quarantined', $2)
                       ON CONFLICT (tool) DO UPDATE SET status = 'quarantined', reason = $2,
                                                        since = now()""",
                    tool, reason,
                )

    async def load_quarantine(self) -> dict[str, str]:
        async with self._p.acquire() as c:
            rows = await c.fetch(
                "SELECT tool, reason FROM tool_status WHERE status = 'quarantined'"
            )
        return {r["tool"]: (r["reason"] or "") for r in rows}

    async def record_call(
        self, tool: str | None, method: str | None, latency_ms: int, is_error: bool, blocked: bool
    ) -> None:
        async with self._p.acquire() as c:
            await c.execute(
                """INSERT INTO calls (tool, method, latency_ms, is_error, blocked)
                   VALUES ($1, $2, $3, $4, $5)""",
                tool, method, latency_ms, is_error, blocked,
            )

    async def record_drift(self, tool: str, severity: str, changes: list[JsonDict]) -> None:
        async with self._p.acquire() as c:
            await c.execute(
                "INSERT INTO drift_events (tool, severity, changes) VALUES ($1, $2, $3::jsonb)",
                tool, severity, json.dumps(changes),
            )

    async def recent_calls(self, limit: int) -> list[JsonDict]:
        async with self._p.acquire() as c:
            rows = await c.fetch(
                """SELECT tool, method, latency_ms, is_error, blocked, at
                   FROM calls ORDER BY at DESC, id DESC LIMIT $1""",
                limit,
            )
        return [dict(r) for r in rows]

    async def recent_drift(self, limit: int) -> list[JsonDict]:
        async with self._p.acquire() as c:
            rows = await c.fetch(
                """SELECT tool, severity, changes, at
                   FROM drift_events ORDER BY at DESC, id DESC LIMIT $1""",
                limit,
            )
        out: list[JsonDict] = []
        for r in rows:
            d: dict[str, Any] = dict(r)
            if isinstance(d.get("changes"), str):
                d["changes"] = json.loads(d["changes"])
            out.append(d)
        return out
