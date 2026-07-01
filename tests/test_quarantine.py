"""Tests for the in-memory quarantine store."""

from covenant.proxy.quarantine import Quarantine


def test_new_store_is_empty():
    q = Quarantine()
    assert not q.is_quarantined("get_account")
    assert q.all() == {}


def test_mark_and_check():
    q = Quarantine()
    q.mark("get_account", "output field 'balance_usd' removed")
    assert q.is_quarantined("get_account")
    assert q.reason("get_account") == "output field 'balance_usd' removed"


def test_reason_is_none_when_not_quarantined():
    q = Quarantine()
    assert q.reason("nope") is None


def test_clear_releases_a_tool():
    q = Quarantine()
    q.mark("t", "r")
    q.clear("t")
    assert not q.is_quarantined("t")


def test_clear_missing_is_noop():
    q = Quarantine()
    q.clear("never-marked")  # must not raise


def test_all_returns_a_copy():
    q = Quarantine()
    q.mark("a", "ra")
    snapshot = q.all()
    snapshot["b"] = "rb"
    assert not q.is_quarantined("b")  # mutating the snapshot must not touch the store


def test_sync_replaces_quarantine_set():
    q = Quarantine()
    q.mark("old", "gone-next-round")
    q.sync({"new": "breaking now"})
    assert not q.is_quarantined("old")
    assert q.is_quarantined("new")
    assert q.reason("new") == "breaking now"
