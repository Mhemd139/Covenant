"""Layer 1 live demo — nothing simulated.

A real MCP client calls a real tool through the Covenant proxy, in front of a real
MCP server. We ship a real breaking change (rename an output field), let Covenant
detect + quarantine it, and watch the SAME client fail safe instead of reading the
wrong shape. Run from the repo root:  python examples/demo_layer1.py
"""

import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

PY = sys.executable
SERVER_PORT = 8000
PROXY_PORT = 9000
UPSTREAM = f"http://127.0.0.1:{SERVER_PORT}/mcp"
PROXY = f"http://127.0.0.1:{PROXY_PORT}/mcp"
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


def start_server(drift: bool) -> subprocess.Popen:
    env = dict(os.environ, COVENANT_HTTP="1", PORT=str(SERVER_PORT))
    env.pop("COVENANT_DRIFT", None)
    if drift:
        env["COVENANT_DRIFT"] = "1"
    p = subprocess.Popen([PY, "examples/mcp_server.py"], env=env)
    wait_port(SERVER_PORT)
    return p


def start_proxy() -> subprocess.Popen:
    env = dict(os.environ)
    env.pop("COVENANT_DRIFT", None)
    p = subprocess.Popen(
        [PY, "-m", "covenant.cli", "proxy", "--upstream", UPSTREAM, "--port", str(PROXY_PORT)],
        env=env,
    )
    wait_port(PROXY_PORT)
    return p


async def get_account(url: str) -> str:
    async with (
        streamablehttp_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        res = await session.call_tool("get_account", {"account_id": "acct-001"})
        if res.isError:
            return "BLOCKED -> " + (res.content[0].text if res.content else "error")
        shape = res.structuredContent or (res.content[0].text if res.content else res)
        return "OK -> " + str(shape)


def stop(*procs: subprocess.Popen) -> None:
    for p in procs:
        with contextlib.suppress(Exception):
            p.terminate()
    for p in procs:
        with contextlib.suppress(Exception):
            p.wait(timeout=5)


async def main() -> None:
    server = start_server(drift=False)
    proxy = start_proxy()
    try:
        print("\n1. agent asks for a balance THROUGH the proxy (clean):")
        print("   ", await get_account(PROXY))

        print("\n2. Covenant refresh (clean) -> quarantine:")
        print("   ", httpx.post(REFRESH, timeout=10).json()["quarantined"])

        print("\n3. ship a breaking change: restart the server with balance_usd renamed...")
        stop(server)
        server = start_server(drift=True)

        print("\n4. Covenant refresh again -> it catches the break and quarantines:")
        print("   ", httpx.post(REFRESH, timeout=10).json()["quarantined"])

        print("\n5. the SAME agent asks again THROUGH the proxy -> fails safe:")
        print("   ", await get_account(PROXY))

        print("\n6. the agent asks the server DIRECTLY (no proxy) -> silent wrong shape:")
        print("   ", await get_account(UPSTREAM))
        print()
    finally:
        stop(server, proxy)


if __name__ == "__main__":
    asyncio.run(main())
