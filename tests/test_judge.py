"""The semantic judge: prompt payload, verdict parsing, loud failures."""

import pytest

import covenant.judge as judge_mod
from covenant.errors import CovenantError
from covenant.judge import Verdict, judge_probe


def _fake_complete(reply):
    calls = {}

    def fake(model, system, user):
        calls["model"], calls["system"], calls["user"] = model, system, user
        return reply

    return fake, calls


def test_drift_verdict_parsed_and_payload_carries_both_responses(monkeypatch):
    fake, calls = _fake_complete('{"drift": true, "reason": "balance rescaled to cents"}')
    monkeypatch.setattr(judge_mod, "_complete", fake)
    v = judge_probe("get_account", "desc", {"id": "a"}, {"balance_usd": 42.5},
                    {"balance_usd": 4250.0})
    assert v == Verdict(drift=True, reason="balance rescaled to cents")
    assert "42.5" in calls["user"]
    assert "4250.0" in calls["user"]
    assert calls["model"] == judge_mod.DEFAULT_MODEL


def test_fenced_json_is_tolerated(monkeypatch):
    fake, _ = _fake_complete('```json\n{"drift": false, "reason": "same meaning"}\n```')
    monkeypatch.setattr(judge_mod, "_complete", fake)
    assert judge_probe("t", None, {}, {}, {}).drift is False


def test_unparseable_verdict_is_loud(monkeypatch):
    fake, _ = _fake_complete("cannot judge, sorry")
    monkeypatch.setattr(judge_mod, "_complete", fake)
    with pytest.raises(CovenantError):
        judge_probe("t", None, {}, {}, {})


def test_model_override_wins(monkeypatch):
    fake, calls = _fake_complete('{"drift": false, "reason": "ok"}')
    monkeypatch.setattr(judge_mod, "_complete", fake)
    judge_probe("t", None, {}, {}, {}, model="custom-model")
    assert calls["model"] == "custom-model"


def test_gemini_models_route_to_google(monkeypatch):
    fake, calls = _fake_complete('{"drift": false, "reason": "ok"}')
    monkeypatch.setattr(judge_mod, "_complete_google", fake)
    judge_probe("t", None, {}, {}, {}, model="gemini-2.5-flash")
    assert calls["model"] == "gemini-2.5-flash"


def test_default_model_routes_to_anthropic(monkeypatch):
    fake, calls = _fake_complete('{"drift": false, "reason": "ok"}')
    monkeypatch.setattr(judge_mod, "_complete_anthropic", fake)
    judge_probe("t", None, {}, {}, {})
    assert calls["model"] == judge_mod.DEFAULT_MODEL
