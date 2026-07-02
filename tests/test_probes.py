"""Layer 3 probe pipeline: config parsing, lock round-trip, and fingerprint diffs."""

import pytest

from covenant.config import load_config
from covenant.contract import read_baseline, write_baseline
from covenant.diff import diff_probes
from covenant.errors import ConfigError
from covenant.fingerprint import fingerprint


def _probe(tool, response, args=None):
    return {
        "tool": tool, "args": args or {},
        "fingerprint": fingerprint(response), "sample": response,
    }


def _live(tool, response, args=None, is_error=False, error=None):
    return {
        "tool": tool, "args": args or {},
        "response": response, "is_error": is_error, "error": error,
    }


def test_lost_response_field_is_breaking():
    base = [_probe("get_txns", {"amount_usd": 1.0, "merchant": "x"})]
    live = [_live("get_txns", {"amount_cents": 100, "merchant": "x"})]
    changes = diff_probes(base, live)
    kinds = {(c.kind, c.tier) for c in changes}
    assert ("removed", "breaking") in kinds  # amount_usd gone: silent lie
    assert ("added", "compatible") in kinds  # amount_cents new: additive
    assert all(c.location == "behavior" for c in changes)


def test_nested_array_field_loss_is_breaking():
    base = [_probe("t", {"txns": [{"amount_usd": 1.0}, {"amount_usd": 2.0}]})]
    live = [_live("t", {"txns": [{"amount_cents": 100}, {"amount_cents": 200}]})]
    fields = {(c.field, c.tier) for c in diff_probes(base, live)}
    assert ("txns[].amount_usd", "breaking") in fields


def test_scalar_retype_is_degraded():
    base = [_probe("t", {"balance": 42.5})]
    live = [_live("t", {"balance": "42.50"})]
    (c,) = diff_probes(base, live)
    assert (c.kind, c.tier) == ("type_changed_scalar", "degraded")


def test_value_change_same_shape_is_clean():
    base = [_probe("t", {"balance": 42.5})]
    live = [_live("t", {"balance": 4250.0})]  # cents pun: invisible to shape, the judge's job
    assert diff_probes(base, live) == []


def test_probe_error_is_degraded_and_loud():
    base = [_probe("t", {"ok": 1})]
    live = [_live("t", None, is_error=True, error="boom")]
    (c,) = diff_probes(base, live)
    assert c.tier == "degraded"
    assert c.kind == "probe_errored"
    assert "boom" in c.message


def test_probes_matched_by_args_identity():
    base = [_probe("t", {"a": 1}, args={"id": "x"})]
    live = [_live("t", {"a": 1}, args={"id": "x"}), _live("t", {}, args={"id": "y"})]
    assert diff_probes(base, live) == []  # unmatched live probe skipped; CLI gates that state


def test_lock_round_trips_probes_sorted(tmp_path):
    path = tmp_path / "covenant.lock.json"
    probes = [_probe("b", {"x": 1}), _probe("a", {"y": "z"})]
    write_baseline(path, [], server="cmd", probes=probes)
    _, _, loaded = read_baseline(path)
    assert [p["tool"] for p in loaded] == ["a", "b"]  # sorted: lock stays deterministic
    assert loaded[1]["fingerprint"] == fingerprint({"x": 1})
    assert loaded[1]["sample"] == {"x": 1}


def test_config_parses_probes_and_judge_model(tmp_path):
    cfg_file = tmp_path / "covenant.toml"
    cfg_file.write_text(
        '[server]\ncommand = "python x.py"\n'
        '[judge]\nmodel = "my-model"\n'
        '[[probes]]\ntool = "get_account"\nargs = { account_id = "a-1" }\n'
        '[[probes]]\ntool = "ping"\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert [(p.tool, p.args) for p in cfg.probes] == [
        ("get_account", {"account_id": "a-1"}), ("ping", {}),
    ]
    assert cfg.judge_model == "my-model"


def test_config_rejects_probe_without_tool(tmp_path):
    cfg_file = tmp_path / "covenant.toml"
    cfg_file.write_text('[server]\ncommand = "x"\n[[probes]]\nargs = { a = 1 }\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfg_file)
