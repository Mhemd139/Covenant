# Covenant Layer 3 — behavioral probes + semantic judge

Date: 2026-07-03 · Status: shipped · Depends on: Layer 0 classifier (reused unchanged)

## Problem

Layer 0 diffs *declared* schemas. Two blind spots:

1. Most real MCP tools declare no (or loose) `outputSchema` — there is nothing to diff.
2. A server can lie: schema unchanged while the actual response shape or meaning drifts.
   A clean `check` deliberately says "no *schema* drift", not "contract safe" — this layer
   is the answer to that caveat.

## Mechanism

A **probe** is a user-defined safe example call — `[[probes]]` in `covenant.toml` with a
`tool` and `args`. Only list read-only tools: probes are *called* at snapshot and check time.

- `covenant snapshot` runs each probe and stores in the lock: a **fingerprint** (the type
  shape inferred from the actual response) plus the raw **sample** response.
- `covenant check` re-runs the probes and diffs live vs baseline fingerprint **with the
  Layer 0 classifier**. Responses are output-side by definition, so the direction principle
  applies unchanged: lost field / structural retype / gains-null = BREAKING, scalar retype =
  DEGRADED, additions = COMPATIBLE. Changes render with location `behavior`.
- A probe may declare **value pins** — `expect = { field = value }` (v0.1.1): exact output
  values that are part of the contract, compared with exact equality on every check. Pins
  live in `covenant.toml` only, never in the lock — declared truth, not observed state, so
  adding a pin never requires re-snapshotting.
- `covenant check --judge` additionally sends (tool description, args, baseline sample,
  live response) to an LLM judge for **semantic** drift in fields too volatile to pin.

## Fingerprint rules (locked)

- `bool`→boolean · `int`/`float`→number (collapsed: a value that happens to be whole must
  not flap integer↔number between runs) · `str`→string · `None`→null
- `dict` → object with per-key fingerprints. No `required` list — a key missing at check
  time already reports as field-removed.
- `list` → array; `items` kept only when every element fingerprints identically, else bare
  array. Accepted limitation: a uniform array going heterogeneous fingerprints as bare and
  is not flagged — probe tools that return uniform collections.
- Response source order: `structuredContent` → first text block parsed as JSON → raw text
  as a string.

## Severity decisions

| Case | Tier | Why |
|---|---|---|
| Live response loses a field / structural retype / gains null | BREAKING | Same silent-lie class as schema output changes — classifier reused verbatim |
| Probe now returns `isError` | DEGRADED | Loud: the agent sees the error. Direction principle. |
| Pinned field missing or unequal | BREAKING | Deterministic and user-declared — no false-positive class, unlike the judge. Schema and shape still match while the value lies: the exact silent failure quarantine exists for. |
| Judge suspects semantic drift | DEGRADED | The detector is probabilistic; a false BREAKING is a self-inflicted quarantine outage. Same precedent as the composition punt: flag for review, never auto-break. |
| Probe in covenant.toml but not in the lock | error, exit 2 | A baseline mismatch is a config state, not drift — re-snapshot. |

Judge failures (missing key, API error, unparseable verdict) are loud `CovenantError`s →
exit 2, never silently skipped: the user explicitly opted in with `--judge`.

## Determinism

The lock stays deterministic for a server whose probe responses are stable (sorted keys;
probes sorted by tool + canonical args). A server returning volatile values (timestamps)
legitimately changes `sample` between snapshots — probe stable read-only tools.

## Demo levers (examples/mcp_server.py)

- `COVENANT_BEHAVIOR_DRIFT=1` — `get_transactions` (loose `dict` output, invisible to
  Layer 0) renames `amount_usd`→`amount_cents` in the response body only. Schema check
  stays clean; the probe catches BREAKING. CI-runnable, no API key.
- `COVENANT_SEMANTIC_DRIFT=1` — `get_account` returns the balance ×100. Schema and shape
  identical; the committed `expect` pin catches it deterministically (BREAKING, exit 1,
  CI-runnable, no API key). `--judge` also flags it, and covers the unpinned fields.

## Out of scope

Automatic probe generation; *auto-generated* value pins (snapshot-testing style — a pin
the user didn't type is a pin they won't trust) and tolerance/regex matchers on pins;
judging live traffic at the proxy (cost — Layer 3 judges probes on demand).
