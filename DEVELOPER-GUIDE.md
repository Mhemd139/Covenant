# Covenant — developer's guide

This is the owner's map of the codebase: what each part does, why it's built that way,
how to demo it, and what to say (and not say) when presenting it. The README sells the
tool to users; this file explains it to *you*.

## The one-paragraph version

MCP servers expose tools; agents consume them. When a server changes a tool — renames an
output field, tightens an input, rescales a value — nothing throws. The agent keeps
calling, reads a field that no longer exists, and confidently reports a wrong answer.
Covenant makes the tool contract **explicit** (`covenant snapshot` → committed
`covenant.lock.json`), **checked** (`covenant check` diffs the live server against the
baseline and classifies every change), and **enforced** (`covenant proxy` quarantines
drifted tools at runtime; the K8s operator does this declaratively for a fleet).

## The intellectual core: the direction principle

If you explain only one thing, explain this. Severity is not "how big is the change" —
it's **which side of the tool the change is on**, because the consumer is an LLM agent
that re-reads tool definitions every run:

- **Input-side changes fail loud.** The server rejects a bad call, or the agent re-reads
  the schema and adapts. Recoverable → **DEGRADED** (warn; fails CI only under `--strict`).
- **Output-side changes fail silent.** The agent reads a value that is gone, retyped, or
  now intermittently `null` — and proceeds confidently. Unrecoverable → **BREAKING**
  (fails CI; quarantined at the proxy).

This inverts REST intuition (where a tightened input is the classic break) and it is the
justification for every row of the rule table in `covenant/diff.py`. The full rationale
lives in `docs/superpowers/specs/2026-07-01-covenant-layer0-contract-core-design.md`.

## Layer map

Dependency-ordered: each layer ships alone and reuses the ones below it. Optional
dependencies are real extras in `pyproject.toml` — the core installs with nothing but
`mcp`, `typer`, `rich`.

### Layer 0 — contract core (`covenant/*.py`)

| File | Job |
|---|---|
| `introspect.py` | Connects to an MCP server (stdio subprocess or streamable-HTTP), lists tools, runs probes. The only file that talks MCP. |
| `contract.py` | Tool → canonical contract record; read/write/parse the lock file. The lock is **deterministic**: sorted keys, no timestamp — re-snapshotting an unchanged server is byte-identical, so the lock diffs cleanly in git. |
| `diff.py` | The classifier. **Pure** — no I/O, takes two contract sets, returns `Change` records with `tier` ∈ breaking/degraded/compatible. Walks nested schemas recursively (`balance.currency`, `items[].sku`), handles type unions/nullability, and deliberately refuses to guess at `$ref`/`allOf`/`oneOf` composition (flags DEGRADED for manual review instead). |
| `report.py` | Renders the drift table (rich) or `--json`, and maps tiers → exit codes. |
| `cli.py` | Typer app: `snapshot`, `check`, `proxy`. Wires config → introspection → diff → report. |
| `config.py` | Parses `covenant.toml` (server target, `[[probes]]`, `[judge]`). |
| `errors.py` | `CovenantError`: every expected failure becomes **one clean line and exit 2** — never a stack trace, never swallowed. |
| `fingerprint.py` | Response → type-shape fingerprint (see Layer 3). |

**Exit codes are the CI contract**: 0 clean, 1 breaking (or degraded under `--strict`),
2 config/connection error. `schema_hash` covers schemas only — a description typo must
not read as an identity change.

### Layer 1 — proxy + quarantine (`covenant/proxy/`)

`server.py` is a FastAPI reverse-proxy that forwards every JSON-RPC exchange
byte-for-byte (SSE passthrough included) — the client cannot tell it's there. A
`tools/call` to a **quarantined** tool is short-circuited with a clean MCP `isError`
result and never forwarded: the agent sees "tool unavailable" instead of hallucinating
around drifted output. `detect.py` re-checks the upstream; `quarantine.py` holds state.

The key design decision: **drift detection is proxy-owned**. `POST /covenant/refresh`
re-reads the baseline from disk (so a re-snapshot or updated ConfigMap takes effect
without a restart), then makes the proxy re-list the upstream *itself*. Enforcement
never depends on the client's `tools/list` timing, because the SDK can list *after*
the call it should have protected.

