"""Tests for config loading (covenant.toml + CLI overrides)."""

import pytest

from covenant.config import load_config
from covenant.errors import ConfigError


def write_toml(tmp_path, text):
    p = tmp_path / "covenant.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_stdio_command_and_baseline_path(tmp_path):
    p = write_toml(tmp_path, """
[server]
command = "python examples/mcp_server.py"
[baseline]
path = "covenant.lock.json"
""")
    cfg = load_config(p)
    assert cfg.server_command == "python examples/mcp_server.py"
    assert cfg.server_url is None
    assert cfg.baseline_path == "covenant.lock.json"


def test_loads_http_url(tmp_path):
    p = write_toml(tmp_path, """
[server]
url = "http://localhost:8000/mcp"
""")
    cfg = load_config(p)
    assert cfg.server_url == "http://localhost:8000/mcp"
    assert cfg.server_command is None


def test_baseline_path_defaults(tmp_path):
    p = write_toml(tmp_path, '[server]\ncommand = "x"\n')
    cfg = load_config(p)
    assert cfg.baseline_path == "covenant.lock.json"


def test_server_override_url(tmp_path):
    p = write_toml(tmp_path, '[server]\ncommand = "x"\n')
    cfg = load_config(p, server_override="http://host/mcp")
    assert cfg.server_url == "http://host/mcp"
    assert cfg.server_command is None


def test_server_override_command(tmp_path):
    p = write_toml(tmp_path, '[server]\nurl = "http://host/mcp"\n')
    cfg = load_config(p, server_override="python server.py")
    assert cfg.server_command == "python server.py"
    assert cfg.server_url is None


def test_missing_config_and_no_override_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")


def test_override_works_without_config_file(tmp_path):
    cfg = load_config(tmp_path / "nope.toml", server_override="python server.py")
    assert cfg.server_command == "python server.py"


def test_neither_command_nor_url_raises(tmp_path):
    p = write_toml(tmp_path, "[baseline]\npath = 'x.json'\n")
    with pytest.raises(ConfigError):
        load_config(p)
