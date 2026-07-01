"""Tests for the pure reporting logic: exit codes and JSON output."""

import json

from covenant.diff import Change
from covenant.report import exit_code, to_json


def ch(tier, kind="removed", location="output"):
    return Change("t", location, "f", kind, tier, "msg")


def test_exit_code_zero_when_only_compatible():
    assert exit_code([ch("compatible")], strict=False) == 0


def test_exit_code_zero_when_degraded_and_not_strict():
    assert exit_code([ch("degraded")], strict=False) == 0


def test_exit_code_one_when_breaking():
    assert exit_code([ch("breaking"), ch("compatible")], strict=False) == 1


def test_exit_code_one_when_degraded_and_strict():
    assert exit_code([ch("degraded")], strict=True) == 1


def test_exit_code_zero_for_no_changes():
    assert exit_code([], strict=False) == 0


def test_to_json_is_machine_readable():
    out = to_json([ch("breaking")])
    data = json.loads(out)
    assert data[0]["tier"] == "breaking"
    assert data[0]["kind"] == "removed"
    assert data[0]["location"] == "output"
