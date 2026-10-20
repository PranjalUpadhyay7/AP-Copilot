import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app.comms.sitl_manager import terminate as _terminate_sitl
from tests.adversarial_llm.fake_chat_model import (
    ScriptedChatModel,
    final_message,
    tool_call_message,
)

ARDUPILOT_ROOT = os.environ.get("ARDUPILOT_ROOT") or os.path.expanduser("~/ardupilot")
SIM_VEHICLE = os.path.join(ARDUPILOT_ROOT, "Tools/autotest/sim_vehicle.py")
SITL_PYTHON = os.environ.get("SITL_PYTHON", "/usr/bin/python3")

INSTANCE = 30
PORT = 5760 + 10 * INSTANCE

TEST_PARAM = "LOG_FILE_BUFSIZE"


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

    scripted_model = ScriptedChatModel(responses=[
        tool_call_message(
            "propose_param_change",
            {"name": TEST_PARAM, "new_value": 50.0, "reason": "increase dataflash log buffer"},
            "call_1",
        ),
        final_message("I've proposed increasing LOG_FILE_BUFSIZE to 50 KiB -- please review."),
    ])
    monkeypatch.setattr(sm, "get_nim_chat_model", lambda: scripted_model)

    from app.main import app
    with TestClient(app) as c:
        yield c


def test_full_propose_confirm_apply_summary_snapshot_cycle(sitl_copter, client):
    # session/start
    start_resp = client.post("/session/start", json={"connection_string": sitl_copter})
    assert start_resp.status_code == 200, start_resp.text
    start_data = start_resp.json()
    session_id = start_data["session_id"]
    assert start_data["vehicle_type"] == "ArduCopter"
    assert start_data["read_only"] is False, "expected real metadata from the local ArduPilot checkout"

    # vehicle/status
    status_resp = client.get("/vehicle/status", params={"session_id": session_id})
    assert status_resp.status_code == 200
    assert status_resp.json()["connected"] is True

    # chat -> propose (scripted model calls propose_param_change)
    chat_resp = client.post("/chat", json={"session_id": session_id, "message": "increase the log buffer"})
    assert chat_resp.status_code == 200, chat_resp.text
    chat_data = chat_resp.json()
    assert chat_data["reply"] is None, "a turn that pauses for approval must not also return a final reply"
    proposal = chat_data["pending_proposal"]
    assert proposal is not None
    assert proposal["param_name"] == TEST_PARAM
    assert proposal["accepted"] is True
    proposal_id = proposal["proposal_id"]

    # GET /proposals reflects the pending one
    list_resp = client.get("/proposals", params={"session_id": session_id})
    assert list_resp.status_code == 200
    assert [p["proposal_id"] for p in list_resp.json()] == [proposal_id]

    # confirm -> apply
    confirm_resp = client.post(f"/proposals/{proposal_id}/confirm", json={"session_id": session_id})
    assert confirm_resp.status_code == 200, confirm_resp.text
    confirm_data = confirm_resp.json()
    assert confirm_data["outcome"] == "applied"

    # Pending list is empty again now that it's resolved.
    list_resp2 = client.get("/proposals", params={"session_id": session_id})
    assert list_resp2.json() == []

    # session/summary reflects the applied change
    summary_resp = client.get("/session/summary", params={"session_id": session_id})
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["applied_count"] == 1
    assert summary["rejected_count"] == 0
    assert summary["pending_count"] == 0

    # safety-snapshot always present, regardless of what changed
    snapshot_resp = client.get("/safety-snapshot", params={"session_id": session_id})
    assert snapshot_resp.status_code == 200
    assert "Safety Parameter Snapshot" in snapshot_resp.json()["text"]

    # session/end triggers the same summary + snapshot one more time
    end_resp = client.post("/session/end", params={"session_id": session_id})
    assert end_resp.status_code == 200
    assert end_resp.json()["applied_count"] == 1


def test_revise_proposal_applies_revised_value_not_original(sitl_copter, client):
    start_resp = client.post("/session/start", json={"connection_string": sitl_copter})
    session_id = start_resp.json()["session_id"]

    chat_resp = client.post("/chat", json={"session_id": session_id, "message": "increase the log buffer"})
    proposal = chat_resp.json()["pending_proposal"]
    proposal_id = proposal["proposal_id"]
    assert proposal["proposed_value"] == 50.0

    revise_resp = client.post(
        f"/proposals/{proposal_id}/revise", json={"session_id": session_id, "new_value": 75.0}
    )
    assert revise_resp.status_code == 200, revise_resp.text
    revised = revise_resp.json()
    assert revised["proposal_id"] == proposal_id
    assert revised["proposed_value"] == 75.0
    assert revised["accepted"] is True

    confirm_resp = client.post(f"/proposals/{proposal_id}/confirm", json={"session_id": session_id})
    assert confirm_resp.status_code == 200, confirm_resp.text
    assert confirm_resp.json()["outcome"] == "applied"

    status_resp = client.get("/vehicle/status", params={"session_id": session_id})
    assert status_resp.json()["connected"] is True

    summary_resp = client.get("/session/summary", params={"session_id": session_id})
    assert summary_resp.json()["applied_count"] == 1


def test_reboot_reconnects_the_same_session_and_chat_still_works(sitl_copter, client):
    import json

    start = client.post("/session/start", json={"connection_string": sitl_copter}).json()
    session_id, params_before = start["session_id"], start["param_count"]
    assert start["frame_label"] == "Quadcopter"

    resp = client.post("/session/reboot/stream", params={"session_id": session_id})
    events = [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]
    assert events[-1]["type"] == "final", events[-3:]
    links = [e["link"] for e in events if e["type"] == "progress"]
    assert "down" in links and links[-1] == "up", links
    assert events[-1]["param_count"] > 0.9 * params_before and events[-1]["armed"] is False

    status = client.get("/vehicle/status", params={"session_id": session_id}).json()
    assert status["connected"] is True and status["session_id"] == session_id

    chat = client.post("/chat", json={"session_id": session_id, "message": "increase the log buffer"})
    assert chat.status_code == 200, chat.text  # same chat session, new link
    assert chat.json()["pending_proposal"] is not None
