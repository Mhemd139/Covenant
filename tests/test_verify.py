"""Pure verifier tests: reference compilation, tiering, resolution, pins."""

from covenant.verify import Reference, compile_references, resolve_result, verify


def tool(name, out=None):
    return {"name": name, "description": "d", "inputSchema": None, "outputSchema": out}


def obj(props, required=None):
    schema = {"type": "object", "properties": props}
    if required is not None:
        schema["required"] = required
    return schema


def probe(tool_name, fingerprint, args=None, expect=None):
    p = {"tool": tool_name, "args": args or {}, "fingerprint": fingerprint, "sample": {}}
    if expect:
        p["expect"] = expect
    return p


def result_of(payload):
    return {"structuredContent": payload}


NUM = {"type": "number"}
STR = {"type": "string"}


# --- reference compilation -------------------------------------------------

def test_output_schema_wins_over_fingerprint():
    refs = compile_references(
        [tool("t", out=obj({"a": STR}))], [probe("t", obj({"b": NUM}))])
    assert refs["t"].schema == obj({"a": STR})


def test_core_fingerprint_is_the_intersection():
    refs = compile_references([tool("t")], [
        probe("t", obj({"a": NUM, "varies": STR}), args={"x": 1}),
        probe("t", obj({"a": NUM, "varies": NUM}), args={"x": 2}),
        probe("t", obj({"a": NUM}), args={"x": 3}),
    ])
    # 'varies' differs across probes -> not core; 'a' agrees -> core and required
    assert refs["t"].schema == {
        "type": "object", "properties": {"a": NUM}, "required": ["a"]}


def test_disagreeing_toplevel_types_mean_no_reference():
    refs = compile_references([tool("t")], [probe("t", NUM), probe("t", STR)])
    assert "t" not in refs


def test_unprobed_tool_without_output_schema_has_no_reference():
    assert compile_references([tool("t")], []) == {}


def test_pins_are_keyed_by_probe_identity():
    refs = compile_references(
        [tool("t")], [probe("t", obj({"a": NUM}), args={"q": 1}, expect={"a": 42})])
    assert list(refs["t"].pins.values()) == [{"a": 42}]


# --- result resolution (Layer 3 rule verbatim) ------------------------------

def test_resolution_prefers_structured_content():
    r = {"structuredContent": {"a": 1}, "content": [{"type": "text", "text": "{\"a\": 2}"}]}
    assert resolve_result(r) == {"a": 1}


def test_resolution_parses_first_text_block_as_json():
    assert resolve_result({"content": [{"type": "text", "text": "{\"a\": 2}"}]}) == {"a": 2}


def test_resolution_falls_back_to_raw_text():
    assert resolve_result({"content": [{"type": "text", "text": "plain"}]}) == "plain"


# --- tiers ------------------------------------------------------------------

REF = Reference("t", obj({"a": NUM, "b": STR}, required=["a"]), {})


def test_clean_response_is_ok():
    assert verify(REF, result_of({"a": 1, "b": "x"}), None).outcome == "ok"


def test_missing_reference_field_is_a_violation():
    v = verify(REF, result_of({"b": "x"}), None)
    assert v.outcome == "violation"
    assert "missing" in v.reasons[0]


def test_forbidden_null_is_a_violation():
    v = verify(REF, result_of({"a": None, "b": "x"}), None)
    assert v.outcome == "violation"
    assert "null" in v.reasons[0]


def test_structural_retype_is_a_violation():
    assert verify(REF, result_of({"a": {"nested": 1}, "b": "x"}), None).outcome == "violation"


def test_scalar_retype_is_degraded_never_blocks():
    v = verify(REF, result_of({"a": 1, "b": 7}), None)
    assert v.outcome == "degraded"


def test_extra_fields_are_ok():
    assert verify(REF, result_of({"a": 1, "b": "x", "extra": True}), None).outcome == "ok"


def test_optional_declared_field_may_be_absent():
    assert verify(REF, result_of({"a": 1}), None).outcome == "ok"


def test_no_reference_is_unverified():
    assert verify(None, result_of({"a": 1}), None).outcome == "unverified"


def test_pin_mismatch_is_a_violation_only_for_matching_args():
    ref = Reference("t", None, {'t:{"q":1}': {"a": 42}})
    assert verify(ref, result_of({"a": 41}), {"q": 1}).outcome == "violation"
    assert verify(ref, result_of({"a": 41}), {"q": 2}).outcome == "ok"


def test_violation_outranks_degraded():
    ref = Reference("t", obj({"a": NUM, "b": STR}, required=["a", "b"]), {})
    v = verify(ref, result_of({"a": "wrong-scalar"}), None)  # b missing + a retyped
    assert v.outcome == "violation"
