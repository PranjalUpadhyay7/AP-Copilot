import os

import pytest
from fastapi.testclient import TestClient

INSTANCE = 35
ARDUPILOT_ROOT = os.environ.get("ARDUPILOT_ROOT") or os.path.expanduser("~/ardupilot")


@pytest.fixture
def client(monkeypatch, tmp_path):
    if not os.path.exists(os.path.join(ARDUPILOT_ROOT, "Tools/autotest/sim_vehicle.py")):
        pytest.skip(f"ArduPilot checkout not found at {ARDUPILOT_ROOT}")

    monkeypatch.setenv("ARDUPILOT_ROOT", ARDUPILOT_ROOT)
    import app.api.session_manager as sm

    monkeypatch.setattr(sm, "ARDUPILOT_ROOT", ARDUPILOT_ROOT)
    monkeypatch.setattr(sm, "AUDIT_DB_PATH", tmp_path / "audit.sqlite3")
    monkeypatch.setattr(sm, "DEFAULT_CHECKPOINT_DB", tmp_path / "checkpoints.sqlite3")
    from tests.adversarial_llm.fake_chat_model import ScriptedChatModel

    monkeypatch.setattr(sm, "get_nim_chat_model", lambda: ScriptedChatModel(responses=[]))

    from app.main import app
    with TestClient(app) as c:
        yield c


def _sitl_process_running() -> bool:
    import subprocess

    out = subprocess.run(["ps", "aux"], capture_output=True, text=True, check=True).stdout
    return f"-I {INSTANCE}" in out or f"-I{INSTANCE}" in out


def test_simulation_mode_launches_and_tears_down_sitl(client):
    assert not _sitl_process_running(), f"instance {INSTANCE} already running -- test isolation violated"

    start_resp = client.post("/session/start", json={
        "mode": "simulation",
        "sitl_settings": {"vehicle": "copter", "instance": INSTANCE, "wipe_eeprom": True, "speedup": 1},
    })
    assert start_resp.status_code == 200, start_resp.text
    data = start_resp.json()
    assert data["vehicle_type"] == "ArduCopter"
    assert data["read_only"] is False
    session_id = data["session_id"]

    assert _sitl_process_running(), "backend claimed success but no SITL process for this instance is running"

    status_resp = client.get("/vehicle/status", params={"session_id": session_id})
    assert status_resp.status_code == 200
    assert status_resp.json()["connected"] is True

    end_resp = client.post("/session/end", params={"session_id": session_id})
    assert end_resp.status_code == 200

    import time
    deadline = time.time() + 20
    while time.time() < deadline and _sitl_process_running():
        time.sleep(1)
    assert not _sitl_process_running(), "SITL process for this instance was not terminated by /session/end"


def test_simulation_mode_rejects_unknown_vehicle(client):
    resp = client.post("/session/start", json={
        "mode": "simulation",
        "sitl_settings": {"vehicle": "rover", "instance": INSTANCE},
    })
    assert resp.status_code == 502
    assert "unknown simulated vehicle" in resp.json()["detail"]
