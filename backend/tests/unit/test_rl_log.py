import json

import pytest

from app.telemetry import rl_log


def _lines():
    return [json.loads(line) for line in rl_log.log_path().read_text().splitlines()]


def test_turn_without_tool_calls_is_not_logged():
    assert rl_log.log_episode(session_id="s", user_problem="hi", approaches_tried=[], final_outcome="answered") is None
    assert not rl_log.log_path().exists()


def test_episode_then_updates_are_separate_append_only_lines():
    ep = rl_log.log_episode(
        session_id="s", user_problem="fix RTL", approaches_tried=[{"stage": "tool_call"}], final_outcome="pending_confirmation",
    )
    rl_log.log_update(ep, final_outcome="proposed_accepted")
    rl_log.log_resolution_signal(ep, "worked")
    first, second, third = _lines()
    assert first["record"] == "episode" and first["resolution_signal"] == "not_asked"
    assert first["user_problem"] == "fix RTL" and first["episode_id"] == ep
    assert second == {**second, "record": "update", "episode_id": ep, "final_outcome": "proposed_accepted"}
    assert third["resolution_signal"] == "worked"


def test_invalid_resolution_signal_rejected():
    with pytest.raises(ValueError):
        rl_log.log_resolution_signal("e", "probably")


def test_unwritable_log_never_raises(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("AP_COPILOT_RL_LOG", str(blocker / "log.jsonl"))  # parent is a file
    assert rl_log.log_episode(session_id="s", user_problem="p", approaches_tried=[{}], final_outcome="answered")


def test_feedback_endpoint_records_explicit_answer_and_404s_unknown_session(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.session_manager import session_manager
    from app.main import app

    client = TestClient(app)
    monkeypatch.setattr(session_manager, "get", lambda sid: object() if sid == "good" else (_ for _ in ()).throw(KeyError(sid)))
    ok = client.post("/episodes/e1/feedback", json={"session_id": "good", "worked": False})
    assert ok.status_code == 200 and ok.json() == {"recorded": True}
    assert _lines()[-1] == {**_lines()[-1], "episode_id": "e1", "resolution_signal": "did_not_work"}
    assert client.post("/episodes/e1/feedback", json={"session_id": "bad", "worked": True}).status_code == 404
