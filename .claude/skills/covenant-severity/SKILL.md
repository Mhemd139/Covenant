---
name: covenant-severity
description: Use when classifying an MCP tool-schema change as breaking/degraded/compatible, modifying covenant/diff.py, reviewing classifier output, or arguing about a severity tier in Covenant.
---

# Covenant severity classification

## The consumer model (read this before classifying anything)

The consumer of an MCP tool is **not a compiled client pinned to a schema version**. It is an LLM agent that **re-reads the live tool schema on every run** — it sees the new inputSchema when generating arguments, and it reads fields out of results. REST/OpenAPI severity intuition is calibrated for pinned clients and gives **wrong answers here**.

Second constraint: BREAKING triggers **quarantine** (Layer 1). A false positive is a self-inflicted outage — a working tool taken offline. So severity ≠ sensitivity.

## The direction principle

> **Input-side changes fail loud** — the server rejects the call, or the agent re-reads and adapts → **DEGRADED**.
> **Output-side changes fail silent** — the agent reads a value that is gone, retyped, or now null, and proceeds confidently → **BREAKING**.
> Quarantine converts silent failures into loud ones; applying it to an already-loud failure has no upside.

Within schema-only view, **no input change is ever BREAKING**.

## Rule table

| Change | Tier |
|---|---|
| Output field removed | **BREAKING** |
| Output required→optional | **BREAKING** |
| Output gains `null` in type | **BREAKING** — intermittent silent absence, the worst silent class |
| Output structural retype (scalar↔object/array) | **BREAKING** |
| Tool removed | **BREAKING** (linter; proxy has nothing to quarantine) |
| Output scalar↔scalar retype (e.g. int→string) | DEGRADED — LLM is type-tolerant; a code consumer fails *loudly* (TypeError) |
| New required input · optional→required | DEGRADED — agent sees it and fills it; never rejected for absence |
| Input retyped / narrowed / field removed | DEGRADED — stale session gets a *loud* rejection; fresh read adapts |
| Input enum narrowed · output enum widened | DEGRADED |
| Description changed | DEGRADED (info) — materiality is Layer 3's judge |
| `$ref`/`allOf`/`anyOf`/`oneOf` subschema changed | DEGRADED "composed schema changed — manual review"; never deep-diffed, never silently passed |
| Optional input added · output field added · input enum widened · output enum narrowed | COMPATIBLE |

## Red flags — stop, you're using the wrong consumer model

- "New required input = breaking" — pinned-client intuition. The agent re-reads the schema and fills the field. DEGRADED.
- "Gains null is just a warning" — no. Tests pass, prod intermittently returns null, the agent reads it as truth. BREAKING.
- "int→string breaks arithmetic" — a code consumer fails with a *loud* TypeError; the LLM consumer tolerates it. Loud/recoverable = DEGRADED.
- "This input change could silently corrupt results" — semantic puns (dollars→cents) are real but invisible to schema diff; they are Layer 3's job. Do not promote input changes to BREAKING to compensate.

Full rationale and named edge cases: `docs/superpowers/specs/2026-07-01-covenant-layer0-contract-core-design.md`.
