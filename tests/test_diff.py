"""Rule-table tests for the pure classifier in covenant.diff.

Each test pins one row of the spec's classification table: it asserts the tier,
location, and kind of the emitted change. These verify the differ *matches* the
effectiveness model (they cannot prove the model is correct — that is L3's job).
"""

from covenant.diff import diff_tools


def tool(name="acct", description="d", inp=None, out=None):
    return {"name": name, "description": description, "inputSchema": inp, "outputSchema": out}


def obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


def one(changes, tool=None, location=None, field=None):
    """Return the single change matching the filters; assert exactly one."""
    hits = [
        c
        for c in changes
        if (tool is None or c.tool == tool)
        and (location is None or c.location == location)
        and (field is None or c.field == field)
    ]
    assert len(hits) == 1, f"expected 1 change, got {len(hits)}: {hits}"
    return hits[0]


# ---- output field presence -------------------------------------------------

def test_output_field_removed_is_breaking():
    base = [tool(out=obj({"balance_usd": {"type": "number"}, "currency": {"type": "string"}}))]
    curr = [tool(out=obj({"currency": {"type": "string"}}))]
    c = one(diff_tools(base, curr), location="output", field="balance_usd")
    assert c.tier == "breaking"
    assert c.kind == "removed"


def test_output_field_added_is_compatible():
    base = [tool(out=obj({"balance_usd": {"type": "number"}}))]
    curr = [tool(out=obj({"balance_usd": {"type": "number"}, "currency": {"type": "string"}}))]
    c = one(diff_tools(base, curr), location="output", field="currency")
    assert c.tier == "compatible"
    assert c.kind == "added"


# ---- input field presence --------------------------------------------------

def test_input_required_field_added_is_degraded():
    base = [tool(inp=obj({"id": {"type": "string"}}, required=["id"]))]
    curr = [tool(inp=obj(
        {"id": {"type": "string"}, "region": {"type": "string"}}, required=["id", "region"]))]
    c = one(diff_tools(base, curr), location="input", field="region")
    assert c.tier == "degraded"
    assert c.kind == "added"


def test_input_optional_field_added_is_compatible():
    base = [tool(inp=obj({"id": {"type": "string"}}, required=["id"]))]
    curr = [tool(inp=obj(
        {"id": {"type": "string"}, "verbose": {"type": "boolean"}}, required=["id"]))]
    c = one(diff_tools(base, curr), location="input", field="verbose")
    assert c.tier == "compatible"


def test_input_field_removed_is_degraded():
    base = [tool(inp=obj({"id": {"type": "string"}, "legacy": {"type": "string"}}))]
    curr = [tool(inp=obj({"id": {"type": "string"}}))]
    c = one(diff_tools(base, curr), location="input", field="legacy")
    assert c.tier == "degraded"
    assert c.kind == "removed"


# ---- required transitions --------------------------------------------------

def test_output_required_to_optional_is_breaking():
    base = [tool(out=obj({"balance_usd": {"type": "number"}}, required=["balance_usd"]))]
    curr = [tool(out=obj({"balance_usd": {"type": "number"}}, required=[]))]
    c = one(diff_tools(base, curr), location="output", field="balance_usd")
    assert c.tier == "breaking"
    assert c.kind == "now_optional"


def test_output_optional_to_required_is_compatible():
    base = [tool(out=obj({"balance_usd": {"type": "number"}}, required=[]))]
    curr = [tool(out=obj({"balance_usd": {"type": "number"}}, required=["balance_usd"]))]
    c = one(diff_tools(base, curr), location="output", field="balance_usd")
    assert c.tier == "compatible"


def test_input_optional_to_required_is_degraded():
    base = [tool(inp=obj({"region": {"type": "string"}}, required=[]))]
    curr = [tool(inp=obj({"region": {"type": "string"}}, required=["region"]))]
    c = one(diff_tools(base, curr), location="input", field="region")
    assert c.tier == "degraded"
    assert c.kind == "newly_required"


def test_input_required_to_optional_is_compatible():
    base = [tool(inp=obj({"region": {"type": "string"}}, required=["region"]))]
    curr = [tool(inp=obj({"region": {"type": "string"}}, required=[]))]
    c = one(diff_tools(base, curr), location="input", field="region")
    assert c.tier == "compatible"


# ---- tool-level ------------------------------------------------------------

def test_tool_removed_is_breaking():
    base = [tool(name="get_account"), tool(name="ping")]
    curr = [tool(name="ping")]
    c = one(diff_tools(base, curr), tool="get_account", location="tool")
    assert c.tier == "breaking"
    assert c.kind == "tool_removed"


