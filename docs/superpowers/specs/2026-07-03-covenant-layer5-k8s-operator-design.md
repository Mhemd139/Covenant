# Layer 5 — Kubernetes operator + Helm (`MCPContract` CRD)

## Scope

Declarative contract conformance in a cluster: an `MCPContract` CR names an MCP
server, a baseline ConfigMap, and a check interval; a kopf operator runs the
existing Layer 0/3 check on that schedule, writes the verdict into `.status`
(printer columns: `kubectl get mcpc` → RESULT / BREAKING / LAST CHECK), and
optionally POSTs the proxy's `/covenant/refresh` so quarantine follows drift.
One Helm chart ships the CRD, the proxy Deployment/Service, and the operator
Deployment with least-privilege RBAC. One Dockerfile serves both roles.

## Named decisions

- **In-operator checks, not Jobs.** The roadmap said "probes as Jobs"; running
  each check as a Job means building status feedback from Job pods (log
  scraping or per-Job RBAC to patch the CR) — heavy machinery for a check that
  takes milliseconds. The operator runs the check in-process on a kopf timer.
  Revisit Jobs when a check becomes long or needs isolation.
- **Purity split.** `reconcile.py` holds all logic (due-gating, check, status
  shaping) with zero kopf/kubernetes imports — the whole layer unit-tests
  without a cluster. `handlers.py` is glue only.
- **Per-CR scheduling via due-gating.** kopf's timer interval is fixed at
  decoration time (30s poll); each CR keeps its own `spec.intervalSeconds`
  (default 300) enforced by `due()` against `status.lastCheckTime`. Cheap
  polls, per-contract schedules, no custom scheduler.
- **A failed check is status, not an exception.** Unreachable server or bad
  baseline → `result: error` in status; the operator must not crash-loop on
  one bad contract. The only raised failure is `kopf.PermanentError` for a
  misconfigured CR (missing ConfigMap key), which kopf reports without retry.
- **Baseline from a ConfigMap** — the same committed `covenant.lock.json`,
  mounted by the proxy and read by the operator (`parse_baseline` extracted
  from `read_baseline` for string input). One artifact, both consumers.
- **Probes run when the baseline has them.** Probe records carry tool + args,
  so the operator re-runs and diffs them with the Layer 3 pipeline — no extra
  CR config.
- **RBAC is least-privilege**: mcpcontracts (+status) list/watch/get/patch,
  configmaps get, events create. Nothing else.

## Demo

```bash
docker build -t covenant-mcp:0.1.0 .
helm install covenant deploy/helm/covenant --set proxy.upstream=http://my-server:8000/mcp
kubectl create configmap covenant-baseline --from-file=covenant.lock.json
kubectl apply -f examples/mcpcontract.yaml
kubectl get mcpcontracts -w    # RESULT flips clean -> breaking when the server drifts
```

## Deferred

- Jobs-based probe execution (see above), multi-server fleets per CR,
  metrics from the operator itself (the proxy already exposes drift metrics).
