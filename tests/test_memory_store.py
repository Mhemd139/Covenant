"""Tests for the in-memory store (the proxy's default, no database)."""

import asyncio

from covenant.store.memory import InMemoryStore


def run(coro):
    return asyncio.run(coro)


def test_set_status_and_load_only_quarantined():
    s = InMemoryStore()
    run(s.set_status("get_account", "quarantined", "output field 'balance_usd' removed"))
    run(s.set_status("ping", "ok", None))
    assert run(s.load_quarantine()) == {"get_account": "output field 'balance_usd' removed"}


def test_sync_quarantine_replaces_the_set():
    s = InMemoryStore()
    run(s.set_status("a", "quarantined", "x"))
    run(s.sync_quarantine({"b": "y"}))
    assert run(s.load_quarantine()) == {"b": "y"}


def test_record_call_then_recent_most_recent_first():
    s = InMemoryStore()
    run(s.record_call("get_account", "tools/call", 12, False, False))
    run(s.record_call("get_account", "tools/call", 0, True, True))
    calls = run(s.recent_calls(10))
    assert len(calls) == 2
    assert calls[0]["blocked"] is True
    assert calls[1]["latency_ms"] == 12


def test_recent_calls_honours_limit():
    s = InMemoryStore()
    for i in range(5):
        run(s.record_call("t", "tools/call", i, False, False))
    assert len(run(s.recent_calls(3))) == 3


def test_record_drift_then_recent():
    s = InMemoryStore()
    run(s.record_drift("get_account", "breaking", [{"message": "balance_usd removed"}]))
    drift = run(s.recent_drift(10))
    assert drift[0]["tool"] == "get_account"
    assert drift[0]["severity"] == "breaking"
