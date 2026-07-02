"""Tests for proxy drift detection: which tools to quarantine, and why.

Reuses the Layer 0 classifier, so this only checks that *breaking* changes (and
only breaking) become quarantine entries with a readable reason.
"""

from covenant.proxy.detect import detect


def tool(name, out=None, inp=None, description="d"):
    return {"name": name, "description": description, "inputSchema": inp, "outputSchema": out}


def obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


def test_no_drift_no_quarantine():
    base = [tool("get_account", out=obj({"balance_usd": {"type": "number"}}))]
    assert detect(base, base) == {}


def test_breaking_output_removal_quarantines_with_reason():
    base = [tool("get_account", out=obj({"balance_usd": {"type": "number"}}))]
    live = [tool("get_account", out=obj({"available_balance": {"type": "number"}}))]
    q = detect(base, live)
    assert "get_account" in q
    assert "balance_usd" in q["get_account"]


def test_degraded_change_does_not_quarantine():
    # input field removed = degraded (loud), not breaking
    base = [tool("t", inp=obj({"legacy": {"type": "string"}}))]
    live = [tool("t", inp=obj({}))]
    assert detect(base, live) == {}


def test_tool_removed_quarantines():
    base = [tool("a"), tool("b")]
    live = [tool("a")]
    assert "b" in detect(base, live)


def test_multiple_breaking_reasons_joined_per_tool():
    base = [tool("t", out=obj({"a": {"type": "number"}, "b": {"type": "string"}}))]
    live = [tool("t", out=obj({}))]
    q = detect(base, live)
    assert "a" in q["t"] and "b" in q["t"]
