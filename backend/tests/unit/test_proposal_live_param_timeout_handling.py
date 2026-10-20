from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.session_manager import session_manager
from app.main import app


def test_confirm_returns_502_not_a_bare_500_on_live_param_timeout():
    with (
        patch.object(session_manager, "get", return_value=MagicMock()),
        patch.object(session_manager, "resolve_proposal", side_effect=TimeoutError("only received 621/1408 params")),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/proposals/some-id/confirm", json={"session_id": "fake-session"})

    assert resp.status_code == 502
    assert "try again" in resp.json()["detail"].lower()


def test_revise_returns_502_not_a_bare_500_on_live_param_timeout():
    with (
        patch.object(session_manager, "get", return_value=MagicMock()),
        patch.object(session_manager, "revise_proposal", side_effect=TimeoutError("only received 621/1408 params")),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/proposals/some-id/revise", json={"session_id": "fake-session", "new_value": 1.0})

    assert resp.status_code == 502


def test_rollback_returns_502_not_a_bare_500_on_live_param_timeout():
    with (
        patch.object(session_manager, "get", return_value=MagicMock()),
        patch.object(session_manager, "propose_rollback", side_effect=TimeoutError("only received 621/1408 params")),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/audit/1/rollback", json={"session_id": "fake-session"})

    assert resp.status_code == 502
