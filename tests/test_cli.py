"""End-to-end CLI tests: snapshot -> (flip drift lever) -> check, asserting exit codes."""

import sys
from pathlib import Path

from typer.testing import CliRunner

from covenant.cli import app

runner = CliRunner()

EXAMPLE = str((Path(__file__).parent.parent / "examples" / "mcp_server.py").resolve())
SERVER = f'"{sys.executable}" "{EXAMPLE}"'


def test_snapshot_then_clean_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["snapshot", "--server", SERVER])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "covenant.lock.json").exists()

    r = runner.invoke(app, ["check", "--server", SERVER])
    assert r.exit_code == 0, r.output


def test_drift_is_caught_as_breaking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["snapshot", "--server", SERVER])

    monkeypatch.setenv("COVENANT_DRIFT", "1")  # inherited by the introspected subprocess
    r = runner.invoke(app, ["check", "--server", SERVER])
    assert r.exit_code == 1, r.output
    assert "balance_usd" in r.output
    assert "BREAKING" in r.output


def test_drift_json_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["snapshot", "--server", SERVER])
    monkeypatch.setenv("COVENANT_DRIFT", "1")
    r = runner.invoke(app, ["check", "--server", SERVER, "--json"])
    assert r.exit_code == 1
    assert '"tier": "breaking"' in r.output


def test_snapshot_refuses_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["snapshot", "--server", SERVER])
    r = runner.invoke(app, ["snapshot", "--server", SERVER])
    assert r.exit_code == 2
    r = runner.invoke(app, ["snapshot", "--server", SERVER, "--force"])
    assert r.exit_code == 0


def test_check_without_baseline_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["check", "--server", SERVER])
    assert r.exit_code == 2
