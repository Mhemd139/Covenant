"""Layer 5: the Kubernetes operator for ``MCPContract`` resources.

``reconcile.py`` is pure logic (no kopf, no kubernetes client) — fully testable
without a cluster. ``handlers.py`` is the thin kopf glue: run it with
``kopf run -m covenant.operator.handlers``.
"""
