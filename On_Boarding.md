You are starting a fresh, greenfield project in this empty directory (c:/Dev/Covenant).
You are running on Opus at max effort, in PLAN MODE. Do NOT write any code or create any
files yet. Your only job this turn is to produce a build plan I will approve before any build begins.

# What this project is

Covenant — a contract-and-drift firewall for an MCP (Model Context Protocol) server fleet.
It is a one-night portfolio project to land a specific job: NVIDIA "AI Engineering Platform
Development Engineer" (their stack: Kubernetes, AI harness agent, RAG, MCP, top-tier LLMs;
their standout signals: MCP, OpenAPI/OAS, FastAPI/async Python, RAG, vector DBs, K8s
operators/Helm, A2A protocol). The plan must be optimized to land that job via a live demo,
not to be a complete product.

# What Covenant does (the locked concept — do not redesign it)

- It is a FastAPI async reverse-proxy that sits BETWEEN an MCP client (an agent) and a real MCP
  server. Every tool call flows through it and is logged: request, response, JSON schema, latency, errors.
- For each tool it captures a CONTRACT snapshot: the tool's input/output JSON schema (and, later, a
  behavioral fingerprint).
- On a later run it DIFFS the new snapshot against the baseline and classifies each change as
  compatible or BREAKING (a renamed/removed/retyped field is breaking).
- On a breaking change it does two things: (1) flags the exact diff in plain language, (2) QUARANTINES
  the tool at the proxy so the downstream agent gets a clean "tool unavailable" instead of silently
  hallucinating around a field that moved.

# What is LOCKED (do not relitigate; build around these)

- ONE NIGHT, solo, demo-first. The deliverable is a bulletproof ~60-second LIVE demo: I change one
  field on a live MCP tool, redeploy, and Covenant flags the exact breaking diff + shows an agent task
  now failing + quarantines the tool — with NOTHING simulated.
- Demo target = a REAL MCP server I run LOCALLY and can edit, so I control the drift on cue (real
  protocol, my lever — no public-network flakiness in the demo). The proxy cannot tell it's local.
- The CORE that must always work (never cut): proxy → contract snapshot → schema-diff drift detection
  → quarantine. That four-piece core IS Covenant.
- CUT to a slide, do NOT build: the Kubernetes operator + CRD + Helm. Keep it only in the architecture
  diagram / "production story."
- A2A: do NOT build a multi-agent A2A orchestration core (that is scope-creep that eats the night).
  INSTEAD, as an ADDITIVE, cut-LAST module, the proxy may DETECT and quarantine a recursive-delegation /
  unbounded-loop (A2A recursive-DoS) pattern via a depth/cycle counter + circuit breaker. It must NEVER
  block the core demo. Framing: "Covenant guards A2A; it does not orchestrate over A2A."
- Behavioral/semantic drift detection and RAG-generated plain-English explanations are ENHANCEMENTS,
  cut-if-time. Start with pure schema-diff — it is easy and already the wow moment.

# Environment (already verified)

- Empty dir c:/Dev/Covenant on Windows. Python 3.14, Docker 29.6, git all installed.
- Postgres and any services run IN Docker (docker-compose). Vector store only if RAG survives the cut —
  pick the lowest-friction option (pgvector or Qdrant) if so.

# Model assignment — put this INTO the plan

You (the planner) run on Opus/max. In the plan you produce, assign a model to EACH build task:
- Opus (max effort) for the load-bearing reasoning: the proxy logic, the drift detector, the quarantine.
- Sonnet 5 for well-specified grind: docker-compose, the Postgres schema, the local test MCP server,
  boilerplate, test scaffolding.
Label every task with its model so I know what to set when I build it.

# What I want from you (the plan)

Produce, in plan mode, for my approval:
1. A two-sentence summary of Covenant, so I can confirm we're aligned.
2. An ORDERED, hour-by-hour build plan. Each step: what gets built, which files, which model (Opus/Sonnet),
   and — critically — the WORKING, demoable slice that exists at the end of that step. The core demo must be
   reachable by roughly the halfway point, then hardened.
3. The exact 60-second demo script, beat by beat, that the whole plan builds toward.
4. The ordered CUT-LINE list (first-to-cut → last-to-cut) so I always know what drops if time runs short.
5. The "smallest version that still lands the demo" (the 4-hour fallback).
6. The exact FIRST action you'll take once I approve (first files/commands).
7. At most 3 blocking questions for me — only if you genuinely cannot plan without the answer.

Be tight and directive. This is a working plan, not an essay. Protect the "nothing simulated / runs on a
real MCP server" property above everything. When ready, present the plan and stop for my approval.




WHEN FINISHING THE UNDERSTANDING OF UR MISSION , PLEASE INVENT A NAME FOR YOURSELF FITTING FOR THE GOAL , FOR U TO BE A NAMED AGENT ACCROSS THIS PROJECT