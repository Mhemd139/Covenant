# Layer 4 — observability (Prometheus metrics + Grafana dashboard)

## Scope

Prometheus metrics on the proxy, exposed at `GET /covenant/metrics`, plus a
provisioned Grafana dashboard in docker-compose. **OTel spans are deferred**: the
OTel SDK is a heavy dependency tree, and every signal the demo needs (per-tool
traffic, latency, drift, quarantine) is a metric, not a trace. Revisit when a
real multi-hop fleet exists to trace.

## Named decisions

- **Per-app `CollectorRegistry`** — the prometheus_client default registry is
  process-global; two `create_app` calls in one process (every test run) would
  collide with `Duplicated timeseries`. Each app gets its own registry;
  `/covenant/metrics` renders only its own.
- **`prometheus-client` lives in the `[proxy]` extra** — metrics are meaningless
  without the proxy process, and the core CLI must stay dependency-light
  (Layer 0 rule). No new extra for one pure-Python package.
- **Endpoint is `/covenant/metrics`, not `/metrics`** — everything Covenant owns
  sits under `/covenant/*`; the proxy is transparent everywhere else. Prometheus
  sets `metrics_path` per job, so the non-default path costs one config line.
- **Metrics are in-process, not store-backed** — Prometheus scrapes cumulative
  counters and handles restarts (`rate()` is reset-aware). The Layer 2 store
  remains the durable record; metrics are the live signal. No double-write.
- **Best-effort principle carries over** — metric mutations are non-throwing
  in-memory operations on the request path; no awaits, no store timeout needed.

## Metrics

| Metric | Type | Labels | Incremented |
|---|---|---|---|
| `covenant_calls_total` | Counter | `tool`, `outcome` (`ok`/`error`/`blocked`) | every `tools/call` through the proxy |
| `covenant_call_latency_seconds` | Histogram | `tool` | forwarded calls only (blocked calls never reach upstream) |
| `covenant_drift_total` | Counter | `severity` | per breaking tool on `/covenant/refresh` |
| `covenant_quarantined_tools` | Gauge | — | set after every quarantine sync (refresh + in-band) |

## Dashboard

`deploy/grafana/dashboards/covenant.json`, provisioned automatically:
calls-by-outcome rate, p95 latency (`histogram_quantile` over buckets),
quarantined-tools stat (green 0 / red ≥1), drift events. Compose runs
Prometheus (scrapes the host-run proxy via `host.docker.internal`, 5s interval)
and anonymous-admin Grafana on :3000.

## Demo

```bash
docker compose up -d prometheus grafana
covenant proxy --upstream http://localhost:8000/mcp   # + traffic
curl -X POST http://localhost:9000/covenant/refresh   # after drifting the server
```

Quarantine stat flips green→red on the dashboard within one scrape.
