"""Layer 3's semantic judge — an LLM verdict on probe responses whose *shape* is
unchanged but whose *meaning* may have drifted (units, scale, encoding, repurposed
fields). Fingerprints can't see these; schema diffs never could.

A verdict is advisory by design: DEGRADED, never BREAKING — a probabilistic
detector must not trigger quarantine (a false positive is a self-inflicted outage).
Judge failures are loud CovenantErrors: the user explicitly opted in with --judge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .._types import JsonDict
from ..errors import CovenantError

DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # cheap and fast; override via [judge].model

_SYSTEM = (
    "You are Covenant's semantic-drift judge for MCP tool contracts. Compare a "
    "baseline response with a live response from the same tool called with the same "
    "arguments. The consumer is an LLM agent that trusts the live response to mean "
    "the same thing as the baseline: same units, scale, encoding, and per-field "
    "semantics. Fresh values are fine; flag only changes of meaning (unit or scale "
    "shifts, format changes, repurposed fields). Reply with ONLY this JSON: "
    '{"drift": true|false, "reason": "<one short sentence>"}'
)


@dataclass(frozen=True)
class Verdict:
    drift: bool
    reason: str


def _complete(model: str, system: str, user: str) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise CovenantError('--judge needs extras: pip install "covenant-mcp[judge]"') from e
    try:
        msg = anthropic.Anthropic().messages.create(
            model=model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:  # noqa: BLE001 - missing key / API failure: one clean error
        raise CovenantError(f"judge call failed: {e}") from e
    return "".join(getattr(b, "text", "") for b in msg.content)


def judge_probe(
    tool: str,
    description: str | None,
    args: JsonDict,
    baseline_sample: object,
    live_response: object,
    model: str | None = None,
) -> Verdict:
    """Ask the judge whether the live response semantically drifted from the baseline."""
    payload = json.dumps(
        {
            "tool": tool,
            "description": description,
            "arguments": args,
            "baseline_response": baseline_sample,
            "live_response": live_response,
        },
        sort_keys=True,
    )
    raw = _complete(model or DEFAULT_MODEL, _SYSTEM, payload).strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
        return Verdict(drift=bool(data["drift"]), reason=str(data["reason"]))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise CovenantError(f"judge returned an unparseable verdict: {raw!r}") from e
