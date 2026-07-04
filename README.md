# Covenant

**A contract linter for MCP servers — catch breaking tool-schema changes before your agents do.**

[![CI](https://github.com/Mhemd139/Covenant/actions/workflows/ci.yml/badge.svg)](https://github.com/Mhemd139/Covenant/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An MCP server's tools are a contract. When someone renames an output field or tightens an input schema, nothing throws — the LLM agents depending on that tool keep calling it, read a field that no longer exists, and **confidently report a wrong answer**. REST solved this with OpenAPI diffing and contract testing; MCP has had nothing equivalent.

Covenant makes the contract explicit, versioned, and enforced:

- **`covenant snapshot`** — introspect an MCP server (stdio or streamable-HTTP) and commit its tool contracts to a deterministic `covenant.lock.json`
- **`covenant check`** — diff the live server against the baseline, classify every change **BREAKING / DEGRADED / COMPATIBLE**, and exit non-zero in CI when the contract breaks
- **`covenant proxy`** — a transparent reverse-proxy that **quarantines** drifted tools at runtime, so downstream agents get a clean "tool unavailable" instead of silently hallucinating
- **`[[probes]]` + `--judge`** — behavioral fingerprints of what tools **actually return** (works even when a server declares no `outputSchema`), plus an optional LLM judge for semantic drift

## Quickstart

```bash
git clone https://github.com/Mhemd139/Covenant && cd Covenant
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Snapshot the bundled example server, then break it for real — `COVENANT_DRIFT=1` renames the `balance_usd` output field on a live tool:

```bash
$ covenant check
OK no drift - contract matches the baseline.

$ COVENANT_DRIFT=1 covenant check
                                  Covenant - contract drift
+--------------------------------------------------------------------------------------------+
| tier       | location | change                                                             |
|------------+----------+--------------------------------------------------------------------|
| BREAKING   | behavior | probe get_account: output field 'balance_usd' removed              |
| BREAKING   | output   | output field 'balance_usd' removed                                 |
| COMPATIBLE | behavior | probe get_account: output optional field 'available_balance' added |
| COMPATIBLE | output   | output required field 'available_balance' added                    |
+--------------------------------------------------------------------------------------------+
x 2 breaking change(s) - downstream agents would fail silently. Fix or quarantine.
$ echo $?
1
```

The lie is caught twice: in the declared schema (`output` rows) and — because the committed config probes the tool — in the actual response body (`behavior` rows).

Point it at your own server via [covenant.toml](covenant.toml) (a stdio launch command **or** an HTTP URL), or override inline with `--server`:

```bash
covenant snapshot --server http://localhost:8000/mcp
covenant check    --server http://localhost:8000/mcp --json   # machine-readable, for CI
```

## The severity model

The consumer of an MCP tool is not a compiled client pinned to a schema version — it is an **LLM agent that re-reads the tool definition on every run**. That changes what "breaking" means, and Covenant's classifier is built on one direction principle:

> **Input-side changes fail loud** — the server rejects the call, or the agent re-reads the schema and adapts → **DEGRADED** (warn; fail CI only under `--strict`).
> **Output-side changes fail silent** — the agent reads a value that is gone, retyped, or now intermittently `null`, and proceeds confidently → **BREAKING** (fail CI; quarantine at the proxy).

| Change | Tier |
|---|---|
| Output field removed · output required→optional · output gains `null` · structural output retype (scalar↔object/array) | **BREAKING** |
| Tool removed | **BREAKING** |
| Input retyped/narrowed · new required input · scalar↔scalar output retype · enum changes that add risk · description changed | DEGRADED |
| Optional input added · output field added · input enum widened | COMPATIBLE |

The differ walks nested schemas recursively (dotted paths like `balance.currency`, `items[].sku`), handles `type` unions/nullability with a full change matrix, and deliberately **does not guess** at `$ref`/`allOf`/`anyOf`/`oneOf` composition — a changed composed schema is flagged DEGRADED for manual review, never silently passed. A clean `check` explicitly means "no *schema* drift", not "contract safe" — behavioral and semantic drift are out of scope (see roadmap).

Full rationale, rule table, and named edge cases: [Layer 0 design spec](docs/superpowers/specs/2026-07-01-covenant-layer0-contract-core-design.md).

## Use it in CI

Commit `covenant.toml` + `covenant.lock.json`, then:

```yaml
- name: Contract check
  run: |
    pip install "covenant-mcp[dev] @ git+https://github.com/Mhemd139/Covenant"
    covenant check --json   # exit 1 on breaking drift, 2 on config/connection error
```

This repo runs exactly that against its own example server on every push — including a job that *injects* the breaking change and asserts Covenant catches it. See [ci.yml](.github/workflows/ci.yml).

## Behavioral drift: probes + judge

A schema check can't see a server that *lies* — schema unchanged, response different. And most real MCP tools declare no `outputSchema` at all, so there is nothing to diff. Probes cover both. Commit safe, **read-only** example calls in `covenant.toml`:

```toml
[[probes]]
tool = "get_transactions"
args = { account_id = "acct-001" }
```

`covenant snapshot` runs each probe and stores its response **fingerprint** — the type shape of what actually came back — in the lock, alongside one **sample** response so the optional `--judge` pass has a baseline to compare meaning against. Shape drift is judged on the fingerprint alone; values legitimately change between runs. `covenant check` re-runs the probes and classifies shape drift with the same severity model, at location `behavior`:

```bash
$ COVENANT_BEHAVIOR_DRIFT=1 covenant check   # response body renames a field; schema untouched
                                     Covenant - contract drift
+-------------------------------------------------------------------------------------------------+
| tier       | location | change                                                                  |
|------------+----------+-------------------------------------------------------------------------|
| BREAKING   | behavior | probe get_transactions: output field 'transactions[].amount_usd'        |
|            |          | removed                                                                 |
| COMPATIBLE | behavior | probe get_transactions: output optional field                           |
|            |          | 'transactions[].amount_cents' added                                     |
+-------------------------------------------------------------------------------------------------+
x 1 breaking change(s) - downstream agents would fail silently. Fix or quarantine.
```

For drift a fingerprint can't see — same shape, changed *meaning*, like a balance quietly rescaled from dollars to cents — add the LLM judge:

```bash
pip install -e ".[judge]"
covenant check --judge           # try it: COVENANT_SEMANTIC_DRIFT=1 covenant check --judge --strict
```

The judge model is set with `[judge] model` in `covenant.toml`; the name picks the provider — `claude-*` models use `ANTHROPIC_API_KEY`, `gemini-*` models use `GOOGLE_API_KEY`.

Judge verdicts are **advisory by design**: they render DEGRADED (fail only under `--strict`), never BREAKING — a probabilistic detector must not trigger quarantine. Full rationale: [Layer 3 design spec](docs/superpowers/specs/2026-07-03-covenant-layer3-behavioral-probes-design.md).

## Runtime guard: the proxy

The linter catches drift at ship time; the proxy contains it at runtime. It forwards every JSON-RPC exchange byte-for-byte (SSE passthrough included) so the client can't tell it's there — but a `tools/call` to a quarantined tool is short-circuited with a clean MCP `isError` result and never forwarded.

```bash
pip install -e ".[proxy]"
covenant proxy --upstream http://localhost:8000/mcp --port 9000
# point your MCP client at http://127.0.0.1:9000/mcp
```

- `POST /covenant/refresh` — Covenant re-reads the baseline from disk (picking up a re-snapshot or an updated ConfigMap mount), then re-lists the upstream itself and re-checks. Detection is proxy-owned by design: a client's `tools/list` can arrive *after* the call it should have protected, so enforcement never depends on client behavior.
- `GET /covenant/status` — currently quarantined tools and why.
- `GET /covenant/calls` — recent call log with latency and outcomes.
- `GET /covenant/metrics` — Prometheus metrics: per-tool call counters (ok/error/blocked), latency histograms, drift events, quarantine gauge. `docker compose up -d prometheus grafana` gives a provisioned dashboard at `http://localhost:3000` — the quarantine stat flips green→red within one scrape of a drift.

Try it end-to-end with a live agent-style client: [examples/demo_layer1.py](examples/demo_layer1.py).

## Optional persistence

By default the proxy keeps state in memory. Give it Postgres and quarantine survives restarts, with calls and drift events persisted when the store is reachable (writes are best-effort — see below):

```bash
docker compose up -d db
pip install -e ".[store]"
covenant proxy --upstream http://localhost:8000/mcp \
  --database-url postgresql://covenant:covenant@127.0.0.1:5432/covenant
```

Store failures are logged and never break the request path — a firewall must not drop traffic because its own telemetry hiccuped. Demo: [examples/demo_layer2.py](examples/demo_layer2.py).

## Kubernetes: the `MCPContract` operator

Declare contract conformance instead of scripting it. The Helm chart ships the proxy, a kopf operator, and an `MCPContract` CRD — the operator re-runs the contract check on each CR's own schedule, writes the verdict into status, and nudges the proxy to quarantine on drift:

```bash
docker build -t covenant-mcp:0.1.0 .
helm install covenant deploy/helm/covenant --set proxy.upstream=http://my-server:8000/mcp
kubectl create configmap covenant-baseline --from-file=covenant.lock.json
kubectl apply -f examples/mcpcontract.yaml
kubectl get mcpcontracts -w        # RESULT flips clean -> breaking when the server drifts
```

Design decisions (in-operator checks vs Jobs, per-CR scheduling, error-as-status): [Layer 5 design spec](docs/superpowers/specs/2026-07-03-covenant-layer5-k8s-operator-design.md).

## Architecture

Covenant is built in dependency-ordered layers; each ships alone and each higher layer reuses the contract core.

| # | Layer | Status |
|---|---|---|
| 0 | Contract core — introspection, committed baseline, severity classifier, CLI | ✅ shipped |
| 1 | Transparent proxy + quarantine | ✅ shipped |
| 2 | Postgres contract store (call log, drift events, durable quarantine) | ✅ shipped |
| 3 | Behavioral probes — response fingerprints + LLM judge for semantic drift | ✅ shipped |
| 4 | Observability — Prometheus metrics + Grafana dashboard (OTel deferred) | ✅ shipped |
| 5 | K8s operator + Helm — `MCPContract` CRD, scheduled in-operator checks | ✅ shipped |

Design specs for the shipped layers live in [docs/superpowers/specs](docs/superpowers/specs).

## Development

```bash
pip install -e ".[dev]"
pytest                      # 112 tests; Postgres-backed tests skip without a DB
ruff check . && mypy covenant
```

Layer boundaries are enforced by imports: the core (`covenant/*.py`) depends only on `mcp`, `typer`, `rich`; the proxy extras (`fastapi`, `httpx`, `uvicorn`), store extra (`asyncpg`), and judge extra (`anthropic`) are optional and imported on use.

## License

[MIT](LICENSE)
