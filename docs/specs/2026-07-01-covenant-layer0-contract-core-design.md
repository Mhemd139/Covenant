# Covenant — Layer 0: Contract Core (design)

**Date:** 2026-07-01
**Status:** Approved to build (Cue: "let it run"); revised after Cue review round 2
**Author:** Aurelius

> **Operating priority (Cue).** Layer 0 is a *means*, not the demo. The beat that
> lands is the live 0+1 moment — mutate a tool, Covenant catches it, the tool is
> **quarantined**, a running agent fails safe instead of hallucinating. So: get the
> **classifier** (schema traversal + severity rules) right — that is where the
> differentiating reasoning becomes real code — keep everything else in Layer 0
> minimal, and sprint to Layer 1. Do not gold-plate enum/edge cases at the cost of
> reaching quarantine.

## Where this sits

Covenant is being built as a full contract-and-drift firewall for MCP servers,
decomposed into six dependency-ordered layers:

| # | Layer | Adds |
|---|---|---|
| **0** | **Contract core** *(this spec)* | Introspection → committed baseline → schema diff (breaking/degraded/compatible). Pure library + CLI. |
| 1 | Proxy + quarantine | FastAPI async MCP reverse-proxy; in-band capture; fail-safe quarantine |
| 2 | Contract store | Postgres (asyncpg/JSONB): versioned snapshots + call log |
| 3 | Probe agent + RAG | ReAct workers, pgvector, probe generation, LLM-judge, behavioral fingerprints |
| 4 | Observability | OTel spans, Prometheus, Grafana, live dashboard |
| 5 | K8s operator + Helm | `MCPContract` CRD, reconcile loop, probes-as-Jobs |

Every higher layer reuses Layer 0's contract model and classifier. Layer 0 ships
as the scaffolded `covenant-mcp` package (deps: `mcp`, `typer`, `rich` only).

## Purpose

A pure, offline library + CLI that:
1. Introspects an MCP server (stdio or HTTP), capturing each tool's
   `(description, inputSchema, outputSchema)`.
2. Writes them to a **committed baseline** (`covenant.lock.json`).
3. Diffs a live server against that baseline, classifying every change by a
   three-tier severity model, and exits non-zero in CI when the contract breaks.

No server, no database, no LLM, no network beyond the single introspection
connection. This is the honest schema-half of the drift detector.

## The effectiveness model (why the classifier is shaped this way)

The consumer of an MCP tool is not a compiled client pinned to a schema version.
It is an **LLM agent that re-reads the current tool definition on every run** —
it is shown the live `inputSchema` when it generates arguments, and it reads
fields out of the result. So "breaking" is not "incompatible with a frozen
contract"; it is:

> Does this change cause the agent to (a) get its call **rejected**,
> (b) **mis-generate** arguments, or (c) **read a field that is gone or changed** —
> and with what probability, given the agent sees the new schema?

Second constraint: Covenant **quarantines** (Layer 1). A false positive is not
noise — it is a **self-inflicted outage**. A working tool taken offline is also
an agent task-failure. Therefore effectiveness ≠ sensitivity. The objective:

> **Quarantine a change only when the modeled failure is both (1) high-probability
> given the agent re-reads the schema, AND (2) *silent* — forwarding yields a
> confident wrong answer, which is worse than a clean "tool unavailable."**
> Where the failure is real but *loud* or *recoverable*, warn — do not take the
> tool down.

### Direction principle

> **Input-side changes fail loud** — the server rejects the call, or the agent
> re-reads the schema and adapts → **DEGRADED**.
> **Output-side changes fail silent** — the agent reads a wrong/absent value and
> proceeds confidently → **BREAKING**.
> Quarantine converts a silent failure into a loud one; applying it to an
> already-loud failure is a self-inflicted outage with no upside.

Consequence: **within Layer 0's schema-only view, no input change is classified
BREAKING.** This is a statement about what schema-diff can *see*, not a claim that
input changes are always safe. Two silent input paths genuinely exist — a
*semantic pun* (units dollars→cents at the same type), and a *newly-required field
the agent fills plausibly-but-wrong* on a tool that does not semantically validate,
whose wrong result is then read as correct. Both hinge on field *meaning*, not
shape, so both are **deferred to Layer 3** — not claimed away. Layer 0 does not
call them safe; it says it cannot see them.

