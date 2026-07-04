"""Render classifier results: exit codes, machine JSON, and a rich terminal view.

Exit-code policy (Layer 0 is a review gate, not a runtime guard): breaking ⇒ 1;
degraded ⇒ 1 only under ``--strict``; otherwise 0.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from rich.console import Console
from rich.table import Table

from .diff import Change

_TIER_STYLE = {"breaking": "bold red", "degraded": "yellow", "compatible": "green"}
_TIER_ORDER = {"breaking": 0, "degraded": 1, "compatible": 2}


def summarize(changes: list[Change]) -> tuple[str, dict[str, int]]:
    """Worst tier ('clean' when none) plus per-tier counts — the one severity ladder."""
    counts = {"breaking": 0, "degraded": 0, "compatible": 0}
    for c in changes:
        counts[c.tier] += 1
    result = "breaking" if counts["breaking"] else "degraded" if counts["degraded"] else "clean"
    return result, counts


def exit_code(changes: list[Change], strict: bool) -> int:
    result, _ = summarize(changes)
    return 1 if result == "breaking" or (strict and result == "degraded") else 0


def to_json(changes: list[Change]) -> str:
    return json.dumps([asdict(c) for c in changes], indent=2)


def render(changes: list[Change], strict: bool, console: Console | None = None) -> None:
    console = console or Console()
    if not changes:
        console.print("[green]OK no drift[/green] - contract matches the baseline.")
        console.print("[dim]note: schemas and configured probes only - unprobed behavior "
                      "and description materiality are not checked.[/dim]")
        return

    table = Table(title="Covenant - contract drift", show_lines=False)
    table.add_column("tier", no_wrap=True)
    table.add_column("location", no_wrap=True)
    table.add_column("change")

    for c in sorted(changes, key=lambda c: (_TIER_ORDER.get(c.tier, 9), c.location)):
        style = _TIER_STYLE.get(c.tier, "")
        msg = c.message + (f"  [dim]({c.note})[/dim]" if c.note else "")
        table.add_row(f"[{style}]{c.tier.upper()}[/{style}]", c.location, msg)

    console.print(table)

    _, counts = summarize(changes)
    breaking, degraded = counts["breaking"], counts["degraded"]
    if breaking:
        console.print(f"[bold red]x {breaking} breaking change(s)[/bold red] - "
                      "downstream agents would fail silently. Fix or quarantine.")
    elif degraded and strict:
        console.print(f"[yellow]x {degraded} degraded change(s)[/yellow] - failing under --strict.")
    elif degraded:
        console.print(f"[yellow]! {degraded} degraded change(s)[/yellow] - review; "
                      "not failing (use --strict to fail).")
    else:
        console.print("[green]OK only compatible changes.[/green]")
