"""Operator reconcile logic — pure functions, no kopf, no cluster."""

import json
from datetime import UTC, datetime, timedelta

from covenant.operator import reconcile

NOW = datetime(2026, 7, 3, 12, 0, 0, tzinfo=UTC)


def baseline(props):
    return json.dumps({
        "covenant_version": "0.1.0",
        "server": "http://up/mcp",
        "tools": {
            "get_account": {
                "description": "d",
                "inputSchema": None,
                "outputSchema": {"type": "object", "properties": props},
                "schema_hash": "sha256:x",
            }
        },
    })


def live(props):
    return [{
        "name": "get_account", "description": "d",
        "inputSchema": None,
        "outputSchema": {"type": "object", "properties": props},
    }]


# --- due() -----------------------------------------------------------------

def test_never_checked_is_due():
    assert reconcile.due(None, 300, NOW)


def test_not_due_before_interval():
    last = (NOW - timedelta(seconds=100)).isoformat()
    assert not reconcile.due(last, 300, NOW)


def test_due_after_interval():
    last = (NOW - timedelta(seconds=301)).isoformat()
    assert reconcile.due(last, 300, NOW)


def test_garbage_timestamp_is_due():
    assert reconcile.due("not-a-date", 300, NOW)


def test_naive_timestamp_is_due():
    # parses fine but can't be compared with an aware now — must not raise
    assert reconcile.due("2026-07-03T11:00:00", 300, NOW)


# --- check_contract() --------------------------------------------------------

def test_clean_check(monkeypatch):
    monkeypatch.setattr(reconcile, "introspect",
                        lambda cfg: live({"balance_usd": {"type": "number"}}))
    status = reconcile.check_contract(
        "http://up/mcp", baseline({"balance_usd": {"type": "number"}}), NOW)
    assert status["result"] == "clean"
    assert status["breaking"] == 0
    assert status["lastCheckTime"] == NOW.isoformat()


def test_breaking_check(monkeypatch):
    monkeypatch.setattr(reconcile, "introspect",
                        lambda cfg: live({"renamed": {"type": "number"}}))
    status = reconcile.check_contract(
        "http://up/mcp", baseline({"balance_usd": {"type": "number"}}), NOW)
    assert status["result"] == "breaking"
    assert status["breaking"] >= 1
    assert "balance_usd" in status["message"]


def test_unreachable_server_is_error_not_raise(monkeypatch):
    def boom(cfg):
        from covenant.errors import ConnectionError
        raise ConnectionError("could not introspect MCP server")

    monkeypatch.setattr(reconcile, "introspect", boom)
    status = reconcile.check_contract("http://down/mcp", baseline({}), NOW)
    assert status["result"] == "error"
    assert "could not introspect" in status["message"]
    assert status["breaking"] == 0  # zeroed: a merge patch must not show stale counts


def test_bad_baseline_is_error_not_raise():
    status = reconcile.check_contract("http://up/mcp", "{not json", NOW)
    assert status["result"] == "error"


def test_non_object_baseline_is_error_not_raise():
    # valid JSON, wrong shape — must land in status, not escape as AttributeError
    status = reconcile.check_contract("http://up/mcp", "[]", NOW)
    assert status["result"] == "error"


def test_malformed_probe_record_is_error_not_raise(monkeypatch):
    monkeypatch.setattr(reconcile, "introspect", lambda cfg: live({}))
    b = json.loads(baseline({}))
    b["probes"] = [{"args": {}}]  # no 'tool' key
    status = reconcile.check_contract("http://up/mcp", json.dumps(b), NOW)
    assert status["result"] == "error"
