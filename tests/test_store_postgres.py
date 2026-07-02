"""Integration tests for PostgresStore against a real Postgres.

Skipped unless COVENANT_TEST_DB is set (e.g. the docker-compose database), so the
suite is green with no infra and fully exercised with it. This is the honest
coverage line for the store — stated, not hidden.

Each test runs its whole flow inside a single event loop: an asyncpg pool is bound
to the loop that created it, so one asyncio.run per test (not per call).
"""

import asyncio
import os

import pytest

DB = os.environ.get("COVENANT_TEST_DB")
pytestmark = pytest.mark.skipif(not DB, reason="set COVENANT_TEST_DB to run Postgres tests")


async def _fresh():
    from covenant.store.postgres import PostgresStore

    s = PostgresStore(DB)
    await s.connect()
    async with s._p.acquire() as c:
        await c.execute("TRUNCATE calls, drift_events, tool_status")
    return s


def test_quarantine_round_trips_across_reconnect():
    from covenant.store.postgres import PostgresStore

    async def body():
        s = await _fresh()
        await s.sync_quarantine({"get_account": "output field 'balance_usd' removed"})
        await s.close()
        # a fresh store (simulating a proxy restart) loads the persisted quarantine
        s2 = PostgresStore(DB)
        await s2.connect()
        q = await s2.load_quarantine()
        await s2.close()
        return q

    assert asyncio.run(body()) == {"get_account": "output field 'balance_usd' removed"}


def test_record_call_and_recent_ordering():
    async def body():
        s = await _fresh()
        await s.record_call("get_account", "tools/call", 12, False, False)
        await s.record_call("get_account", "tools/call", 0, True, True)
        calls = await s.recent_calls(10)
        await s.close()
        return calls

    calls = asyncio.run(body())
    assert len(calls) == 2
    assert calls[0]["blocked"] is True


def test_record_drift_json_round_trips():
    async def body():
        s = await _fresh()
        await s.record_drift(
            "get_account", "breaking", [{"message": "balance_usd removed", "field": "x"}]
        )
        drift = await s.recent_drift(10)
        await s.close()
        return drift

    drift = asyncio.run(body())
    assert drift[0]["tool"] == "get_account"
    assert drift[0]["changes"][0]["field"] == "x"
