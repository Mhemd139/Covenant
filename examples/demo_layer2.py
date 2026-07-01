"""Layer 2 demo — quarantine survives a proxy restart (Postgres persistence).

Needs the compose Postgres up (`docker compose up -d db`). Run from the repo root:
    python examples/demo_layer2.py
"""

import contextlib
import os
import socket
import subprocess
import sys
import time

import httpx

PY = sys.executable
DB = "postgresql://covenant:covenant@127.0.0.1:5432/covenant"
SERVER_PORT = 8000
PROXY_PORT = 9000
UPSTREAM = f"http://127.0.0.1:{SERVER_PORT}/mcp"
STATUS = f"http://127.0.0.1:{PROXY_PORT}/covenant/status"
REFRESH = f"http://127.0.0.1:{PROXY_PORT}/covenant/refresh"


def wait_port(port: int, timeout: float = 20.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"port {port} never came up")


def start_server() -> subprocess.Popen:
    env = dict(os.environ, COVENANT_HTTP="1", PORT=str(SERVER_PORT), COVENANT_DRIFT="1")
    p = subprocess.Popen([PY, "examples/mcp_server.py"], env=env)
    wait_port(SERVER_PORT)
    return p


def start_proxy() -> subprocess.Popen:
    env = dict(os.environ, DATABASE_URL=DB)
    env.pop("COVENANT_DRIFT", None)
    p = subprocess.Popen(
        [PY, "-m", "covenant.cli", "proxy", "-u", UPSTREAM, "-p", str(PROXY_PORT)], env=env
    )
    wait_port(PROXY_PORT)
    time.sleep(1.0)  # let startup (store.connect + load_quarantine) finish
    return p


def stop(*procs: subprocess.Popen) -> None:
    for p in procs:
        with contextlib.suppress(Exception):
            p.terminate()
    for p in procs:
        with contextlib.suppress(Exception):
            p.wait(timeout=5)


def main() -> None:
    server = start_server()
    proxy = start_proxy()
    try:
        print("\n1. refresh -> Covenant detects the break and persists quarantine to Postgres:")
        print("   ", httpx.post(REFRESH, timeout=10).json()["quarantined"])

        print("\n2. quarantine before restart:")
        print("   ", httpx.get(STATUS, timeout=10).json()["quarantined"])

        print("\n3. --- kill the proxy and start a FRESH one (no refresh this time) ---")
        stop(proxy)
        proxy = start_proxy()

        print("\n4. quarantine AFTER restart, loaded straight from Postgres (no refresh):")
        print("   ", httpx.get(STATUS, timeout=10).json()["quarantined"])
        print()
    finally:
        stop(server, proxy)


if __name__ == "__main__":
    main()