def test_tool_added_is_compatible():
    base = [tool(name="ping")]
    curr = [tool(name="ping"), tool(name="get_account")]
    c = one(diff_tools(base, curr), tool="get_account", location="tool")
    assert c.tier == "compatible"
    assert c.kind == "tool_added"


def test_description_changed_is_degraded_info():
    base = [tool(name="ping", description="Ping the service.")]
    curr = [tool(name="ping", description="Health-check the service and return uptime.")]
    c = one(diff_tools(base, curr), tool="ping", location="description")
    assert c.tier == "degraded"
    assert c.kind == "description_changed"


def test_no_change_yields_no_changes():
    base = [tool(out=obj({"balance_usd": {"type": "number"}}))]
    curr = [tool(out=obj({"balance_usd": {"type": "number"}}))]
    assert diff_tools(base, curr) == []


# ---- type changes: scalar / structural split -------------------------------

def test_output_scalar_retype_is_degraded():
    base = [tool(out=obj({"balance": {"type": "integer"}}))]
    curr = [tool(out=obj({"balance": {"type": "string"}}))]
    c = one(diff_tools(base, curr), location="output", field="balance")
    assert c.tier == "degraded"
    assert c.kind == "type_changed_scalar"


def test_output_structural_retype_is_breaking():
    base = [tool(out=obj({"balance": {"type": "number"}}))]
    curr = [tool(out=obj({"balance": {"type": "object", "properties": {}}}))]
    c = one(diff_tools(base, curr), location="output", field="balance")
    assert c.tier == "breaking"
    assert c.kind == "type_changed_structural"


def test_output_object_to_array_is_structural_breaking():
    base = [tool(out=obj({"items": {"type": "object", "properties": {}}}))]
    curr = [tool(out=obj({"items": {"type": "array", "items": {"type": "string"}}}))]
    c = one(diff_tools(base, curr), location="output", field="items")
    assert c.tier == "breaking"
    assert c.kind == "type_changed_structural"


def test_input_scalar_retype_is_degraded():
    base = [tool(inp=obj({"id": {"type": "integer"}}))]
    curr = [tool(inp=obj({"id": {"type": "string"}}))]
    c = one(diff_tools(base, curr), location="input", field="id")
    assert c.tier == "degraded"
    assert c.kind == "type_changed_scalar"


# ---- nullability / unions (the type-as-list matrix) ------------------------

def test_output_nullable_added_is_breaking():
    base = [tool(out=obj({"balance": {"type": "number"}}))]
    curr = [tool(out=obj({"balance": {"type": ["number", "null"]}}))]
    c = one(diff_tools(base, curr), location="output", field="balance")
    assert c.tier == "breaking"
    assert c.kind == "nullable_added"


def test_input_nullable_added_is_compatible():
    base = [tool(inp=obj({"id": {"type": "string"}}))]
    curr = [tool(inp=obj({"id": {"type": ["string", "null"]}}))]
    c = one(diff_tools(base, curr), location="input", field="id")
    assert c.tier == "compatible"


def test_output_null_removed_is_compatible():
    base = [tool(out=obj({"balance": {"type": ["number", "null"]}}))]
    curr = [tool(out=obj({"balance": {"type": "number"}}))]
    c = one(diff_tools(base, curr), location="output", field="balance")
    assert c.tier == "compatible"


def test_input_null_removed_is_degraded():
    base = [tool(inp=obj({"id": {"type": ["string", "null"]}}))]
    curr = [tool(inp=obj({"id": {"type": "string"}}))]
    c = one(diff_tools(base, curr), location="input", field="id")
    assert c.tier == "degraded"
    assert c.kind == "union_narrowed"


def test_output_union_widened_is_degraded():
    base = [tool(out=obj({"v": {"type": "string"}}))]
    curr = [tool(out=obj({"v": {"type": ["string", "integer"]}}))]
    c = one(diff_tools(base, curr), location="output", field="v")
    assert c.tier == "degraded"
    assert c.kind == "union_widened"


def test_input_union_widened_is_compatible():
    base = [tool(inp=obj({"v": {"type": "string"}}))]
    curr = [tool(inp=obj({"v": {"type": ["string", "integer"]}}))]
    c = one(diff_tools(base, curr), location="input", field="v")
    assert c.tier == "compatible"


