"""Warden CLI — the bulletproof terminal surface for the demo.

Reads Warden's HTTP status/calls endpoints and renders tool status (green OK /
red QUARANTINED), the plain-language breaking diff, and the recent call log.

    python -m warden.cli            # one-shot snapshot
    python -m warden.cli --watch    # live refresh
"""

import os
import sys
import time

import httpx
from rich.console import Console
from rich.table import Table

WARDEN_URL = os.environ.get("WARDEN_URL", "http://localhost:8080")
console = Console()


def _fetch() -> tuple[list, list]:
    with httpx.Client(base_url=WARDEN_URL, timeout=5.0) as c:
        status = c.get("/warden/status").json().get("tools", [])
        calls = c.get("/warden/calls", params={"limit": 10}).json().get("calls", [])
    return status, calls


def _status_tables(status: list, calls: list) -> tuple[Table, Table]:
    tools = Table(title="Warden · Tool Contracts", expand=True)
    tools.add_column("Tool", style="bold")
    tools.add_column("Status", justify="center")
    tools.add_column("Contract drift / detail")
    for t in sorted(status, key=lambda x: x["tool"]):
        if t["status"] == "quarantined":
            badge = "[white on red] QUARANTINED [/]"
            detail = "[red]" + (t.get("reason") or "breaking change") + "[/]"
        else:
            badge = "[black on green] OK [/]"
            detail = "[dim]no drift[/]"
        tools.add_row(t["tool"], badge, detail)

    log = Table(title="Recent calls", expand=True)
    log.add_column("Time", style="dim")
    log.add_column("Tool")
    log.add_column("Method")
    log.add_column("Latency", justify="right")
    log.add_column("Result", justify="center")
    for c in calls:
        if c["blocked"]:
            result = "[white on red]BLOCKED[/]"
        elif c["is_error"]:
            result = "[red]ERROR[/]"
        else:
            result = "[green]OK[/]"
        lat = f"{c['latency_ms']} ms" if c["latency_ms"] is not None else "-"
        log.add_row(c["ts"][11:19], c["tool"] or "-", c["method"] or "-", lat, result)
    return tools, log


def render_once() -> None:
    status, calls = _fetch()
    tools, log = _status_tables(status, calls)
    console.print(tools)
    console.print(log)


def watch(interval: float = 1.0) -> None:
    from rich.live import Live
    from rich.console import Group

    with Live(console=console, refresh_per_second=4, screen=False) as live:
        while True:
            status, calls = _fetch()
            tools, log = _status_tables(status, calls)
            live.update(Group(tools, log))
            time.sleep(interval)


if __name__ == "__main__":
    if "--watch" in sys.argv:
        try:
            watch()
        except KeyboardInterrupt:
            pass
    else:
        render_once()
