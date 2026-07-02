"""Layer 1 — the transparent MCP proxy that quarantines drifted tools.

Reuses the Layer 0 classifier (``covenant.diff``) and contract model
(``covenant.contract``) unchanged; adds only live proxying, detection, and an
in-memory quarantine. Requires the optional ``proxy`` extra (fastapi/uvicorn/httpx).
"""
