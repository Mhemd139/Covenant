"""The `covenant` CLI: `snapshot` writes a baseline, `check` diffs against it.

Typed CovenantErrors render as one clean line with exit code 2; a breaking drift
(or degraded under --strict) exits 1; a clean check exits 0.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from . import report
from ._types import JsonDict
from .config import Config, load_config
from .contract import contract_from_tool, read_baseline, write_baseline
from .diff import Change, diff_probes, diff_tools
from .errors import CovenantError
from .fingerprint import fingerprint, probe_key
from .introspect import introspect, run_probes

app = typer.Typer(add_completion=False, help="A contract linter for MCP servers.")
console = Console()
err = Console(stderr=True)

_server_opt = typer.Option(
    None, "--server", "-s", help="Override server: an http(s) URL or a launch command."
)


def _snapshot_probes(cfg: Config) -> list[JsonDict]:
    """Run the configured probes and build their baseline records."""
    records: list[JsonDict] = []
    for r in run_probes(cfg, cfg.probes):
        if r["is_error"]:
            raise CovenantError(f"probe {r['tool']} failed at snapshot: {r['error']}")
        records.append({
            "tool": r["tool"],
            "args": r["args"],
            "fingerprint": fingerprint(r["response"]),
            "sample": r["response"],
        })
    return records


def _check_probes(
    cfg: Config, base_tools: list[JsonDict], base_probes: list[JsonDict], judge: bool
) -> list[Change]:
    """Re-run the probes, diff fingerprints, and (optionally) judge semantics."""
    base_by = {probe_key(p["tool"], p.get("args")): p for p in base_probes}
    missing = [p.tool for p in cfg.probes if probe_key(p.tool, p.args) not in base_by]
    if missing:
        raise CovenantError(
            f"probe(s) not in baseline: {', '.join(missing)} - "
            "re-run `covenant snapshot --force`"
        )
    live = run_probes(cfg, cfg.probes)
    changes = diff_probes(base_probes, live)
    if not judge:
        return changes
    from .judge import judge_probe  # the [judge] extra is optional; import on use

    descriptions = {t["name"]: t.get("description") for t in base_tools}
    # A probe is identified by tool + args, so judge each live probe on its own
    # merits: skip only the probes that themselves errored or shape-drifted, never
    # a clean probe that happens to share a tool name with a drifted sibling.
    for r in live:
        base = base_by[probe_key(r["tool"], r["args"])]  # every live key is baselined (see above)
        if r["is_error"] or diff_probes([base], [r]):
            continue  # errors and shape drift are already reported; judge only clean shapes
        verdict = judge_probe(
            r["tool"], descriptions.get(r["tool"]), r["args"],
            base.get("sample"), r["response"], model=cfg.judge_model,
        )
        if verdict.drift:
            changes.append(Change(
                r["tool"], "behavior", None, "semantic_drift", "degraded",
                f"probe {r['tool']}: semantic drift suspected - {verdict.reason}",
                note="LLM-judge verdict - review manually",
            ))
    return changes


@app.command()
def snapshot(
    server: str | None = _server_opt,
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
        probes = _snapshot_probes(cfg) if cfg.probes else None
        target = cfg.server_url or cfg.server_command or ""
        write_baseline(path, contracts, server=target, probes=probes)
    except CovenantError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(2) from e

    console.print(f"[green]OK snapshotted {len(contracts)} tool(s)[/green] -> {path}")
    for c in contracts:
        console.print(f"  [cyan]{c.name}[/cyan]  [dim]{c.schema_hash[:19]}...[/dim]")
    if probes:
        console.print(f"  [dim]+ {len(probes)} behavioral probe(s) fingerprinted[/dim]")


@app.command()
def check(
    server: str | None = _server_opt,
    strict: bool = typer.Option(False, "--strict", help="Fail on degraded changes too."),
    json_out: bool = typer.Option(False, "--json", help="Emit changes as JSON."),
    judge: bool = typer.Option(
        False, "--judge",
        help="Judge probe responses for semantic drift with an LLM (needs ANTHROPIC_API_KEY).",
    ),
) -> None:
    """Diff the live server against the baseline and classify every change."""
    try:
        cfg = load_config(server_override=server)
        _, base_tools, base_probes = read_baseline(cfg.baseline_path)
        current = introspect(cfg)
        changes = diff_tools(base_tools, current)
        if cfg.probes:
            changes += _check_probes(cfg, base_tools, base_probes, judge)
        elif judge:
            raise CovenantError("--judge needs [[probes]] in covenant.toml to judge")
    except CovenantError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(2) from e
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
    database_url: str | None = typer.Option(
        None, "--database-url", envvar="DATABASE_URL",
        help="Postgres URL to persist quarantine + call log (optional).",
    ),
) -> None:
    """Run the transparent proxy: forward to the upstream, quarantine drifted tools."""
    try:
        try:
            import uvicorn

            from .proxy.server import create_app
        except ImportError as e:
            raise CovenantError('proxy needs extras: pip install "covenant-mcp[proxy]"') from e

        store = None
        if database_url:
            try:
                from .store.postgres import PostgresStore
            except ImportError as e:
                raise CovenantError('persistence needs: pip install "covenant-mcp[store]"') from e
            store = PostgresStore(database_url)

        _, base_tools, _ = read_baseline(baseline)
    except CovenantError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(2) from e

    fastapi_app = create_app(upstream, base_tools, store=store, baseline_path=baseline)
    persistence = "postgres" if store else "in-memory (no persistence)"
    console.print(f"[green]Covenant proxy[/green] guarding [cyan]{upstream}[/cyan] "
                  f"at [cyan]http://{host}:{port}/mcp[/cyan]")
    console.print(f"[dim]baseline: {baseline} ({len(base_tools)} tools) | store: {persistence} | "
                  f"POST http://{host}:{port}/covenant/refresh to re-check[/dim]")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
