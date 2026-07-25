"""Per-call response verification: hold one live ``tools/call`` result to a
per-tool reference (the v0.2.0 design spec).

The reference is the tool's declared ``outputSchema`` when present, else its *core
fingerprint* — the intersection of the tool's baselined probe fingerprints: fields
present in every probe response, with agreed types. Intersection, not union, so a
field that varies across probed args is not core and legitimate variance cannot
false-positive. A tool with neither is unverifiable per-call.

Tiers mirror the classifier's output-side rules applied to one live response
(direction principle): a missing reference field, a structural retype, or a
forbidden ``null`` is a silent lie — ``violation``, block-worthy. A scalar↔scalar
retype is ``degraded`` — loud for code, tolerable for LLM consumers, never blocks.
Extra fields are compatible; ``additionalProperties: false`` is deliberately not
enforced (the classifier treats added output fields as compatible, and the verifier
must not block what ``check`` waves through). Value pins are exact equality and
always ``violation``.

Pure functions, no I/O, no proxy imports — Layer 0 rules; this is the TDD anchor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ._types import JsonDict
from .diff import diff_expect
from .fingerprint import probe_key

_COMPOSED = ("$ref", "allOf", "anyOf", "oneOf")
_SCALARS = {"string", "number", "integer", "boolean", "null"}


@dataclass(frozen=True)
class Reference:
    tool: str
    schema: JsonDict | None  # outputSchema, else core fingerprint (required injected)
    pins: dict[str, JsonDict]  # probe_key -> pinned expect values


@dataclass(frozen=True)
class Verdict:
    outcome: str  # "ok" | "violation" | "degraded" | "unverified"
    reasons: tuple[str, ...] = ()


def _intersect(a: JsonDict, b: JsonDict) -> JsonDict | None:
    """Core-shape intersection of two fingerprints; None when the types disagree."""
    if a == b:
        return a
    if a.get("type") != b.get("type"):
        return None
    if a.get("type") == "object":
        pa, pb = a.get("properties") or {}, b.get("properties") or {}
        props = {}
        for name in pa.keys() & pb.keys():
            merged = _intersect(pa[name], pb[name])
            if merged is not None:
                props[name] = merged
        return {"type": "object", "properties": props}
    if a.get("type") == "array":
        return {"type": "array"}  # agreed it's an array; items vary, so not core
    return None


def _require_all(schema: JsonDict) -> JsonDict:
    """Core fields were present in every probe, so every core field is mandatory."""
    if schema.get("type") != "object":
        return schema
    props = {k: _require_all(v) for k, v in (schema.get("properties") or {}).items()}
    return {"type": "object", "properties": props, "required": sorted(props)}


def compile_references(
    tools: list[JsonDict], probes: list[JsonDict]
) -> dict[str, Reference]:
    """Compile per-tool references from a loaded baseline (once per baseline load)."""
    fps: dict[str, list[JsonDict]] = {}
    pins: dict[str, dict[str, JsonDict]] = {}
    for p in probes:
        name = str(p["tool"])
        fps.setdefault(name, []).append(p["fingerprint"])
        if p.get("expect"):
            pins.setdefault(name, {})[probe_key(name, p.get("args"))] = p["expect"]

    refs: dict[str, Reference] = {}
    for t in tools:
        name = str(t["name"])
        schema: JsonDict | None = t.get("outputSchema")
        if schema is None and name in fps:
            core: JsonDict | None = fps[name][0]
            for fp in fps[name][1:]:
                core = _intersect(core, fp) if core is not None else None
            schema = _require_all(core) if core is not None else None
        if schema is not None or name in pins:
            refs[name] = Reference(name, schema, pins.get(name, {}))
    return refs


def resolve_result(result: JsonDict) -> object:
    """Layer 3 result resolution on the wire shape: ``structuredContent``, else the
    first text block parsed as JSON, else raw text."""
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    for block in result.get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if isinstance(text, str):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return None


def _type_of(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "object"
    return "array"


def _matches(value: object, expected: set[str]) -> bool:
    t = _type_of(value)
    if t in expected:
        return True
    return t == "number" and not isinstance(value, float) and "integer" in expected


def _check(value: object, schema: JsonDict, path: str) -> list[tuple[str, str]]:
    """Walk the reference against the live value; return (tier, message) findings."""
    if any(k in schema for k in _COMPOSED):
        return []  # composition punt, same as the classifier
    t = schema.get("type")
    expected: set[str] = set(t) if isinstance(t, list) else {t} if isinstance(t, str) else set()
    if not expected:
        return []
    label = path or "response"
    if not _matches(value, expected):
        if value is None:
            return [("violation", f"'{label}' is null where the reference forbids it")]
        got = _type_of(value)
        structural = bool(({got} | expected) - _SCALARS)
        tier = "violation" if structural else "degraded"
        return [(tier, f"'{label}' retyped {sorted(expected)} -> {got}")]
    findings: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value:
                child = f"{path}.{name}" if path else name
                findings.append(("violation", f"field '{child}' missing"))
        for name, sub in (schema.get("properties") or {}).items():
            if isinstance(sub, dict) and name in value:
                findings += _check(value[name], sub, f"{path}.{name}" if path else name)
    elif isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, element in enumerate(value):
                findings += _check(element, items, f"{label}[{i}]")
    return findings


def verify(ref: Reference | None, result: JsonDict, args: JsonDict | None) -> Verdict:
    """Verify one non-error ``tools/call`` result against its compiled reference."""
    if ref is None:
        return Verdict("unverified")
    response = resolve_result(result)
    findings: list[tuple[str, str]] = []
    if ref.schema is not None:
        findings += _check(response, ref.schema, "")
    expect = ref.pins.get(probe_key(ref.tool, args or {}))
    if expect:
        findings += [("violation", c.message) for c in diff_expect(ref.tool, expect, response)]
    violations = tuple(m for tier, m in findings if tier == "violation")
    if violations:
        return Verdict("violation", violations)
    degraded = tuple(m for tier, m in findings if tier == "degraded")
    if degraded:
        return Verdict("degraded", degraded)
    return Verdict("ok")
