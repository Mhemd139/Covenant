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


@app.command()
def proxy(
    upstream: str = typer.Option(..., "--upstream", "-u", help="Upstream MCP server URL to guard."),
    baseline: str = typer.Option("covenant.lock.json", "--baseline", "-b"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(9000, "--port", "-p"),
) -> None:
    """Run the transparent proxy: forward to the upstream, quarantine drifted tools."""
    try:
        import uvicorn

        from .proxy.server import create_app
    except ImportError as e:
        err.print('[red]error:[/red] proxy needs extras: pip install "covenant-mcp[proxy]"')
        raise typer.Exit(2) from e

    try:
        _, base_tools = read_baseline(baseline)
    except CovenantError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(2) from e

    fastapi_app = create_app(upstream, base_tools)
    console.print(f"[green]Covenant proxy[/green] guarding [cyan]{upstream}[/cyan] "
                  f"at [cyan]http://{host}:{port}/mcp[/cyan]")
    console.print(f"[dim]baseline: {baseline} ({len(base_tools)} tools) | "
                  f"POST http://{host}:{port}/covenant/refresh to re-check[/dim]")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
