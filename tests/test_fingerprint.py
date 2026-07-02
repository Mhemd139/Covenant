"""Fingerprint inference: the locked rules from the Layer 3 spec."""

import pytest

from covenant.fingerprint import fingerprint, probe_key


def test_scalars():
    assert fingerprint(True) == {"type": "boolean"}
    assert fingerprint(3) == {"type": "number"}
    assert fingerprint(3.5) == {"type": "number"}  # collapsed: no int/float flapping
    assert fingerprint("x") == {"type": "string"}
    assert fingerprint(None) == {"type": "null"}


def test_nested_object():
    assert fingerprint({"balance": 42.5, "meta": {"currency": "USD"}}) == {
        "type": "object",
        "properties": {
            "balance": {"type": "number"},
            "meta": {"type": "object", "properties": {"currency": {"type": "string"}}},
        },
    }


def test_arrays_keep_items_only_when_uniform():
    assert fingerprint([1, 2.5]) == {"type": "array", "items": {"type": "number"}}
    assert fingerprint([1, "a"]) == {"type": "array"}
    assert fingerprint([]) == {"type": "array"}


def test_non_json_value_is_loud():
    with pytest.raises(ValueError):
        fingerprint({1, 2})


def test_probe_key_canonicalizes_args():
    assert probe_key("t", {"a": 1, "b": 2}) == probe_key("t", {"b": 2, "a": 1})
    assert probe_key("t", None) == probe_key("t", {})
    assert probe_key("t", {"a": 1}) != probe_key("t", {"a": 2})
