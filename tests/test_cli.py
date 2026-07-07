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


def _write_toml(tmp_path, extra=""):
    (tmp_path / "covenant.toml").write_text(
        f"[server]\ncommand = '{SERVER}'\n{extra}", encoding="utf-8"
    )


def test_probes_catch_behavioral_drift(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_toml(tmp_path, '\n[[probes]]\ntool = "get_transactions"\n'
                          'args = { account_id = "acct-001" }\n')
    r = runner.invoke(app, ["snapshot"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["check"])
    assert r.exit_code == 0, r.output

    monkeypatch.setenv("COVENANT_BEHAVIOR_DRIFT", "1")  # schema identical; response body lies
    r = runner.invoke(app, ["check"])
    assert r.exit_code == 1, r.output
    assert "amount_usd" in r.output
    assert "BREAKING" in r.output
    assert "behavior" in r.output


def test_pins_catch_value_drift(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_toml(tmp_path, '\n[[probes]]\ntool = "get_account"\n'
                          'args = { account_id = "acct-001" }\n'
                          'expect = { balance_usd = 4210.0, currency = "USD" }\n')
    runner.invoke(app, ["snapshot"])
    r = runner.invoke(app, ["check"])
    assert r.exit_code == 0, r.output

    monkeypatch.setenv("COVENANT_SEMANTIC_DRIFT", "1")  # same schema, same shape, value x100
    r = runner.invoke(app, ["check"])
    assert r.exit_code == 1, r.output
    assert "balance_usd" in r.output
    assert "BREAKING" in r.output


def test_probe_missing_from_baseline_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_toml(tmp_path)
    runner.invoke(app, ["snapshot"])
    _write_toml(tmp_path, '\n[[probes]]\ntool = "get_weather"\nargs = { city = "Haifa" }\n')
    r = runner.invoke(app, ["check"])
    assert r.exit_code == 2
    assert "snapshot" in r.output


def test_judge_without_probes_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["snapshot", "--server", SERVER])
    r = runner.invoke(app, ["check", "--server", SERVER, "--judge"])
    assert r.exit_code == 2