### Layer 2 — store (`covenant/store/`)

Optional Postgres persistence (`asyncpg`): quarantine survives restarts; calls and drift
events are logged. The invariant to quote: **store writes are best-effort — log and
swallow, never fail the request path**. A firewall must not drop traffic because its own
telemetry hiccuped. `memory.py` is the default in-process implementation, `base.py` the
interface, so the proxy code has one code path.

### Layer 3 — behavioral probes + LLM judge (`fingerprint.py`, `judge/`)

Schema checking can't see a server that *lies* (schema unchanged, body different), and
most real MCP tools declare no `outputSchema` at all. Probes cover both: you commit safe,
read-only example calls in `covenant.toml`; `snapshot` runs them and stores each
response's **fingerprint** — the type shape of what actually came back — plus one sample
response. `check` re-runs the probes and classifies shape drift with the same severity
model, at location `behavior`.

The judge (`--judge`, `[judge]` extra) catches drift a fingerprint can't: same shape,
changed meaning (a balance quietly rescaled dollars→cents). The model name picks the
provider — `claude-*` → Anthropic, `gemini-*` → Gemini.

The invariant to quote: **judge verdicts are advisory — DEGRADED, never BREAKING.** A
probabilistic detector must not trigger quarantine. Shape drift is judged on the
fingerprint alone because values legitimately change between runs.

### Layer 4 — observability (`covenant/proxy/metrics.py`, `deploy/`)

Prometheus metrics at `GET /covenant/metrics`: per-tool call counters (ok/error/blocked),
latency histograms, drift events, a quarantine gauge. `docker compose up -d prometheus
grafana` gives a provisioned dashboard — the quarantine stat flips green→red within one
scrape of a drift.

Two decisions worth naming:
- **One `CollectorRegistry` per app instance**, never the global registry — tests create
  many apps and the global one collides.
- **Label-cardinality guard**: tool labels are clamped to the baseline name set (unknown
  tool names become `"unknown"`), so an attacker calling ten thousand made-up tool names
  can't mint ten thousand Prometheus series.

### Layer 5 — K8s operator + Helm (`covenant/operator/`, `deploy/helm/covenant/`)

Declarative contract conformance: an `MCPContract` CR names a server, a baseline
ConfigMap, and an interval; a kopf operator runs the existing Layer 0/3 check on that
schedule, writes the verdict into `.status` (printer columns: `kubectl get mcpcontracts`
→ RESULT / BREAKING / LAST CHECK), and POSTs the proxy's `/covenant/refresh` so
quarantine follows drift.

Decisions worth naming:
- **Purity split**: `reconcile.py` holds all logic and has **zero kopf/kubernetes
  imports** — the whole layer unit-tests without a cluster (`tests/test_operator.py`).
  `handlers.py` is glue only.
- **In-operator checks, not Jobs** (a deliberate deviation from the original pitch): a
  check takes milliseconds; running it as a Job means log-scraping or per-Job RBAC just
  to get status back. Revisit Jobs when a check becomes long or needs isolation.
- **Per-CR scheduling via due-gating**: kopf's timer interval is fixed at decoration time
  (30s poll); each CR keeps its own `spec.intervalSeconds` enforced by `due()` against
  `status.lastCheckTime`.
- **A failed check is status, not an exception**: unreachable server, malformed
  baseline, or missing ConfigMap key → `status.result: error`, with tier counts zeroed
  so kopf's merge patch can't leave stale numbers behind. The operator never raises
  from the timer and never crash-loops on one bad contract.
- **RBAC is least-privilege**: mcpcontracts (+status) list/watch/get/patch, configmaps
  get, events create. Nothing else.

One Dockerfile serves both roles (proxy and operator); the Helm chart ships CRD + proxy
Deployment/Service + operator Deployment.

## How the pieces talk

```
covenant.toml ──snapshot──▶ covenant.lock.json (committed, deterministic)
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        ▼                          ▼                           ▼
  covenant check (CI)        covenant proxy               K8s operator
  diff + probes + judge      quarantine on drift          same check on a schedule,
  exit 0/1/2                 /covenant/refresh            verdict → CR status,
                             /covenant/metrics            nudges proxy refresh
```

