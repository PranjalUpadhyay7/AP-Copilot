import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app.comms.sitl_manager import terminate as _terminate_sitl

ARDUPILOT_ROOT = os.environ.get("ARDUPILOT_ROOT") or os.path.expanduser("~/ardupilot")
SIM_VEHICLE = os.path.join(ARDUPILOT_ROOT, "Tools/autotest/sim_vehicle.py")
SITL_PYTHON = os.environ.get("SITL_PYTHON", "/usr/bin/python3")

INSTANCE = 31
PORT = 5760 + 10 * INSTANCE


def _sitl_env() -> dict:
    env = dict(os.environ)
    for var in ("DISPLAY", "TMUX", "STY", "ZELLIJ", "SITL_RITW_TERMINAL"):
        env.pop(var, None)
    return env


def _wait_port(port: int, deadline: float) -> None:
    import socket

    last_err = None
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return
        except OSError as e:
            last_err = e
            time.sleep(2)
    raise TimeoutError(f"port {port} never opened: {last_err}")


@pytest.fixture
def sitl_copter():
    if not os.path.exists(SIM_VEHICLE):
        pytest.skip(f"ArduPilot checkout not found at {ARDUPILOT_ROOT}")
    proc = subprocess.Popen(
        [SITL_PYTHON, SIM_VEHICLE, "-v", "ArduCopter", "-f", "quad", "-I", str(INSTANCE),
         "--no-mavproxy", "--no-rebuild", "-w"],
        cwd=ARDUPILOT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=_sitl_env(),
    )
    try:
        _wait_port(PORT, time.time() + 180)
        yield f"tcp:127.0.0.1:{PORT}"
    finally:
        _terminate_sitl(proc)


@pytest.fixture
def client(monkeypatch, tmp_path):
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


def test_compass_calibration_procedure_end_to_end(sitl_copter, client):
    start_resp = client.post("/session/start", json={"connection_string": sitl_copter})
    assert start_resp.status_code == 200, start_resp.text
    session_id = start_resp.json()["session_id"]

    # Start the named procedure.
    proc_resp = client.post("/procedures/compass-calibration/start", params={"session_id": session_id})
    assert proc_resp.status_code == 200, proc_resp.text
    procedure = proc_resp.json()
    assert procedure["title"] == "Compass calibration"
    assert len(procedure["steps"]) >= 3
    manual_steps = [s for s in procedure["steps"] if s["manual"]]
    automatable_steps = [s for s in procedure["steps"] if not s["manual"]]
    assert manual_steps, "expected at least one human-manual step (rotating the vehicle)"
    assert automatable_steps, "expected the trigger step to be automatable"
    procedure_id = procedure["procedure_id"]

    # It's reflected as pending.
    list_resp = client.get("/procedures", params={"session_id": session_id})
    assert [p["procedure_id"] for p in list_resp.json()] == [procedure_id]

    # Confirm -> triggers MAV_CMD_DO_START_MAG_CAL against real SITL.
    confirm_resp = client.post(f"/procedures/{procedure_id}/confirm", json={"session_id": session_id})
    assert confirm_resp.status_code == 200, confirm_resp.text
    outcome = confirm_resp.json()["outcome"]
    assert outcome == "triggered", confirm_resp.json()

    # Resolved -- no longer pending.
    list_resp2 = client.get("/procedures", params={"session_id": session_id})
    assert list_resp2.json() == []

    client.post("/session/end", params={"session_id": session_id})


def test_rejecting_procedure_never_triggers_it(sitl_copter, client):
    start_resp = client.post("/session/start", json={"connection_string": sitl_copter})
    session_id = start_resp.json()["session_id"]

    proc_resp = client.post("/procedures/compass-calibration/start", params={"session_id": session_id})
    procedure_id = proc_resp.json()["procedure_id"]

    reject_resp = client.post(f"/procedures/{procedure_id}/reject", json={"session_id": session_id})
    assert reject_resp.status_code == 200
    assert reject_resp.json()["outcome"] == "rejected"

    client.post("/session/end", params={"session_id": session_id})
