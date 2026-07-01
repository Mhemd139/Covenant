"""Async Postgres access for Warden (asyncpg pool + JSONB codec).

All queries name their columns explicitly. The pool applies the idempotent
schema on startup so Warden is self-sufficient even on a fresh database.
"""

import json
import os
from pathlib import Path

import asyncpg

_SCHEMA = Path(__file__).parent / "schema.sql"


async def _init_conn(conn: asyncpg.Connection) -> None:
    # Pass/return Python dicts for JSONB columns transparently.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def create_pool() -> asyncpg.Pool:
    dsn = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(dsn, init=_init_conn, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA.read_text())
    return pool


# --- snapshots -------------------------------------------------------------

async def insert_snapshot(pool, tool_name, input_schema, output_schema, schema_hash, is_baseline):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tool_snapshot (tool_name, input_schema, output_schema, schema_hash, is_baseline)"
            " VALUES ($1, $2, $3, $4, $5)",
            tool_name, input_schema, output_schema, schema_hash, is_baseline,
        )


async def get_baseline(pool, tool_name):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT tool_name, input_schema, output_schema, schema_hash FROM tool_snapshot"
            " WHERE tool_name = $1 AND is_baseline = TRUE ORDER BY captured_at ASC LIMIT 1",
            tool_name,
        )


async def get_latest(pool, tool_name):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT tool_name, input_schema, output_schema, schema_hash FROM tool_snapshot"
            " WHERE tool_name = $1 ORDER BY captured_at DESC LIMIT 1",
            tool_name,
        )


# --- call log --------------------------------------------------------------

async def log_call(pool, tool_name, method, request, response, latency_ms, is_error, blocked):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO call_log (tool_name, method, request, response, latency_ms, is_error, blocked)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7)",
            tool_name, method, request, response, latency_ms, is_error, blocked,
        )


async def get_recent_calls(pool, limit=20):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT ts, tool_name, method, latency_ms, is_error, blocked FROM call_log"
            " ORDER BY ts DESC LIMIT $1",
            limit,
        )


# --- drift + status --------------------------------------------------------

async def record_drift(pool, tool_name, severity, changes, quarantined):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO drift_event (tool_name, severity, changes, quarantined) VALUES ($1, $2, $3, $4)",
            tool_name, severity, changes, quarantined,
        )


async def get_recent_drift(pool, limit=10):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT detected_at, tool_name, severity, changes, quarantined FROM drift_event"
            " ORDER BY detected_at DESC LIMIT $1",
            limit,
        )


async def set_status(pool, tool_name, status, reason):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tool_status (tool_name, status, reason, since) VALUES ($1, $2, $3, now())"
            " ON CONFLICT (tool_name) DO UPDATE SET status = EXCLUDED.status,"
            " reason = EXCLUDED.reason, since = now()",
            tool_name, status, reason,
        )


async def get_status(pool, tool_name) -> str:
    if not tool_name:
        return "ok"
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM tool_status WHERE tool_name = $1", tool_name)
    return row["status"] if row else "ok"


async def get_all_status(pool):
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT tool_name, status, reason, since FROM tool_status ORDER BY tool_name")