def test_output_union_gaining_structural_member_is_breaking():
    # scalar -> [scalar, object]: the field can now return an object where the
    # agent expects a scalar. A structural member added to a union must classify
    # as structural/breaking, not a mere degraded widening.
    base = [tool(out=obj({"balance": {"type": "number"}}))]
    curr = [tool(out=obj({"balance": {"type": ["number", "object"]}}))]
    c = one(diff_tools(base, curr), location="output", field="balance")
    assert c.tier == "breaking"
    assert c.kind == "type_changed_structural"


# ---- enums -----------------------------------------------------------------

def test_input_enum_narrowed_is_degraded():
    base = [tool(inp=obj({"mode": {"type": "string", "enum": ["a", "b", "c"]}}))]
    curr = [tool(inp=obj({"mode": {"type": "string", "enum": ["a", "b"]}}))]
    c = one(diff_tools(base, curr), location="input", field="mode")
    assert c.tier == "degraded"
    assert c.kind == "enum_narrowed"


def test_input_enum_widened_is_compatible():
    base = [tool(inp=obj({"mode": {"type": "string", "enum": ["a", "b"]}}))]
    curr = [tool(inp=obj({"mode": {"type": "string", "enum": ["a", "b", "c"]}}))]
    c = one(diff_tools(base, curr), location="input", field="mode")
    assert c.tier == "compatible"
    assert c.kind == "enum_widened"


def test_output_enum_widened_is_degraded():
    base = [tool(out=obj({"status": {"type": "string", "enum": ["ok", "err"]}}))]
    curr = [tool(out=obj({"status": {"type": "string", "enum": ["ok", "err", "pending"]}}))]
    c = one(diff_tools(base, curr), location="output", field="status")
    assert c.tier == "degraded"
    assert c.kind == "enum_widened"


def test_output_enum_narrowed_is_compatible():
    base = [tool(out=obj({"status": {"type": "string", "enum": ["ok", "err", "pending"]}}))]
    curr = [tool(out=obj({"status": {"type": "string", "enum": ["ok", "err"]}}))]
    c = one(diff_tools(base, curr), location="output", field="status")
    assert c.tier == "compatible"
    assert c.kind == "enum_narrowed"


# ---- nested objects: dotted paths ------------------------------------------

def test_nested_output_field_removed_reports_dotted_path():
    inner_b = {"type": "object",
               "properties": {"amount": {"type": "number"}, "currency": {"type": "string"}}}
    inner_c = {"type": "object", "properties": {"amount": {"type": "number"}}}
    base = [tool(out=obj({"balance": inner_b}))]
    curr = [tool(out=obj({"balance": inner_c}))]
    c = one(diff_tools(base, curr), location="output", field="balance.currency")
    assert c.tier == "breaking"
    assert c.kind == "removed"


def test_nested_scalar_retype_reports_dotted_path():
    inner_b = {"type": "object", "properties": {"amount": {"type": "number"}}}
    inner_c = {"type": "object", "properties": {"amount": {"type": "string"}}}
    base = [tool(out=obj({"balance": inner_b}))]
    curr = [tool(out=obj({"balance": inner_c}))]
    c = one(diff_tools(base, curr), location="output", field="balance.amount")
    assert c.kind == "type_changed_scalar"


# ---- arrays: items[] -------------------------------------------------------

def test_array_item_field_removed_reports_bracket_path():
    items_b = {"type": "object",
               "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}}}
    items_c = {"type": "object", "properties": {"qty": {"type": "integer"}}}
    base = [tool(out=obj({"lines": {"type": "array", "items": items_b}}))]
    curr = [tool(out=obj({"lines": {"type": "array", "items": items_c}}))]
    c = one(diff_tools(base, curr), location="output", field="lines[].sku")
    assert c.tier == "breaking"
    assert c.kind == "removed"


# ---- composition punt ------------------------------------------------------

def test_composed_schema_change_is_degraded_composed_changed():
    base = [tool(out=obj({"val": {"anyOf": [{"type": "string"}]}}))]
    curr = [tool(out=obj({"val": {"anyOf": [{"type": "string"}, {"type": "integer"}]}}))]
    c = one(diff_tools(base, curr), location="output", field="val")
    assert c.tier == "degraded"
    assert c.kind == "composed_changed"


def test_unchanged_composed_schema_yields_no_change():
    base = [tool(out=obj({"val": {"$ref": "#/defs/Money"}}))]
    curr = [tool(out=obj({"val": {"$ref": "#/defs/Money"}}))]
    assert diff_tools(base, curr) == []
