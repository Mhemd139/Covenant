"""Schema-diff drift detection.

Diffs a tool's current (inputSchema, outputSchema) against its stored baseline and
classifies each change. A removed field, a retyped field, or a newly-required field
is BREAKING; an added optional field is compatible. Any breaking change quarantines
the tool. This is the load-bearing classifier of the Covenant core.
"""

from . import capture, db


def _type_of(prop: dict) -> str:
    if not isinstance(prop, dict):
        return "unknown"
    t = prop.get("type")
    if isinstance(t, list):
        return "|".join(str(x) for x in t)
    if t:
        return str(t)
    if "anyOf" in prop:
        return "anyOf"
    if "$ref" in prop:
        return "ref"
    return "unknown"


def _diff_object(location: str, baseline: dict, current: dict) -> list[dict]:
    baseline = baseline or {}
    current = current or {}
    props_b = baseline.get("properties", {}) or {}
    props_c = current.get("properties", {}) or {}
    req_b = set(baseline.get("required", []) or [])
    req_c = set(current.get("required", []) or [])
    changes: list[dict] = []

    for name in props_b:
        if name not in props_c:
            changes.append({
                "location": location, "field": name, "kind": "removed",
                "type": _type_of(props_b[name]), "breaking": True,
                "message": f"{location} field '{name}' ({_type_of(props_b[name])}) removed",
            })
            continue
        tb, tc = _type_of(props_b[name]), _type_of(props_c[name])
        if tb != tc:
            changes.append({
                "location": location, "field": name, "kind": "type_changed",
                "from": tb, "to": tc, "breaking": True,
                "message": f"{location} field '{name}' retyped {tb} → {tc}",
            })
        elif name in req_c and name not in req_b:
            changes.append({
                "location": location, "field": name, "kind": "newly_required",
                "type": tc, "breaking": True,
                "message": f"{location} field '{name}' is now required",
            })

    for name in props_c:
        if name not in props_b:
            required = name in req_c
            changes.append({
                "location": location, "field": name, "kind": "added",
                "type": _type_of(props_c[name]), "breaking": required,
                "message": (
                    f"{location} {'required' if required else 'optional'} field "
                    f"'{name}' ({_type_of(props_c[name])}) added"
                ),
            })
    return changes


def diff_schemas(base_in, base_out, cur_in, cur_out) -> list[dict]:
    return _diff_object("input", base_in, cur_in) + _diff_object("output", base_out, cur_out)


def summarize(changes: list[dict]) -> str:
    return "; ".join(c["message"] for c in changes)


async def detect(pool, tools: list[dict]) -> list[dict]:
    """Diff each tool against baseline; quarantine on breaking change. Returns per-tool drift."""
    results: list[dict] = []
    for t in tools:
        name = t["name"]
        if not name:
            continue
        baseline = await db.get_baseline(pool, name)
        if baseline is None:
            continue

        changes = diff_schemas(
            baseline["input_schema"], baseline["output_schema"],
            t.get("inputSchema"), t.get("outputSchema"),
        )
        breaking = [c for c in changes if c["breaking"]]

        if breaking:
            was_quarantined = await db.get_status(pool, name) == "quarantined"
            await db.set_status(pool, name, "quarantined", summarize(breaking))
            if not was_quarantined:  # record the transition once
                await db.record_drift(pool, name, "breaking", changes, True)
            results.append({"tool": name, "severity": "breaking", "changes": changes})
        elif changes:
            await db.set_status(pool, name, "ok", None)
            results.append({"tool": name, "severity": "compatible", "changes": changes})
        else:
            await db.set_status(pool, name, "ok", None)
    return results
