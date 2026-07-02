## Idea 1 — Covenant

*A contract-and-drift firewall for an MCP server fleet.*

**The gap.** By 2026, MCP is the default way teams give agents tools, and any serious org is running many MCP servers at once — internal ones plus third-party ones, each versioned independently. When a server quietly changes a tool's input schema, output shape, description, or behavior, the agents depending on it don't throw an error. They degrade: they start picking the wrong tool, mis-filling arguments, or hallucinating around a response field that moved. You find out through falling task-success rates in production, days later, and then a human bisects it by hand. REST solved this a decade ago with OpenAPI plus contract testing (Pact); MCP has essentially nothing equivalent yet. The people who hurt are exactly the people on this NVIDIA team — anyone operating long-living agentic workflows on a fleet of MCP servers — and today their only "test" is re-running flows manually or waiting for complaints.

**What it does.** You point Covenant at your MCP servers. It introspects every tool, and an LLM agent — using the MCP spec and each server's own docs as context — generates a probe suite per tool (valid, invalid, and edge inputs), calls each tool through Covenant's proxy, and checks responses against a learned contract: schema validity plus semantic invariants. It snapshots that contract. On every later run it diffs the new snapshot against the baseline, classifies each change as compatible or breaking, and when something breaks it does two things at once — flags the exact diff with a plain-English explanation, and quarantines the tool at the proxy so downstream agents get a clean "tool unavailable" instead of silently hallucinating. It sits permanently in front of the fleet as the layer that keeps your agents honest.

**Why it lands this NVIDIA job.** This is the densest match to the standout list of any idea here — it touches almost all of them at once:
- *"Develop and evolve the micro-services ecosystem that gives the agent its capabilities"* — Covenant governs exactly that ecosystem.
- *"Instrument, evaluate, and improve the platform's reliability — build observability, track quality, feed signals back"* — this is its entire reason for existing.
- *Stand out: "Knowledge of OAS, MCP, A2A"* — contracts are OpenAPI-for-tools; this is dead center.
- *Stand out: "Kubernetes operators, Helm charts, cluster management"* — see the operator below.
- *Stand out: FastAPI/async, RAG pipelines, vector databases, agentic frameworks (ReAct)* — all load-bearing.

**The architecture.**
- **Ingress:** a FastAPI async reverse-proxy speaking MCP (stdio / SSE / streamable-HTTP) that sits between agents and real servers; every call flows through it and is recorded (request, response, schema, latency, errors).
- **Contract store:** Postgres holds the server/tool registry, versioned contract snapshots (input/output JSON Schema plus behavioral fingerprints).
- **Vector store** (pgvector or Qdrant): chunks of the MCP spec and each server's tool docs, used for RAG to generate meaningful probes and to explain failures in spec terms.
- **Probe agent** (ReAct, async workers): per tool, RAG-pulls spec + docs, plans probes, calls through the proxy, evaluates response against schema + invariants + an LLM-as-judge with guardrails, writes a verdict. Side-effect safety via dry-run conventions and an allowlist.
- **Drift detector:** schema diff (added/removed/required/enum/type, classified breaking vs additive) plus behavioral diff (response-shape and value-distribution fingerprints across probe runs).
- **Fail-safe + observability:** quarantine at the proxy; OpenTelemetry spans on every call, Prometheus metrics (per-tool success, drift events, latency), Grafana.
- **K8s — the centerpiece for the standout bullet:** a Kubernetes operator with an `MCPContract` CRD. You declaratively register servers and probe policies; the operator reconciles desired conformance state, runs probes as Jobs on schedule, and writes conformance status back into the CRD. Ships as a Helm chart.

**The "wow" moment.** Live, you change one tool on one MCP server — rename a field, tighten an enum — and redeploy. Within seconds the dashboard flags the exact breaking diff, shows a real agent task that now fails because of it, and the proxy quarantines the tool so the downstream agent fails safe instead of hallucinating. The invisible failure becomes visible and contained in real time.

**The hardest part.** Behavioral drift, not schema drift. Schema diffing is easy. The real engineering is semantic-equivalence checking — deciding whether the *meaning* of a tool's output changed across versions — without being fooled by benign nondeterminism, and generating probe inputs valid enough to exercise real behavior without triggering side effects. An LLM saying "looks different" is not enough; you need invariants and fingerprints doing the heavy lifting and the judge only at the margins.
