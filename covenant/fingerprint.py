"""Infer a minimal JSON-Schema-shaped fingerprint from a live probe response.

A fingerprint captures the *type shape* of what a tool actually returned — never its
values, which legitimately change between runs. Shapes are what agents rely on, so
fingerprint diffs feed the same output-side severity rules as declared schemas.

Locked inference rules (Layer 3 design spec): int/float collapse to ``number`` so a
value that happens to be whole never flaps the shape; objects carry no ``required``
(a missing key already reports as field-removed); arrays keep ``items`` only when
every element fingerprints identically, so ordering can't flap the shape either.
"""

from __future__ import annotations

import json

from ._types import JsonDict
from .errors import CovenantError


def fingerprint(value: object) -> JsonDict:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int | float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if value is None:
        return {"type": "null"}
    if isinstance(value, dict):
        return {"type": "object", "properties": {k: fingerprint(v) for k, v in value.items()}}
    if isinstance(value, list):
        shapes = [fingerprint(v) for v in value]
        if shapes and all(s == shapes[0] for s in shapes):
            return {"type": "array", "items": shapes[0]}
        return {"type": "array"}
    raise CovenantError(f"cannot fingerprint non-JSON value of type {type(value).__name__}")


def probe_key(tool: str, args: JsonDict | None) -> str:
    """Identity of a probe: tool + canonical args. Changing args means a new baseline."""
    return f"{tool}:{json.dumps(args or {}, sort_keys=True, separators=(',', ':'))}"
