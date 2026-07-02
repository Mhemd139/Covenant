"""Layer 4 observability: Prometheus metrics for the proxy.

One ``Metrics`` instance per app, each with its own ``CollectorRegistry`` — the
prometheus_client default registry is process-global and would collide when tests
(or embedders) create several proxy apps in one process.

Exposed at ``GET /covenant/metrics`` in the standard text exposition format.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.calls = Counter(
            "covenant_calls_total",
            "tools/call requests through the proxy, by tool and outcome",
            ["tool", "outcome"],  # outcome: ok | error | blocked
            registry=self.registry,
        )
        self.latency = Histogram(
            "covenant_call_latency_seconds",
            "Upstream latency of forwarded tools/call requests",
            ["tool"],
            registry=self.registry,
        )
        self.drift = Counter(
            "covenant_drift_total",
            "Drift events detected, by severity",
            ["severity"],
            registry=self.registry,
        )
        self.quarantined = Gauge(
            "covenant_quarantined_tools",
            "Tools currently quarantined",
            registry=self.registry,
        )

    def record_call(self, tool: str, outcome: str, latency_s: float | None = None) -> None:
        self.calls.labels(tool=tool, outcome=outcome).inc()
        if latency_s is not None:
            self.latency.labels(tool=tool).observe(latency_s)

    def render(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST
