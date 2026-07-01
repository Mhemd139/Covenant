"""The pure contract classifier — the load-bearing core of Layer 0.

Diffs baseline tool contracts against current ones and classifies every change as
``breaking`` / ``degraded`` / ``compatible`` per the effectiveness model in the
Layer 0 design spec. Pure functions, no I/O, so it is the TDD anchor and is reused
unchanged by every higher layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ._types import JsonDict

_COMPOSED = ("$ref", "allOf", "anyOf", "oneOf")


def _canonical(schema: JsonDict | None) -> str:
    return json.dumps(schema or {}, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Change:
    tool: str
    location: str  # "input" | "output" | "tool" | "description"
    field: str | None
    kind: str
    tier: str  # "breaking" | "degraded" | "compatible"
    message: str
    note: str | None = None


_SCALAR = {"string", "number", "integer", "boolean", "null"}


def _props(schema: JsonDict | None) -> JsonDict:
    return (schema or {}).get("properties", {}) or {}


def _required(schema: JsonDict | None) -> set[str]:
    return set((schema or {}).get("required", []) or [])


def _type_set(schema: JsonDict | None) -> set[str]:
    t = (schema or {}).get("type")
    if t is None:
        return set()
    return set(t) if isinstance(t, list) else {t}


def _diff_type(
    tool: str, location: str, field: str, base: JsonDict, curr: JsonDict
) -> Change | None:
    tb, tc = _type_set(base), _type_set(curr)
    if tb == tc:
        return None
    added, removed = tc - tb, tb - tc
    out = location == "output"

    if added == {"null"} and not removed:
        tier = "breaking" if out else "compatible"
        return Change(tool, location, field, "nullable_added", tier,
                      f"{location} field '{field}' is now nullable")
    if removed == {"null"} and not added:
        tier = "compatible" if out else "degraded"
        return Change(tool, location, field, "union_narrowed", tier,
                      f"{location} field '{field}' no longer accepts null")
    if added and not removed:
        tier = "degraded" if out else "compatible"
        return Change(tool, location, field, "union_widened", tier,
                      f"{location} field '{field}' widened its type to {sorted(tc)}")
    if removed and not added:
        tier = "compatible" if out else "degraded"
        return Change(tool, location, field, "union_narrowed", tier,
                      f"{location} field '{field}' narrowed its type to {sorted(tc)}")

    structural = bool((added | removed) - _SCALAR)
    if structural:
        tier = "breaking" if out else "degraded"
        return Change(tool, location, field, "type_changed_structural", tier,
                      f"{location} field '{field}' structural retype {sorted(tb)}->{sorted(tc)}")
    note = "BREAKING for strict/code consumers; LLM consumers are type-tolerant" if out else None
    return Change(tool, location, field, "type_changed_scalar", "degraded",
                  f"{location} field '{field}' retyped {sorted(tb)} -> {sorted(tc)}", note)


def _diff_enum(
    tool: str, location: str, field: str, base: JsonDict, curr: JsonDict
) -> Change | None:
    eb, ec = base.get("enum"), curr.get("enum")
    if eb is None or ec is None or eb == ec:
        return None
    added, removed = set(ec) - set(eb), set(eb) - set(ec)
    out = location == "output"
    if removed and not added:
        tier = "compatible" if out else "degraded"
        return Change(tool, location, field, "enum_narrowed", tier,
                      f"{location} field '{field}' enum narrowed to {sorted(ec)}")
    if added and not removed:
        tier = "degraded" if out else "compatible"
        return Change(tool, location, field, "enum_widened", tier,
                      f"{location} field '{field}' enum widened to {sorted(ec)}")
    # both added and removed: treat as narrowed (a value the consumer knew is gone)
    tier = "compatible" if out else "degraded"
    return Change(tool, location, field, "enum_narrowed", tier,
                  f"{location} field '{field}' enum changed to {sorted(ec)}")


def _is_composed(schema: JsonDict | None) -> bool:
    return isinstance(schema, dict) and any(k in schema for k in _COMPOSED)


def _diff_field(
    tool: str, location: str, path: str, base: JsonDict, curr: JsonDict
) -> list[Change]:
    # Composition punt: do not deep-diff $ref/allOf/anyOf/oneOf — hash-compare and flag.
    if _is_composed(base) or _is_composed(curr):
        if _canonical(base) != _canonical(curr):
            return [Change(tool, location, path, "composed_changed", "degraded",
                           f"{location} field '{path}' composed schema changed — manual review")]
        return []

    changes: list[Change] = []
    t = _diff_type(tool, location, path, base, curr)
    if t is not None:
        changes.append(t)
    e = _diff_enum(tool, location, path, base, curr)
    if e is not None:
        changes.append(e)

    # Recurse: same-typed nested object → dotted path; array → items[] path.
    tb, tc = _type_set(base), _type_set(curr)
    if "object" in tb and "object" in tc:
        changes += _diff_object(tool, location, base, curr, f"{path}.")
    elif "array" in tb and "array" in tc:
        ib, ic = base.get("items"), curr.get("items")
        if isinstance(ib, dict) and isinstance(ic, dict):
            changes += _diff_field(tool, location, f"{path}[]", ib, ic)
    return changes


def _diff_object(
    tool: str, location: str, base: JsonDict | None, curr: JsonDict | None, prefix: str = ""
) -> list[Change]:
    """Compare two object schemas' properties and required-sets, recursively."""
    changes: list[Change] = []
    pb, pc = _props(base), _props(curr)
    rb, rc = _required(base), _required(curr)

    for name in pb:
        if name not in pc:
            tier = "breaking" if location == "output" else "degraded"
            changes.append(Change(
                tool, location, f"{prefix}{name}", "removed", tier,
                f"{location} field '{prefix}{name}' removed",
            ))

    for name in pc:
        path = f"{prefix}{name}"
        if name not in pb:
            required = name in rc
            if location == "output":
                tier = "compatible"
            else:
                tier = "degraded" if required else "compatible"
            changes.append(Change(
                tool, location, path, "added", tier,
                f"{location} {'required' if required else 'optional'} field '{path}' added",
            ))
            continue
        # present in both: type / enum / nested, then required transitions
        changes += _diff_field(tool, location, path, pb[name], pc[name])
        was, now = name in rb, name in rc
        if not was and now:
            tier = "degraded" if location == "input" else "compatible"
            changes.append(Change(
                tool, location, path, "newly_required", tier,
                f"{location} field '{path}' is now required",
            ))
        elif was and not now:
            tier = "breaking" if location == "output" else "compatible"
            changes.append(Change(
                tool, location, path, "now_optional", tier,
                f"{location} field '{path}' is no longer required",
            ))

    return changes


