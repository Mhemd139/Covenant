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

## Quickstart

```bash
git clone https://github.com/Mhemd139/Covenant && cd Covenant
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Snapshot the bundled example server, then break it for real — `COVENANT_DRIFT=1` renames the `balance_usd` output field on a live tool:

```bash
$ covenant check
OK no schema drift - contract matches the baseline.

$ COVENANT_DRIFT=1 covenant check
                         Covenant - contract drift
+-------------------------------------------------------------------------+
| tier       | location | change                                          |
|------------+----------+-------------------------------------------------|
| BREAKING   | output   | output field 'balance_usd' removed              |
| COMPATIBLE | output   | output required field 'available_balance' added |
+-------------------------------------------------------------------------+
x 1 breaking change(s) - downstream agents would fail silently.
$ echo $?
1
```

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

## Runtime guard: the proxy

The linter catches drift at ship time; the proxy contains it at runtime. It forwards every JSON-RPC exchange byte-for-byte (SSE passthrough included) so the client can't tell it's there — but a `tools/call` to a quarantined tool is short-circuited with a clean MCP `isError` result and never forwarded.

```bash
pip install -e ".[proxy]"
covenant proxy --upstream http://localhost:8000/mcp --port 9000
# point your MCP client at http://127.0.0.1:9000/mcp
```

- `POST /covenant/refresh` — Covenant re-lists the upstream itself and re-checks. Detection is proxy-owned by design: a client's `tools/list` can arrive *after* the call it should have protected, so enforcement never depends on client behavior.
- `GET /covenant/status` — currently quarantined tools and why.
- `GET /covenant/calls` — recent call log with latency and outcomes.

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

## Architecture

Covenant is built in dependency-ordered layers; each ships alone and each higher layer reuses the contract core.

| # | Layer | Status |
|---|---|---|
| 0 | Contract core — introspection, committed baseline, severity classifier, CLI | ✅ shipped |
| 1 | Transparent proxy + quarantine | ✅ shipped |
| 2 | Postgres contract store (call log, drift events, durable quarantine) | ✅ shipped |
| 3 | Probe agent + RAG — behavioral fingerprints, LLM-judge for semantic drift | roadmap |
| 4 | Observability — OTel spans, Prometheus, dashboard | roadmap |
| 5 | K8s operator + Helm — `MCPContract` CRD, probes as Jobs | roadmap |

Design specs for the shipped layers live in [docs/superpowers/specs](docs/superpowers/specs).

## Development

```bash
pip install -e ".[dev]"
pytest                      # 86 tests; Postgres-backed tests skip without a DB
ruff check . && mypy covenant
```

Layer boundaries are enforced by imports: the core (`covenant/*.py`) depends only on `mcp`, `typer`, `rich`; the proxy extras (`fastapi`, `httpx`, `uvicorn`) and store extras (`asyncpg`) are optional and lazily imported.

## License

[MIT](LICENSE)
