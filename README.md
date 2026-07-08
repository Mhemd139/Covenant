# Covenant

**A contract linter and drift firewall for MCP servers.**

[![CI](https://github.com/Mhemd139/Covenant/actions/workflows/ci.yml/badge.svg)](https://github.com/Mhemd139/Covenant/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/Mhemd139/Covenant/tree/main/LICENSE)

When an MCP server changes a tool — renames an output field, tightens an input schema — nothing throws. The LLM agents depending on that tool keep calling it, read a field that no longer exists, and confidently report a wrong answer. Existing MCP scanners hash tool definitions and tell you *that* something changed; Covenant classifies every change by whether it **breaks the agent** — and enforces the verdict, from CI to runtime.

Covenant makes the tool contract explicit, versioned, and enforced:

| Command | What it does |
| --- | --- |
| `covenant snapshot` | Introspect a server (stdio or HTTP) and commit its tool contracts to a deterministic `covenant.lock.json` |
| `covenant check` | Diff the live server against the baseline, classify every change **BREAKING / DEGRADED / COMPATIBLE**, exit non-zero in CI on breaking drift |
| `covenant proxy` | Transparent reverse-proxy that **quarantines** drifted tools at runtime — agents get a clean "tool unavailable" instead of silently wrong data |
| `MCPContract` CRD | Kubernetes operator that runs the same check on a schedule and enforces it fleet-wide |

## Quickstart

```bash
git clone https://github.com/Mhemd139/Covenant && cd Covenant
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The repo ships a real example server with a committed baseline. Check it, then break it for real — `COVENANT_DRIFT=1` renames a live tool's output field:

```bash
covenant check                    # OK no drift - exit 0
COVENANT_DRIFT=1 covenant check   # catches the lie - exit 1
```

![covenant check catching a breaking change](https://raw.githubusercontent.com/Mhemd139/Covenant/main/docs/assets/drift-check.svg)

The lie is caught twice: in the declared schema (`output` rows) and in the actual response body (`behavior` rows), because the committed config probes the tool.

Point it at your own server via [covenant.toml](https://github.com/Mhemd139/Covenant/blob/main/covenant.toml), or inline:

```bash
pip install covenant-mcp
covenant snapshot --server http://localhost:8000/mcp   # or a stdio launch command
covenant check    --server http://localhost:8000/mcp --json
```

## The severity model

The consumer of an MCP tool is an LLM agent that re-reads tool definitions on every run — which changes what "breaking" means. Covenant classifies by one direction principle:

> **Input-side changes fail loud** — the server rejects the call, or the agent adapts → **DEGRADED** (warn; fail CI only under `--strict`).
> **Output-side changes fail silent** — the agent reads a value that is gone, retyped, or now `null`, and proceeds confidently → **BREAKING** (fail CI; quarantine at the proxy).

| Change | Tier |
| --- | --- |
| Output field removed · output required→optional · output gains `null` · structural output retype · tool removed · pinned value changed | **BREAKING** |
| Input retyped/narrowed · new required input · scalar output retype · risky enum changes · description changed | DEGRADED |
| Optional input added · output field added · input enum widened | COMPATIBLE |

Nested schemas are walked recursively (`balance.currency`, `items[].sku`). Composed schemas (`$ref`/`allOf`/`anyOf`/`oneOf`) are never guessed at — a change there flags DEGRADED for manual review. Full rationale: [Layer 0 design spec](https://github.com/Mhemd139/Covenant/blob/main/docs/specs/2026-07-01-covenant-layer0-contract-core-design.md).

## Use it in CI

Commit `covenant.toml` + `covenant.lock.json`, then:

```yaml
- name: Contract check
  run: |
    pip install covenant-mcp
    covenant check --json   # exit 1 on breaking drift, 2 on config/connection error
```

This repo runs exactly that against its own example server on every push — including a job that injects the breaking change and asserts Covenant catches it ([ci.yml](https://github.com/Mhemd139/Covenant/blob/main/.github/workflows/ci.yml)).

## Behavioral drift: probes + judge

A schema check can't see a server that *lies* — schema unchanged, response different. And most real MCP tools declare no `outputSchema` at all. Probes cover both: commit safe, **read-only** example calls in `covenant.toml`:

```toml
[[probes]]
tool = "get_transactions"
args = { account_id = "acct-001" }
```

`snapshot` stores each response's **fingerprint** (the type shape of what actually came back); `check` re-runs the probes and classifies shape drift with the same severity model.

A fingerprint remembers that *a number lives there* — not which number. When the exact value is part of the contract — a reference balance, a currency code, a unit — **pin it**:

```toml
[[probes]]
tool = "get_account"
args = { account_id = "acct-001" }
expect = { balance_usd = 4210.0, currency = "USD" }
```

`check` compares every pinned field against the live response with exact equality — no tolerance, no patterns. A mismatch is **BREAKING**: schema and shape still match while the value lies (a balance rescaled to cents, dollars quietly converted to another currency) — exactly the silent failure the direction principle exists to catch. Pins are opt-in and deterministic, like `pip --require-hashes`: nothing is pinned unless you type it. Try it on the example server — `COVENANT_SEMANTIC_DRIFT=1 covenant check` rescales the live balance ×100 and exits 1.

For drift you *didn't* pin — fields too volatile to pin, meaning shifts across the whole response — add the LLM judge:

```bash
pip install -e ".[judge]"
covenant check --judge    # [judge] model in covenant.toml: claude-* / gemini-*
```

![the LLM judge catching a semantic rescale no schema diff can see](https://raw.githubusercontent.com/Mhemd139/Covenant/main/docs/assets/judge-verdict.png)

Judge verdicts are **advisory by design** — DEGRADED, never BREAKING: a probabilistic detector must not trigger quarantine. Details: [Layer 3 design spec](https://github.com/Mhemd139/Covenant/blob/main/docs/specs/2026-07-03-covenant-layer3-behavioral-probes-design.md).

## Runtime guard: the proxy

The linter catches drift at ship time; the proxy contains it at runtime. It forwards every JSON-RPC exchange byte-for-byte (SSE passthrough included) — but a `tools/call` to a quarantined tool is short-circuited with a clean MCP `isError` result.

```bash
pip install -e ".[proxy]"
covenant proxy --upstream http://localhost:8000/mcp --port 9000
# point your MCP client at http://127.0.0.1:9000/mcp
```

| Endpoint | Purpose |
| --- | --- |
| `POST /covenant/refresh` | Re-read the baseline, re-list the upstream, re-check, update quarantine |
| `GET /covenant/status` | Currently quarantined tools and why |
| `GET /covenant/calls` | Recent call log with latency and outcomes |
| `GET /covenant/metrics` | Prometheus metrics: per-tool calls, latency, drift events, quarantine gauge |

Detection is proxy-owned: `refresh` re-lists the upstream itself, so enforcement never depends on the client's `tools/list` timing. Optional Postgres persistence keeps quarantine across restarts (`--database-url`, `[store]` extra); store writes are best-effort and never fail the request path.

`docker compose up -d` also brings up Prometheus + a provisioned Grafana dashboard at `http://localhost:3000` — the quarantine stat flips green→red within one scrape of a drift:

![Grafana dashboard: blocked calls and a quarantined tool after a live drift](https://raw.githubusercontent.com/Mhemd139/Covenant/main/docs/assets/grafana-quarantine.png)

## Kubernetes: the `MCPContract` operator

Declare contract conformance instead of scripting it. The Helm chart ships the proxy, a kopf operator, and an `MCPContract` CRD — the operator re-runs the check on each contract's own schedule, writes the verdict into status, and nudges the proxy to quarantine on drift:

```bash
docker build -t covenant-mcp:0.1.0 .
helm install covenant deploy/helm/covenant --set proxy.upstream=http://my-server:8000/mcp
kubectl create configmap covenant-baseline --from-file=covenant.lock.json
kubectl apply -f examples/mcpcontract.yaml
kubectl get mcpcontracts -w        # RESULT flips clean -> breaking when the server drifts
```

A failed check is `status.result: error`, never a crash-loop. Details: [Layer 5 design spec](https://github.com/Mhemd139/Covenant/blob/main/docs/specs/2026-07-03-covenant-layer5-k8s-operator-design.md).

## Architecture

Dependency-ordered layers; each ships alone, and every enforcement surface (CI, proxy, operator) reuses the same classifier and baseline format:

| # | Layer | Extra |
| --- | --- | --- |
| 0 | Contract core — introspection, baseline, severity classifier, CLI | — |
| 1 | Transparent proxy + quarantine | `[proxy]` |
| 2 | Postgres store — durable quarantine, call log, drift events | `[store]` |
| 3 | Behavioral probes + LLM judge | `[judge]` |
| 4 | Prometheus metrics + Grafana dashboard | `[proxy]` |
| 5 | K8s operator + Helm chart | `[operator]` |

The full codebase tour lives in [docs/ARCHITECTURE.md](https://github.com/Mhemd139/Covenant/blob/main/docs/ARCHITECTURE.md); per-layer design specs (rationale, rule tables, named decisions) in [docs/specs](https://github.com/Mhemd139/Covenant/tree/main/docs/specs).

## Development

```bash
pip install -e ".[dev]"
pytest                        # Postgres-backed tests skip without COVENANT_TEST_DB
ruff check . && mypy covenant # mypy is strict
```

Layer boundaries are enforced by imports: the core depends only on `mcp`, `typer`, `rich`; everything else is an optional extra imported on use.

## License

[MIT](https://github.com/Mhemd139/Covenant/tree/main/LICENSE)
