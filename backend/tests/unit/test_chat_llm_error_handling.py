from unittest.mock import MagicMock, patch

import httpx
import openai
from fastapi.testclient import TestClient
from langgraph.errors import GraphRecursionError

from app.api.session_manager import session_manager
from app.main import app


def _fake_timeout_error() -> openai.APITimeoutError:
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    return openai.APITimeoutError(request=request)


def test_chat_returns_504_on_llm_timeout_not_bare_500():
    with (
        patch.object(session_manager, "get", return_value=MagicMock()),
        patch.object(session_manager, "send_message", side_effect=_fake_timeout_error()),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/chat", json={"session_id": "fake-session", "message": "hello"})

    assert resp.status_code == 504
    detail = resp.json()["detail"]
    assert "model" in detail.lower()
    assert "try again" in detail.lower()


def test_chat_returns_504_on_graph_recursion_limit_not_bare_500():
    error = GraphRecursionError("Recursion limit of 60 reached without hitting a stop condition.")

    with (
        patch.object(session_manager, "get", return_value=MagicMock()),
        patch.object(session_manager, "send_message", side_effect=error),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/chat", json={"session_id": "fake-session", "message": "hello"})

    assert resp.status_code == 504
    detail = resp.json()["detail"]
    assert "smaller" in detail.lower() or "steps" in detail.lower()


def test_chat_returns_504_on_llm_api_status_error_eg_retired_model():
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    response = httpx.Response(410, request=request, json={"detail": "model retired"})
    error = openai.APIStatusError("model retired", response=response, body={"detail": "model retired"})

    with (
        patch.object(session_manager, "get", return_value=MagicMock()),
        patch.object(session_manager, "send_message", side_effect=error),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/chat", json={"session_id": "fake-session", "message": "hello"})

    assert resp.status_code == 504