**On the "loud" path — own the common case.** Covenant exists for *long-living*
agents, so a session holding a now-stale tool definition is the target user's
**normal**, not an edge. When such a session sends a value the changed input
schema no longer accepts, the server rejects it and the agent *sees the error* —
that is precisely why input-side changes are DEGRADED, not BREAKING: the failure
is loud, whether the agent adapts on a fresh read or gets a visible rejection on a
stale one. The tier is not a bet that staleness is rare; it is that the failure is
never silent.

## Severity tiers → response

| Tier | Meaning | Linter exit | Proxy action (Layer 1) |
|---|---|---|---|
| **BREAKING** | High-P, silent agent failure | **1** | **quarantine** |
| **DEGRADED** | Real risk, loud or recoverable | 0 (warn); **1** under `--strict` | warn; quarantine under strict policy |
| **COMPATIBLE** | Agent provably unaffected | 0 | pass |

## Classification rules

| Change | Tier | Mechanism |
|---|---|---|
| Output field removed | **BREAKING** | Agent reads a field that is gone — the canonical silent hallucination. |
| Output type changed — **structural** (scalar↔object/array, object↔array, nested shape change) | **BREAKING** | The agent's read model is wrong: it reads a field expecting a scalar and gets an object → silent corruption. |
| Output type changed — **scalar↔scalar** (e.g. `int`→`string`) | DEGRADED | LLM consumer is type-tolerant (`100` ≈ `"100"`); a strict code consumer fails *loudly* (TypeError). Recoverable, not silent. |
| Output field gains `null` in its type (nullable) | **BREAKING** | Cousin of required→optional: the read may now be `null`, intermittently and silently. |
| Output required→optional | **BREAKING** | Field now intermittently absent: tests pass, prod returns null. Worst silent class. |
| Output enum widened | DEGRADED | Agent may read an unhandled value; often tolerated by an LLM consumer. |
| Input type changed / narrowed | **DEGRADED** | A long-lived (stale) session sends the old type → server rejects it *loudly*; a fresh read adapts to the new type. Either path is loud — never a silent wrong answer. |
| Input field removed | DEGRADED | A stale session still sends it → rejected loudly (or ignored); a fresh read stops sending it. Loud/recoverable, and a behavioral-change signal for Layer 3. |
| New required input · optional→required | DEGRADED | Agent sees it and fills it, possibly wrong; never rejected for absence (loud/recoverable). |
| Input enum narrowed | DEGRADED | Agent picks only current values; risk is lost capability, not a rejected call. |
| Composed-schema change (`$ref`/`allOf`/`anyOf`/`oneOf` present) | DEGRADED | Not deep-diffed on this sprint (see Schema traversal). Structural-hash changed → flag "composed schema changed — manual review." Deliberate, labeled. |
| Tool removed | **BREAKING** (linter) | Loud but fatal capability loss. Linter must fail CI; the proxy has nothing to quarantine (the call already errors cleanly) — split noted, not fudged. |
| Description changed | DEGRADED (info) | In an LLM system, description drives tool-selection and arg-filling. "Material vs typo" needs the Layer 3 judge; Layer 0 reports it. |
| Optional input added · output field added · input enum widened · output enum narrowed | COMPATIBLE | Agent strictly unaffected. |

`--strict` promotes DEGRADED to a failing/quarantining state for teams that want
maximum containment. Note there is deliberately **no** matching "lenient" knob to
*demote* a BREAKING: the scalar/structural split resolves the one over-eager case
(output type change) at classification time, so a lever that could hide a real
silent break is unnecessary and unsafe.

## Schema traversal & type-change semantics (the real engineering of `diff.py`)

Real MCP `inputSchema`/`outputSchema` are nested JSON Schema, not flat field maps.
A top-level-`properties`-only differ passes on the bank example and silently
no-ops (or crashes) on real servers — which would quietly undercut the "runs on
real servers" pitch. So this is scoped deliberately, in two tiers:

**Handled now (mandatory, cheap):**

