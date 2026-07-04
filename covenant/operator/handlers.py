"""kopf glue for the MCPContract operator: ``kopf run -m covenant.operator.handlers``.

A timer fires every POLL_S per resource; ``reconcile.due`` gates it to the CR's own
``spec.intervalSeconds`` so each contract keeps its own schedule. Every failure mode
lands in ``status.result`` — the operator never crash-loops on one bad contract.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import kopf
from kubernetes import client as k8s
from kubernetes import config as k8s_config

from ..config import DEFAULT_BASELINE
from ..errors import CovenantError
from . import reconcile

log = logging.getLogger("covenant.operator")

GROUP, VERSION, PLURAL = "covenant.dev", "v1alpha1", "mcpcontracts"
POLL_S = 30
_REFRESH_TIMEOUT_S = 10.0
# Sync handlers share one thread pool; a check blocks its slot for up to the MCP
# transport timeout, so the default pool (cpus+4) would let a few hung servers
# starve every other CR's timer. Sized for hundreds of CRs; tunable.
_MAX_WORKERS = 32


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_: Any) -> None:
    settings.execution.max_workers = _MAX_WORKERS
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()  # local development against a kubeconfig


def _baseline_text(spec: kopf.Spec, namespace: str) -> str:
    ref = spec["baselineConfigMap"]
    cm = k8s.CoreV1Api().read_namespaced_config_map(ref["name"], namespace)
    key = ref.get("key", DEFAULT_BASELINE)
    text = (cm.data or {}).get(key)
    if text is None:
        raise CovenantError(f"configmap {ref['name']} has no key {key!r}")
    return str(text)


@kopf.timer(GROUP, VERSION, PLURAL, interval=POLL_S)
def check(*, spec: kopf.Spec, status: kopf.Status, namespace: str | None,
          patch: kopf.Patch, **_: Any) -> None:
    interval = int(spec.get("intervalSeconds", reconcile.DEFAULT_INTERVAL_S))
    now = datetime.now(UTC)
    if not reconcile.due(status.get("lastCheckTime"), interval, now):
        return

    try:
        # MCPContract is namespaced; kopf types namespace optional for cluster scope.
        baseline = _baseline_text(spec, namespace or "default")
        server_url = str(spec["server"])  # required by the CRD; guarded anyway
    except Exception as e:  # noqa: BLE001 - a misconfigured CR is status, not a crash-loop
        patch.status.update(
            reconcile.error_status(now, f"misconfigured MCPContract: {e}"))
        return

    result = reconcile.check_contract(server_url, baseline, now)
    patch.status.update(result)

    # Nudge the proxy to re-check and quarantine; best-effort, like store writes.
    refresh_url = spec.get("proxyRefreshUrl")
    if refresh_url and result.get("result") != "error":
        try:
            httpx.post(str(refresh_url), timeout=_REFRESH_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            log.warning("proxy refresh failed (%s): %s", refresh_url, e)