def _diff_tool(base: JsonDict, curr: JsonDict) -> list[Change]:
    name = base.get("name") or curr.get("name") or ""
    changes: list[Change] = []

    if (base.get("description") or "") != (curr.get("description") or ""):
        changes.append(Change(
            name, "description", None, "description_changed", "degraded",
            f"description of '{name}' changed",
        ))

    changes += _diff_object(name, "input", base.get("inputSchema"), curr.get("inputSchema"))
    changes += _diff_object(name, "output", base.get("outputSchema"), curr.get("outputSchema"))
    return changes


def diff_tools(baseline: list[JsonDict], current: list[JsonDict]) -> list[Change]:
    """Diff a baseline tool set against the current one; return all changes."""
    by_name_base = {t["name"]: t for t in baseline}
    by_name_curr = {t["name"]: t for t in current}
    changes: list[Change] = []

    for name, base in by_name_base.items():
        if name not in by_name_curr:
            changes.append(Change(
                name, "tool", None, "tool_removed", "breaking",
                f"tool '{name}' was removed",
            ))
        else:
            changes += _diff_tool(base, by_name_curr[name])

    for name in by_name_curr:
        if name not in by_name_base:
            changes.append(Change(
                name, "tool", None, "tool_added", "compatible",
                f"tool '{name}' was added",
            ))

    return changes
