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


def test_sync_never_releases_a_response_caught_tool():
    q = Quarantine()
    q.mark_response("liar", "response violated the contract")
    q.sync({})  # the in-band tools/list sync on client connect
    assert q.is_quarantined("liar")
    assert q.sources() == {"liar": "response"}


def test_clear_responses_releases_only_the_response_bucket():
    q = Quarantine()
    q.mark("schema-bad", "rs")
    q.mark_response("liar", "rr")
    q.clear_responses()
    assert not q.is_quarantined("liar")
    assert q.is_quarantined("schema-bad")


def test_sources_labels_both_buckets():
    q = Quarantine()
    q.mark("both", "rs")
    q.mark_response("both", "rr")
    assert q.sources() == {"both": "schema+response"}


def test_clear_releases_from_both_buckets():
    q = Quarantine()
    q.mark("t", "rs")
    q.mark_response("t", "rr")
    q.clear("t")
    assert not q.is_quarantined("t")
