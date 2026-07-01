"""The `covenant` CLI: `snapshot` writes a baseline, `check` diffs against it.

Typed CovenantErrors render as one clean line with exit code 2; a breaking drift
(or degraded under --strict) exits 1; a clean check exits 0.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from . import report
from .config import load_config
from .contract import contract_from_tool, read_baseline, write_baseline
from .diff import diff_tools
from .errors import CovenantError
from .introspect import introspect

app = typer.Typer(add_completion=False, help="A contract linter for MCP servers.")
console = Console()
err = Console(stderr=True)

_server_opt = typer.Option(
    None, "--server", "-s", help="Override server: an http(s) URL or a launch command."
)


@app.command()
def snapshot(
    server: str = _server_opt,
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing baseline."),
) -> None:
    """Introspect the server and write its tool contracts to the baseline."""
    try:
        cfg = load_config(server_override=server)
        path = Path(cfg.baseline_path)
        if path.exists() and not force:
            raise CovenantError(f"baseline already exists: {path} (use --force to overwrite)")

        tools = introspect(cfg)
        contracts = [contract_from_tool(t) for t in tools]
        target = cfg.server_url or cfg.server_command or ""
        write_baseline(path, contracts, server=target)
    except CovenantError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(2) from e

    console.print(f"[green]OK snapshotted {len(contracts)} tool(s)[/green] -> {path}")
    for c in contracts:
        console.print(f"  [cyan]{c.name}[/cyan]  [dim]{c.schema_hash[:19]}...[/dim]")


@app.command()
def check(
    server: str = _server_opt,
    strict: bool = typer.Option(False, "--strict", help="Fail on degraded changes too."),
    json_out: bool = typer.Option(False, "--json", help="Emit changes as JSON."),
) -> None:
    """Diff the live server against the baseline and classify every change."""
    try:
        cfg = load_config(server_override=server)
        _, base_tools = read_baseline(cfg.baseline_path)
        current = introspect(cfg)
    except CovenantError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(2) from e

    changes = diff_tools(base_tools, current)
    if json_out:
        console.print_json(report.to_json(changes))
    else:
        report.render(changes, strict=strict, console=console)

    raise typer.Exit(report.exit_code(changes, strict=strict))


if __name__ == "__main__":
    app()
