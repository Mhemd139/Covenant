"""Tests for the contract model: hash determinism and baseline round-trip."""

import json

from covenant.contract import (
    ToolContract,
    contract_from_tool,
    read_baseline,
    schema_hash,
    write_baseline,
)


def test_schema_hash_is_key_order_independent():
    a = schema_hash({"type": "object", "properties": {"x": {"type": "number"}}}, None)
    b = schema_hash({"properties": {"x": {"type": "number"}}, "type": "object"}, None)
    assert a == b


def test_schema_hash_changes_when_schema_changes():
    a = schema_hash({"type": "object", "properties": {"x": {"type": "number"}}}, None)
    b = schema_hash({"type": "object", "properties": {"x": {"type": "string"}}}, None)
    assert a != b


def test_schema_hash_excludes_description():
    # description is not part of schema identity, so it cannot affect the hash
    t1 = contract_from_tool({"name": "t", "description": "one", "inputSchema": {"type": "object"}})
    t2 = contract_from_tool({"name": "t", "description": "TWO", "inputSchema": {"type": "object"}})
    assert t1.schema_hash == t2.schema_hash


def test_schema_hash_has_sha256_prefix():
    assert schema_hash({"type": "object"}, None).startswith("sha256:")


def test_baseline_round_trips(tmp_path):
    contracts = [
        contract_from_tool({
            "name": "get_account",
            "description": "Look up an account.",
            "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
            "outputSchema": {"type": "object", "properties": {"balance_usd": {"type": "number"}}},
        }),
    ]
    path = tmp_path / "covenant.lock.json"
    write_baseline(path, contracts, server="python examples/mcp_server.py")

    server, tools = read_baseline(path)
    assert server == "python examples/mcp_server.py"
    assert tools[0]["name"] == "get_account"
    assert tools[0]["inputSchema"]["properties"]["id"]["type"] == "string"
    assert tools[0]["outputSchema"]["properties"]["balance_usd"]["type"] == "number"


def test_baseline_write_is_byte_deterministic(tmp_path):
    contracts = [contract_from_tool({
        "name": "t", "description": "d",
        "inputSchema": {"type": "object",
                        "properties": {"b": {"type": "number"}, "a": {"type": "string"}}},
    })]
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    write_baseline(p1, contracts, server="s")
    write_baseline(p2, contracts, server="s")
    assert p1.read_bytes() == p2.read_bytes()


def test_baseline_has_no_timestamp(tmp_path):
    contracts = [contract_from_tool(
        {"name": "t", "description": "d", "inputSchema": {"type": "object"}})]
    path = tmp_path / "covenant.lock.json"
    write_baseline(path, contracts, server="s")
    data = json.loads(path.read_text())
    assert "generated_at" not in data
    assert "timestamp" not in data
    assert data["covenant_version"]


def test_tool_contract_is_a_dataclass_with_expected_fields():
    c = ToolContract(
        name="t", description="d", input_schema={"type": "object"},
        output_schema=None, schema_hash="sha256:abc",
    )
    assert c.name == "t"
    assert c.output_schema is None
