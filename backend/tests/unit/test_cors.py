from fastapi.testclient import TestClient

from app.main import app


def test_preflight_for_session_start_succeeds():
    with TestClient(app) as client:
        resp = client.options(
            "/session/start",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "POST" in resp.headers["access-control-allow-methods"]


def test_actual_response_carries_cors_header():
    with TestClient(app) as client:
        resp = client.get("/health", headers={"Origin": "http://tauri.localhost"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"