One classifier (`diff.py`), one baseline format (`contract.py`), three enforcement
surfaces (CI, runtime proxy, cluster). That reuse is the architecture argument: higher
layers add *where* the check runs, never *what* the check means.

## Demo script

```bash
# 1. The linter catches a lie in the schema AND the body
covenant check                          # OK, exit 0
COVENANT_DRIFT=1 covenant check         # BREAKING (output + behavior rows), exit 1

# 2. Schema-identical drift — only probes catch it
COVENANT_BEHAVIOR_DRIFT=1 covenant check    # schema clean, behavior BREAKING, exit 1

# 3. Semantic drift — same shape, changed meaning; only the judge catches it
COVENANT_SEMANTIC_DRIFT=1 covenant check --judge --strict   # DEGRADED, exit 1 (strict)

# 4. Runtime containment
covenant proxy --upstream http://localhost:8000/mcp --port 9000
curl -X POST localhost:9000/covenant/refresh   # proxy re-checks, quarantines
curl localhost:9000/covenant/status

# 5. Observability
docker compose up -d prometheus grafana        # dashboard at localhost:3000

# 6. Fleet (needs a cluster + docker build)
helm install covenant deploy/helm/covenant --set proxy.upstream=http://my-server:8000/mcp
kubectl create configmap covenant-baseline --from-file=covenant.lock.json
kubectl apply -f examples/mcpcontract.yaml
kubectl get mcpcontracts -w                    # RESULT flips clean -> breaking
```

CI runs the drift injections against the repo's own example server on every push
(`.github/workflows/ci.yml`) — the project eats its own dog food.

## Verification status — be precise about this

- 125 tests, `ruff`, strict `mypy` — green locally and in CI. Postgres tests run against
  a real container when `COVENANT_TEST_DB` is set.
- The operator's *logic* is fully tested cluster-free (that's what the purity split
  buys). **The Helm chart has not been `helm lint`-ed or applied to a real cluster**, and
  the Grafana dashboard was provisioned but not live-exercised end-to-end. Say
  "cluster-verification pending" if asked, not "fully tested".

## Honest limitations (know these before someone finds them)

- **Probes are hand-committed, not LLM-generated.** The original pitch (Project.md) had a
  ReAct agent RAG-generating probe suites; what shipped is `[[probes]]` you write
  yourself. Honest framing: committed probes are deterministic and side-effect-safe by
  construction; generated probes are the roadmap.
- **The judge is advisory by design** — it cannot quarantine. This is a feature (no
  probabilistic quarantine), but it means semantic drift alone never blocks anything.
- **Composed schemas (`$ref`/`allOf`/`anyOf`/`oneOf`) are not resolved** — changes there
  flag DEGRADED for manual review. Deliberate: never silently pass what you can't parse.
- **A clean `check` means "no schema/behavior drift on what we probed"**, not "contract
  safe". Coverage is exactly your probe list.
- **No OTel spans** (deferred; Prometheus only). No value-distribution fingerprints —
  shape only, plus the judge at the margins.

## Presenting it — three framings, same system

- **Technical reviewer**: lead with the direction principle and the purity discipline
  (pure `diff.py`, pure `reconcile.py`, deterministic lock). The claim is a working
  severity *theory* for MCP drift plus three enforcement surfaces reusing one classifier
  — not novel algorithms, novel application: OpenAPI-diff/Pact discipline ported to a
  protocol that has none, with an agent-aware twist (input-loud/output-silent).
- **Pitch**: "REST got OpenAPI diffing and contract testing a decade ago; MCP — the way
  every agent gets its tools now — has nothing. Covenant is the contract firewall for
  MCP: it catches the drift before your agents hallucinate around it, and quarantines the
  tool so they fail safe." The wow moment is demo #2: schema identical, body changed,
  caught anyway.
- **Job-portfolio (platform/reliability roles)**: point at the layer table — reverse
  proxy (FastAPI/async), Postgres store, Prometheus/Grafana, kopf operator + CRD + Helm
  with least-privilege RBAC — each an independently shippable increment with its own
  design spec under `docs/superpowers/specs/`.