- **Recursive walk** of nested `properties` and array `items`, producing
  **dotted field paths** (`balance.currency`, `items[].sku`). A change deep in a
  structure is reported at its path with the same rule table applied there.
- **`type` as a list** (JSON Schema unions / nullability). Full matrix, so no
  sub-case is left to the implementer's improvisation:

  | Union change | Output field (agent reads) | Input field (agent sends) |
  | --- | --- | --- |
  | Add `null` | **BREAKING** (`nullable_added` — may now read null) | COMPATIBLE (accepts more) |
  | Remove `null` | COMPATIBLE (always present now) | DEGRADED (`union_narrowed` — stale null rejected loudly) |
  | Widen (add non-null member) | DEGRADED (`union_widened` — may read unhandled type) | COMPATIBLE (accepts more) |
  | Narrow (remove non-null member) | COMPATIBLE (subset of previously-handled types) | DEGRADED (`union_narrowed` — stale value rejected loudly) |

- **Scalar vs structural** classification of a type change, per the table: scalar
  set = `string|number|integer|boolean|null`; anything crossing into/out of
  `object`/`array` (or `object`↔`array`) is structural → BREAKING.

**Punted now (labeled, conservative — NOT deep-diffed):**

- **Composition keywords** `$ref`, `allOf`, `anyOf`, `oneOf`. Resolving/normalizing
  these is a rabbit hole not worth a sprint. When a field's schema contains one,
  Covenant does **not** attempt a structural diff of it; it compares a canonical
  hash of that subschema and, on change, emits a single **DEGRADED** change:
  *"composed schema changed — manual review."* This never crashes and never
  false-passes; it fails toward "look at this," which is the safe direction for a
  loud/recoverable tier. Deep composition diffing is a documented follow-up.

This is the hardest part of Layer 0 and the part worth the care (per the operating
priority); everything downstream is thin around it.

## Module layout

Each file has one purpose; `diff.py` is pure (no I/O) so it is the TDD anchor.

```
covenant/
  __init__.py     (exists) package docstring + __version__
  errors.py       (exists) CovenantError / ConfigError / ConnectionError / BaselineError
  config.py       load covenant.toml (tomllib) + CLI overrides → Config
  introspect.py   connect (stdio OR http) → list[ToolContract]  (transport-agnostic)
  contract.py     ToolContract model, canonical hash, baseline read/write
  diff.py         PURE classifier: (baseline_tools, current_tools) → list[Change]
  report.py       render Changes via rich; --json machine output; exit-code summary
  cli.py          typer app: `snapshot`, `check`
examples/
  mcp_server.py   FastMCP bank server with a COVENANT_DRIFT env drift lever
tests/
  test_diff.py        pure classifier, drives the rule table (TDD, written first)
  test_contract.py    hash stability + baseline round-trip determinism
  test_introspect.py  real snapshot against the example server
  test_cli.py         snapshot → flip lever → check; asserts exit codes
```

## Data model

### `ToolContract`
```
name: str
description: str | None
input_schema: dict | None
output_schema: dict | None
schema_hash: str     # sha256 over canonical(input_schema)|canonical(output_schema)
```
Canonicalization: `json.dumps(schema or {}, sort_keys=True, separators=(",", ":"))`.

**Named decision — this is a *schema*-identity hash, not a *contract*-identity
hash.** `description` is deliberately excluded, so a description edit does not
change `schema_hash`. Description drift is still detected — by the differ (as a
DEGRADED/info change) — just not by the hash. Rationale: the hash is a fast
"did the schema move?" check; folding a prose field into it would make cosmetic
typo fixes read as identity changes. Consistent with description being load-bearing
*and* L3-owned for materiality.

### `Change`
```
tool: str
location: "input" | "output" | "tool" | "description"
field: str | None
kind: "removed" | "added"
      | "type_changed_scalar" | "type_changed_structural"   # output split drives tier
      | "nullable_added" | "union_widened" | "union_narrowed"
      | "newly_required" | "now_optional"
      | "enum_narrowed" | "enum_widened"
      | "composed_changed"                                    # $ref/allOf/anyOf/oneOf punt
      | "tool_removed" | "tool_added"
      | "description_changed"
tier: "breaking" | "degraded" | "compatible"
message: str          # plain-English, human-triage-ready
note: str | None       # optional annotation (e.g. scalar-retype code-consumer caveat)
```

### Baseline file `covenant.lock.json`
Deterministic and git-friendly: sorted keys, **no timestamp**, so re-snapshotting
an unchanged server yields a byte-identical file (clean diffs).
```json
{
  "covenant_version": "0.1.0",
  "server": "python examples/mcp_server.py",
  "tools": {
    "get_account": {
      "description": "Look up a bank account and its current balance.",
      "inputSchema": { "...": "..." },
      "outputSchema": { "...": "..." },
      "schema_hash": "sha256:..."
    }
  }
}
```
`covenant_version` gates the format so Layer 3 can add a `fingerprint` field
without breaking older baselines.

## Config

`covenant.toml` at repo root; CLI flags override.
```toml
[server]
command = "python examples/mcp_server.py"   # stdio: launched as a subprocess
# url   = "http://localhost:8000/mcp"        # OR http: streamable-HTTP

[baseline]
path = "covenant.lock.json"
```
Read with `tomllib` (stdlib, 3.11+). Missing/invalid config → `ConfigError` → exit 2.

## CLI

- `covenant snapshot [--server X] [--force]`
  Introspect → write baseline. Refuses to overwrite without `--force`. Rich
  summary of captured tools + hashes.
- `covenant check [--server X] [--strict] [--json]`
  Introspect → diff vs baseline → report. Exit **0** clean/compatible-only ·
  **1** breaking (or degraded under `--strict`) · **2** config/connection error.

Errors are typed `CovenantError` subclasses rendered as one clean line — never a
stack trace, never a swallowed failure. `--json` emits the `Change` list for CI.

**Caveat printed on every clean run.** A green `check` means **"no *schema*
drift"** — not "contract safe." Layer 0 is blind to behavioral drift and to
whether a description change is *material* (both L3-owned). The report says so
explicitly, so a passing exit code is never mistaken for a semantic guarantee.

## Transport & example server

`introspect.py` supports **stdio** (`command`, launched as a subprocess and torn
down) and **HTTP** (`url`, streamable-HTTP) — the `mcp` SDK provides both cheaply,
and Layers 1+ need HTTP.

`examples/mcp_server.py` is a FastMCP bank server (adapted from the prior
`test_mcp_server`): `get_account`, `get_weather`, `convert_currency`. `get_account`
carries the **drift lever** — when `COVENANT_DRIFT=1`, its output field
`balance_usd` is renamed to `available_balance` (an output-field-removed =
BREAKING change). So `snapshot` → set the env var → `check` reproduces a real
breaking diff end-to-end, no simulation.

## Testing (TDD, `diff.py` first)

1. **`test_diff.py`** — written first, drives the rule table: one case per row,
   asserting `tier` and `location`. Pure functions, no I/O. **Must also cover the
   hard part explicitly** — a nested-object change at a dotted path, an
   `items[]` array change, each `type`-union matrix cell, the scalar/structural
   split, and the composition punt emitting `composed_changed`. The riskiest code
   gets the most cases, not the fewest.
2. **`test_contract.py`** — hash stability (same schema → same hash; key order
   irrelevant), baseline round-trip is byte-deterministic.
3. **`test_introspect.py`** — snapshot the real example server; assert the
   captured tool set and schema shapes.
4. **`test_cli.py`** — full flow: `snapshot` (clean, exit 0) → flip
   `COVENANT_DRIFT` → `check` (exit 1, `get_account` BREAKING) → `--strict`
   promotes a degraded-only change to exit 1.

**Honest limit of this suite.** These tests transcribe the rule table, so they
verify the differ *matches* the effectiveness model — not that the model is
*correct*. The model's correctness is a design judgment (argued in this spec and
its review), validated empirically only at Layer 3's LLM-judge against real agent
outcomes. Green here means "consistent," not "proven effective."

## Non-goals (owned by later layers)

- Runtime proxying / quarantine enforcement (Layer 1).
- Persistence beyond the flat baseline file (Layer 2).
- Behavioral / semantic drift, probe generation, LLM-judge, "material description
  change" detection (Layer 3).
- Metrics/tracing/dashboard (Layer 4), K8s/Helm (Layer 5).
```
